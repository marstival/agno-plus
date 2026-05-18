"""ImageReader — OCR via vision LLM.

Note: OCR is the acknowledged exception to the "no LLM calls during ingestion"
rule — it is a reading step (extracting text from pixels), not a reasoning step.

Requires: pip install agno-plus[image]
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Any

from agno_plus.core.models import Document

logger = logging.getLogger(__name__)

_MEDIA_TYPE_MAP: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
}


class ImageReader:
    """Extract text from images using a vision LLM (OpenAI GPT-4o or Ollama llava).

    Args:
        backend: "openai" (default) or "ollama".
        model: Vision model name. Defaults to "gpt-4o" for openai, "llava" for ollama.
        api_key: OpenAI API key (required for openai backend).
        ollama_base_url: Base URL for Ollama (default http://localhost:11434).
    """

    SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"})

    def __init__(
        self,
        backend: str = "openai",
        model: str | None = None,
        api_key: str | None = None,
        ollama_base_url: str = "http://localhost:11434",
    ) -> None:
        self._backend = backend
        self._model = model or ("gpt-4o" if backend == "openai" else "llava")
        self._api_key = api_key
        self._ollama_base_url = ollama_base_url

    def read(self, source: bytes | str, filename: str = "image.jpg", **kwargs: Any) -> list[Document]:
        if isinstance(source, str):
            source = source.encode()
        ocr_text = self._extract_text(source, filename)
        return [
            Document(
                id=f"image-{uuid.uuid4().hex[:8]}",
                content=ocr_text,
                source_type="image",
                source_name=filename,
                metadata={"filename": filename, "ocr_backend": self._backend},
            )
        ]

    # ------------------------------------------------------------------
    # Backend dispatch
    # ------------------------------------------------------------------

    def _extract_text(self, image_bytes: bytes, filename: str) -> str:
        if self._backend == "ollama":
            return self._extract_ollama(image_bytes, filename)
        return self._extract_openai(image_bytes, filename)

    def _extract_openai(self, image_bytes: bytes, filename: str) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai is required for vision OCR. "
                "Install with: pip install agno-plus[image]"
            )

        client = OpenAI(api_key=self._api_key)
        ext = filename.rsplit(".", 1)[-1].lower()
        media_type = _MEDIA_TYPE_MAP.get(ext, "image/jpeg")
        image_data = base64.standard_b64encode(image_bytes).decode()
        data_url = f"data:{media_type};base64,{image_data}"

        prompt = (
            "Extract all visible text from this image faithfully. "
            "Return strict JSON with a single key 'ocr_text' containing the full extracted text. "
            "If no text is visible, return {\"ocr_text\": \"\"}."
        )
        response = client.chat.completions.create(
            model=self._model,
            max_tokens=2000,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        content = (response.choices[0].message.content or "").strip()
        try:
            return str(json.loads(content).get("ocr_text", ""))
        except Exception:
            return content

    def _extract_ollama(self, image_bytes: bytes, filename: str) -> str:
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx is required for Ollama OCR backend. "
                "Install with: pip install httpx"
            )

        image_data = base64.standard_b64encode(image_bytes).decode()
        payload = {
            "model": self._model,
            "prompt": "Extract all visible text from this image. Return only the extracted text, nothing else.",
            "images": [image_data],
            "stream": False,
        }
        response = httpx.post(
            f"{self._ollama_base_url}/api/generate",
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
