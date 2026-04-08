"""Transcriber protocol and factory."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Transcriber(Protocol):
    """Interface every transcription backend must satisfy."""

    async def transcribe(self, audio_path: str) -> str: ...


def get_transcriber(mode: str) -> Transcriber:
    """Return the appropriate transcriber for *mode* ("local" or "cloud")."""
    if mode == "local":
        from secretary.transcription.whisper_local import LocalWhisperTranscriber

        return LocalWhisperTranscriber()

    if mode == "cloud":
        from secretary.transcription.whisper_cloud import CloudWhisperTranscriber

        return CloudWhisperTranscriber()

    raise ValueError(f"Unknown whisper_mode: {mode!r}. Expected 'local' or 'cloud'.")
