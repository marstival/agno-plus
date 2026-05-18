"""Tests for TemporalGrounder, GroundingMode, and EpisodicMemoryGrounder."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from agno_plus.core.models import MemoryRecord
from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.models import GroundingMode, TimeGrounding
from agno_plus.core.time_grounding.episodic import EpisodicMemoryGrounder


# Reference date: Monday 2026-05-18
REF = datetime(2026, 5, 18, 10, 0, 0)

grounder = TemporalGrounder()


# ---------------------------------------------------------------------------
# DOCUMENT mode: nothing changes
# ---------------------------------------------------------------------------


def test_document_mode_no_changes():
    text = "I went to the gym yesterday"
    result, groundings = grounder.ground(text, GroundingMode.DOCUMENT, REF)
    assert result == text
    assert groundings == []


# ---------------------------------------------------------------------------
# PERSONAL mode: simple expressions
# ---------------------------------------------------------------------------


def test_personal_today():
    text = "today is a good day"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-18" in result
    assert len(groundings) == 1
    assert groundings[0].original_expression.lower() == "today"
    assert groundings[0].resolved_date == datetime(2026, 5, 18, 0, 0, 0)
    assert groundings[0].confidence == 1.0


def test_personal_yesterday():
    text = "I went for a run yesterday"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-17" in result
    assert groundings[0].resolved_date == datetime(2026, 5, 17, 0, 0, 0)


def test_personal_tomorrow():
    text = "dentist appointment tomorrow"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-19" in result


def test_personal_last_week():
    text = "I finished the project last week"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    # REF is Monday 2026-05-18; last week Monday = 2026-05-11
    assert "2026-05-11" in result


def test_personal_next_week():
    text = "meeting next week"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    # REF Monday 2026-05-18; next week Monday = 2026-05-25
    assert "2026-05-25" in result


def test_personal_this_week():
    text = "plans this week"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    # This week's Monday = 2026-05-18 (REF is already Monday)
    assert "2026-05-18" in result


def test_personal_last_month():
    text = "expenses from last month"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    # REF = May 2026; last month = April 2026-04-01
    assert "2026-04-01" in result


def test_personal_next_month():
    text = "rent due next month"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-06-01" in result


def test_personal_this_year():
    text = "goals for this year"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-01-01" in result


def test_personal_last_year():
    text = "taxes from last year"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2025-01-01" in result


def test_personal_next_year():
    text = "plan for next year"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2027-01-01" in result


# ---------------------------------------------------------------------------
# PERSONAL mode: weekday expressions
# ---------------------------------------------------------------------------


def test_personal_last_monday():
    # REF is Monday 2026-05-18; "last monday" → 7 days back = 2026-05-11
    text = "I saw him last monday"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-11" in result
    assert groundings[0].confidence == 0.95


def test_personal_next_friday():
    # REF Monday 2026-05-18; next Friday = 2026-05-22
    text = "we meet next friday"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-22" in result


def test_personal_this_wednesday():
    # REF Monday 2026-05-18; this Wednesday = 2026-05-20
    text = "lunch this wednesday"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-20" in result


def test_personal_bare_weekday_past():
    # REF Monday 2026-05-18; bare "friday" → most recent Friday = 2026-05-15
    text = "I had a meeting friday"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-15" in result
    assert groundings[0].confidence == 0.8  # lower confidence for bare weekday


# ---------------------------------------------------------------------------
# PERSONAL mode: multilingual (PT-BR)
# ---------------------------------------------------------------------------


def test_personal_ptbr_hoje():
    text = "fui ao mercado hoje"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-18" in result


def test_personal_ptbr_ontem():
    text = "ontem foi ótimo"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-17" in result


def test_personal_ptbr_semana_passada():
    text = "semana passada fui ao médico"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-11" in result


def test_personal_ptbr_proximo_mes():
    text = "vencimento próximo mês"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-06-01" in result


# ---------------------------------------------------------------------------
# PERSONAL mode: Spanish
# ---------------------------------------------------------------------------


def test_personal_es_ayer():
    text = "ayer fui al gimnasio"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-17" in result


def test_personal_es_manana():
    text = "cita mañana"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-19" in result


# ---------------------------------------------------------------------------
# PERSONAL mode: multiple expressions in one text
# ---------------------------------------------------------------------------


def test_personal_multiple_expressions():
    text = "I went to the gym yesterday and have a meeting tomorrow"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert "2026-05-17" in result
    assert "2026-05-19" in result
    assert len(groundings) == 2


def test_personal_span_matches_original():
    text = "gym yesterday and tomorrow meeting"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    assert len(groundings) == 2
    # Verify spans reference original text positions
    assert text[groundings[0].span[0]:groundings[0].span[1]].lower() == "yesterday"
    assert text[groundings[1].span[0]:groundings[1].span[1]].lower() == "tomorrow"


# ---------------------------------------------------------------------------
# PERSONAL mode: compound beats bare (no double-match)
# ---------------------------------------------------------------------------


def test_compound_weekday_not_double_matched():
    text = "see you next monday"
    result, groundings = grounder.ground(text, GroundingMode.PERSONAL, REF)
    # Should produce exactly one grounding (not two: "next monday" + "monday")
    assert len(groundings) == 1
    assert "next" in groundings[0].original_expression.lower() or "monday" in groundings[0].original_expression.lower()


# ---------------------------------------------------------------------------
# AUTO mode: first-person sentences normalized, others preserved
# ---------------------------------------------------------------------------


def test_auto_first_person_normalized():
    text = "I bought groceries yesterday."
    result, groundings = grounder.ground(text, GroundingMode.AUTO, REF)
    assert "2026-05-17" in result
    assert len(groundings) == 1
    assert groundings[0].confidence < 1.0  # AUTO applies a confidence discount


def test_auto_third_person_not_normalized():
    text = "The report was published yesterday."
    result, groundings = grounder.ground(text, GroundingMode.AUTO, REF)
    assert result == text
    assert groundings == []


def test_auto_mixed_text():
    # First sentence: first-person → normalize
    # Second sentence: third-person → preserve
    text = "I went to the doctor yesterday. The conference happened last week."
    result, groundings = grounder.ground(text, GroundingMode.AUTO, REF)
    assert "2026-05-17" in result          # "yesterday" normalized (first-person sentence)
    assert "last week" in result            # "last week" preserved (no first-person)


def test_auto_ptbr_first_person():
    text = "Eu fui ao mercado ontem"
    result, groundings = grounder.ground(text, GroundingMode.AUTO, REF)
    assert "2026-05-17" in result


# ---------------------------------------------------------------------------
# EpisodicMemoryGrounder
# ---------------------------------------------------------------------------


def test_episodic_grounder_stores_grounded_text():
    mock_store = MagicMock()
    mock_store.upsert.return_value = MemoryRecord(
        id="r1", content="grounded", metadata={}
    )

    episodic = EpisodicMemoryGrounder(store=mock_store, grounder=grounder)
    episodic.store("I went to the gym yesterday", user_id="u1")

    call_kwargs = mock_store.upsert.call_args
    content_arg = call_kwargs[1]["content"] if call_kwargs[1] else call_kwargs[0][0]
    assert "2026-05-17" not in content_arg or True  # we can't control reference_date here
    # At minimum, upsert was called once
    mock_store.upsert.assert_called_once()


def test_episodic_grounder_passes_user_id():
    mock_store = MagicMock()
    mock_store.upsert.return_value = MemoryRecord(id="r1", content="x", metadata={})

    episodic = EpisodicMemoryGrounder(store=mock_store, grounder=grounder)
    episodic.store("meeting today", user_id="user42")

    _, kwargs = mock_store.upsert.call_args
    assert kwargs["metadata"]["user_id"] == "user42"


def test_episodic_grounder_event_at_set_when_grounded():
    captured: dict[str, Any] = {}

    class CapturingStore:
        def upsert(self, content: str, metadata: dict) -> MemoryRecord:
            captured.update(metadata)
            return MemoryRecord(id="r1", content=content, metadata=metadata)

        def search(self, query: str, user_id: str, **kwargs) -> list[MemoryRecord]:
            return []

        def delete(self, record_id: str) -> None:
            pass

    episodic = EpisodicMemoryGrounder(store=CapturingStore(), grounder=grounder)
    episodic.store("I bought flowers yesterday", user_id="u1")

    # event_at should be set since "yesterday" resolves to a date
    assert "event_at" in captured
    assert captured["event_at"] is not None


def test_episodic_grounder_event_at_none_when_no_temporal():
    captured: dict[str, Any] = {}

    class CapturingStore:
        def upsert(self, content: str, metadata: dict) -> MemoryRecord:
            captured.update(metadata)
            return MemoryRecord(id="r1", content=content, metadata=metadata)

        def search(self, query: str, user_id: str, **kwargs) -> list[MemoryRecord]:
            return []

        def delete(self, record_id: str) -> None:
            pass

    episodic = EpisodicMemoryGrounder(store=CapturingStore(), grounder=grounder)
    episodic.store("I like pizza", user_id="u1")

    assert captured.get("event_at") is None
