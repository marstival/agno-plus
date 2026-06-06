"""Unit tests for IntelligentPdfReader heading detection and metadata.

PDF parsing requires real bytes so full round-trip tests live in the example
integration runs. These cover the new pure-Python pieces: the heading stack
and the structured table metadata that flow into Document.metadata.
"""

from __future__ import annotations

from agno_plus.core.readers.pdf import _HeadingStack


class TestHeadingStack:
    def test_empty_initially(self) -> None:
        s = _HeadingStack()
        assert s.path == []

    def test_numbered_single_level(self) -> None:
        s = _HeadingStack()
        s.update_from_line("3 Pricing Tiers")
        assert s.path == ["3 Pricing Tiers"]

    def test_numbered_nested(self) -> None:
        s = _HeadingStack()
        s.update_from_line("3 Terms")
        s.update_from_line("3.1 Payment")
        assert s.path == ["3 Terms", "3.1 Payment"]

    def test_numbered_sibling_pops_deeper(self) -> None:
        s = _HeadingStack()
        s.update_from_line("3 Terms")
        s.update_from_line("3.1 Payment")
        s.update_from_line("3.2 Delivery")
        assert s.path == ["3 Terms", "3.2 Delivery"]

    def test_numbered_new_top_clears_stack(self) -> None:
        s = _HeadingStack()
        s.update_from_line("3 Terms")
        s.update_from_line("3.1 Payment")
        s.update_from_line("4 References")
        assert s.path == ["4 References"]

    def test_all_caps_short_line_is_heading(self) -> None:
        s = _HeadingStack()
        s.update_from_line("INVOICE")
        assert s.path == ["INVOICE"]
        s.update_from_line("PAYMENT TERMS")
        assert s.path == ["PAYMENT TERMS"]

    def test_all_caps_rejects_column_header_row(self) -> None:
        """Column-header rows like 'QTY DESCRIPTION UNIT PRICE LINE TOTAL'
        must not be treated as section headings."""
        s = _HeadingStack()
        s.update_from_line("QTY DESCRIPTION UNIT PRICE LINE TOTAL")
        assert s.path == []  # 5 words → exceeds heading word limit

    def test_all_caps_rejects_single_letters(self) -> None:
        """'Q T Y' shouldn't qualify (each word too short)."""
        s = _HeadingStack()
        s.update_from_line("Q T Y")
        assert s.path == []

    def test_all_caps_rejects_terminal_punctuation(self) -> None:
        s = _HeadingStack()
        s.update_from_line("NOTE.")
        assert s.path == []

    def test_lowercase_paragraph_is_not_heading(self) -> None:
        s = _HeadingStack()
        s.update_from_line("The following tiers apply per the contract:")
        assert s.path == []

    def test_blank_line_is_noop(self) -> None:
        s = _HeadingStack()
        s.update_from_line("3 Terms")
        s.update_from_line("")
        s.update_from_line("   ")
        assert s.path == ["3 Terms"]

    def test_roman_numeral_heading(self) -> None:
        s = _HeadingStack()
        s.update_from_line("III. Background")
        assert s.path == ["III. Background"]

    def test_mixed_numbered_and_all_caps(self) -> None:
        """Real PDFs interleave numbered sections with uppercase callouts.
        Each updates the depth-1 slot."""
        s = _HeadingStack()
        s.update_from_line("1. Introduction")
        s.update_from_line("BILLING")
        assert s.path == ["BILLING"]
