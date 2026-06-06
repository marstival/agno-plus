"""Semantic merge chunking — deterministic, no framework dependencies.

Three strategies:
  chunk_text_structured — preferred for prose: splits on structural boundaries
      (headings, bullets, speaker turns) then merges small blocks up to
      max_tokens. Accepts an optional cosine-similarity function for
      semantic merge decisions (inject from adapter layer).
  chunk_text — fallback: simple word-count sliding window with overlap.
  chunk_table_block — for tabular blocks: emits one summary chunk plus one
      chunk per row. Each row chunk repeats the heading breadcrumb,
      table label, and column labels so it is self-contained for vector
      retrieval. Designed to be called by the pipeline when a Document's
      metadata indicates block_type='table'.
  chunk_prose_block — wraps chunk_text_structured and prepends a heading
      breadcrumb so prose chunks carry their section context.
"""

from __future__ import annotations

import re
from typing import Callable


def chunk_text_structured(
    text: str,
    max_tokens: int = 400,
    overlap_tokens: int = 40,
    similarity_fn: Callable[[str, str], float] | None = None,
    similarity_threshold: float = 0.75,
) -> list[str]:
    """Split text on structural boundaries then merge up to max_tokens.

    Args:
        text: Input text (Markdown is fine).
        max_tokens: Approximate word-count limit per chunk.
        overlap_tokens: Words to carry from the previous chunk as context.
        similarity_fn: Optional callable(a, b) → float in [0,1]. When
            provided, adjacent blocks with similarity >= threshold are merged
            regardless of size (up to max_tokens). Injected from adapter
            layer to keep core dependency-free.
        similarity_threshold: Minimum similarity to force-merge two blocks.
    """
    blocks = _split_blocks(text)
    if not blocks:
        return []
    return _merge_blocks(blocks, max_tokens, overlap_tokens, similarity_fn, similarity_threshold)


def chunk_table_block(
    *,
    columns: list[str],
    rows: list[dict[str, str]],
    headings: list[str] | None = None,
    table_label: str | None = None,
) -> list[str]:
    """Produce one summary chunk + one chunk per row for a structured table.

    Each chunk is self-contained: every row chunk repeats the column labels
    inline as key/value pairs, prefixed with the table's heading breadcrumb
    and label. The summary chunk lets queries like "do I have a pricing
    table?" hit even when no individual row is the best match.

    Args:
        columns: Column names in order.
        rows: List of {column_name: value} dicts.
        headings: Section-heading stack at the table's location, deepest last.
        table_label: Most recent heading, table caption, or None.

    Returns: [summary, row1, row2, ...] — empty if columns or rows are empty.
    """
    if not columns or not rows:
        return []

    parts: list[str] = []
    if headings:
        parts.append(" > ".join(headings))
    parts.append(table_label or "Table")
    prefix = " — ".join(parts)

    rowword = "row" if len(rows) == 1 else "rows"
    summary = f"{prefix} — columns: {', '.join(columns)} — {len(rows)} {rowword}"

    row_chunks: list[str] = []
    for row in rows:
        kv = ", ".join(f"{c}: {row.get(c, '')}" for c in columns)
        row_chunks.append(f"{prefix} — {kv}")

    return [summary, *row_chunks]


def chunk_prose_block(
    content: str,
    *,
    headings: list[str] | None = None,
    max_tokens: int = 400,
    overlap_tokens: int = 40,
) -> list[str]:
    """Chunk prose with a heading breadcrumb prepended to each chunk.

    Falls through to chunk_text_structured then prepends `[Heading > ...] `
    so the chunk carries its section context. Skips the prefix when a chunk
    is itself one of the headings, to avoid `[X] X` duplication.
    """
    base = chunk_text_structured(content, max_tokens, overlap_tokens) or [content]
    if not headings:
        return base
    breadcrumb = " > ".join(headings)
    headings_set = {h.strip() for h in headings}
    return [
        c if c.strip() in headings_set else f"[{breadcrumb}] {c}"
        for c in base
    ]


def chunk_text(
    text: str,
    max_tokens: int = 400,
    overlap_tokens: int = 40,
) -> list[str]:
    """Simple word-count sliding window chunker (fallback, no boundary detection)."""
    if not text or not text.strip():
        return []
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current: list[str] = []

    for word in words:
        current.append(word)
        if len(current) >= max_tokens:
            chunks.append(" ".join(current))
            overlap = min(overlap_tokens, len(current))
            current = current[-overlap:]

    if current:
        chunks.append(" ".join(current))
    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_HEADING_RE = re.compile(r"^#{1,6}\s+")
_BULLET_RE = re.compile(r"^[-*•]|\d+\.\s+")
_SPEAKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{0,32}:\s+")


def _split_blocks(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    lines = [line.rstrip() for line in text.splitlines()]
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            content = " ".join(l for l in current if l.strip())
            if content:
                blocks.append(content)
            current.clear()

    for line in lines:
        if not line.strip():
            flush()
            continue
        if _HEADING_RE.match(line) or line.isupper():
            flush()
            blocks.append(line.strip())
        elif _BULLET_RE.match(line) or _SPEAKER_RE.match(line):
            flush()
            blocks.append(line.strip())
        else:
            current.append(line.strip())

    flush()
    return blocks


def _token_len(s: str) -> int:
    return len(s.split())


def _merge_blocks(
    blocks: list[str],
    max_tokens: int,
    overlap_tokens: int,
    similarity_fn: Callable[[str, str], float] | None,
    similarity_threshold: float,
) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        if current:
            chunks.append(" ".join(current))

    for i, block in enumerate(blocks):
        block_tokens = _token_len(block)

        if not current:
            current = [block]
            current_tokens = block_tokens
            continue

        # Semantic merge check (optional)
        force_split = False
        if similarity_fn is not None and i > 0:
            sim = similarity_fn(blocks[i - 1], block)
            if sim < similarity_threshold:
                force_split = True

        if force_split or current_tokens + block_tokens > max_tokens:
            flush()
            if overlap_tokens > 0 and chunks:
                overlap_words = " ".join(chunks[-1].split()[-overlap_tokens:])
                current = [overlap_words, block] if overlap_words else [block]
            else:
                current = [block]
            current_tokens = _token_len(" ".join(current))
        else:
            current.append(block)
            current_tokens += block_tokens

    flush()
    return chunks
