"""
Wraps the Gemini Live 2.5 Flash API WebSocket session.
One instance per connected browser client.
"""
import asyncio
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
LIVE_MODEL = os.environ.get('GEMINI_LIVE_MODEL', 'gemini-live-2.5-flash-preview')


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
        Async generator yielding event dicts consumed by main.py:
          {'type': 'audio', 'data': '<base64 PCM 24kHz>'}
          {'type': 'transcript', 'role': 'agent'|'patient', 'text': '...'}
          {'type': 'turn_complete'}
          {'type': 'error', 'code': 'SESSION_DROPPED', 'message': '...'}
        """
        try:
            async for response in self._session.receive():
                # Inline PCM audio bytes from agent
                if response.data:
                    yield {
                        'type': 'audio',
                        'data': base64.b64encode(response.data).decode(),
                    }

                # Agent text (when response_modalities includes TEXT)
                if response.text:
                    self.sm.append_transcript('agent', response.text)
                    yield {'type': 'transcript', 'role': 'agent', 'text': response.text}

                sc = response.server_content
                if sc:
                    # Patient speech transcription
                    if sc.input_transcription and sc.input_transcription.text:
                        text = sc.input_transcription.text.strip()
                        if text:
                            self.sm.append_transcript('patient', text)
                            yield {'type': 'transcript', 'role': 'patient', 'text': text}

                    # Agent speech transcription (when audio-only response)
                    if sc.output_transcription and sc.output_transcription.text:
                        text = sc.output_transcription.text.strip()
                        if text:
                            # Deduplicate against recent transcript entry
                            recent = self.sm.transcript[-1] if self.sm.transcript else None
                            if not recent or recent['role'] != 'agent' or recent['text'] != text:
                                self.sm.append_transcript('agent', text)
                                yield {'type': 'transcript', 'role': 'agent', 'text': text}

                    if sc.turn_complete:
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
