"""
Wraps the Gemini Live API WebSocket session.
One instance per connected browser client.
"""
import base64
import logging
import os

from google import genai
from google.genai import types

from prompts import build_system_prompt
from state_machine import IntakeStateMachine

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GOOGLE_PROJECT_ID', '')
LOCATION   = os.environ.get('GOOGLE_LOCATION', 'us-central1')
LIVE_MODEL = os.environ.get('GEMINI_LIVE_MODEL', 'gemini-2.0-flash-live-preview-04-09')


class GeminiLiveSession:
    def __init__(self, sm: IntakeStateMachine, credentials):
        self.sm = sm
        self.credentials = credentials
        self._session = None
        self._client = None
        self._context_manager = None

    async def start(self):
        self._client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION,
            credentials=self.credentials,
        )
        config = types.LiveConnectConfig(
            response_modalities=['AUDIO'],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name='Aoede')
                )
            ),
            system_instruction=build_system_prompt(self.sm),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )
        self._context_manager = self._client.aio.live.connect(
            model=LIVE_MODEL,
            config=config,
        )
        self._session = await self._context_manager.__aenter__()
        logger.info("Gemini Live session started — model=%s", LIVE_MODEL)

    async def trigger_greeting(self):
        """
        Send an initial text turn so Aria speaks first without waiting for
        patient audio. The system prompt instructs her to greet the patient,
        so this single trigger kicks off the full conversation flow.
        """
        await self._session.send_client_content(
            turns=[types.Content(
                role='user',
                parts=[types.Part(text='Hello')],
            )],
            turn_complete=True,
        )

    async def send_audio(self, pcm_bytes: bytes):
        """Send raw PCM 16kHz mono audio from the browser mic."""
        if not self._session:
            raise RuntimeError("Session not started")
        await self._session.send_realtime_input(
            audio=types.Blob(
                mime_type='audio/pcm;rate=16000',
                data=pcm_bytes,
            )
        )

    async def receive(self):
        """
        Async generator for the full multi-turn conversation.

        The SDK's session.receive() exits after ONE turn_complete — this outer
        loop re-enters it for each subsequent turn, keeping the session alive
        for the entire intake call.

        Yields:
          {'type': 'audio',      'data': '<base64 PCM 24kHz>'}
          {'type': 'transcript', 'role': 'agent'|'patient', 'text': '...'}
          {'type': 'turn_complete'}
          {'type': 'error',      'code': 'SESSION_DROPPED', 'message': '...'}
        """
        agent_buf:   list[str] = []
        patient_buf: list[str] = []

        try:
            while True:
                received_anything = False

                async for response in self._session.receive():
                    received_anything = True

                    # Inline PCM audio — stream immediately for low latency
                    if response.data:
                        yield {
                            'type': 'audio',
                            'data': base64.b64encode(response.data).decode(),
                        }

                    sc = response.server_content
                    if sc:
                        # Accumulate patient speech across chunks
                        if sc.input_transcription and sc.input_transcription.text:
                            patient_buf.append(sc.input_transcription.text)

                        # Accumulate agent speech across chunks
                        if sc.output_transcription and sc.output_transcription.text:
                            agent_buf.append(sc.output_transcription.text)

                        if sc.turn_complete:
                            # Emit each side as one complete message per turn
                            patient_text = ''.join(patient_buf).strip()
                            if patient_text:
                                self.sm.append_transcript('patient', patient_text)
                                yield {'type': 'transcript', 'role': 'patient', 'text': patient_text}

                            agent_text = ''.join(agent_buf).strip()
                            if agent_text:
                                self.sm.append_transcript('agent', agent_text)
                                yield {'type': 'transcript', 'role': 'agent', 'text': agent_text}

                            agent_buf.clear()
                            patient_buf.clear()
                            yield {'type': 'turn_complete'}

                if not received_anything:
                    # WebSocket closed cleanly — session over
                    logger.info("Gemini Live session closed by server")
                    break
                # One turn complete — loop back to receive the next turn

        except Exception as e:
            logger.exception("Gemini Live session error")
            yield {
                'type': 'error',
                'code': 'SESSION_DROPPED',
                'message': str(e),
            }

    async def close(self):
        if self._context_manager and self._session:
            try:
                await self._context_manager.__aexit__(None, None, None)
            except Exception:
                pass
        self._session = None
        self._context_manager = None
        logger.info("Gemini Live session closed")
