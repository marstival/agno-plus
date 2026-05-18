"""Time grounding domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class GroundingMode(str, Enum):
    PERSONAL = "personal"   # normalize all relative expressions (conversations, receipts)
    DOCUMENT = "document"   # preserve all expressions (literary text, reference docs)
    AUTO = "auto"           # sentence-level: normalize only first-person + relative-time sentences


@dataclass
class TimeGrounding:
    original_expression: str
    resolved_date: datetime
    confidence: float
    span: tuple[int, int]   # char offsets in the original (pre-replacement) text
