"""Tests for _publication_label: year-month badge derivation for the paper list.

Priority: publication_date (full date) -> arXiv YYMM from URL -> publication_year (year only).
Format: "YY.MM" when month is known, else "YYYY", else None.
"""
from app.services import papers


def test_publication_date_full_date_to_yy_dot_mm():
    assert papers._publication_label({"publication_date": "2026-05-15"}) == "26.05"


def test_publication_date_year_month_only():
    assert papers._publication_label({"publication_date": "2025-12"}) == "25.12"


def test_arxiv_abs_url_yymm():
    assert papers._publication_label({"paper_url": "https://arxiv.org/abs/2508.10146"}) == "25.08"


def test_arxiv_pdf_url_with_version():
    assert papers._publication_label({"paper_url": "https://arxiv.org/pdf/2501.00881v2"}) == "25.01"


def test_arxiv_from_source_url_original():
    assert papers._publication_label({"source_url_original": "https://arxiv.org/abs/2606.02494"}) == "26.06"


def test_publication_date_takes_priority_over_arxiv():
    meta = {
        "publication_date": "2024-03-10",
        "paper_url": "https://arxiv.org/abs/2307.16789",
        "publication_year": 2024,
    }
    assert papers._publication_label(meta) == "24.03"


def test_arxiv_takes_priority_over_year_even_when_they_differ():
    # arXiv submission month 2307 -> 23.07, despite publication_year=2024 (venue year)
    meta = {"paper_url": "https://arxiv.org/abs/2307.16789", "publication_year": 2024}
    assert papers._publication_label(meta) == "23.07"


def test_year_only_fallback():
    assert papers._publication_label({"publication_year": 2025}) == "2025"


def test_year_only_for_non_arxiv_url():
    meta = {"paper_url": "https://www.turing.com/resources/ai-agent-frameworks", "publication_year": 2025}
    assert papers._publication_label(meta) == "2025"


def test_no_date_returns_none():
    assert papers._publication_label({"paper_url": "https://example.com/x"}) is None
    assert papers._publication_label({}) is None


def test_malformed_publication_date_falls_back_to_year():
    meta = {"publication_date": "n/a", "publication_year": 2023}
    assert papers._publication_label(meta) == "2023"


def test_publication_year_as_string():
    assert papers._publication_label({"publication_year": "2022"}) == "2022"
