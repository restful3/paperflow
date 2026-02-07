"""Web search service using Brave Search API.

Provides:
1. brave_search() - Generic web search wrapper
2. enrich_paper_metadata() - Enrich paper_meta.json with venue/DOI/year/URL
"""

import json
import re
from datetime import datetime
from pathlib import Path

import httpx

from ..config import settings


# ── Known venue patterns ──────────────────────────────────────────────────

_VENUE_PATTERNS = [
    # Conferences
    (re.compile(r'\b(NeurIPS|NIPS)\b', re.IGNORECASE), 'NeurIPS'),
    (re.compile(r'\bICML\b', re.IGNORECASE), 'ICML'),
    (re.compile(r'\bICLR\b', re.IGNORECASE), 'ICLR'),
    (re.compile(r'\bCVPR\b', re.IGNORECASE), 'CVPR'),
    (re.compile(r'\bICCV\b', re.IGNORECASE), 'ICCV'),
    (re.compile(r'\bECCV\b', re.IGNORECASE), 'ECCV'),
    (re.compile(r'\bACL\s+20\d{2}\b', re.IGNORECASE), None),
    (re.compile(r'\bEMNLP\b', re.IGNORECASE), 'EMNLP'),
    (re.compile(r'\bNAACL\b', re.IGNORECASE), 'NAACL'),
    (re.compile(r'\bAAAI\b', re.IGNORECASE), 'AAAI'),
    (re.compile(r'\bIJCAI\b', re.IGNORECASE), 'IJCAI'),
    (re.compile(r'\bSIGGRAPH\b', re.IGNORECASE), 'SIGGRAPH'),
    (re.compile(r'\bCHI\s+20\d{2}\b', re.IGNORECASE), None),
    (re.compile(r'\bKDD\b', re.IGNORECASE), 'KDD'),
    (re.compile(r'\bWWW\b(?!\.)', re.IGNORECASE), 'WWW'),
    (re.compile(r'\bCoRL\b', re.IGNORECASE), 'CoRL'),
    (re.compile(r'\bRSS\s+20\d{2}\b', re.IGNORECASE), None),
    # Journals
    (re.compile(r'\bNature\b(?:\s+\w+)*', re.IGNORECASE), None),
    (re.compile(r'\bScience\b', re.IGNORECASE), 'Science'),
    (re.compile(r'\bIEEE\s+\w+', re.IGNORECASE), None),
    (re.compile(r'\bACM\s+\w+', re.IGNORECASE), None),
    (re.compile(r'\bJMLR\b', re.IGNORECASE), 'JMLR'),
    (re.compile(r'\bTACL\b', re.IGNORECASE), 'TACL'),
    # Preprints
    (re.compile(r'\barXiv\b', re.IGNORECASE), 'arXiv'),
    (re.compile(r'\bbioRxiv\b', re.IGNORECASE), 'bioRxiv'),
    (re.compile(r'\bmedRxiv\b', re.IGNORECASE), 'medRxiv'),
    (re.compile(r'\bOpenReview\b', re.IGNORECASE), 'OpenReview'),
]

_DOI_RE = re.compile(r'\b(10\.\d{4,}/[^\s,;"\'>]+)')
_YEAR_RE = re.compile(r'\b((?:19|20)\d{2})\b')

_ACADEMIC_DOMAINS = [
    "arxiv.org", "doi.org", "openreview.net", "semanticscholar.org",
    "ieee.org", "acm.org", "springer.com", "nature.com", "sciencedirect.com",
]


def _extract_venue(text: str, url: str | None = None) -> str | None:
    if url:
        if "arxiv.org" in url:
            return "arXiv"
        if "openreview.net" in url:
            return "OpenReview"
        if "biorxiv.org" in url:
            return "bioRxiv"
        if "medrxiv.org" in url:
            return "medRxiv"
    for pattern, default_name in _VENUE_PATTERNS:
        m = pattern.search(text)
        if m:
            return default_name or m.group(0).strip()
    return None


def _extract_year(text: str) -> int | None:
    years = [int(y) for y in _YEAR_RE.findall(text) if 1990 <= int(y) <= 2030]
    if not years:
        return None
    from collections import Counter
    return Counter(years).most_common(1)[0][0]


async def brave_search(query: str, count: int = 5) -> list[dict]:
    """Search the web using Brave Search API.

    Args:
        query: Search query string.
        count: Number of results to return (max 20).

    Returns:
        List of result dicts with keys: title, url, description.
        Empty list if API key not configured or request fails.
    """
    api_key = settings.BRAVE_SEARCH_API_KEY
    if not api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count, "text_decorations": "false"},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for r in data.get("web", {}).get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            })
        return results
    except Exception:
        return []


async def enrich_paper_metadata(paper_name: str) -> dict:
    """Search for a paper and enrich its paper_meta.json.

    Looks up the paper by title + first author on the web,
    then extracts venue, DOI, publication year, and URL.
    Only fills in fields that are currently missing.

    Args:
        paper_name: Paper directory name (in outputs or archives).

    Returns:
        Dict with enrichment results:
        - success: bool
        - enriched_fields: list of field names that were added
        - error: str (if failed)
    """
    # Locate paper directory
    paper_dir = None
    for base in [settings.outputs_dir, settings.archives_dir]:
        candidate = base / paper_name
        if candidate.is_dir():
            paper_dir = candidate
            break

    if not paper_dir:
        return {"success": False, "error": "Paper not found", "enriched_fields": []}

    # Load existing metadata
    meta_path = paper_dir / "paper_meta.json"
    if not meta_path.is_file():
        return {"success": False, "error": "No paper_meta.json found", "enriched_fields": []}

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"success": False, "error": f"Failed to read metadata: {e}", "enriched_fields": []}

    title = meta.get("title")
    if not title:
        return {"success": False, "error": "No title in metadata", "enriched_fields": []}

    # Build query
    authors = meta.get("authors", [])
    first_author_last = authors[0].split()[-1] if authors else ""
    query = f'"{title}"'
    if first_author_last:
        query += f" {first_author_last}"

    # Search
    results = await brave_search(query)
    if not results:
        return {"success": False, "error": "No search results", "enriched_fields": []}

    # Aggregate text
    all_text = ""
    first_academic_url = None
    for r in results:
        all_text += f" {r['title']} {r['description']} {r['url']}"
        if not first_academic_url:
            if any(d in r["url"] for d in _ACADEMIC_DOMAINS):
                first_academic_url = r["url"]

    if not first_academic_url and results:
        first_academic_url = results[0]["url"]

    # Extract fields
    enriched = {}

    if not meta.get("venue"):
        venue = _extract_venue(all_text, url=first_academic_url)
        if venue:
            enriched["venue"] = venue

    if not meta.get("doi"):
        doi_match = _DOI_RE.search(all_text)
        if doi_match:
            enriched["doi"] = doi_match.group(1).rstrip(".")

    if not meta.get("publication_year"):
        year = _extract_year(all_text)
        if year:
            enriched["publication_year"] = year

    if not meta.get("paper_url") and first_academic_url:
        enriched["paper_url"] = first_academic_url

    if not enriched:
        return {"success": True, "enriched_fields": [], "error": None}

    # Save
    enriched["web_enriched_at"] = datetime.now().isoformat()
    meta.update(enriched)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    field_names = [k for k in enriched if k != "web_enriched_at"]
    return {"success": True, "enriched_fields": field_names, "error": None}
