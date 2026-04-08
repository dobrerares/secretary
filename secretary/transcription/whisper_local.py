"""Local Whisper transcription via faster-whisper."""

from __future__ import annotations

import asyncio
import functools
import logging
from concurrent.futures import ThreadPoolExecutor

from secretary.config.settings import settings

logger = logging.getLogger(__name__)

# Dedicated thread-pool so transcription doesn't starve the event loop.
_executor = ThreadPoolExecutor(max_workers=1)


class LocalWhisperTranscriber:
    """Transcriber backed by faster-whisper running on the local machine.

    The model is loaded lazily on the first call to :meth:`transcribe` so that
    import-time stays fast and memory is only consumed when actually needed.
    """

    def __init__(self) -> None:
        self._model = None

    # -- internal helpers -------------------------------------------------- #

    def _load_model(self):
        """Load the WhisperModel (called inside the thread pool)."""
        if self._model is not None:
            return

        from faster_whisper import WhisperModel  # type: ignore[import-untyped]

        model_size = settings.whisper_model_size or "small"
        logger.info("Loading faster-whisper model '%s' ...", model_size)
        self._model = WhisperModel(model_size, device="auto", compute_type="default")
        logger.info("faster-whisper model '%s' loaded.", model_size)

    def _transcribe_sync(self, audio_path: str) -> str:
        """Run transcription synchronously (called inside the thread pool)."""
        self._load_model()
        assert self._model is not None

        segments, _info = self._model.transcribe(audio_path, beam_size=5)
        text = " ".join(segment.text.strip() for segment in segments)
        return text

    # -- public API -------------------------------------------------------- #

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe *audio_path* and return the recognised text.

        The heavy lifting happens in a thread-pool executor so the asyncio
        event loop is never blocked.
        """
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            _executor,
            functools.partial(self._transcribe_sync, audio_path),
        )
        return text
