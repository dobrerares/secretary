"""Audio conversion and temp-file helpers."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


async def convert_ogg_to_wav(ogg_path: str) -> str:
    """Convert an OGG/Opus file to 16 kHz mono WAV using ffmpeg.

    Returns the path to the newly created WAV file (same directory,
    ``.wav`` extension).
    """
    wav_path = str(Path(ogg_path).with_suffix(".wav"))

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",            # overwrite without asking
        "-i", ogg_path,
        "-ar", "16000",  # 16 kHz sample rate
        "-ac", "1",      # mono
        wav_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")
        raise RuntimeError(f"ffmpeg conversion failed (exit {proc.returncode}): {error_msg}")

    logger.debug("Converted %s -> %s", ogg_path, wav_path)
    return wav_path


async def cleanup_temp_files(*paths: str) -> None:
    """Remove temporary files, silently ignoring any that are already gone."""
    for path in paths:
        try:
            os.remove(path)
            logger.debug("Removed temp file %s", path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Failed to remove temp file %s", path, exc_info=True)
