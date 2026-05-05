"""Cloud Whisper transcription via the OpenAI API."""

from __future__ import annotations

import logging
from pathlib import Path

from openai import AsyncOpenAI

from secretary.config.settings import settings

logger = logging.getLogger(__name__)


class CloudWhisperTranscriber:
    """Transcriber that delegates to OpenAI's Whisper API."""

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            api_key = settings.openai_api_key
            if not api_key:
                raise RuntimeError("SECRETARY_OPENAI_API_KEY is not set -- cannot use cloud Whisper transcription.")
            self._client = AsyncOpenAI(api_key=api_key)
        return self._client

    async def transcribe(self, audio_path: str) -> str:
        """Send *audio_path* to the OpenAI Whisper API and return the text."""
        client = self._get_client()
        audio_file = Path(audio_path)

        logger.info("Sending %s to OpenAI Whisper API ...", audio_file.name)
        with open(audio_file, "rb") as f:
            transcription = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )

        text = transcription.text.strip()
        logger.info("Cloud transcription complete (%d chars).", len(text))
        return text
