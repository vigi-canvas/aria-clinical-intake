"""
Wraps the Gemini Live 2.5 Flash API WebSocket session.
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
LOCATION = os.environ.get('GOOGLE_LOCATION', 'us-central1')
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
        logger.info("Gemini Live session started — model=%s phase=%s", LIVE_MODEL, self.sm.phase)

    async def send_audio(self, pcm_bytes: bytes):
        """Send raw PCM 16kHz mono audio from browser mic."""
        if not self._session:
            raise RuntimeError("Session not started")
        await self._session.send(
            input=types.LiveClientRealtimeInput(
                media_chunks=[types.Blob(
                    mime_type='audio/pcm;rate=16000',
                    data=pcm_bytes,
                )]
            )
        )

    async def receive(self):
        """
        Async generator yielding event dicts consumed by main.py.
        Transcripts are buffered and emitted as a single message per turn.

          {'type': 'audio', 'data': '<base64 PCM 24kHz>'}
          {'type': 'transcript', 'role': 'agent'|'patient', 'text': '...'}
          {'type': 'turn_complete'}
          {'type': 'error', 'code': 'SESSION_DROPPED', 'message': '...'}
        """
        agent_buf = []   # accumulates agent output_transcription chunks within a turn
        patient_buf = [] # accumulates patient input_transcription chunks within a turn

        try:
            async for response in self._session.receive():
                # Audio bytes — stream immediately for low-latency playback
                if response.data:
                    yield {
                        'type': 'audio',
                        'data': base64.b64encode(response.data).decode(),
                    }

                sc = response.server_content
                if sc:
                    # Buffer patient speech transcription chunks
                    if sc.input_transcription and sc.input_transcription.text:
                        patient_buf.append(sc.input_transcription.text)

                    # Buffer agent output transcription chunks
                    if sc.output_transcription and sc.output_transcription.text:
                        agent_buf.append(sc.output_transcription.text)

                    if sc.turn_complete:
                        # Emit patient transcript as a single message
                        patient_text = ''.join(patient_buf).strip()
                        if patient_text:
                            self.sm.append_transcript('patient', patient_text)
                            yield {'type': 'transcript', 'role': 'patient', 'text': patient_text}

                        # Emit agent transcript as a single message
                        agent_text = ''.join(agent_buf).strip()
                        if agent_text:
                            self.sm.append_transcript('agent', agent_text)
                            yield {'type': 'transcript', 'role': 'agent', 'text': agent_text}

                        agent_buf.clear()
                        patient_buf.clear()

                        yield {'type': 'turn_complete'}

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
