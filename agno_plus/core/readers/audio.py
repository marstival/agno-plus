"""AudioReader — Whisper STT ingestion reader.

Backend selected via constructor: "local" (faster-whisper) or "openai".
Requires: pip install agno-plus[audio]
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from typing import Any

from agno_plus.core.models import Document

logger = logging.getLogger(__name__)


class AudioReader:
    """Transcribe audio files to Document using Whisper.

    Args:
        backend: "local" uses faster-whisper (no internet).
                 "openai" uses the OpenAI Whisper API.
        model_size: faster-whisper model size (default "base"). Ignored for openai.
        api_key: OpenAI API key (required when backend="openai").
    """

    SUPPORTED_EXTENSIONS = frozenset({".mp3", ".m4a", ".wav", ".ogg", ".flac", ".webm"})

    def __init__(
        self,
        backend: str = "local",
        model_size: str = "base",
        api_key: str | None = None,
    ) -> None:
        self._backend = backend
        self._model_size = model_size
        self._api_key = api_key
        self._local_model: Any = None

    def transcribe(self, source: bytes, filename: str = "recording.webm") -> str:
        """Transcribe audio bytes to text. Returns the raw transcript string.

        Useful for real-time voice input (chat STT) where a Document wrapper is not needed.
        """
        return self._transcribe(source, filename)

    def read(self, source: bytes | str, filename: str = "audio.mp3", **kwargs: Any) -> list[Document]:
        if isinstance(source, str):
            source = source.encode()
        transcript = self._transcribe(source, filename)
        return [
            Document(
                id=f"audio-{uuid.uuid4().hex[:8]}",
                content=transcript,
                source_type="audio",
                source_name=filename,
                metadata={"filename": filename},
            )
        ]

    # ------------------------------------------------------------------
    # Backend dispatch
    # ------------------------------------------------------------------

    def _transcribe(self, audio_bytes: bytes, filename: str) -> str:
        if self._backend == "openai":
            return self._transcribe_openai(audio_bytes, filename)
        return self._transcribe_local(audio_bytes, filename)

    def _transcribe_local(self, audio_bytes: bytes, filename: str) -> str:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper is required for local STT. "
                "Install with: pip install agno-plus[audio]"
            )

        if self._local_model is None:
            self._local_model = WhisperModel(self._model_size, compute_type="int8")
            logger.info("Loaded local Whisper model size=%s", self._model_size)

        suffix = os.path.splitext(filename)[1] or ".mp3"
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            segments, _ = self._local_model.transcribe(tmp_path)
            return " ".join(seg.text.strip() for seg in segments)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _transcribe_openai(self, audio_bytes: bytes, filename: str) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai is required for OpenAI STT backend. "
                "Install with: pip install agno-plus[audio]"
            )

        client = OpenAI(api_key=self._api_key)
        suffix = os.path.splitext(filename)[1] or ".mp3"
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            with open(tmp_path, "rb") as f:
                result = client.audio.transcriptions.create(model="whisper-1", file=f)
            return result.text
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
