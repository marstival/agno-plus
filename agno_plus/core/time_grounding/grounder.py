"""Multilingual temporal grounding — deterministic, no LLM calls."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable

from agno_plus.core.time_grounding.models import GroundingMode, TimeGrounding


# ---------------------------------------------------------------------------
# Canonical concepts → locale variants
# ---------------------------------------------------------------------------

_SIMPLE_EXPRESSIONS: list[tuple[str, list[str]]] = [
    ("now", [
        "now", "current time", "current date",
        "agora", "data atual", "hora atual",
        "ahora", "fecha actual", "hora actual",
    ]),
    ("today", ["today", "hoje", "hoy"]),
    ("tomorrow", ["tomorrow", "amanha", "amanhã", "mañana", "manana"]),
    ("yesterday", ["yesterday", "ontem", "ayer"]),
    ("this_week", ["this week", "esta semana", "essa semana", "esta semana"]),
    ("last_week", [
        "last week", "semana passada", "última semana", "ultima semana", "semana anterior",
    ]),
    ("next_week", [
        "next week", "próxima semana", "proxima semana", "semana que vem",
    ]),
    ("this_month", [
        "this month", "este mês", "este mes", "mês atual", "mes atual",
    ]),
    ("last_month", [
        "last month", "mês passado", "mes passado", "último mês", "ultimo mes",
        "mes anterior", "mes pasado",
    ]),
    ("next_month", [
        "next month", "próximo mês", "proximo mes", "mês que vem", "mes que vem",
        "mes siguiente",
    ]),
    ("this_year", ["this year", "este ano", "este año"]),
    ("last_year", [
        "last year", "ano passado", "último ano", "ultimo ano", "ano anterior",
        "año pasado",
    ]),
    ("next_year", [
        "next year", "próximo ano", "proximo ano", "ano que vem", "próximo año",
        "proximo año",
    ]),
]

# Weekday name → 0-based index (Monday=0, Sunday=6)
_WEEKDAY_NAMES: dict[str, int] = {
    "monday": 0, "segunda": 0, "segunda-feira": 0, "lunes": 0,
    "tuesday": 1, "terça": 1, "terca": 1, "terça-feira": 1, "martes": 1,
    "wednesday": 2, "quarta": 2, "quarta-feira": 2, "miércoles": 2, "miercoles": 2,
    "thursday": 3, "quinta": 3, "quinta-feira": 3, "jueves": 3,
    "friday": 4, "sexta": 4, "sexta-feira": 4, "viernes": 4,
    "saturday": 5, "sábado": 5, "sabado": 5,
    "sunday": 6, "domingo": 6,
}

# Modifier words by type
_MODIFIER_LAST: frozenset[str] = frozenset([
    "last", "passada", "passado", "última", "ultimo", "última", "pasado", "anterior",
])
_MODIFIER_NEXT: frozenset[str] = frozenset([
    "next", "próxima", "proxima", "próximo", "proximo",
])
_MODIFIER_THIS: frozenset[str] = frozenset([
    "this", "esta", "este",
])

_FIRST_PERSON_RE = re.compile(
    r"\b(I|me|my|mine|myself|we|our|ours|ourselves|us"
    r"|eu|meu|meus|minha|minhas|nós|nos|nossa|nossas|nosso|nossos"
    r"|yo|mi|mis|nosotros|nosotras)\b",
    re.IGNORECASE | re.UNICODE,
)


# ---------------------------------------------------------------------------
# Date arithmetic helpers
# ---------------------------------------------------------------------------


def _start_of_week(ref: datetime, weeks_offset: int = 0) -> datetime:
    monday = ref - timedelta(days=ref.weekday()) + timedelta(weeks=weeks_offset)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month(ref: datetime, months_offset: int = 0) -> datetime:
    m = ref.month + months_offset
    y = ref.year + (m - 1) // 12
    m = ((m - 1) % 12) + 1
    return ref.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)


def _start_of_year(ref: datetime, years_offset: int = 0) -> datetime:
    return ref.replace(
        year=ref.year + years_offset, month=1, day=1,
        hour=0, minute=0, second=0, microsecond=0,
    )


def _resolve_weekday(weekday_idx: int, modifier: str, ref: datetime) -> datetime:
    ref_weekday = ref.weekday()  # 0=Monday

    if modifier == "last":
        days_back = (ref_weekday - weekday_idx) % 7 or 7
        return (ref - timedelta(days=days_back)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if modifier == "next":
        days_forward = (weekday_idx - ref_weekday) % 7 or 7
        return (ref + timedelta(days=days_forward)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if modifier == "this":
        days_diff = weekday_idx - ref_weekday
        return (ref + timedelta(days=days_diff)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    # bare weekday: most recent occurrence (including today)
    days_back = (ref_weekday - weekday_idx) % 7
    return (ref - timedelta(days=days_back)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


_SIMPLE_RESOLVERS: dict[str, Callable[[datetime], datetime]] = {
    "now": lambda r: r,
    "today": lambda r: r.replace(hour=0, minute=0, second=0, microsecond=0),
    "yesterday": lambda r: (r - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ),
    "tomorrow": lambda r: (r + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ),
    "this_week": lambda r: _start_of_week(r, 0),
    "last_week": lambda r: _start_of_week(r, -1),
    "next_week": lambda r: _start_of_week(r, 1),
    "this_month": lambda r: _start_of_month(r, 0),
    "last_month": lambda r: _start_of_month(r, -1),
    "next_month": lambda r: _start_of_month(r, 1),
    "this_year": lambda r: _start_of_year(r, 0),
    "last_year": lambda r: _start_of_year(r, -1),
    "next_year": lambda r: _start_of_year(r, 1),
}


# ---------------------------------------------------------------------------
# Pattern registry
# ---------------------------------------------------------------------------


# Each entry: (compiled_pattern, canonical_key, confidence)
# canonical_key form:
#   "simple:{name}"       → looked up in _SIMPLE_RESOLVERS
#   "weekday:{mod}:{idx}" → resolved via _resolve_weekday
_PatternEntry = tuple[re.Pattern[str], str, float]


def _build_patterns() -> list[_PatternEntry]:
    entries: list[tuple[str, str, float]] = []

    # Simple expressions
    for canonical, variants in _SIMPLE_EXPRESSIONS:
        for expr in variants:
            entries.append((expr, f"simple:{canonical}", 1.0))

    # Weekday with modifier (compound expressions first so they beat bare weekdays)
    for mod_type, mod_words in [
        ("last", _MODIFIER_LAST),
        ("next", _MODIFIER_NEXT),
        ("this", _MODIFIER_THIS),
    ]:
        for mod_word in mod_words:
            for weekday_name, weekday_idx in _WEEKDAY_NAMES.items():
                full_expr = f"{mod_word} {weekday_name}"
                entries.append((full_expr, f"weekday:{mod_type}:{weekday_idx}", 0.95))

    # Bare weekday names (lower confidence — ambiguous direction)
    for weekday_name, weekday_idx in _WEEKDAY_NAMES.items():
        entries.append((weekday_name, f"weekday:bare:{weekday_idx}", 0.8))

    # Longest pattern first to ensure compound matches beat substrings
    entries.sort(key=lambda x: len(x[0]), reverse=True)

    result: list[_PatternEntry] = []
    for expr, canonical, conf in entries:
        pat = re.compile(r"(?i)\b" + re.escape(expr) + r"\b", re.UNICODE)
        result.append((pat, canonical, conf))
    return result


_PATTERNS: list[_PatternEntry] = _build_patterns()


# ---------------------------------------------------------------------------
# TemporalGrounder
# ---------------------------------------------------------------------------


class TemporalGrounder:
    """Multilingual rule-based normalization of relative time references.

    Supports EN, PT-BR, ES. No LLM calls — purely deterministic.
    """

    def ground(
        self,
        text: str,
        mode: GroundingMode,
        reference_date: datetime,
    ) -> tuple[str, list[TimeGrounding]]:
        """Normalize relative time expressions in text.

        Returns (grounded_text, list_of_TimeGrounding). Spans in TimeGrounding
        refer to positions in the original text before replacement.
        """
        if mode == GroundingMode.DOCUMENT:
            return text, []
        if mode == GroundingMode.PERSONAL:
            matches = self._find_matches(text, reference_date)
            return self._apply_replacements(text, matches)
        # AUTO mode: per-sentence first-person heuristic
        return self._ground_auto(text, reference_date)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_matches(
        self,
        text: str,
        reference_date: datetime,
    ) -> list[tuple[int, int, str, datetime, float]]:
        """Collect non-overlapping matches, longest pattern first."""
        covered: set[int] = set()
        matches: list[tuple[int, int, str, datetime, float]] = []

        for pattern, canonical, confidence in _PATTERNS:
            for m in pattern.finditer(text):
                start, end = m.start(), m.end()
                if any(i in covered for i in range(start, end)):
                    continue
                resolved = self._resolve(canonical, reference_date)
                if resolved is None:
                    continue
                matches.append((start, end, m.group(), resolved, confidence))
                covered.update(range(start, end))

        return sorted(matches, key=lambda x: x[0])

    def _resolve(self, canonical: str, ref: datetime) -> datetime | None:
        if canonical.startswith("simple:"):
            key = canonical[7:]
            resolver = _SIMPLE_RESOLVERS.get(key)
            return resolver(ref) if resolver else None
        if canonical.startswith("weekday:"):
            _, modifier, idx_str = canonical.split(":")
            return _resolve_weekday(int(idx_str), modifier, ref)
        return None

    def _apply_replacements(
        self,
        text: str,
        matches: list[tuple[int, int, str, datetime, float]],
    ) -> tuple[str, list[TimeGrounding]]:
        groundings: list[TimeGrounding] = []
        result = text

        for start, end, expr, resolved, conf in sorted(
            matches, key=lambda x: x[0], reverse=True
        ):
            replacement = f"{resolved.strftime('%Y-%m-%d')} [{expr}]"
            result = result[:start] + replacement + result[end:]
            groundings.append(
                TimeGrounding(
                    original_expression=expr,
                    resolved_date=resolved,
                    confidence=conf,
                    span=(start, end),
                )
            )

        groundings.sort(key=lambda g: g.span[0])
        return result, groundings

    def _get_sentence_at(self, text: str, pos: int) -> str:
        """Return the sentence in text that contains character position pos."""
        start = pos
        while start > 0 and text[start - 1] not in ".!?\n":
            start -= 1
        end = pos
        while end < len(text) and text[end] not in ".!?\n":
            end += 1
        return text[start:end].strip()

    def _ground_auto(
        self,
        text: str,
        reference_date: datetime,
    ) -> tuple[str, list[TimeGrounding]]:
        all_matches = self._find_matches(text, reference_date)

        active: list[tuple[int, int, str, datetime, float]] = []
        for start, end, expr, resolved, conf in all_matches:
            sentence = self._get_sentence_at(text, start)
            if _FIRST_PERSON_RE.search(sentence):
                active.append((start, end, expr, resolved, conf * 0.9))

        if not active:
            return text, []
        return self._apply_replacements(text, active)
