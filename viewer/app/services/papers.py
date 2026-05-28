import datetime as _dt
import json as _json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse, urljoin
from urllib.request import Request, urlopen

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _slugify_name(text: str, max_len: int = 80) -> str:
    s = (text or "untitled").strip().lower()
    s = re.sub(r"https?://", "", s)
    s = re.sub(r"[^a-z0-9가-힣_-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:max_len] or "untitled")


def _fetch_url_html(url: str, timeout: int = 20) -> tuple[str, str]:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (PaperFlow URL Import)"})
    with urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()
        data = resp.read()
    return data.decode("utf-8", errors="ignore"), final_url


def _extract_text_from_html(html: str, max_chars: int = 24000) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<noscript[\s\S]*?</noscript>", " ", html, flags=re.I)
    m = re.search(r"<(article|main)[^>]*>([\s\S]*?)</\1>", html, flags=re.I)
    body = m.group(2) if m else html
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]



def _extract_pdf_text_simple(pdf_path: Path, max_pages: int = 2) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        parts: list[str] = []
        for p in reader.pages[:max_pages]:
            parts.append((p.extract_text() or "").strip())
        return "\n".join(x for x in parts if x)
    except Exception:
        return ""


def _looks_like_pdf_bytes(data: bytes) -> bool:
    return bool(data and data[:5] == b"%PDF-")


def _download_pdf(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (PaperFlow URL Import)"})
    with urlopen(req, timeout=timeout) as resp:
        content_type = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read()
    if _looks_like_pdf_bytes(data):
        return data
    # Some servers mislabel content-type but still return real PDF.
    if "application/pdf" in content_type and data:
        return data
    raise ValueError("Not a PDF response")


def _arxiv_transform(m: re.Match, url: str) -> list[str]:
    arxiv_id = m.group(1)
    v = m.group(2) or ""
    return [f"https://arxiv.org/pdf/{arxiv_id}{v}.pdf"]


def _arxiv_old_transform(m: re.Match, url: str) -> list[str]:
    cat_id = m.group(1)
    v = m.group(2) or ""
    return [f"https://arxiv.org/pdf/{cat_id}{v}.pdf"]


def _ar5iv_transform(m: re.Match, url: str) -> list[str]:
    arxiv_id = m.group(1)
    return [f"https://arxiv.org/pdf/{arxiv_id}.pdf"]


def _openreview_transform(m: re.Match, url: str) -> list[str]:
    oid = m.group(1)
    return [f"https://openreview.net/pdf?id={oid}"]


def _acl_transform(m: re.Match, url: str) -> list[str]:
    paper_id = m.group(1).rstrip("/")
    return [f"https://aclanthology.org/{paper_id}.pdf"]


def _huggingface_transform(m: re.Match, url: str) -> list[str]:
    arxiv_id = m.group(1)
    return [f"https://arxiv.org/pdf/{arxiv_id}.pdf"]


def _pmlr_transform(m: re.Match, url: str) -> list[str]:
    prefix = m.group(1)
    return [f"https://proceedings.mlr.press/{prefix}.pdf"]


def _semanticscholar_transform(m: re.Match, url: str) -> list[str]:
    sha = m.group(1)
    return [f"https://pdfs.semanticscholar.org/{sha[:4]}/{sha}.pdf"]


def _paperswithcode_transform(m: re.Match, url: str) -> list[str]:
    return []


def _biorxiv_transform(m: re.Match, url: str) -> list[str]:
    doi_path = m.group(1)
    host = m.group(0).split("/content/")[0]
    if "://" not in host:
        host = "https://" + host
    return [f"{host}/content/{doi_path}.full.pdf"]


_SITE_PDF_TRANSFORMERS: list[tuple[re.Pattern, callable]] = [
    # arXiv new-style: arxiv.org/abs/2301.12345 or arxiv.org/abs/2301.12345v2
    (re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})(v\d+)?"), _arxiv_transform),
    # arXiv old-style: arxiv.org/abs/hep-ph/0512345
    (re.compile(r"arxiv\.org/abs/([-a-z]+/\d{7})(v\d+)?"), _arxiv_old_transform),
    # ar5iv (HTML rendering of arXiv papers)
    (re.compile(r"ar5iv\.labs\.arxiv\.org/html/(\d{4}\.\d{4,5})"), _ar5iv_transform),
    # OpenReview: openreview.net/forum?id=xxx
    (re.compile(r"openreview\.net/forum\?id=([A-Za-z0-9_-]+)"), _openreview_transform),
    # ACL Anthology: aclanthology.org/2023.acl-long.1/
    (re.compile(r"aclanthology\.org/([A-Za-z0-9._-]+)/?\s*$"), _acl_transform),
    # HuggingFace Papers: huggingface.co/papers/2301.12345
    (re.compile(r"huggingface\.co/papers/(\d{4}\.\d{4,5})"), _huggingface_transform),
    # PMLR: proceedings.mlr.press/v235/chen24a.html
    (re.compile(r"proceedings\.mlr\.press/(v\d+/[^/]+?)\.html"), _pmlr_transform),
    # Semantic Scholar: semanticscholar.org/paper/Title/40-char-hex
    (re.compile(r"semanticscholar\.org/paper/[^/]+/([0-9a-f]{40})"), _semanticscholar_transform),
    # Papers with Code (no direct PDF, fall back to HTML anchors)
    (re.compile(r"paperswithcode\.com/paper/"), _paperswithcode_transform),
    # bioRxiv / medRxiv: (bio|med)rxiv.org/content/10.1101/...
    (re.compile(r"(?:bio|med)rxiv\.org/content/(10\.\d{4,9}/[\w./-]+?)(?:v\d+)?$"), _biorxiv_transform),
]


def _site_transform_pdf_urls(url: str) -> list[str]:
    for pattern, fn in _SITE_PDF_TRANSFORMERS:
        m = pattern.search(url)
        if m:
            return fn(m, url)
    return []


def _resolve_doi_redirect(url: str, timeout: int = 15) -> str | None:
    if "doi.org/" not in url:
        return None
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (PaperFlow URL Import)"})
        with urlopen(req, timeout=timeout) as resp:
            final = resp.geturl()
        if final and final != url:
            return final
    except Exception:
        pass
    return None


def _candidate_pdf_urls_from_page(url: str, html: str) -> list[str]:
    candidates: list[str] = []

    # If original URL already points to PDF
    if url.lower().endswith(".pdf"):
        candidates.append(url)

    # Standard scholarly meta tags
    meta_patterns = [
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:pdf["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pat in meta_patterns:
        for u in re.findall(pat, html, flags=re.I):
            candidates.append(urljoin(url, u.strip()))

    # Common anchor patterns
    anchor_patterns = [
        r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
        r'href=["\']([^"\']+/pdf(?:\?[^"\']*)?)["\']',
    ]
    for pat in anchor_patterns:
        for u in re.findall(pat, html, flags=re.I):
            candidates.append(urljoin(url, u.strip()))

    # de-dup preserve order
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


_STRICT_PDF_DOMAINS = (
    "arxiv.org", "openreview.net", "aclanthology.org", "proceedings.mlr.press",
    "biorxiv.org", "medrxiv.org", "acm.org", "ieeexplore.ieee.org",
    "springer.com", "nature.com", "sciencedirect.com",
)


def _resolve_url_to_pdf_bytes(url: str) -> tuple[bytes, str, str]:
    """Resolve URL to PDF bytes. Used by import_url_as_paper and mcp_jobs.

    Returns: (pdf_bytes, final_url_after_redirects, import_method)
      import_method in {"site_transform", "direct_pdf", "html_fallback"}
    Raises: ValueError with concrete reason on failure.
    """
    # A. URL validation
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL. Use http(s) URL.")
    host = (urlparse(url).netloc or "").lower()
    if not host:
        raise ValueError("Invalid URL host.")

    # B. DOI pre-resolve
    effective_url = url
    if "doi.org/" in url:
        resolved = _resolve_doi_redirect(url)
        if resolved:
            effective_url = resolved

    download_errors: list[str] = []

    # D. Site transformer -> PDF URL candidates (zero network requests)
    for cand in _site_transform_pdf_urls(effective_url):
        try:
            return _download_pdf(cand, timeout=35), effective_url, "site_transform"
        except Exception as e:
            download_errors.append(f"{cand}: {str(e)[:80]}")

    # F. Fallback: single HTML fetch + HTML-based candidate discovery
    html_for_discovery = ""
    final_url = effective_url
    try:
        html_for_discovery, final_url = _fetch_url_html(effective_url)
    except Exception:
        pass

    # If redirect discovered a new URL, re-apply site transformer
    if final_url and final_url != effective_url:
        effective_url = final_url
        for cand in _site_transform_pdf_urls(final_url):
            try:
                return _download_pdf(cand, timeout=35), effective_url, "site_transform"
            except Exception as e:
                download_errors.append(f"{cand}: {str(e)[:80]}")

    # HTML-based candidate discovery (meta tags, anchors)
    if html_for_discovery:
        for cand in _candidate_pdf_urls_from_page(effective_url, html_for_discovery):
            try:
                return _download_pdf(cand, timeout=35), effective_url, "direct_pdf"
            except Exception as e:
                download_errors.append(f"{cand}: {str(e)[:80]}")

    # G. strict_pdf_required check (based on effective_url, not original doi.org)
    effective_host = (urlparse(effective_url).netloc or "").lower()
    if any(d in effective_host for d in _STRICT_PDF_DOMAINS):
        detail = f" direct-download failed ({'; '.join(download_errors[:2])})" if download_errors else ""
        raise ValueError("해당 논문 링크는 원문 PDF 직접 다운로드가 필요하지만 실패했습니다." + detail)

    # H. Headless browser print-to-pdf fallback (non-academic/general pages)
    browser_bin = (
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if not browser_bin:
        msg = "No headless browser found (google-chrome/chromium)."
        if download_errors:
            msg += f" direct-download failed ({'; '.join(download_errors[:2])})"
        raise ValueError(msg)

    mcp_tmp_dir = settings.newones_dir / ".mcp_tmp"
    mcp_tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=mcp_tmp_dir, suffix=".pdf", delete=False) as tf:
        tmp_path = Path(tf.name)
    try:
        cmd = [
            browser_bin,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--virtual-time-budget=30000",
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            f"--print-to-pdf={tmp_path}",
            url,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            raise ValueError("Headless browser executable missing.")
        except subprocess.TimeoutExpired:
            raise ValueError("PDF 생성 타임아웃(60s).")
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or "").strip()
            raise ValueError(f"PDF 생성 실패: {err[:200]}")

        # I. Quality gates (file-based)
        if not tmp_path.exists() or tmp_path.stat().st_size < 1024:
            raise ValueError("PDF 생성 결과가 비정상입니다.")

        pdf_text = _extract_pdf_text_simple(tmp_path, max_pages=2)
        norm = re.sub(r"\s+", " ", (pdf_text or "")).strip().lower()
        bot_keywords = [
            "verifying the device", "verifying your browser", "verify you are human",
            "checking your browser", "device verification",
            "captcha", "are you a robot", "access denied",
            "just a moment", "ddos protection", "cloudflare",
            "attention required", "unusual traffic",
        ]
        norm_nospace = norm.replace(" ", "")
        bot_hit = sum(1 for k in bot_keywords if k in norm or k.replace(" ", "") in norm_nospace)
        if bot_hit >= 1 and len(norm) < 600:
            raise ValueError("사이트 봇 감지/인증 페이지가 캡처되었습니다. 이 사이트는 자동 가져오기를 지원하지 않습니다.")

        error_keywords = [
            "page not found", "404 not found", "403 forbidden",
            "no longer exists", "has been moved", "page you requested",
            "this page isn't available", "page doesn't exist",
            "requested url was not found", "server error", "500 internal",
        ]
        error_hit = sum(1 for k in error_keywords if k in norm or k.replace(" ", "") in norm_nospace)
        if error_hit >= 1 and len(norm) < 600:
            raise ValueError("에러 페이지(404/403 등)가 캡처되었습니다. URL이 유효한지 확인해 주세요.")

        weak_keywords = ["privacy policy", "notify me", "owner login", "terms", "copyright", "built for agents"]
        weak_hit = sum(1 for k in weak_keywords if k in norm)
        if len(norm) < 220 or weak_hit >= 3:
            raise ValueError("원문 본문이 아닌 푸터/배너만 인쇄되어 가져오기에 실패했습니다. 원문 페이지를 직접 열어 본문이 보이는 링크인지 확인해 주세요.")

        return tmp_path.read_bytes(), effective_url, "html_fallback"
    finally:
        tmp_path.unlink(missing_ok=True)


def import_url_as_paper(url: str, title: str | None = None) -> tuple[bool, str, str | None]:
    """Import a web URL by creating a PDF in newones/ queue.

    Returns: (ok, message, queued_pdf_name)
    """
    try:
        pdf_bytes, _final_url, _method = _resolve_url_to_pdf_bytes(url)
    except ValueError as e:
        return False, str(e), None

    settings.newones_dir.mkdir(parents=True, exist_ok=True)
    host = (urlparse(url).netloc or "").lower()
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify_name(title or host)
    pdf_name = f"web-{slug}-{ts}.pdf"
    pdf_path = settings.newones_dir / pdf_name

    # Atomic publish: write to .part then rename
    part_path = pdf_path.with_suffix(pdf_path.suffix + ".part")
    try:
        part_path.write_bytes(pdf_bytes)
        os.replace(part_path, pdf_path)
    except Exception as e:
        part_path.unlink(missing_ok=True)
        return False, f"queue write failed: {e}", None

    try:
        _write_source_sidecar(pdf_name, url)
    except Exception:
        pass

    return True, f"URL queued as PDF: {pdf_name}", pdf_name

from ..config import settings


def _source_sidecar_candidates(filename: str) -> list[Path]:
    """Return sidecar lookup order: new .meta path first, then legacy path."""
    return [
        settings.newones_meta_dir / f"{filename}.url.txt",
        settings.newones_dir / f"{filename}.url.txt",
    ]


def _read_source_sidecar(filename: str) -> str | None:
    for p in _source_sidecar_candidates(filename):
        try:
            if p.is_file():
                v = p.read_text(encoding="utf-8").strip()
                if v:
                    return v
        except Exception:
            continue
    return None


def _write_source_sidecar(filename: str, url: str) -> None:
    settings.newones_meta_dir.mkdir(parents=True, exist_ok=True)
    p = settings.newones_meta_dir / f"{filename}.url.txt"
    p.write_text(url, encoding="utf-8")


def _dir_size_mb(path: Path) -> float:
    try:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return total / (1024 * 1024)
    except Exception:
        return 0.0


def _load_paper_metadata(paper_dir: Path) -> dict | None:
    """Load paper_meta.json from a paper directory if it exists."""
    meta_path = paper_dir / "paper_meta.json"
    if meta_path.is_file():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            return None
    return None


def _paper_info(paper_dir: Path, location: str) -> dict:
    """Build info dict for a single paper directory."""
    files: dict[str, bool] = {
        "pdf": False,
        "md_ko": False,
        "md_en": False,
        "md_ko_explained": False,
        "md_en_explained": False,
        "md_lint_report": False,
    }
    for f in paper_dir.iterdir():
        if not f.is_file():
            continue
        if f.name.endswith(".pdf"):
            files["pdf"] = True
        elif f.name.endswith("_ko_explained.md"):
            files["md_ko_explained"] = True
        elif f.name.endswith("_explained.md"):
            files["md_en_explained"] = True
        elif f.name.endswith("_mdlint_report.json"):
            files["md_lint_report"] = True
        elif f.name.endswith("_ko.md"):
            files["md_ko"] = True
        elif f.name.endswith(".md"):
            files["md_en"] = True

    # Folder modification time as fallback date
    try:
        mtime = paper_dir.stat().st_mtime
        added_at = _dt.datetime.fromtimestamp(mtime).isoformat()
    except Exception:
        added_at = None

    info = {
        "name": paper_dir.name,
        "location": location,
        "formats": files,
        "size_mb": round(_dir_size_mb(paper_dir), 1),
        "added_at": added_at,
    }

    # Load AI-extracted metadata if available
    meta = _load_paper_metadata(paper_dir)
    if meta:
        info["title"] = meta.get("title")
        info["title_ko"] = meta.get("title_ko")
        info["authors"] = meta.get("authors", [])
        info["abstract"] = meta.get("abstract")
        info["abstract_ko"] = meta.get("abstract_ko")
        info["categories"] = meta.get("categories", [])
        info["original_filename"] = meta.get("original_filename")
        info["extracted_at"] = meta.get("extracted_at")
        info["publication_year"] = meta.get("publication_year")
        info["doc_type"] = meta.get("doc_type")
        info["venue"] = meta.get("venue")
        info["doi"] = meta.get("doi")
        info["paper_url"] = meta.get("paper_url")
        info["source_url"] = meta.get("source_url_original") or meta.get("paper_url")
    else:
        info["title"] = None
        info["title_ko"] = None
        info["authors"] = []
        info["abstract"] = None
        info["abstract_ko"] = None
        info["categories"] = []
        info["original_filename"] = None
        info["extracted_at"] = None
        info["publication_year"] = None
        info["doc_type"] = None
        info["venue"] = None
        info["doi"] = None
        info["paper_url"] = None
        info["source_url"] = None

    # Sidecar fallback: if source_url still missing, check source sidecar in .meta then legacy path
    if not info.get("source_url") and info.get("original_filename"):
        try:
            info["source_url"] = _read_source_sidecar(info["original_filename"])
        except Exception:
            pass

    # Derive source_domain for display when venue is missing
    src = info.get("source_url")
    if src:
        try:
            from urllib.parse import urlparse
            host = urlparse(src).hostname or ""
            if host.startswith("www."):
                host = host[4:]
            info["source_domain"] = host
        except Exception:
            info["source_domain"] = None
    else:
        info["source_domain"] = None

    # Check for chat history
    chat_history_file = paper_dir / "chat_history.json"
    has_chat_history = chat_history_file.exists()
    chat_message_count = 0

    if has_chat_history:
        try:
            with open(chat_history_file, "r", encoding="utf-8") as f:
                chat_data = _json.load(f)
                chat_message_count = len(chat_data.get("messages", []))
        except Exception:
            pass

    info["chat"] = {
        "has_history": has_chat_history,
        "message_count": chat_message_count
    }

    return info


def list_papers(tab: str = "unread") -> list[dict]:
    if tab == "archived":
        base = settings.archives_dir
        location = "archives"
    else:
        base = settings.outputs_dir
        location = "outputs"

    if not base.exists():
        return []

    last_read = get_all_last_read()
    papers = []
    for item in sorted(base.iterdir(), key=lambda p: p.name):
        if not _safe_child_dir(base, item):
            continue
        info = _paper_info(item, location)
        info["last_read_at"] = last_read.get(item.name)
        papers.append(info)
    return papers


def get_paper_info(name: str) -> dict | None:
    """Find paper in outputs or archives and return info."""
    paper_dir = safe_paper_dir(name)
    if not paper_dir:
        return None
    # Determine location by parent directory identity (resolved)
    try:
        if paper_dir.parent.resolve() == settings.archives_dir.resolve():
            loc = "archives"
        else:
            loc = "outputs"
    except (OSError, RuntimeError):
        loc = "outputs"
    info = _paper_info(paper_dir, loc)
    info["last_read_at"] = get_all_last_read().get(name)
    return info


def find_processed_paper(original_filename: str | None = None, source_url: str | None = None) -> dict | None:
    """Resolve a processed paper folder using original filename or source URL.

    Also checks .url.txt sidecar files (created by import_url_as_paper) when
    source_url is not yet in paper_meta.json.

    Returns dict: {name, location, viewer_path} or None
    """
    if not original_filename and not source_url:
        return None

    def _norm_url(u: str | None) -> str:
        if not u:
            return ""
        try:
            p = urlparse(u.strip())
            host = (p.netloc or "").lower()
            path = (p.path or "").rstrip("/")
            query = ("?" + p.query) if p.query else ""
            # Normalize arXiv to https + canonical host/path for stable matching
            if host in ("arxiv.org", "www.arxiv.org"):
                return f"https://arxiv.org{path}{query}"
            scheme = (p.scheme or "https").lower()
            return f"{scheme}://{host}{path}{query}"
        except Exception:
            return (u or "").strip()

    norm_source_url = _norm_url(source_url)
    is_arxiv_abs = "arxiv.org/abs/" in norm_source_url

    candidates: list[tuple[Path, str]] = []
    for base, loc in [(settings.outputs_dir, "outputs"), (settings.archives_dir, "archives")]:
        if not base.exists():
            continue
        for item in base.iterdir():
            if not _safe_child_dir(base, item):
                continue
            candidates.append((item, loc))

    # Prefer newest first
    candidates.sort(key=lambda x: x[0].stat().st_mtime if x[0].exists() else 0, reverse=True)

    for paper_dir, loc in candidates:
        meta = _load_paper_metadata(paper_dir) or {}
        if original_filename and meta.get("original_filename") == original_filename:
            return _resolve_result(paper_dir, loc)
        if source_url and (
            _norm_url(meta.get("paper_url")) == norm_source_url
            or _norm_url(meta.get("source_url_original")) == norm_source_url
        ):
            # Guard: for arXiv abs links, ignore legacy page-capture imports
            # (e.g., original_filename like web-*.pdf from print fallback).
            orig = (meta.get("original_filename") or "").lower()
            if is_arxiv_abs and orig.startswith("web-"):
                pass
            else:
                return _resolve_result(paper_dir, loc)

        # Fallback: check source sidecar (.meta first, legacy path fallback)
        if source_url and meta.get("original_filename"):
            try:
                sidecar_url = _read_source_sidecar(meta["original_filename"])
                if _norm_url(sidecar_url) == norm_source_url:
                    # Guard: for arXiv abs links, ignore legacy page-capture imports
                    orig = (meta.get("original_filename") or "").lower()
                    if is_arxiv_abs and orig.startswith("web-"):
                        continue
                    # Backfill source_url_original into paper_meta.json for future lookups
                    meta_path = paper_dir / "paper_meta.json"
                    try:
                        import json as _json
                        meta["source_url_original"] = source_url
                        meta_path.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    return _resolve_result(paper_dir, loc)
            except Exception:
                pass

    return None


def _resolve_result(paper_dir: Path, location: str) -> dict:
    """Build resolve result with format availability info."""
    formats: dict[str, bool] = {}
    for f in paper_dir.iterdir():
        if not f.is_file():
            continue
        if f.name.endswith(".pdf"):
            formats["pdf"] = True
        elif f.name.endswith("_ko_explained.md"):
            formats["md_ko_explained"] = True
        elif f.name.endswith("_explained.md"):
            formats["md_en_explained"] = True
        elif f.name.endswith("_ko.md"):
            formats["md_ko"] = True
        elif f.name.endswith(".md"):
            formats["md_en"] = True
    return {
        "name": paper_dir.name,
        "location": location,
        "viewer_path": f"/viewer/{quote(paper_dir.name, safe='')}",
        "formats": formats,
    }


def _is_within(base: Path, candidate: Path) -> bool:
    """True only if `candidate` resolves under `base`."""
    try:
        base_resolved = base.resolve()
        cand_resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return False
    try:
        cand_resolved.relative_to(base_resolved)
        return True
    except ValueError:
        return False


def _is_safe_paper_name(name: str) -> bool:
    """Paper names are single directory components produced by the batch pipeline."""
    if not name or "\x00" in name:
        return False
    if "/" in name or "\\" in name:
        return False
    if name in {".", ".."}:
        return False
    return True


def safe_paper_dir(name: str) -> Path | None:
    """Resolve a paper directory under outputs/ or archives/, rejecting traversal.

    Public helper — re-used by web_search and any other module that needs to
    map a user-supplied paper name to a filesystem directory.
    Returns None for unsafe names, unknown papers, or symlink escapes.
    """
    if not _is_safe_paper_name(name):
        return None
    for base in [settings.outputs_dir, settings.archives_dir]:
        d = base / name
        if not d.is_dir():
            continue
        if not _is_within(base, d):
            continue
        return d
    return None


def safe_paper_dir_at_location(name: str, location: str | None) -> Path | None:
    """Like safe_paper_dir but pinned to the location the caller recorded.

    Used by MCP code paths where a JobRecord remembers whether the paper was
    completed under outputs/ or archives/. Resolving via that recorded location
    avoids collisions when both directories happen to hold a folder with the
    same paper_name (e.g. outputs reuse of an archived title).

    - location="outputs"  → only look in settings.outputs_dir
    - location="archives" → only look in settings.archives_dir
    - location=None       → fall back to safe_paper_dir (outputs-first scan),
                            preserving behavior for legacy records persisted
                            before the location field existed
    """
    if location is None:
        return safe_paper_dir(name)
    if location not in ("outputs", "archives"):
        return None
    if not _is_safe_paper_name(name):
        return None
    base = settings.outputs_dir if location == "outputs" else settings.archives_dir
    d = base / name
    if not d.is_dir():
        return None
    if not _is_within(base, d):
        return None
    return d


def _safe_child_dir(base: Path, item: Path) -> bool:
    """Accept only non-hidden directories that resolve under their base.

    Used by listing code paths (`list_papers`, `_get_existing_papers_summary`)
    that take entries from `base.iterdir()` rather than user-supplied names.
    Even though the source isn't user input, a symlink under `outputs/` or
    `archives/` can still escape — keep the symlink-escape threat model
    consistent across all paths.
    """
    if item.name.startswith("."):
        return False
    if not item.is_dir():
        return False
    return _is_within(base, item)


# Backward-compatible alias — keep _resolve_paper_dir for any in-tree callers.
_resolve_paper_dir = safe_paper_dir


def get_pdf_path(name: str) -> Path | None:
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith(".pdf"):
            return f
    return None


def get_md_ko_path(name: str) -> Path | None:
    """Get Korean markdown file path with deterministic priority.

    Priority:
    1) <folder_name>_ko.md exact match
    2) Other *_ko.md files excluding backup/explained variants (newest first)
    """
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None

    exact = paper_dir / f"{name}_ko.md"
    if exact.is_file():
        return exact

    cands: list[Path] = []
    for f in paper_dir.iterdir():
        if not f.is_file():
            continue
        fn = f.name
        if not fn.endswith("_ko.md"):
            continue
        if fn.endswith("_ko_explained.md"):
            continue
        if ".bak" in fn or "_backup_" in fn:
            continue
        cands.append(f)

    if not cands:
        return None

    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0]


def get_md_en_path(name: str) -> Path | None:
    """Get English markdown file path."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith(".md") and not f.name.endswith("_ko.md") and not f.name.endswith("_explained.md"):
            return f
    return None


def get_md_ko_explained_path(name: str) -> Path | None:
    """Get Korean explained markdown file path."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith("_ko_explained.md"):
            return f
    return None


def get_md_en_explained_path(name: str) -> Path | None:
    """Get English explained markdown file path."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith("_explained.md") and not f.name.endswith("_ko_explained.md"):
            return f
    return None


def save_markdown(name: str, md_type: str, content: str) -> tuple[bool, str]:
    """Save edited markdown content with timestamped backup.

    Args:
        name: Paper folder name.
        md_type: "ko" or "en".
        content: New markdown content.
    """
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return False, f"Paper '{name}' not found."

    # Find the target file
    target = None
    if md_type == "ko":
        for f in paper_dir.iterdir():
            if f.name.endswith("_ko.md") and not f.name.endswith("_ko_explained.md"):
                target = f
                break
    else:
        for f in paper_dir.iterdir():
            if f.name.endswith(".md") and not f.name.endswith("_ko.md") and not f.name.endswith("_explained.md"):
                target = f
                break

    if not target:
        label = "Korean" if md_type == "ko" else "English"
        return False, f"{label} markdown file not found."

    # Create timestamped backup
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target.with_suffix(f".{timestamp}.bak")
    try:
        shutil.copy2(str(target), str(backup_path))
    except Exception as e:
        return False, f"Failed to create backup: {e}"

    # Write new content
    try:
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        return False, f"Failed to save: {e}"

    # Invalidate RAG chat chunks cache
    chat_chunks_file = paper_dir / "chat_chunks.json"
    if chat_chunks_file.exists():
        try:
            chat_chunks_file.unlink()
        except Exception:
            pass

    return True, f"Saved. Backup: {backup_path.name}"


def get_asset_path(name: str, filename: str) -> Path | None:
    """Get path to an asset (image) in a paper directory."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    asset = paper_dir / filename
    if asset.is_file() and paper_dir in asset.resolve().parents:
        return asset
    return None


def archive_paper(name: str) -> tuple[bool, str]:
    if not _is_safe_paper_name(name):
        return False, f"Invalid paper name."
    src = settings.outputs_dir / name
    if not src.is_dir() or not _is_within(settings.outputs_dir, src):
        return False, f"Paper '{name}' not found in outputs."
    dest = settings.archives_dir / name
    if dest.exists():
        return False, f"'{name}' already exists in archives."
    settings.archives_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True, f"'{name}' archived."


def restore_paper(name: str) -> tuple[bool, str]:
    if not _is_safe_paper_name(name):
        return False, f"Invalid paper name."
    src = settings.archives_dir / name
    if not src.is_dir() or not _is_within(settings.archives_dir, src):
        return False, f"Paper '{name}' not found in archives."
    dest = settings.outputs_dir / name
    if dest.exists():
        return False, f"'{name}' already exists in outputs."
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True, f"'{name}' restored."


def delete_paper(name: str) -> tuple[bool, str]:
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return False, f"Paper '{name}' not found."

    # Clean up chatbot files before deletion
    chat_history_file = paper_dir / "chat_history.json"
    if chat_history_file.exists():
        try:
            chat_history_file.unlink()
        except Exception:
            pass  # Continue even if deletion fails

    chat_chunks_file = paper_dir / "chat_chunks.json"
    if chat_chunks_file.exists():
        try:
            chat_chunks_file.unlink()
        except Exception:
            pass  # Continue even if deletion fails

    size = _dir_size_mb(paper_dir)
    shutil.rmtree(str(paper_dir))
    delete_progress(name)
    delete_rating(name)
    delete_last_read(name)
    return True, f"'{name}' deleted ({size:.1f} MB freed)."


def get_stats() -> dict:
    unread = 0
    archived = 0
    if settings.outputs_dir.exists():
        unread = sum(1 for d in settings.outputs_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    if settings.archives_dir.exists():
        archived = sum(1 for d in settings.archives_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    return {"unread": unread, "archived": archived, "total": unread + archived}


def get_latest_log() -> dict | None:
    logs_dir = settings.logs_dir
    if not logs_dir.exists():
        return None
    log_files = sorted(logs_dir.glob("paperflow_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not log_files:
        return None
    latest = log_files[0]
    try:
        content = latest.read_text(encoding="utf-8", errors="replace")
        # Return last 200 lines to keep response size reasonable
        lines = content.splitlines()
        tail = _ANSI_RE.sub("", "\n".join(lines[-200:]))
        return {"filename": latest.name, "content": tail, "total_lines": len(lines)}
    except Exception:
        return None


def _safe_filename(filename: str) -> str | None:
    """Accept only a single filename component. Reject traversal / absolute paths."""
    if not filename or "\x00" in filename:
        return None
    if "/" in filename or "\\" in filename:
        return None
    if filename in {".", ".."}:
        return None
    # Path() with a single component leaves it intact; verify .name round-trip
    candidate = Path(filename).name
    if candidate != filename:
        return None
    return candidate


def save_upload(filename: str, data: bytes) -> tuple[bool, str]:
    safe = _safe_filename(filename)
    if not safe:
        return False, "Invalid filename."
    settings.newones_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.newones_dir / safe
    # Defense-in-depth: ensure dest stays under newones_dir
    if not _is_within(settings.newones_dir, dest):
        return False, "Invalid filename."
    if dest.exists():
        return False, f"'{safe}' already exists in upload queue."
    dest.write_bytes(data)
    return True, f"'{safe}' uploaded."


def _extract_pdf_text(pdf_path: Path, max_pages: int = 3) -> str:
    """Extract text from first few pages of PDF using PyPDF2."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        text = ""
        for page in reader.pages[:max_pages]:
            text += page.extract_text() or ""
        return text[:3000]
    except Exception:
        return ""


def _get_existing_papers_summary() -> list[dict]:
    """Collect title+authors from all existing paper_meta.json files."""
    papers = []
    for base, location in [(settings.outputs_dir, "outputs"), (settings.archives_dir, "archives")]:
        if not base.exists():
            continue
        for paper_dir in base.iterdir():
            if not _safe_child_dir(base, paper_dir):
                continue
            meta = _load_paper_metadata(paper_dir)
            if meta and meta.get("title"):
                papers.append({
                    "title": meta["title"],
                    "authors": meta.get("authors", []),
                    "location": location,
                    "folder": paper_dir.name,
                })
    return papers


async def check_duplicate_paper(pdf_path: Path) -> list[dict]:
    """Extract title/authors from uploaded PDF via AI, compare against existing papers.

    Returns list of similar papers: [{title, authors, location, folder}]
    Returns empty list if no duplicates or on any error (fail-open).
    """
    text = _extract_pdf_text(pdf_path)
    if not text.strip():
        return []

    existing = _get_existing_papers_summary()
    if not existing:
        return []

    existing_list = "\n".join(
        f"- [{i}] \"{p['title']}\" by {', '.join(p['authors'][:3]) if p['authors'] else 'Unknown'}"
        for i, p in enumerate(existing)
    )

    prompt = f"""From the following PDF text, extract the paper title and authors.
Then compare against the existing papers list below and identify any that appear to be the same paper (same title or very similar title with same authors).

PDF text (first pages):
---
{text}
---

Existing papers:
{existing_list}

Respond in JSON format only:
{{
  "extracted_title": "the paper title",
  "extracted_authors": ["author1", "author2"],
  "matches": [0, 3]
}}

Rules:
- A match means the same paper (not just related topic)
- Consider title variations (e.g., with/without subtitle, abbreviations)
- If unsure, do NOT include as match
- Return empty matches [] if no duplicates found"""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=os.getenv("OPENAI_BASE_URL", ""),
            api_key=os.getenv("OPENAI_API_KEY", "")
        )

        response = await client.chat.completions.create(
            model=os.getenv("TRANSLATION_MODEL", "gemini-2.5-flash"),
            messages=[
                {"role": "system", "content": "You are a metadata extraction assistant. Respond only in valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=512,
        )

        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        result = _json.loads(result_text)
        matches = result.get("matches", [])

        if not matches:
            return []

        similar = []
        for idx in matches:
            if 0 <= idx < len(existing):
                paper = existing[idx]
                similar.append({
                    "title": paper["title"],
                    "authors": paper["authors"],
                    "location": paper["location"],
                    "folder": paper["folder"],
                })
        return similar

    except Exception:
        return []


def delete_uploaded_file(filename: str) -> tuple[bool, str]:
    """Remove an uploaded file from newones/ (for duplicate skip)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return False, "Invalid filename."
    path = settings.newones_dir / filename
    if path.is_file():
        path.unlink()
        return True, f"'{filename}' removed."
    return False, "File not found in upload queue."


def get_processing_status() -> dict:
    """Read processing status file and combine with queued files in newones/."""
    from datetime import datetime, timezone

    status_path = settings.logs_dir / "processing_status.json"
    processing = {
        "current_file": None,
        "stage": "idle",
        "stage_num": 0,
        "total_stages": 0,
        "stage_label": "Idle",
        "updated_at": None,
        "error": None,
    }

    # Read status file if exists
    if status_path.is_file():
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                processing = _json.load(f)
        except Exception:
            pass

    # Check for stale status (>120s old, not idle/complete)
    stale = False
    if processing.get("updated_at") and processing.get("stage") not in ("idle", "complete"):
        try:
            updated = datetime.fromisoformat(processing["updated_at"])
            age = (datetime.now() - updated).total_seconds()
            if age > 600:
                stale = True
        except Exception:
            pass

    # List PDF files in newones/ directory (queued for processing)
    files = []
    newones = settings.newones_dir
    if newones.exists():
        pdf_files = sorted(
            [f for f in newones.iterdir() if f.is_file() and f.name.lower().endswith(".pdf")],
            key=lambda f: f.stat().st_mtime,
        )
        current_file = processing.get("current_file")
        queue_pos = 0
        for pdf in pdf_files:
            size_mb = round(pdf.stat().st_size / (1024 * 1024), 1)
            entry = {"filename": pdf.name, "size_mb": size_mb}

            if current_file and pdf.name == current_file:
                entry["status"] = "stale" if stale else "processing"
                entry["stage"] = processing.get("stage", "")
                entry["stage_num"] = processing.get("stage_num", 0)
                entry["total_stages"] = processing.get("total_stages", 0)
                entry["stage_label"] = processing.get("stage_label", "")
                entry["sub_progress"] = processing.get("sub_progress") or 0
                if processing.get("detail"):
                    entry["detail"] = processing["detail"]
                if processing.get("error"):
                    entry["error"] = processing["error"]
            else:
                queue_pos += 1
                entry["status"] = "queued"
                entry["queue_position"] = queue_pos

            files.append(entry)

    return {"files": files, "processing": processing}


def delete_queued_file(filename: str) -> tuple[bool, str]:
    """Delete a queued PDF from newones/ directory. Only allows deleting files not currently being processed."""
    from datetime import datetime

    # Sanitize: prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return False, "Invalid filename."

    filepath = settings.newones_dir / filename
    if not filepath.is_file():
        return False, f"'{filename}' not found in queue."

    # Check if this file is currently being processed
    status_path = settings.logs_dir / "processing_status.json"
    if status_path.is_file():
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                processing = _json.load(f)
            current = processing.get("current_file")
            stage = processing.get("stage", "idle")
            if current == filename and stage not in ("idle", "complete", "error"):
                return False, f"'{filename}' is currently being processed. Cannot delete."
        except Exception:
            pass

    try:
        filepath.unlink()
        return True, f"'{filename}' removed from queue."
    except Exception as e:
        return False, f"Failed to delete '{filename}': {e}"


def request_cancel_processing(filename: str, delete_file: bool = True, force: bool = True) -> tuple[bool, str]:
    """Request cancellation for a processing file.

    - If currently processing: enqueue cancel request for converter watchdog.
    - If queued only: delete immediately when delete_file=True.
    """
    from ..config import settings  # lazy import so test fixtures can replace settings
    if "/" in filename or "\\" in filename or ".." in filename:
        return False, "Invalid filename."

    status_path = settings.logs_dir / "processing_status.json"
    cancel_path = settings.logs_dir / "cancel_requests.json"
    filepath = settings.newones_dir / filename

    current = None
    stage = "idle"
    if status_path.is_file():
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                st = _json.load(f)
            current = st.get("current_file")
            stage = st.get("stage", "idle")
        except Exception:
            pass

    is_processing = (current == filename and stage not in ("idle", "complete", "error"))

    # queued (not processing): delete now if requested
    if not is_processing:
        if delete_file and filepath.exists():
            try:
                filepath.unlink()
                # cleanup sidecars + partial outputs
                stem = Path(filename).stem
                for side in [
                    settings.newones_meta_dir / f"{filename}.url.txt",
                    settings.newones_dir / f"{filename}.url.txt",
                ]:
                    try:
                        if side.exists():
                            side.unlink()
                    except Exception:
                        pass

                out_by_stem = settings.outputs_dir / stem
                if out_by_stem.exists() and out_by_stem.is_dir():
                    shutil.rmtree(out_by_stem, ignore_errors=True)

                # remove any output folder that already contains the source pdf
                if settings.outputs_dir.exists():
                    for d in settings.outputs_dir.iterdir():
                        if d.is_dir() and (d / filename).exists():
                            shutil.rmtree(d, ignore_errors=True)

                return True, f"'{filename}' removed from queue (with partial outputs)."
            except Exception as e:
                return False, f"Failed to delete '{filename}': {e}"
        return True, f"Cancel request accepted for '{filename}'."

    # processing: write cancel request for converter watchdog
    payload = {"requests": []}
    if cancel_path.is_file():
        try:
            with open(cancel_path, "r", encoding="utf-8") as f:
                payload = _json.load(f) or {"requests": []}
        except Exception:
            payload = {"requests": []}

    reqs = payload.get("requests") or []
    # dedupe by filename
    reqs = [r for r in reqs if r.get("filename") != filename]
    reqs.append({
        "filename": filename,
        "delete_file": bool(delete_file),
        "force": bool(force),
        "requested_at": _dt.datetime.now().isoformat(),
    })
    payload["requests"] = reqs

    try:
        cancel_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(cancel_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, cancel_path)
        return True, f"Cancel requested for '{filename}'."
    except Exception as e:
        return False, f"Failed to request cancel: {e}"


# ── Reading Progress ───────────────────────────────────────────────────────

_PROGRESS_FILE = "reading_progress.json"


def _progress_path() -> Path:
    return settings.outputs_dir / _PROGRESS_FILE


def get_all_progress() -> dict[str, int]:
    path = _progress_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def save_progress(paper_name: str, progress: int) -> bool:
    progress = max(0, min(100, progress))
    data = get_all_progress()
    data[paper_name] = progress
    try:
        with open(_progress_path(), "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def delete_progress(paper_name: str) -> None:
    data = get_all_progress()
    if paper_name in data:
        del data[paper_name]
        try:
            with open(_progress_path(), "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass


# ── Last Read Timestamp ───────────────────────────────────────────────────

_LAST_READ_FILE = "paper_last_read.json"


def _last_read_path() -> Path:
    return settings.outputs_dir / _LAST_READ_FILE


def get_all_last_read() -> dict[str, str]:
    path = _last_read_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def touch_last_read(paper_name: str) -> bool:
    if not _is_safe_paper_name(paper_name):
        return False
    data = get_all_last_read()
    data[paper_name] = _dt.datetime.now().isoformat()
    try:
        with open(_last_read_path(), "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def delete_last_read(paper_name: str) -> None:
    if not _is_safe_paper_name(paper_name):
        return
    data = get_all_last_read()
    if paper_name in data:
        del data[paper_name]
        try:
            with open(_last_read_path(), "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass


# ── Paper Ratings ─────────────────────────────────────────────────────────

_RATINGS_FILE = "paper_ratings.json"


def _ratings_path() -> Path:
    return settings.outputs_dir / _RATINGS_FILE


def get_all_ratings() -> dict[str, int]:
    path = _ratings_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def save_rating(paper_name: str, rating: int) -> bool:
    rating = max(0, min(5, rating))
    data = get_all_ratings()
    if rating == 0:
        data.pop(paper_name, None)
    else:
        data[paper_name] = rating
    try:
        with open(_ratings_path(), "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def delete_rating(paper_name: str) -> None:
    data = get_all_ratings()
    if paper_name in data:
        del data[paper_name]
        try:
            with open(_ratings_path(), "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass
