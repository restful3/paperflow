#!/usr/bin/env python3
import gc
import json
import os
import re
import subprocess
import time
from pathlib import Path
import base64
from datetime import datetime
import shutil
import sys
import urllib.request
from urllib.parse import urlparse
from html.parser import HTMLParser
import fcntl
from contextlib import contextmanager


@contextmanager
def _gpu_lock(timeout=1800, poll=2.0):
    """converter(MinerU)↔TTS 사이드카 GPU 상호배제용 공유 flock.
    tts_service/app/gpulock.py 와 동일 로직을 인라인 복제(컨테이너 간 import 불가).
    같은 호스트 inode(./outputs/.gpu.lock)면 컨테이너가 달라도 상호배제된다.
    """
    lockpath = os.environ.get("PF_GPU_LOCK", "/app/outputs/.gpu.lock")
    os.makedirs(os.path.dirname(lockpath), exist_ok=True)
    fh = open(lockpath, "w")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() > deadline:
                fh.close(); raise TimeoutError("GPU lock timeout")
            time.sleep(poll)
    try:
        yield fh
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()


# Marker-pdf imports
MARKER_AVAILABLE = False
try:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    MARKER_AVAILABLE = True
except ImportError:
    pass

# MinerU imports
MINERU_AVAILABLE = False
try:
    from mineru.cli.common import do_parse, read_fn as mineru_read_fn
    MINERU_AVAILABLE = True
except ImportError:
    pass

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    """Print colored header"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}\n")

def print_info(text):
    """Print info message"""
    print(f"{Colors.OKCYAN}ℹ {text}{Colors.ENDC}")

def print_success(text):
    """Print success message"""
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")

def print_warning(text):
    """Print warning message"""
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")

def print_error(text):
    """Print error message"""
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")

def print_progress(current, total, text=""):
    """Print progress bar"""
    percent = (current / total) * 100
    bar_length = 50
    filled = int(bar_length * current / total)
    bar = '█' * filled + '░' * (bar_length - filled)
    print(f"\r{Colors.OKBLUE}[{bar}] {percent:.1f}% {text}{Colors.ENDC}", end='', flush=True)
    if current == total:
        print()

def _count_active_stages(pipeline):
    """Count the number of active pipeline stages for progress tracking."""
    count = 0
    if pipeline.get("convert_to_markdown", True):
        count += 1
    if pipeline.get("extract_metadata", False):
        count += 1
    if pipeline.get("check_duplicate", True) and pipeline.get("extract_metadata", False):
        count += 1
    if pipeline.get("select_cover", True) and pipeline.get("extract_metadata", False):
        count += 1
    if pipeline.get("translate_to_korean", False):
        count += 1
    return max(count, 1)


def _find_source_url_sidecar(pdf_path):
    """Find imported source URL sidecar for a PDF file.

    Returns URL string or None.
    """
    pdf_name = os.path.basename(pdf_path)
    candidates = [
        os.path.join("newones", ".meta", f"{pdf_name}.url.txt"),
        os.path.join("newones", f"{pdf_name}.url.txt"),
    ]
    for c in candidates:
        try:
            if os.path.isfile(c):
                with open(c, "r", encoding="utf-8") as f:
                    u = f.read().strip()
                if u.startswith(("http://", "https://")):
                    return u
        except Exception:
            continue
    return None


class _SimpleHTMLTextExtractor(HTMLParser):
    """Very lightweight HTML → Markdown extractor with basic block separation."""

    BLOCK_TAGS = {"p", "div", "section", "article", "main", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "blockquote"}
    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_depth = 0
        self._pre_depth = 0
        self._inline_code_depth = 0

    def handle_starttag(self, tag, attrs):
        t = (tag or "").lower()
        if t in self.SKIP_TAGS:
            self._skip_depth += 1
        if self._skip_depth > 0:
            return
        if t == "pre":
            self._pre_depth += 1
            self.parts.append("\n\n```\n")
        elif t == "code":
            if self._pre_depth == 0:
                self._inline_code_depth += 1
                self.parts.append("`")
        elif re.fullmatch(r"h[1-6]", t):
            self.parts.append("\n\n" + ("#" * int(t[1])) + " ")
        elif t == "li":
            self.parts.append("\n- ")
        elif t in self.BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        t = (tag or "").lower()
        if t in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if t == "pre" and self._pre_depth > 0:
            self._pre_depth -= 1
            self.parts.append("\n```\n")
        elif t == "code" and self._pre_depth == 0 and self._inline_code_depth > 0:
            self._inline_code_depth -= 1
            self.parts.append("`")
        elif t in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._pre_depth > 0:
            self.parts.append(data or "")
            return
        if self._inline_code_depth > 0:
            self.parts.append((data or "").strip())
            return
        s = (data or "").strip()
        if not s:
            return
        self.parts.append(s + " ")

    def get_text(self):
        txt = "".join(self.parts)
        txt = re.sub(r"\n{3,}", "\n\n", txt)
        segments = re.split(r'(```[\s\S]*?```)', txt)
        for idx, segment in enumerate(segments):
            if segment.startswith("```"):
                continue
            segments[idx] = re.sub(r"[ \t]{2,}", " ", segment)
        txt = "".join(segments)
        return txt.strip()


# arXiv(및 유사 학술 사이트) 초록 랜딩페이지 스크랩에만 등장하는 보일러플레이트 표식.
# URL-first HTML 추출이 /abs/ 같은 랜딩페이지를 긁어 본문 대신 채워 넣는 것을 감지한다.
_LANDING_PAGE_MARKERS = (
    "View a PDF of the paper",
    "Submission history",
    "arXivLabs",
    "Connected Papers",
    "Bibliographic Explorer",
    "Which authors of this paper are endorsers",
    "export BibTeX citation",
)


def _looks_like_paper_landing_page(text: str) -> bool:
    """True iff the markdown looks like a scraped arXiv(-style) abstract landing
    page rather than the paper body. URL-first HTML 추출 결과가 이에 해당하면
    거부하고 실제 PDF 변환으로 폴백시킨다(2개 이상 표식일 때만 판정 → 우연한
    단일 언급 오탐 방지)."""
    if not text:
        return False
    return sum(1 for m in _LANDING_PAGE_MARKERS if m in text) >= 2


def _md_is_landing_page(md_path: str) -> bool:
    """md_path 파일을 읽어 랜딩페이지 스크랩인지 판정(읽기 실패 시 False)."""
    try:
        with open(md_path, encoding="utf-8", errors="ignore") as f:
            return _looks_like_paper_landing_page(f.read())
    except OSError:
        return False


# 알려진 논문 랜딩/원문 route. 이 URL 들은 스크랩해 봤자 초록 랜딩페이지라
# URL-first 를 태우지 않고 큐의 실제 PDF 를 변환한다. host 단위가 아니라
# route 단위로 제한한다 — 예: huggingface.co/papers 는 논문, /blog 는 아티클.
_PAPER_LANDING_ROUTES = (
    ("arxiv.org", ("/abs/", "/pdf/")),
    ("doi.org", ("/",)),
    ("dx.doi.org", ("/",)),
    ("openreview.net", ("/forum", "/pdf")),
    ("biorxiv.org", ("/content/",)),
    ("medrxiv.org", ("/content/",)),
    ("alphaxiv.org", ("/abs/", "/paper/", "/papers/")),
    ("huggingface.co", ("/papers/",)),
)


def _is_paper_landing_url(url: str) -> bool:
    """True iff url 이 알려진 논문 랜딩/원문 route 에 해당."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    host = (p.netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    path = p.path or "/"
    for h, prefixes in _PAPER_LANDING_ROUTES:
        if host == h and any(path.startswith(pre) for pre in prefixes):
            return True
    return False


def _url_to_markdown_html_first(source_url, output_dir, base_name, timeout=20):
    """Try URL-first extraction and write markdown.

    Returns (md_path, info_dict) or (None, info_dict on failure)
    """
    info = {"stage": "html_primary", "url": source_url, "ok": False, "reason": ""}
    try:
        req = urllib.request.Request(source_url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read()
        if "html" not in ctype and not source_url.lower().startswith(("http://", "https://")):
            info["reason"] = f"non-html content-type: {ctype}"
            return None, info

        html = raw.decode("utf-8", errors="ignore")
        parser = _SimpleHTMLTextExtractor()
        parser.feed(html)
        text = parser.get_text()

        # Basic quality floor for HTML extraction
        if len(text) < 1200:
            info["reason"] = f"too-short extracted text ({len(text)} chars)"
            return None, info

        # Build simple markdown body
        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else base_name
        text, fence_report = normalize_code_fence_languages(text)
        md_path = os.path.join(output_dir, f"{base_name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n")
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")

        info["ok"] = True
        info["chars"] = len(text)
        info["code_fence_normalization"] = fence_report
        return md_path, info
    except Exception as e:
        info["reason"] = str(e)
        return None, info


def _url_to_markdown_browser_fallback(source_url, output_dir, base_name, timeout=25):
    """Fallback extractor for JS-heavy pages.

    Uses jina AI readability mirror as a browser-like rendered-text fallback.
    Returns (md_path, info_dict) or (None, info_dict).
    """
    info = {"stage": "browser_fallback", "url": source_url, "ok": False, "reason": ""}
    try:
        mirror_url = f"https://r.jina.ai/http://{source_url.replace('https://', '').replace('http://', '')}"
        req = urllib.request.Request(mirror_url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()

        text = raw.decode("utf-8", errors="ignore").strip()
        # mirror preamble cleanup
        text = re.sub(r"^Title:\s*.*?\n+", "", text, flags=re.I)
        text = re.sub(r"^URL Source:\s*.*?\n+", "", text, flags=re.I)
        text = re.sub(r"^Markdown Content:\s*\n+", "", text, flags=re.I)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        text, fence_report = normalize_code_fence_languages(text)

        if len(text) < 1200:
            info["reason"] = f"too-short fallback text ({len(text)} chars)"
            return None, info

        md_path = os.path.join(output_dir, f"{base_name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {base_name}\n\n")
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")

        info["ok"] = True
        info["chars"] = len(text)
        info["mirror"] = "r.jina.ai"
        info["code_fence_normalization"] = fence_report
        return md_path, info
    except Exception as e:
        info["reason"] = str(e)
        return None, info


def _discard_landing_md(md_path, stage_label):
    """랜딩페이지로 판정된 md 를 삭제. 삭제 성공/실패와 무관하게 경고만 남긴다."""
    print_warning(f"{stage_label} result looks like an arXiv abstract landing-page scrape — discarding to convert the real PDF instead")
    try:
        os.remove(md_path)
    except OSError:
        pass


def _try_url_first_extraction(source_url, output_dir, base_name, pipeline):
    """URL-first(HTML → browser fallback) 추출 시도.

    성공 시 md_path, 실패(=PDF 변환으로 폴백해야 함) 시 None 반환.

    가드 2중:
    - Fix B: 알려진 논문 랜딩 URL 이면 스크랩해 봤자 초록이므로 전체 스킵
    - Fix A: 1차 추출이 랜딩페이지로 판정되어 폐기됐으면 같은 URL 을
      browser fallback 으로 재시도하지 않는다 (판정 대상은 URL 자체이므로;
      r.jina.ai 출력은 마커가 제거돼 내용 가드를 비결정적으로 통과했었다)
    """
    if _is_paper_landing_url(source_url):
        print_info(f"Paper landing URL detected — skipping URL-first, converting the queued PDF: {source_url}")
        return None

    md_path, html_info = _url_to_markdown_html_first(source_url, output_dir, base_name)
    if md_path and _md_is_landing_page(md_path):
        _discard_landing_md(md_path, "URL-first")
        md_path = None
        html_info["reason"] = "discarded_paper_landing_page"
        print_warning("Skipping browser fallback for the same landing URL -> fallback to PDF converter")
        return None
    if md_path:
        print_success(f"URL-first extraction complete ({html_info.get('chars', 0)} chars): {md_path}")
        return md_path
    print_warning(f"URL-first extraction failed: {html_info.get('reason', 'unknown')}")

    if not pipeline.get("browser_fallback", True):
        return None
    print_info("Trying browser fallback extraction...")
    md_path, binfo = _url_to_markdown_browser_fallback(source_url, output_dir, base_name)
    if md_path and _md_is_landing_page(md_path):
        _discard_landing_md(md_path, "Browser fallback")
        md_path = None
        binfo["reason"] = "discarded_paper_landing_page"
    if md_path:
        print_success(f"Browser fallback extraction complete ({binfo.get('chars', 0)} chars): {md_path}")
        return md_path
    print_warning(f"Browser fallback failed: {binfo.get('reason', 'unknown')} -> fallback to PDF converter")
    return None


def write_processing_status(filename, stage, stage_num, total_stages, stage_label, error=None, detail=None, sub_progress=None):
    """Write processing status to shared JSON file for viewer polling."""
    status = {
        "current_file": filename,
        "stage": stage,
        "stage_num": stage_num,
        "total_stages": total_stages,
        "stage_label": stage_label,
        "updated_at": datetime.now().isoformat(),
        "error": error,
        "detail": detail,
        "sub_progress": sub_progress,
    }
    status_path = os.path.join("logs", "processing_status.json")
    try:
        tmp_path = status_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False)
        os.replace(tmp_path, status_path)
    except Exception:
        pass

def load_config():
    """Load config.json or return defaults"""
    default_config = {
        "processing_pipeline": {
            "convert_to_markdown": True,
            "normalize_headings": True,
            "extract_metadata": True,
            "select_cover": True,
            "translate_to_korean": False,
        },
        "cover_selection": {
            "max_candidates": 6,
            "min_dimension": 200,
            "downscale_px": 768,
            "timeout_seconds": 60,
            "max_retries": 2,
        },
        "metadata_extraction": {
            "max_input_chars": 8000,
            "temperature": 0.1,
            "max_tokens": 2048,
            "timeout_seconds": 60,
            "max_retries": 2,
            "retry_delay_seconds": 2,
            "smart_rename": True,
            "max_folder_name_length": 80
        },
        "converter": {
            "mineru": {
                "backend": "pipeline",
                "parse_method": "auto",
                "lang": "en",
            }
        },
        "translation": {
            "max_retries": 3,
            "retry_delay_seconds": 2,
            "timeout_seconds": 300,
            "max_section_chars": 3000,
            "verify_translation": True,
            "enable_parallel_translation": True,
            "parallel_max_workers": 3,
            "parallel_min_chunks": 2
        }
    }

    try:
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
                # Load top-level config sections with merge
                for key in list(default_config.keys()):
                    if key in loaded:
                        if isinstance(default_config[key], dict) and isinstance(loaded[key], dict):
                            default_config[key].update(loaded[key])
                        else:
                            default_config[key] = loaded[key]
    except Exception as e:
        print_warning(f"Config load failed, using defaults: {e}")

    # Auto-activate dependencies
    pipeline = default_config["processing_pipeline"]

    if pipeline.get("translate_to_korean", False):
        # Translation requires markdown conversion
        pipeline["convert_to_markdown"] = True

    if pipeline.get("extract_metadata", False):
        # Metadata extraction requires markdown conversion
        pipeline["convert_to_markdown"] = True

    return default_config

def load_prompt():
    """Load prompt.md or return default translation prompt"""
    default_prompt = """You are a professional academic translator specializing in English-to-Korean translation. Translate the given Markdown text into natural, fluent Korean.

**Critical - Completeness:**
- Translate EVERY sentence completely. Do NOT skip, omit, summarize, or condense any content.
- The translation must cover 100% of the source text. Every paragraph, every sentence must appear in the output.
- If the input has N paragraphs, the output MUST also have N paragraphs.
- Do NOT add any content that is not in the original text.
- Do NOT add any headings (#, ##, ###, etc.) that do not exist in the source text.
- If the text begins mid-sentence (a continuation), translate it starting from exactly where it begins — do NOT prepend any title or heading.
- Never replace content with "..." or "(이하 생략)" or similar.
- Translate figure/table captions and footnotes fully.
- Skip web boilerplate (cookie notices, privacy banners, navigation menus, sidebar links) — leave them untranslated as-is.

**Core Rules:**
- Use formal Korean academic writing style (합니다체).
- **Strictly preserve all Markdown structure**: headers (#, ##, ###), bold/italics, lists, tables, links, image references.
- **Preserve all mathematical equations** ($...$, $$...$$, LaTeX) — keep the math notation intact but **fix OCR artifacts**:
  - Remove excessive spaces in LaTeX commands: `\\mathrm { A P I }` → `\\mathrm{API}`, `\\mathbf { e }` → `\\mathbf{e}`
  - Fix spaced subscripts/superscripts: `a _ { c }` → `a_{c}`, `x ^ { 2 }` → `x^{2}`
  - Fix spaced environments: `\\begin{array} { c }` → `\\begin{array}{c}`
  - Replace `\\mathrm{min}`, `\\mathrm{max}`, `\\mathrm{log}` etc. with standard LaTeX operators `\\min`, `\\max`, `\\log`
  - Fix bare angle brackets used as delimiters in math: `< \\mathrm{API} >` → `\\langle \\mathrm{API} \\rangle`
  - Do NOT change the mathematical meaning — only fix spacing and OCR noise.
- **Preserve all code blocks** (```...```) exactly as-is.
- **Preserve all citations** ([1], (Smith et al., 2023), <sup>1</sup>) unchanged.
- Translate table cell text only; preserve all table delimiters (|, ---).
- Fix incorrect table syntax during translation if needed.

**Terminology - Parenthetical Glossing Rules:**
- On FIRST occurrence only of a specialized/unfamiliar term, use: 한국어 (English)
  - Example: 미세조정 (fine-tuning), 환각 (hallucination)
- After the first occurrence, use the Korean term ONLY — do NOT repeat the English in parentheses.
- NEVER gloss common terms that Korean tech readers already know. Use them directly without parentheses:
  아키텍처, 프레임워크, 파이프라인, 워크플로, 모듈, 인터페이스, 알고리즘, 데이터셋, 벤치마크, 서버, 클라이언트, 배포, 인스턴스, 플랫폼, 프로토콜, API, GPU, CPU, CUDA, REST, HTTP, JSON, LLM, Transformer
- Use consistent Korean translations throughout — pick ONE translation and stick with it:
  - fine-tuning → 미세조정 (not 파인튜닝)
  - baseline → 기준선 (not 베이스라인)
  - workflow → 워크플로 (not 워크플로우)
  - perplexity → 퍼플렉시티
  - hallucination → 환각
  - inference → 추론
  - embedding → 임베딩
  - training → 학습
  - reasoning trace → 추론 과정

**Style - Natural Korean:**
- Translate English idioms into natural Korean equivalents, NOT literally:
  - "light years ahead" → "한참 앞서" (NOT "수광년 앞서")
  - "every fiber of my being" → "온 마음을 다해" (NOT "존재의 모든 섬유로")
  - "best of both worlds" → "양쪽 장점을 모두 취하여"
  - "poached by X" → "X에 스카우트되어"
- In academic papers, always use "우리" for "we" (NOT "저희" — 저희 is overly humble for academic writing).
- Output ONLY Korean and English. You MUST NOT output any other language (Hindi, Chinese, Japanese, etc.). If unsure of a term, keep the English original rather than guessing in another language.
- Output ONLY the translated Korean text. No explanations, comments, or meta-text.
- If input is already Korean, pass through unchanged.

Translate the following Markdown text into Korean:"""

    try:
        if os.path.exists("prompt.md"):
            with open("prompt.md", "r", encoding="utf-8") as f:
                return f.read()
    except:
        pass

    return default_prompt

def json_to_markdown(json_data, output_md_file, images_dir='img'):
    """Convert JSON to Markdown"""
    if not os.path.exists(images_dir):
        os.makedirs(images_dir)

    markdown_lines = []

    def process_element(element, indent=0):
        if isinstance(element, dict):
            for key, value in element.items():
                if key == "output":
                    process_element(value, indent)
                else:
                    if key in ["format", "metadata", "success"]:
                        continue
                    if key.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
                        if isinstance(value, str):
                            ext = key.split('.')[-1]
                            image_filename = f"{key}"
                            image_path = os.path.join(images_dir, image_filename)
                            with open(image_path, 'wb') as f:
                                f.write(base64.b64decode(value))
                            image_link = f"![]({image_filename})"
                            markdown_lines.append(image_link)
                    else:
                        markdown_lines.append(f"{ '#' * (indent + 1)} {key}\n")
                        process_element(value, indent + 1)
        elif isinstance(element, list):
            for item in element:
                process_element(item, indent)
        else:
            markdown_lines.append(f"{element}\n")

    process_element(json_data)

    with open(output_md_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(markdown_lines))

    return output_md_file

def fix_author_code_blocks(markdown_text):
    """
    Remove code blocks that contain <sup> tags (author affiliations).
    marker-pdf sometimes wraps author sections in code blocks, which causes
    HTML tags to render as literal text instead of being processed.
    """
    import re
    # Pattern to match code blocks containing <sup> tags
    pattern = r'```\n([\s\S]*?<sup>[\s\S]*?)\n```'

    def replace_code_block(match):
        # Extract content inside code block
        content = match.group(1)
        # Return content without code block markers
        return content

    # Replace all matching code blocks
    fixed_text = re.sub(pattern, replace_code_block, markdown_text)
    return fixed_text


_CODE_LANG_ALIASES = {
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "ts": "typescript",
    "yml": "yaml",
}


def _normalize_code_language(lang):
    lang = (lang or "").strip().lower()
    return _CODE_LANG_ALIASES.get(lang, lang)


def _infer_code_language(block_text):
    """Infer a useful Markdown code fence language from block content."""
    import json as _json

    raw_lines = block_text.splitlines()
    lines = [ln.rstrip() for ln in raw_lines]
    nonempty = [ln.strip() for ln in lines if ln.strip()]
    if not nonempty:
        return "", block_text, False

    first = nonempty[0].strip().strip('"\'`').lower()
    known_langs = {
        "bash", "sh", "shell", "python", "python3", "py", "javascript", "js",
        "typescript", "ts", "json", "yaml", "yml", "sql", "html", "xml",
        "go", "golang", "java", "cpp", "c++", "c", "rust", "toml",
        "markdown", "md", "text",
    }

    removed_lang_line = False
    if first in known_langs and len(nonempty) > 1:
        # marker/LLM outputs occasionally place a quoted language marker as
        # the first content line of an otherwise unlabeled fence.
        for idx, ln in enumerate(lines):
            if ln.strip():
                del lines[idx]
                removed_lang_line = True
                break
        block_text = "\n".join(lines)
        return _normalize_code_language(first), block_text, removed_lang_line

    sample = "\n".join(nonempty[:40])

    if sample.startswith(("{", "[")):
        try:
            _json.loads(sample)
            return "json", block_text, False
        except Exception:
            pass

    if re.search(r'^\s*(def|class|async\s+def)\s+\w+|^\s*(from|import)\s+\w+|if\s+__name__\s*==', sample, re.M):
        return "python", block_text, False
    if re.search(r'^\s*package\s+main\b|^\s*func\s+\w+\s*\(', sample, re.M):
        return "go", block_text, False
    if re.search(r'^\s*(const|let|var)\s+\w+\s*=|^\s*(export|import)\s+|^\s*interface\s+\w+|=>', sample, re.M):
        return "typescript", block_text, False
    if re.search(r'^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)\b|^\s*FROM\s+\w+', sample, re.I | re.M):
        return "sql", block_text, False
    if re.search(r'^\s*(curl|wget|pip|uv|npm|pnpm|yarn|docker|git|python|pytest)\b|\$\s+\w+', sample, re.M):
        return "bash", block_text, False
    if re.search(r'^\s*#include\s+<|^\s*(int|void|auto)\s+\w+\s*\(', sample, re.M):
        return "cpp", block_text, False
    if re.search(r'<\/?[A-Za-z][^>]*>', sample):
        return "html", block_text, False
    if re.search(r'^\s*[A-Za-z0-9_.-]+:\s+.+$', sample, re.M) and not re.search(r'[;{}]', sample):
        return "yaml", block_text, False
    if re.search(r'[├└│─→↓←↑]|^\s*\[[^\]]+\]\s+', sample, re.M):
        return "text", block_text, False

    return "", block_text, False


def normalize_code_fence_languages(markdown_text):
    """Normalize fenced code blocks and add language hints where obvious.

    Returns:
        (normalized_markdown, report_dict)
    """
    lines = markdown_text.splitlines()
    out = []
    report = {
        "normalized_tilde_fences": 0,
        "inferred_code_languages": 0,
        "removed_stray_language_lines": 0,
        "unlabeled_code_fences": 0,
    }
    i = 0
    while i < len(lines):
        m = re.match(r'^(\s*)(`{3,}|~{3,})([^`]*)$', lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue

        indent, fence, info = m.group(1), m.group(2), m.group(3).strip()
        if fence.startswith("~"):
            report["normalized_tilde_fences"] += 1

        block_lines = []
        i += 1
        closed = False
        while i < len(lines):
            if re.match(r'^\s*(`{3,}|~{3,})\s*$', lines[i]):
                closed = True
                i += 1
                break
            block_lines.append(lines[i])
            i += 1

        block_text = "\n".join(block_lines)
        lang = _normalize_code_language(info.split()[0]) if info else ""
        if not lang:
            lang, block_text, removed_lang_line = _infer_code_language(block_text)
            if lang:
                report["inferred_code_languages"] += 1
            else:
                report["unlabeled_code_fences"] += 1
            if removed_lang_line:
                report["removed_stray_language_lines"] += 1

        opener = f"{indent}```{lang}" if lang else f"{indent}```"
        out.append(opener)
        if block_text:
            out.extend(block_text.splitlines())
        if closed:
            out.append(f"{indent}```")

    trailing_newline = "\n" if markdown_text.endswith("\n") else ""
    return "\n".join(out) + trailing_newline, report


def convert_pdf_to_md(pdf_path, output_dir):
    """Convert PDF to MD using Marker-pdf library"""
    if not MARKER_AVAILABLE:
        print_error("marker-pdf library not installed!")
        print_info("Install it with: pip install marker-pdf")
        return None

    try:
        print_info(f"Loading PDF: {pdf_path}")
        print_info(f"PDF file size: {os.path.getsize(pdf_path) / (1024*1024):.2f} MB")

        # Force GPU mode only - fail if GPU is not available
        import torch
        if not torch.cuda.is_available():
            print_error("CUDA is not available. GPU is required for this application.")
            raise RuntimeError("GPU (CUDA) is required but not available. Please check your PyTorch installation and GPU drivers.")

        # Check GPU memory with error recovery
        try:
            gpu_mem_free = torch.cuda.mem_get_info()[0] / (1024**3)  # GB
            gpu_mem_total = torch.cuda.mem_get_info()[1] / (1024**3)  # GB
            print_info(f"GPU memory: {gpu_mem_free:.2f} GB free / {gpu_mem_total:.2f} GB total")
        except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
            # CUDA context is corrupted, try to reset
            print_warning(f"GPU memory check failed: {e}")
            print_info("Attempting to reset CUDA context...")
            try:
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                torch.cuda.reset_peak_memory_stats()
                # Try again after reset
                gpu_mem_free = torch.cuda.mem_get_info()[0] / (1024**3)
                gpu_mem_total = torch.cuda.mem_get_info()[1] / (1024**3)
                print_success("CUDA context reset successful")
                print_info(f"GPU memory: {gpu_mem_free:.2f} GB free / {gpu_mem_total:.2f} GB total")
            except Exception as reset_error:
                print_error(f"CUDA reset failed: {reset_error}")
                print_error("GPU is in corrupted state. Please restart Python process or reboot system.")
                raise RuntimeError("CUDA context is corrupted and cannot be recovered")

        # Always use GPU
        device = "cuda"
        dtype = torch.float16
        print_success(f"Using GPU mode (forced)")

        # Create model dict (this loads the AI models)
        print_info(f"Loading Marker-pdf models on GPU... (this may take a minute)")
        model_dict = create_model_dict(device=device, dtype=dtype)

        # Create converter
        converter = PdfConverter(
            artifact_dict=model_dict,
            config={
                "use_llm": False,  # Set to True if you want LLM-based table recognition
                "force_ocr": False,  # Set to True to force OCR on all pages
            }
        )

        # Convert PDF
        print_info("Converting PDF to Markdown (this may take several minutes)...")
        rendered = converter(pdf_path)

        # Extract text and images
        print_info("Extracting markdown and images...")
        full_text, images, metadata = text_from_rendered(rendered)

        # Debug: Check what we got
        print_info(f"Images type: {type(images)}, value: {images if isinstance(images, str) else 'dict/list'}")
        print_info(f"Rendered has images attr: {hasattr(rendered, 'images')}")
        if hasattr(rendered, 'images'):
            print_info(f"Rendered.images type: {type(rendered.images)}")

        # Fix author sections wrapped in code blocks
        print_info("Post-processing markdown (removing code blocks around author sections)...")
        full_text = fix_author_code_blocks(full_text)
        full_text, fence_report = normalize_code_fence_languages(full_text)
        if sum(fence_report.values()) > 0:
            print_info(f"Code fence normalization applied: {fence_report}")

        # Save markdown
        md_path = os.path.join(output_dir, os.path.basename(pdf_path).replace('.pdf', '.md'))
        print_info(f"Saving markdown to: {md_path}")
        # Ensure output directory exists (guards against Docker bind mount sync issues)
        if not os.path.isdir(output_dir):
            print_warning(f"Output directory missing, recreating: {output_dir}")
            os.makedirs(output_dir, exist_ok=True)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(full_text)

        # Save images - check rendered object structure
        image_count = 0
        if hasattr(rendered, 'images') and rendered.images:
            print_info(f"Found images in rendered object: {len(rendered.images)} page(s) with images")
            for page_idx, page_images in rendered.images.items():
                # page_images could be a single Image or a list of Images
                if not isinstance(page_images, list):
                    page_images = [page_images]

                print_info(f"  Page {page_idx}: {len(page_images)} image(s)")
                for img_idx, img in enumerate(page_images):
                    # Generate image filename - page_idx is already a string like "_page_1_Figure_0.jpeg"
                    # Extract just the page number if it's already formatted
                    if isinstance(page_idx, str) and page_idx.startswith('_page_'):
                        img_name = page_idx  # Use as-is
                    else:
                        img_name = f"_page_{page_idx}_Figure_{img_idx}.jpeg"

                    img_path = os.path.join(output_dir, img_name)

                    # Save image
                    try:
                        if hasattr(img, 'save'):
                            # PIL Image object
                            img.save(img_path)
                            print_info(f"    Saved: {img_name}")
                            image_count += 1
                        elif isinstance(img, bytes):
                            # Raw bytes
                            with open(img_path, 'wb') as f:
                                f.write(img)
                            print_info(f"    Saved: {img_name}")
                            image_count += 1
                        else:
                            print_warning(f"    Unknown image type for {img_name}: {type(img)}")
                    except Exception as e:
                        print_error(f"    Failed to save {img_name}: {e}")

        if image_count > 0:
            print_success(f"Saved {image_count} image(s)")
        else:
            print_warning("No images extracted from PDF")

        # Save metadata as JSON
        json_path = os.path.join(output_dir, os.path.basename(pdf_path).replace('.pdf', '.json'))
        print_info(f"Saving metadata to: {json_path}")

        # Convert metadata to JSON-serializable format
        def make_serializable(obj):
            """Convert non-serializable objects to strings"""
            if isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_serializable(item) for item in obj]
            elif hasattr(obj, '__dict__'):
                # Object with attributes - convert to string
                return str(obj)
            else:
                try:
                    json.dumps(obj)
                    return obj
                except (TypeError, ValueError):
                    return str(obj)

        metadata_dict = make_serializable(metadata) if metadata else {}

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata_dict, f, ensure_ascii=False, indent=4)

        print_success(f"PDF conversion complete")

        # Explicitly release GPU memory to allow batch processing
        try:
            import gc
            print_info("Releasing GPU memory...")

            # Get memory before cleanup
            if torch.cuda.is_available():
                mem_before = torch.cuda.memory_allocated() / (1024**3)  # GB
                print_info(f"GPU memory allocated before cleanup: {mem_before:.2f} GB")

            # Delete large objects
            del model_dict
            del converter
            del rendered
            if 'full_text' in locals():
                del full_text
            if 'metadata' in locals():
                del metadata

            # Force garbage collection
            gc.collect()

            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()

                mem_after = torch.cuda.memory_allocated() / (1024**3)  # GB
                mem_freed = mem_before - mem_after
                gpu_mem_free_now = torch.cuda.mem_get_info()[0] / (1024**3)

                print_success(f"GPU memory freed: {mem_freed:.2f} GB")
                print_info(f"GPU memory available: {gpu_mem_free_now:.2f} GB")
        except Exception as e:
            print_warning(f"GPU cleanup warning: {e}")

        return md_path

    except Exception as e:
        print_error(f"PDF to MD conversion error: {e}")
        import traceback
        print_error(traceback.format_exc())

        # Try to cleanup even on error
        try:
            import gc
            if 'model_dict' in locals():
                del model_dict
            if 'converter' in locals():
                del converter
            if 'rendered' in locals():
                del rendered
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print_info("GPU memory cleanup attempted after error")
        except:
            pass

        return None


def _parse_mineru_progress(line):
    """Parse a MinerU log line and return a human-readable stage label if recognized.

    MinerU outputs tqdm progress bars like:
      Layout Predict:  50%|#####     | 5/10 [00:02<00:02]
      MFD Predict:  30%|###       | 3/10 [00:01<00:02]
      OCR-det Predict: 100%|##########| 10/10 [00:05<00:00]
      OCR-rec Predict:  80%|########  | 8/10 [00:04<00:01]
      Processing pages: 100%|##########| 10/10 [00:01<00:00]
    """
    line_lower = line.lower()

    # Extract percentage from tqdm output if present (e.g., "Layout Predict:  50%|")
    pct_match = re.search(r'(\d+)%\|', line)
    pct_str = f" ({pct_match.group(1)}%)" if pct_match else ""

    stage_map = [
        ("reading file bytes", "Reading PDF"),
        ("layout predict", "Layout analysis"),
        ("mfd predict", "Formula detection"),
        ("mfr predict", "Formula recognition"),
        ("table predict", "Table detection"),
        ("table_rec", "Table recognition"),
        ("table rec", "Table recognition"),
        ("table ocr", "Table OCR"),
        ("ocr-det predict", "OCR detection"),
        ("ocr-rec predict", "OCR recognition"),
        ("ocr predict", "OCR processing"),
        ("span predict", "Span analysis"),
        ("processing pages", "Post-processing"),
        ("postprocess", "Post-processing"),
        ("post process", "Post-processing"),
        ("local output dir", "Writing output"),
    ]
    for keyword, label in stage_map:
        if keyword in line_lower:
            return f"{label}{pct_str}"
    return None


def convert_pdf_to_md_mineru(pdf_path, output_dir, config, status_info=None):
    """Convert PDF to MD using MinerU CLI with real-time progress tracking.

    Returns: md_path (str) or None on failure.
    Output contract matches convert_pdf_to_md():
      - {output_dir}/{stem}.md    (markdown file)
      - {output_dir}/images/*.jpg (extracted images)
      - {output_dir}/{stem}.json  (metadata)
    """
    try:
        import torch
        print_info(f"Loading PDF: {pdf_path}")
        print_info(f"PDF file size: {os.path.getsize(pdf_path) / (1024*1024):.2f} MB")

        # Check GPU memory (informational)
        if torch.cuda.is_available():
            try:
                gpu_mem_free = torch.cuda.mem_get_info()[0] / (1024**3)
                gpu_mem_total = torch.cuda.mem_get_info()[1] / (1024**3)
                print_info(f"GPU memory: {gpu_mem_free:.2f} GB free / {gpu_mem_total:.2f} GB total")
            except Exception:
                pass

        pdf_stem = os.path.basename(pdf_path).replace('.pdf', '')
        mineru_cfg = config.get("converter", {}).get("mineru", {})

        backend = mineru_cfg.get("backend", "pipeline")
        lang = mineru_cfg.get("lang", "en")
        method = mineru_cfg.get("parse_method", "auto")

        print_info(f"MinerU converting (backend={backend}, lang={lang}, method={method})...")

        # Ensure output directory exists
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # Helper to update status with detail
        def _update_detail(detail_text):
            if status_info:
                write_processing_status(
                    status_info["pdf_name"], "converting",
                    status_info["stage_num"], status_info["total_stages"],
                    "PDF to Markdown", detail=detail_text
                )

        _update_detail("Starting MinerU...")

        # Use CLI with real-time output parsing for progress tracking
        conversion_success = False
        cmd = [
            "mineru", "-p", pdf_path, "-o", output_dir,
            "-b", backend, "-l", lang, "-m", method,
        ]

        try:
            print_info(f"Running: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            import time
            last_detail = None
            last_update_time = 0
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    print(f"  [MinerU] {line}")
                    # Parse for known stage transitions
                    detail = _parse_mineru_progress(line)
                    if detail:
                        now = time.time()
                        # Throttle: update at most every 2s, or when stage name changes
                        stage_name = detail.split(" (")[0]  # "OCR recognition" from "OCR recognition (50%)"
                        last_stage_name = last_detail.split(" (")[0] if last_detail else None
                        if stage_name != last_stage_name or (now - last_update_time) >= 2:
                            last_detail = detail
                            last_update_time = now
                            _update_detail(detail)

            proc.wait(timeout=600)
            if proc.returncode == 0:
                conversion_success = True
            else:
                print_error(f"MinerU CLI exited with code {proc.returncode}")
        except FileNotFoundError:
            print_warning("MinerU CLI not found, trying Python API...")
            # Fallback: Python API (no real-time progress)
            if MINERU_AVAILABLE:
                try:
                    _update_detail("Converting (Python API)...")
                    pdf_bytes = mineru_read_fn(pdf_path)
                    do_parse(
                        output_dir=output_dir,
                        pdf_file_names=[pdf_stem],
                        pdf_bytes_list=[pdf_bytes],
                        p_lang_list=[lang],
                        backend=backend,
                        parse_method=method,
                    )
                    conversion_success = True
                except Exception as api_err:
                    print_error(f"MinerU Python API failed: {api_err}")
            else:
                print_error("Neither MinerU CLI nor Python API available!")
        except subprocess.TimeoutExpired:
            print_error("MinerU timed out (600s)")
            try:
                proc.kill()
            except Exception:
                pass

        if not conversion_success:
            print_error("MinerU conversion failed")
            return None

        _update_detail("Organizing output files...")

        # Locate MinerU output: output_dir/{pdf_stem}/auto/{pdf_stem}.md
        mineru_out = os.path.join(output_dir, pdf_stem, "auto")
        mineru_md = os.path.join(mineru_out, f"{pdf_stem}.md")

        if not os.path.exists(mineru_md):
            # Try alternative output structure (varies by MinerU version)
            alt_md = os.path.join(output_dir, pdf_stem, f"{pdf_stem}.md")
            if os.path.exists(alt_md):
                mineru_md = alt_md
                mineru_out = os.path.join(output_dir, pdf_stem)
            else:
                print_error(f"MinerU output not found at {mineru_md}")
                return None

        print_info("Relocating MinerU output to PaperFlow structure...")

        # 1) Move markdown file to output_dir
        target_md = os.path.join(output_dir, f"{pdf_stem}.md")
        shutil.move(mineru_md, target_md)
        try:
            with open(target_md, "r", encoding="utf-8") as f:
                md_text = f.read()
            md_text, fence_report = normalize_code_fence_languages(md_text)
            if sum(fence_report.values()) > 0:
                with open(target_md, "w", encoding="utf-8") as f:
                    f.write(md_text)
                print_info(f"Code fence normalization applied: {fence_report}")
        except Exception as e:
            print_warning(f"Code fence normalization skipped: {e}")

        # 2) Move images/ folder to output_dir/images/
        mineru_images = os.path.join(mineru_out, "images")
        target_images = os.path.join(output_dir, "images")
        if os.path.isdir(mineru_images):
            if os.path.exists(target_images):
                shutil.rmtree(target_images)
            shutil.move(mineru_images, target_images)
            image_count = len([f for f in os.listdir(target_images) if os.path.isfile(os.path.join(target_images, f))])
            print_success(f"Saved {image_count} image(s)")
        else:
            print_warning("No images extracted from PDF")

        # 3) Move content_list JSON as metadata
        content_list = os.path.join(mineru_out, f"{pdf_stem}_content_list.json")
        if os.path.exists(content_list):
            target_json = os.path.join(output_dir, f"{pdf_stem}.json")
            shutil.move(content_list, target_json)

        # 4) Clean up MinerU temp directory
        mineru_temp = os.path.join(output_dir, pdf_stem)
        if os.path.isdir(mineru_temp):
            shutil.rmtree(mineru_temp)

        print_success("PDF conversion complete (MinerU)")

        # VRAM cleanup
        try:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                gpu_mem_free_now = torch.cuda.mem_get_info()[0] / (1024**3)
                print_info(f"GPU memory available: {gpu_mem_free_now:.2f} GB")
        except Exception as e:
            print_warning(f"GPU cleanup warning: {e}")

        return target_md

    except Exception as e:
        print_error(f"MinerU conversion error: {e}")
        import traceback
        print_error(traceback.format_exc())

        # Try to cleanup even on error
        try:
            gc.collect()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print_info("GPU memory cleanup attempted after error")
        except:
            pass

        return None


def convert_pdf_to_md_dispatch(pdf_path, output_dir, config, status_info=None):
    """Dispatch PDF conversion to the configured engine (marker or mineru).

    Engine is selected via PDF_CONVERTER environment variable.
    status_info: optional dict with keys (pdf_name, stage_num, total_stages) for progress updates.
    Returns: md_path (str) or None on failure.
    """
    engine = os.environ.get("PDF_CONVERTER", "marker").lower()

    if engine == "mineru":
        if not MINERU_AVAILABLE:
            print_error("PDF_CONVERTER=mineru but MinerU is not installed!")
            print_info("Install it with: pip install 'mineru[all]'")
            return None
        return convert_pdf_to_md_mineru(pdf_path, output_dir, config, status_info=status_info)
    else:
        if not MARKER_AVAILABLE:
            print_error("PDF_CONVERTER=marker but marker-pdf is not installed!")
            print_info("Install it with: pip install marker-pdf")
            return None
        return convert_pdf_to_md(pdf_path, output_dir)


##############################################################################
# Metadata Extraction
# Extract paper title, authors, abstract, categories using AI
##############################################################################

METADATA_EXTRACTION_PROMPT = """You are an academic paper metadata extractor. Given the beginning of an academic paper in Markdown format, extract metadata and return ONLY a valid JSON object:

{
  "title": "Exact paper title",
  "title_ko": "Korean translation of the title",
  "authors": ["Author Name 1", "Author Name 2"],
  "abstract": "Complete abstract text",
  "abstract_ko": "Korean translation of the abstract",
  "categories": ["Category1", "Category2"],
  "source_language": "en",
  "publication_year": 2025,
  "doc_type": "paper"
}

Rules:
- Extract the EXACT title as written in the paper. Do not modify or summarize it.
- Provide a natural Korean translation of the title in "title_ko".
- List ALL authors by their full names in order. If affiliations are mixed in, extract only the names.
- Extract the complete abstract text. If no clear abstract section exists, provide a 1-2 sentence summary of the paper's topic.
- Provide a natural Korean translation of the abstract in "abstract_ko".
- For categories, infer 2-5 relevant academic categories (e.g., "Machine Learning", "Natural Language Processing", "Computer Vision", "Reinforcement Learning", "Robotics", "Data Mining", "Software Engineering", "Optimization", "Deep Learning").
- For source_language, detect the PRIMARY language of the paper body. Use ISO 639-1 codes: "en" (English), "ko" (Korean), "zh" (Chinese), "ja" (Japanese), "de" (German), "fr" (French), etc. If the paper has mixed languages (e.g., English body with Korean abstract), use the main body language.
- Extract the publication year as an integer (e.g., 2025). Look for it in the header, footnotes, copyright notice, or submission date. If not found, use null.
- For doc_type, classify the document into exactly one of: "paper" (academic/research paper, preprint), "report" (technical report, survey, index report), "blog" (personal or company blog post, tutorial, product announcement), "news" (breaking/timely news report, interview), "essay" (opinion piece, editorial, commentary), "article" (a feature/informational article professionally published by a magazine, media outlet, or industry/trade publication — e.g., a business magazine feature or long-form explainer — that is NOT an academic paper, a personal blog post, breaking news, or an opinion essay), "other" (anything else). Infer from the writing style, structure, and source.
- IMPORTANT: All fields above are REQUIRED. You must include every key in your JSON response, especially "doc_type" and "publication_year". Never omit any field.
- Return ONLY the JSON object. No markdown formatting, no code blocks, no explanation.
- If you cannot determine a field, use null for strings or [] for arrays. For doc_type, always choose the closest match — never omit it."""


METADATA_FAILURE_MARKER = "paper_meta.failed.json"


def _write_metadata_failure_marker(output_dir, reason, md_path, model):
    """Record a permanent metadata-extraction failure next to the document.

    scripts/backfill_metadata.py sweeps for these (and for folders with no
    paper_meta.json at all) so a failure is recoverable instead of invisible.
    """
    try:
        with open(os.path.join(output_dir, METADATA_FAILURE_MARKER), 'w', encoding='utf-8') as f:
            json.dump({
                "stage": "extract_metadata",
                "reason": reason,
                "source_md": os.path.basename(md_path) if md_path else None,
                "model": model,
                "failed_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)
        print_warning(f"Failure marker written: {METADATA_FAILURE_MARKER}")
    except Exception as e:
        print_warning(f"Could not write metadata failure marker: {e}")


def _clear_metadata_failure_marker(output_dir):
    """Remove a stale failure marker after a successful (re)extraction."""
    try:
        marker = os.path.join(output_dir, METADATA_FAILURE_MARKER)
        if os.path.exists(marker):
            os.remove(marker)
    except Exception:
        pass


def extract_paper_metadata(md_path, output_dir, config):
    """Extract paper metadata (title, authors, abstract, categories) using AI.

    Reads the first portion of the markdown file and sends it to an
    OpenAI-compatible API for structured metadata extraction.

    Returns:
        Metadata dict on success, None on failure.
    """
    from openai import OpenAI

    # Load AI settings
    api_base = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("TRANSLATION_MODEL", "gemini-claude-sonnet-4-5")

    if not api_base or not api_key:
        print_warning("Metadata extraction skipped: OPENAI_BASE_URL or OPENAI_API_KEY not set")
        return None

    meta_config = config.get("metadata_extraction", {})
    max_input_chars = meta_config.get("max_input_chars", 8000)
    temperature = meta_config.get("temperature", 0.1)
    max_tokens = meta_config.get("max_tokens", 2048)
    timeout = meta_config.get("timeout_seconds", 60)
    max_retries = meta_config.get("max_retries", 2)
    retry_delay = meta_config.get("retry_delay_seconds", 2)

    # Read first portion of markdown
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read(max_input_chars)
    except Exception as e:
        print_error(f"Failed to read markdown for metadata extraction: {e}")
        return None

    if not md_content.strip():
        print_warning("Markdown content is empty, skipping metadata extraction")
        return None

    print_info(f"Sending {len(md_content):,} chars to AI for metadata extraction...")

    client = OpenAI(base_url=api_base, api_key=api_key)

    # Reasoning models (gpt-5.x) can spend the whole completion budget on reasoning
    # tokens and return content=None with finish_reason="length". That used to raise
    # AttributeError on .strip(), which the generic handler below treated as a
    # transient API error — so both attempts failed identically and the document was
    # left with no paper_meta.json (16 occurrences in logs/). Escalate the budget.
    current_max_tokens = max_tokens
    last_error = None

    for attempt in range(max_retries):
        try:
            import time
            start_time = time.time()
            print_info(f"Calling API... (attempt {attempt+1}/{max_retries})")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": METADATA_EXTRACTION_PROMPT},
                    {"role": "user", "content": md_content}
                ],
                temperature=temperature,
                max_tokens=current_max_tokens,
                timeout=timeout
            )

            choice = response.choices[0]
            raw_content = getattr(choice.message, "content", None)
            if raw_content is None or not raw_content.strip():
                finish = getattr(choice, "finish_reason", None)
                last_error = f"empty content from model (finish_reason={finish})"
                if finish == "length":
                    current_max_tokens = min(current_max_tokens * 2, 16384)
                    print_warning(f"Empty content (budget exhausted) — retrying with max_tokens={current_max_tokens}")
                else:
                    print_warning(f"Empty content from model (finish_reason={finish})")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                continue

            result_text = raw_content.strip()
            elapsed = time.time() - start_time
            print_info(f"API response received in {elapsed:.1f}s")

            # Strip markdown code block wrappers if present
            if result_text.startswith("```"):
                result_text = re.sub(r'^```(?:json)?\s*\n?', '', result_text)
                result_text = re.sub(r'\n?```\s*$', '', result_text)

            metadata = json.loads(result_text)

            # Validate title exists and is meaningful
            title = metadata.get("title")
            if not title or not isinstance(title, str) or len(title.strip()) < 3:
                print_warning("Extracted title is too short or missing")
                metadata["title"] = None

            # Ensure authors is a list
            if not isinstance(metadata.get("authors"), list):
                metadata["authors"] = []

            # Ensure categories is a list
            if not isinstance(metadata.get("categories"), list):
                metadata["categories"] = []

            # Ensure Korean fields default to None if missing/invalid
            if not isinstance(metadata.get("title_ko"), str) or not metadata["title_ko"].strip():
                metadata["title_ko"] = None
            if not isinstance(metadata.get("abstract_ko"), str) or not metadata["abstract_ko"].strip():
                metadata["abstract_ko"] = None

            # Validate doc_type — if missing, ask AI with a lightweight follow-up call
            valid_doc_types = {"paper", "report", "blog", "news", "essay", "article", "other"}
            doc_type = metadata.get("doc_type")
            if not isinstance(doc_type, str) or doc_type.lower().strip() not in valid_doc_types:
                print_warning("doc_type missing from AI response, requesting classification...")
                try:
                    dt_resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": (
                                'Classify this document into exactly one of: '
                                '"paper", "report", "blog", "news", "essay", "article", "other". '
                                'Reply with ONLY the single word.'
                            )},
                            {"role": "user", "content": md_content[:3000]}
                        ],
                        temperature=0,
                        max_tokens=10,
                        timeout=15,
                    )
                    dt_val = dt_resp.choices[0].message.content.strip().lower().strip('"\'')
                    if dt_val in valid_doc_types:
                        metadata["doc_type"] = dt_val
                        print_info(f"doc_type classified: {dt_val}")
                    else:
                        metadata["doc_type"] = "other"
                        print_warning(f"doc_type fallback to 'other' (AI returned: {dt_val})")
                except Exception as e:
                    metadata["doc_type"] = "other"
                    print_warning(f"doc_type follow-up call failed, defaulting to 'other': {e}")
            else:
                metadata["doc_type"] = doc_type.lower().strip()

            # Validate source_language (default: "en")
            source_lang = metadata.get("source_language")
            if not isinstance(source_lang, str) or len(source_lang) < 2:
                metadata["source_language"] = "en"
            else:
                metadata["source_language"] = source_lang.lower().strip()[:5]

            # Add envelope fields
            original_filename = os.path.basename(md_path).replace('.md', '.pdf')
            metadata["original_filename"] = original_filename
            metadata["extracted_at"] = datetime.now().isoformat()

            # Preserve exact imported source URL when available (URL import sidecar)
            # so dashboard Paperflow Open mapping can resolve deterministically.
            try:
                sidecar_candidates = [
                    os.path.join("newones", ".meta", f"{original_filename}.url.txt"),
                    os.path.join("newones", f"{original_filename}.url.txt"),  # legacy fallback
                ]
                src_url = None
                for sidecar in sidecar_candidates:
                    if os.path.isfile(sidecar):
                        with open(sidecar, "r", encoding="utf-8") as sf:
                            src_url = sf.read().strip()
                        if src_url:
                            break
                if src_url and src_url.startswith(("http://", "https://")):
                    metadata["source_url_original"] = src_url
                    # prefer exact imported URL for dashboard resolve mapping
                    metadata["paper_url"] = src_url
            except Exception:
                pass

            # Save paper_meta.json
            meta_path = os.path.join(output_dir, "paper_meta.json")
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            print_success(f"Metadata saved to: {meta_path}")

            # Reprocessing succeeded — drop any stale failure marker
            _clear_metadata_failure_marker(output_dir)

            return metadata

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            print_warning(f"JSON parse error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_delay)
        except Exception as e:
            last_error = f"API error: {e}"
            print_warning(f"Metadata extraction API error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                wait_time = retry_delay * (attempt + 1)
                time.sleep(wait_time)

    print_error("Metadata extraction failed after all retries")
    # Leave a durable, greppable trace. Without this the pipeline continues and the
    # document ends up as a permanently blank card in the viewer with nothing on
    # disk to indicate why — the exact failure mode behind the 66-folder backlog.
    _write_metadata_failure_marker(output_dir, last_error or "unknown", md_path, model)
    return None


##############################################################################
# Web Search Enrichment
# Enrich paper metadata with Brave Search API (venue, DOI, year, URL)
##############################################################################

# Known venue patterns for matching search results
_VENUE_PATTERNS = [
    # Conferences
    (re.compile(r'\b(NeurIPS|NIPS)\b', re.IGNORECASE), 'NeurIPS'),
    (re.compile(r'\bICML\b', re.IGNORECASE), 'ICML'),
    (re.compile(r'\bICLR\b', re.IGNORECASE), 'ICLR'),
    (re.compile(r'\bCVPR\b', re.IGNORECASE), 'CVPR'),
    (re.compile(r'\bICCV\b', re.IGNORECASE), 'ICCV'),
    (re.compile(r'\bECCV\b', re.IGNORECASE), 'ECCV'),
    (re.compile(r'\bACL\s+20\d{2}\b', re.IGNORECASE), None),  # use match
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


def _extract_venue_from_text(text, url=None):
    """Extract venue name from search result text."""
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


def _extract_year_from_text(text):
    """Extract publication year from search result text, preferring recent years."""
    years = [int(y) for y in _YEAR_RE.findall(text) if 1990 <= int(y) <= 2030]
    if not years:
        return None
    # Prefer the most common year in the text
    from collections import Counter
    counts = Counter(years)
    return counts.most_common(1)[0][0]


def enrich_metadata_with_web_search(metadata, output_dir, config):
    """Enrich paper metadata using web search.

    Priority: Firecrawl Search API -> Brave Search API fallback.
    """
    import urllib.request
    import urllib.parse

    title = metadata.get("title")
    if not title:
        print_info("Web search enrichment skipped: no title available")
        return metadata

    # Build search query: "title" first_author
    authors = metadata.get("authors", [])
    first_author = authors[0].split()[-1] if authors else ""
    query = f'"{title}"'
    if first_author:
        query += f" {first_author}"

    print_info("Searching web for paper metadata...")

    def _normalize_results(rows):
        out = []
        for r in rows or []:
            out.append({
                "title": (r.get("title") or r.get("metadata", {}).get("title") or "").strip(),
                "description": (r.get("description") or r.get("snippet") or "").strip(),
                "url": (r.get("url") or r.get("link") or "").strip(),
            })
        return [x for x in out if x.get("url")]

    web_results = []

    # 1) Firecrawl first
    firecrawl_key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if firecrawl_key:
        try:
            req = urllib.request.Request(
                "https://api.firecrawl.dev/v1/search",
                data=json.dumps({"query": query, "limit": 5}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {firecrawl_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            rows = payload.get("data") or payload.get("results") or []
            web_results = _normalize_results(rows)
            if web_results:
                print_success("Web search provider: Firecrawl")
        except Exception as e:
            print_warning(f"Firecrawl search failed, fallback to Brave: {e}")

    # 2) Brave fallback
    if not web_results:
        brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
        if not brave_key:
            print_info("Web search enrichment skipped: FIRECRAWL_API_KEY/BRAVE_SEARCH_API_KEY not set")
            return metadata
        try:
            params = urllib.parse.urlencode({
                "q": query,
                "count": 5,
                "text_decorations": "false",
            })
            url = f"https://api.search.brave.com/res/v1/web/search?{params}"
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": brave_key,
            })

            import gzip
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                results = json.loads(data.decode("utf-8"))
            web_results = _normalize_results(results.get("web", {}).get("results", []))
            if web_results:
                print_success("Web search provider: Brave")
        except Exception as e:
            print_warning(f"Brave search failed: {e}")
            web_results = []

    if not web_results:
        print_info("Web search returned no results")
        return metadata

    try:
        # Aggregate text from all results for pattern extraction
        all_text = ""
        first_url = None
        for r in web_results:
            all_text += f" {r.get('title', '')} {r.get('description', '')} {r.get('url', '')}"
            if not first_url:
                rurl = r.get("url", "")
                if any(d in rurl for d in ["arxiv.org", "doi.org", "openreview.net",
                                            "semanticscholar.org", "ieee.org", "acm.org",
                                            "springer.com", "nature.com", "sciencedirect.com"]):
                    first_url = rurl
        if not first_url and web_results:
            first_url = web_results[0].get("url")

        enriched = {}

        if not metadata.get("venue"):
            venue = _extract_venue_from_text(all_text, url=first_url)
            if venue:
                enriched["venue"] = venue
                print_success(f"  Venue: {venue}")

        if not metadata.get("doi"):
            doi_match = _DOI_RE.search(all_text)
            if doi_match:
                doi = doi_match.group(1).rstrip(".")
                enriched["doi"] = doi
                print_success(f"  DOI: {doi}")

        if not metadata.get("publication_year"):
            year = _extract_year_from_text(all_text)
            if year:
                enriched["publication_year"] = year
                print_success(f"  Year: {year}")

        if not metadata.get("paper_url") and first_url:
            enriched["paper_url"] = first_url
            print_success(f"  URL: {first_url}")

        if enriched:
            enriched["web_enriched_at"] = datetime.now().isoformat()
            metadata.update(enriched)
            meta_path = os.path.join(output_dir, "paper_meta.json")
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            print_success(f"Metadata enriched with {len(enriched) - 1} field(s) from web search")
        else:
            print_info("Web search found no additional metadata")

    except Exception as e:
        print_warning(f"Web search enrichment failed: {e}")

    return metadata


def _normalize_title(title):
    """Normalize title for comparison: lowercase, strip punctuation/whitespace."""
    import unicodedata
    t = unicodedata.normalize("NFKD", title.lower().strip())
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t


def _canonical_source_url(url):
    """Normalize source URL for duplicate checks.

    Same titles can legitimately appear in link blogs and canonical source pages.
    Treat them as duplicates only when the canonical source URL also matches, or
    when source URLs are unavailable.
    """
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(str(url).strip())
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        path = re.sub(r'/+', '/', parts.path or '/').rstrip('/') or '/'
        return urlunsplit((scheme, netloc, path, '', ''))
    except Exception:
        return str(url).strip().split('#', 1)[0].rstrip('/').lower()


def check_duplicate_batch(metadata, current_output_dir):
    """Check if paper with same title already exists in outputs/ or archives/.

    Returns list of matching papers: [{title, folder, location}]
    Returns empty list if no duplicates or on error (fail-open).
    """
    title = metadata.get("title", "")
    if not title or len(title) < 5:
        return []

    norm_title = _normalize_title(title)
    current_url = _canonical_source_url(
        metadata.get("source_url_original") or metadata.get("paper_url") or metadata.get("url")
    )
    matches = []

    for base_dir, location in [("outputs", "outputs"), ("archives", "archives")]:
        if not os.path.isdir(base_dir):
            continue
        for folder in os.listdir(base_dir):
            folder_path = os.path.join(base_dir, folder)
            if not os.path.isdir(folder_path) or folder.startswith("."):
                continue
            if os.path.abspath(folder_path) == os.path.abspath(current_output_dir):
                continue
            meta_path = os.path.join(folder_path, "paper_meta.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    existing_meta = json.load(f)
                existing_title = existing_meta.get("title", "")
                if existing_title and _normalize_title(existing_title) == norm_title:
                    existing_url = _canonical_source_url(
                        existing_meta.get("source_url_original") or existing_meta.get("paper_url") or existing_meta.get("url")
                    )
                    if current_url and existing_url and current_url != existing_url:
                        continue
                    matches.append({
                        "title": existing_title,
                        "folder": folder,
                        "location": location,
                    })
            except Exception:
                continue

    return matches


def sanitize_folder_name(title, max_length=80):
    """Convert a paper title to a filesystem-safe folder name.

    Preserves spaces (consistent with existing PaperFlow conventions),
    removes OS-forbidden characters, and truncates at word boundaries.

    Returns:
        Sanitized string, or None if result is empty.
    """
    import unicodedata

    name = unicodedata.normalize('NFKD', title)

    # Remove OS-forbidden characters: / \ : * ? " < > |
    name = re.sub(r'[/\\:*?"<>|]', '', name)

    # Replace newlines and tabs with spaces
    name = re.sub(r'[\n\r\t]', ' ', name)

    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()

    # Remove leading/trailing dots (hidden files on unix)
    name = name.strip('.')

    # Truncate at word boundary if too long
    if len(name) > max_length:
        truncated = name[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.6:
            truncated = truncated[:last_space]
        name = truncated.rstrip()

    return name if name else None


def rename_output_directory(old_output_dir, new_folder_name, original_base_name):
    """Rename the output directory and internal files to match the extracted title.

    Args:
        old_output_dir: Current output directory path (e.g., outputs/old_name).
        new_folder_name: Sanitized new folder name from extracted title.
        original_base_name: Original base name (PDF filename without .pdf).

    Returns:
        Tuple of (new_output_dir, new_folder_name) on success, None on failure.
    """
    parent = os.path.dirname(old_output_dir)
    new_dir = os.path.join(parent, new_folder_name)

    # Handle uniqueness: append suffix if directory already exists
    if os.path.exists(new_dir) and os.path.abspath(new_dir) != os.path.abspath(old_output_dir):
        found_unique = False
        for suffix in range(2, 100):
            candidate = os.path.join(parent, f"{new_folder_name}-{suffix}")
            if not os.path.exists(candidate):
                new_dir = candidate
                new_folder_name = f"{new_folder_name}-{suffix}"
                found_unique = True
                break
        if not found_unique:
            print_warning("Could not find unique folder name, keeping original")
            return None

    try:
        # Step 1: Rename internal files that match original_base_name
        for f in os.listdir(old_output_dir):
            if f.startswith(original_base_name):
                file_suffix = f[len(original_base_name):]  # e.g., ".md", ".json", "_ko.md"
                new_name = new_folder_name + file_suffix
                old_path = os.path.join(old_output_dir, f)
                new_path = os.path.join(old_output_dir, new_name)
                os.rename(old_path, new_path)
                print_info(f"  Renamed: {f} -> {new_name}")

        # Step 2: Rename directory
        os.rename(old_output_dir, new_dir)

        # Step 3: Update paper_meta.json with final folder_name
        meta_path = os.path.join(new_dir, "paper_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            meta["folder_name"] = new_folder_name
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

        return (new_dir, new_folder_name)

    except Exception as e:
        print_error(f"Failed to rename output directory: {e}")
        return None


##############################################################################
# Translation Pipeline
# MD → [YAML분리] → [OCR정리] → [코드보호] → [섹션분류] → [번역(수식OCR정리포함)] → [복원/결합]
##############################################################################

def split_yaml_and_body(content):
    """Separate YAML frontmatter from markdown body.

    Returns:
        (yaml_header, body) - yaml_header is empty string if none found
    """
    if content.startswith('---'):
        end = content.find('---', 3)
        if end != -1:
            end += 3
            yaml_header = content[:end]
            body = content[end:].lstrip('\n')
            return yaml_header, body
    return '', content


def clean_ocr_artifacts(text):
    """Clean common OCR artifacts from marker-pdf output."""
    import re
    lines = text.split('\n')
    cleaned = []

    for line in lines:
        stripped = line.strip()
        # Skip standalone page numbers
        if re.match(r'^[-–—]?\s*\d{1,4}\s*[-–—]?$', stripped):
            continue
        # Skip "Page N" / "Page N of M"
        if re.match(r'^Page\s+\d+(\s+of\s+\d+)?$', stripped, re.IGNORECASE):
            continue
        # Skip copyright lines
        if re.match(r'^[©®]\s*\d{4}', stripped):
            continue
        # Skip standalone DOI
        if re.match(r'^(DOI|doi)\s*:\s*10\.', stripped):
            continue
        cleaned.append(line)

    text = '\n'.join(cleaned)

    # Fix hyphenation across lines: "compu-\nter" → "computer"
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)

    # Fix marker-pdf author code block bug: ``` wrapping <sup> tags
    # Use [^\n]* instead of .*? with DOTALL to prevent catastrophic backtracking
    text = re.sub(
        r'```\n((?:[^\n]*<sup>[^\n]*</sup>[^\n]*\n)+)```',
        r'\1',
        text
    )

    return text


def clean_ocr_math(text):
    """Clean common OCR math formula artifacts from marker-pdf output.

    Fixes excessive spacing in LaTeX commands that marker-pdf introduces:
    - \\mathrm { A P I } → \\mathrm{API}
    - \\begin{array} { c } → \\begin{array}{c}
    - a _ { c } → a_{c}
    - \\mathrm { m i n } → \\min
    """
    import re

    # 1. Fix spaced-out single characters in text-mode commands:
    #    \mathrm { A P I } → \mathrm{API}
    #    \mathbf { e } → \mathbf{e}
    #    \mathtt { A P I } → \mathtt{API}
    #    \text { s o m e } → \text{some}
    def _collapse_spaced_chars(m):
        cmd = m.group(1)  # e.g., "mathrm", "mathbf"
        inner = m.group(2)  # e.g., "A P I" or "e"
        collapsed = inner.replace(' ', '')
        return f'\\{cmd}{{{collapsed}}}'

    text = re.sub(
        r'\\(mathrm|mathbf|mathtt|mathcal|mathbb|mathfrak|text|textbf|textit|tt|bf|it)\s*\{\s*'
        r'((?:[A-Za-z0-9]\s+)*[A-Za-z0-9])\s*\}',
        _collapse_spaced_chars,
        text
    )

    # 2. Fix known math operators misrendered as \mathrm{...}:
    #    \mathrm{min} → \min, \mathrm{max} → \max, etc.
    _MATH_OPS = {
        'min': '\\min', 'max': '\\max', 'log': '\\log', 'exp': '\\exp',
        'sin': '\\sin', 'cos': '\\cos', 'tan': '\\tan',
        'lim': '\\lim', 'sup': '\\sup', 'inf': '\\inf',
        'arg': '\\arg', 'det': '\\det', 'dim': '\\dim',
        'gcd': '\\gcd', 'deg': '\\deg', 'ker': '\\ker',
    }
    for word, replacement in _MATH_OPS.items():
        text = re.sub(
            rf'\\mathrm\{{{word}\}}',
            lambda _, r=replacement: r,
            text
        )

    # 3. Fix spaced subscript/superscript braces:
    #    a _ { c } → a_{c}
    #    x ^ { 2 } → x^{2}
    text = re.sub(
        r'([A-Za-z0-9\}\\])\s*([_^])\s*\{\s*([^}]*?)\s*\}',
        lambda m: f'{m.group(1)}{m.group(2)}{{{m.group(3).strip()}}}',
        text
    )

    # 4. Fix \begin{env} { args } → \begin{env}{args}
    text = re.sub(
        r'(\\begin\{[^}]+\})\s*\{\s*([^}]*?)\s*\}',
        lambda m: f'{m.group(1)}{{{m.group(2).strip()}}}',
        text
    )

    # 5. Fix \end{env} } → \end{env}  (trailing stray braces)
    text = re.sub(
        r'(\\end\{[^}]+\})\s*\}',
        r'\1',
        text
    )

    return text


# ── Heading normalization constants ──────────────────────────────────────────
import re as _re

_HEADING_RE = _re.compile(r'^(#{1,6})\s+(.+)$', _re.MULTILINE)
_SPAN_RE = _re.compile(r'<span[^>]*>|</span>')
_EMPHASIS_RE = _re.compile(r'^\*+(.+?)\*+$')

# Numbered section patterns (most specific first)
_DECIMAL_SUBSUB = _re.compile(r'^(\d{1,2}\.\d{1,2}\.\d{1,2})\b')
_DECIMAL_SUB = _re.compile(r'^(\d{1,2}\.\d{1,2})\b')
_DECIMAL_MAIN = _re.compile(r'^(\d{1,2})\s+\S')
_ROMAN_MAIN = _re.compile(
    r'^(I{1,3}|IV|VI{0,3}|IX|XI{0,3}|X{1,3})[\.\s]+\s*\S',
    _re.IGNORECASE
)
_LETTER_SUB = _re.compile(r'^([A-Z])[\.\)]\s+\S')
_ACM_RE = _re.compile(r'^ACM\s+Reference', _re.IGNORECASE)

_STRUCTURAL_KEYWORDS = {
    'references', 'bibliography', 'appendix', 'appendices',
    'acknowledgements', 'acknowledgments', 'acknowledgement', 'acknowledgment',
    'supplementary material', 'abstract',
}


def _clean_heading_for_matching(text):
    """Strip HTML tags and emphasis markers for pattern matching."""
    cleaned = _SPAN_RE.sub('', text).strip()
    m = _EMPHASIS_RE.match(cleaned)
    if m:
        cleaned = m.group(1).strip()
    return cleaned


def _detect_numbering_scheme(heading_texts):
    """Pre-scan headings to determine document numbering scheme.

    Returns 'decimal', 'roman', or 'mixed'.
    """
    decimal_count = 0
    roman_count = 0
    for h in heading_texts:
        cleaned = _clean_heading_for_matching(h)
        if _DECIMAL_MAIN.match(cleaned) or _DECIMAL_SUB.match(cleaned):
            decimal_count += 1
        if _ROMAN_MAIN.match(cleaned):
            roman_count += 1

    if decimal_count > 0 and roman_count == 0:
        return 'decimal'
    elif roman_count >= 2 and decimal_count == 0:
        return 'roman'
    return 'mixed'


def _is_structural_heading(text):
    """Check if heading matches known structural sections (References, etc.)."""
    # Strip numbering prefix
    stripped = _re.sub(r'^[\dIVXivx\.\s]+', '', text).strip()
    lower = stripped.lower()
    for kw in _STRUCTURAL_KEYWORDS:
        if kw in lower:
            return True
    return False


def normalize_heading_levels(text):
    """Normalize inconsistent markdown heading levels based on section numbering.

    marker-pdf OCR produces random heading levels. This function uses the
    section numbering in heading text to assign correct levels:
      Title (first unnumbered heading) → H1
      Main sections (1, 2, I, II)      → H2
      Sub-sections (1.1, A., B.)       → H3
      Sub-sub-sections (1.1.1)         → H4
      Structural (References, etc.)    → H2
      Unnumbered                       → previous numbered level + 1
    """
    yaml_header, body = split_yaml_and_body(text)

    # Collect all heading texts for scheme detection
    all_headings = _HEADING_RE.findall(body)
    if not all_headings:
        return text

    heading_texts = [h[1] for h in all_headings]
    scheme = _detect_numbering_scheme(heading_texts)

    title_found = False
    last_numbered_level = 2

    def _replace_heading(match):
        nonlocal title_found, last_numbered_level

        heading_content = match.group(2)
        cleaned = _clean_heading_for_matching(heading_content)

        # Title: first heading without a section number
        if not title_found:
            has_number = bool(
                _DECIMAL_MAIN.match(cleaned)
                or (scheme != 'decimal' and _ROMAN_MAIN.match(cleaned))
            )
            if not has_number:
                title_found = True
                return f'# {heading_content}'
            else:
                title_found = True
                # Fall through to numbered logic

        # Numbered patterns (most specific first)
        if _DECIMAL_SUBSUB.match(cleaned):
            level = 4
            last_numbered_level = 4
        elif _DECIMAL_SUB.match(cleaned):
            level = 3
            last_numbered_level = 3
        elif _DECIMAL_MAIN.match(cleaned):
            level = 2
            last_numbered_level = 2
        elif scheme != 'decimal' and _ROMAN_MAIN.match(cleaned):
            level = 2
            last_numbered_level = 2
        elif scheme != 'decimal' and _LETTER_SUB.match(cleaned):
            level = 3
            last_numbered_level = 3
        elif _ACM_RE.match(cleaned):
            level = 4
        elif _is_structural_heading(cleaned):
            level = 2
            last_numbered_level = 2
        else:
            # Unnumbered, non-structural → one level below last numbered
            level = min(last_numbered_level + 1, 4)

        return f'{"#" * level} {heading_content}'

    normalized = _HEADING_RE.sub(_replace_heading, body)

    if yaml_header:
        return yaml_header + '\n' + normalized
    return normalized


def _markdown_preflight_for_translation(text):
    """Preflight markdown cleanup before translation.

    Goal: stabilize fence/code structure in EN markdown so KO translation doesn't
    inherit malformed markdown (nested fences, unclosed fences, mixed fence styles).

    Returns:
        (cleaned_text, report_dict)
    """
    lines = text.splitlines()
    out = []
    report = {
        "tilde_to_backtick": 0,
        "collapsed_duplicate_fence": 0,
        "added_closing_fence": 0,
        "unbalanced_fences_before": 0,
        "removed_cookie_blocks": 0,
        "removed_cookie_lines": 0,
        "removed_short_noise_lines": 0,
        "inferred_code_languages": 0,
        "unlabeled_code_fences": 0,
        "removed_stray_language_lines": 0,
    }

    fence_open = False
    fence_stack = []

    for ln in lines:
        m = re.match(r'^(\s*)(`{3,}|~{3,})([^`]*)$', ln)
        if m:
            indent, fence, rest = m.group(1), m.group(2), m.group(3)
            # Normalize ~~~ to ``` for consistency
            if fence.startswith('~'):
                report["tilde_to_backtick"] += 1
                fence = '```'
            else:
                fence = '```'

            norm_line = f"{indent}{fence}{rest.rstrip()}".rstrip()

            # Collapse immediate duplicate fence lines (common OCR/convert artifact)
            if out and out[-1].strip() == '```' and norm_line.strip() == '```':
                report["collapsed_duplicate_fence"] += 1
                continue

            if not fence_open:
                fence_open = True
                fence_stack.append('```')
            else:
                # closing fence
                fence_open = False
                if fence_stack:
                    fence_stack.pop()

            out.append(norm_line)
            continue

        out.append(ln)

    if fence_stack:
        report["unbalanced_fences_before"] = len(fence_stack)
        while fence_stack:
            out.append('```')
            fence_stack.pop()
            report["added_closing_fence"] += 1

    cleaned = "\n".join(out)

    # Remove common web boilerplate sections that poison translation quality
    # (cookie banners/policies duplicated in captured web PDFs)
    cookie_block_patterns = [
        r'(?ims)^#{1,6}\s*Cookie Policy\s*$.*?(?=^#{1,6}\s|\Z)',
        r'(?ims)^#{1,6}\s*쿠키 정책.*?$.*?(?=^#{1,6}\s|\Z)',
    ]
    for pat in cookie_block_patterns:
        matches = list(re.finditer(pat, cleaned))
        if matches:
            report["removed_cookie_blocks"] += len(matches)
            cleaned = re.sub(pat, '', cleaned)

    cookie_line_patterns = [
        r'(?im)^We use cookies to improve your experience.*$',
        r'(?im)^You can accept, reject, or manage your preferences.*$',
        r'(?im)^See our privacy policy\.?$',
        r'(?im)^사람들이 어떻게 투표하는지 확인할 수 있습니다\.?\s*더 알아보기\s*$',
    ]
    for pat in cookie_line_patterns:
        matches = list(re.finditer(pat, cleaned))
        if matches:
            report["removed_cookie_lines"] += len(matches)
            cleaned = re.sub(pat, '', cleaned)

    # Remove obviously broken tiny noise lines that often come from OCR/page chrome
    before_lines = cleaned.splitlines()
    kept = []
    for ln in before_lines:
        s = ln.strip()
        if re.match(r'^[가-힣]{1,2}$', s):
            report["removed_short_noise_lines"] += 1
            continue
        if re.match(r'^[A-Za-z]{1,3}$', s):
            report["removed_short_noise_lines"] += 1
            continue
        kept.append(ln)
    cleaned = "\n".join(kept)

    # Normalize excessive blank lines introduced by removals
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip() + "\n"
    cleaned, fence_report = normalize_code_fence_languages(cleaned)
    report["inferred_code_languages"] += fence_report.get("inferred_code_languages", 0)
    report["unlabeled_code_fences"] += fence_report.get("unlabeled_code_fences", 0)
    report["removed_stray_language_lines"] += fence_report.get("removed_stray_language_lines", 0)

    return cleaned, report


def compute_quality_signals(text, source_type="unknown"):
    """Compute lightweight text-quality signals for routing/gating.

    Phase 1 stub: metric collection only (no hard fail).
    """
    lines = text.splitlines()
    total = max(1, len(lines))

    boilerplate_patterns = [
        r'(?i)we use cookies',
        r'쿠키를 사용합니다',
        r'쿠키 정책',
        r'설정으로 이동하여 원하는 대로 변경할 수 있습니다',
        r'자세한 정보는 .*정책',
        r'(?i)^privacy policy$',
        r'(?i)^cookie policy$',
    ]
    ocr_patterns = [
        r'\bOpenAl\b',
        r'\bfi\s+rst\b',
        r'\bconfi\s+g\b',
        r'\bobservability\s*\(observability\)\b',
    ]

    boilerplate_lines = 0
    ocr_artifacts = 0
    short_noise = 0
    mixed_language = 0

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if any(re.search(p, s) for p in boilerplate_patterns):
            boilerplate_lines += 1
        if any(re.search(p, s) for p in ocr_patterns):
            ocr_artifacts += 1
        if re.match(r'^[A-Za-z가-힣]{1,3}$', s):
            short_noise += 1
        if re.search(r'[가-힣]', s) and re.search(r'[A-Za-z]{4,}', s):
            mixed_language += 1

    return {
        "source_type": source_type,
        "total_lines": total,
        "boilerplate_lines": boilerplate_lines,
        "boilerplate_ratio": round(boilerplate_lines / total, 4),
        "ocr_artifacts": ocr_artifacts,
        "short_noise_lines": short_noise,
        "short_noise_ratio": round(short_noise / total, 4),
        "mixed_language_lines": mixed_language,
        "mixed_language_ratio": round(mixed_language / total, 4),
    }


def should_fallback_by_quality(signals, quality_cfg=None):
    """Evaluate quality thresholds and return (should_fail_or_fallback, reason)."""
    quality_cfg = quality_cfg or {}
    max_boiler = quality_cfg.get("max_boilerplate_lines", 8)
    max_noise_ratio = quality_cfg.get("max_short_noise_ratio", 0.03)
    max_ocr = quality_cfg.get("max_ocr_artifacts", 5)
    max_mixed = quality_cfg.get("max_mixed_language_ratio", 0.35)

    if signals.get("boilerplate_lines", 0) > max_boiler:
        return True, f"boilerplate_lines>{max_boiler}"
    if signals.get("short_noise_ratio", 0.0) > max_noise_ratio:
        return True, f"short_noise_ratio>{max_noise_ratio}"
    if signals.get("ocr_artifacts", 0) > max_ocr:
        return True, f"ocr_artifacts>{max_ocr}"
    if signals.get("mixed_language_ratio", 0.0) > max_mixed:
        return True, f"mixed_language_ratio>{max_mixed}"
    return False, "ok"


def _code_fence_count(text):
    return len(re.findall(r'^\s*```', text, re.MULTILINE))


def _verify_code_block_integrity(source_text, translated_text):
    """Verify code fence integrity between source and translated markdown."""
    src = _code_fence_count(source_text)
    dst = _code_fence_count(translated_text)

    if src != dst:
        return False, f"code fence count mismatch ({dst}/{src})"
    if dst % 2 != 0:
        return False, "odd number of code fences"
    return True, "ok"


def protect_special_blocks(text):
    """Replace code blocks with placeholders before translation.

    Math expressions ($...$, $$...$$) are NOT protected — they are sent to the
    LLM so it can fix OCR artifacts while preserving the formulas.

    Returns:
        (protected_text, placeholders_dict)
    """
    import re
    placeholders = {}
    counter = [0]

    def _replace(match, prefix):
        key = f"<<{prefix}_{counter[0]}>>"
        placeholders[key] = match.group(0)
        counter[0] += 1
        return key

    # Fenced code blocks (```...```)
    text = re.sub(
        r'```[\s\S]*?```',
        lambda m: _replace(m, 'CODE_BLOCK'),
        text
    )

    # Math is intentionally NOT protected:
    # LLM sees math expressions and can fix OCR artifacts like
    # \mathrm { A P I } → \mathrm{API}, a _ { c } → a_{c}

    return text, placeholders


def restore_special_blocks(text, placeholders):
    """Restore placeholders back to original content."""
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


# Section header translations for skip targets
_SKIP_SECTION_HEADERS = {
    'references': '참고문헌 (References)',
    'bibliography': '참고문헌 (Bibliography)',
    'supplementary material': '보충 자료 (Supplementary Material)',
    'acknowledgements': '감사의 글 (Acknowledgements)',
    'acknowledgments': '감사의 글 (Acknowledgments)',
    'acknowledgement': '감사의 글 (Acknowledgement)',
    'acknowledgment': '감사의 글 (Acknowledgment)',
}


def classify_sections(body):
    """Split body by headings and classify each section.

    Returns:
        list of (section_text, should_translate: bool)
    """
    import re
    # Split on markdown headings, keeping the heading with its content
    parts = re.split(r'(^#{1,4}\s+.+$)', body, flags=re.MULTILINE)

    sections = []
    current_heading = None
    current_body_parts = []

    for part in parts:
        if re.match(r'^#{1,4}\s+', part):
            # Save previous section
            if current_heading is not None or current_body_parts:
                section_text = (current_heading + '\n' if current_heading else '') + '\n'.join(current_body_parts)
                sections.append(section_text.strip())
            current_heading = part
            current_body_parts = []
        else:
            current_body_parts.append(part)

    # Save last section
    if current_heading is not None or current_body_parts:
        section_text = (current_heading + '\n' if current_heading else '') + '\n'.join(current_body_parts)
        sections.append(section_text.strip())

    # Classify each section
    classified = []

    for section in sections:
        if not section:
            continue

        first_line = section.split('\n')[0]
        heading_text = re.sub(r'^#{1,4}\s+', '', first_line).strip()
        heading_lower = heading_text.lower().strip()

        # Check if this section should be skipped (each section judged independently)
        should_skip = False
        for skip_key in _SKIP_SECTION_HEADERS:
            if skip_key in heading_lower:
                should_skip = True
                break

        if should_skip:
            # Translate only the heading, keep body as-is
            heading_match = re.match(r'^(#{1,4})\s+(.+)$', first_line)
            if heading_match:
                level = heading_match.group(1)
                original_title = heading_match.group(2).strip()
                title_lower = original_title.lower()
                # Find matching translation
                translated_title = original_title
                for skip_key, ko_title in _SKIP_SECTION_HEADERS.items():
                    if skip_key in title_lower:
                        translated_title = ko_title
                        break
                rest = section[len(first_line):]
                section = f"{level} {translated_title}{rest}"

            classified.append((section, False))
        else:
            classified.append((section, True))

    return classified


def _is_safe_split_point(prev_paragraph):
    """Check if the paragraph ends at a natural sentence boundary.

    Prevents splitting in the middle of multi-line structures (tables, lists,
    figures) where the next chunk would start with a sentence fragment,
    causing the AI translator to insert spurious headings.
    """
    text = prev_paragraph.rstrip()
    if not text:
        return True
    # Ends with sentence terminator
    if text[-1] in '.?!:)]\u3002':
        return True
    # Ends with a markdown heading (already complete)
    last_line = text.split('\n')[-1]
    if re.match(r'^#{1,6}\s+', last_line):
        return True
    # Ends with a table row
    if last_line.rstrip().endswith('|'):
        return True
    return False


def _split_long_section(section_text, max_chars=5000):
    """Split a long section into chunks at safe paragraph boundaries.

    Uses _is_safe_split_point() to avoid splitting mid-sentence or
    mid-structure, which would cause AI to insert spurious headings.

    Returns:
        list of text chunks, each <= max_chars (best effort)
    """
    if len(section_text) <= max_chars:
        return [section_text]

    paragraphs = section_text.split('\n\n')
    chunks = []
    current_chunk = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for \n\n separator
        if current_len + para_len > max_chars and current_chunk:
            # Only split if previous paragraph ends at a safe boundary
            if _is_safe_split_point(current_chunk[-1]):
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_len = para_len
            else:
                # Not safe to split — keep accumulating even if over max_chars
                current_chunk.append(para)
                current_len += para_len
        else:
            current_chunk.append(para)
            current_len += para_len

    if current_chunk:
        chunks.append('\n\n'.join(current_chunk))

    return chunks if chunks else [section_text]


def _verify_translation(source_text, translated_text):
    """Verify translation completeness by comparing structural metrics.

    Returns:
        (is_ok: bool, reason: str)
    """
    source_len = len(source_text)
    trans_len = len(translated_text)

    if source_len == 0:
        return True, "ok"

    ratio = trans_len / source_len

    # Korean is typically 0.5~1.2x the length of English
    if ratio < 0.4:
        return False, f"too short ({ratio:.0%} of source)"

    # Compare markdown heading counts
    source_headings = len(re.findall(r'^#{1,4}\s+', source_text, re.MULTILINE))
    trans_headings = len(re.findall(r'^#{1,4}\s+', translated_text, re.MULTILINE))
    if source_headings > 0 and trans_headings < source_headings * 0.5:
        return False, f"headings missing ({trans_headings}/{source_headings})"

    # Check for extra headings (AI hallucination)
    if source_headings > 0 and trans_headings > source_headings * 1.5:
        return False, f"extra headings ({trans_headings} vs {source_headings} in source)"

    # Compare paragraph counts
    source_paras = len([p for p in source_text.split('\n\n') if p.strip()])
    trans_paras = len([p for p in translated_text.split('\n\n') if p.strip()])
    if source_paras > 3 and trans_paras < source_paras * 0.5:
        return False, f"paragraphs missing ({trans_paras}/{source_paras})"

    # Check that translation actually contains Korean characters
    # Skip check for short sections (likely contributor names, code, or math)
    if source_len > 800:
        korean_chars = len(re.findall(r'[\uAC00-\uD7A3]', translated_text))
        # Strip markdown/code/math to get prose-like text for comparison
        prose_text = re.sub(r'```[\s\S]*?```', '', translated_text)
        prose_text = re.sub(r'\$\$[\s\S]*?\$\$', '', prose_text)
        prose_text = re.sub(r'`[^`]*`', '', prose_text)
        prose_text = re.sub(r'#{1,6}\s+', '', prose_text)
        prose_text = re.sub(r'\[.*?\]\(.*?\)', '', prose_text)
        prose_text = re.sub(r'<[^>]+>', '', prose_text)
        prose_chars = len(re.sub(r'\s+', '', prose_text))
        if prose_chars > 200 and korean_chars < prose_chars * 0.05:
            return False, f"no Korean detected ({korean_chars} Korean chars in {prose_chars} prose chars)"

    # Check for foreign language contamination (non-Korean, non-English, non-math)
    # Detect Hindi (Devanagari), Chinese, Japanese (Hiragana/Katakana), Arabic, Thai, etc.
    foreign_chars = re.findall(
        r'[\u0900-\u097F'   # Devanagari (Hindi)
        r'\u0600-\u06FF'    # Arabic
        r'\u0E00-\u0E7F'    # Thai
        r'\u3040-\u309F'    # Hiragana (Japanese)
        r'\u30A0-\u30FF'    # Katakana (Japanese)
        r'\u4E00-\u9FFF'    # CJK (Chinese) - only flag if no Korean context
        r']', translated_text
    )
    if len(foreign_chars) >= 3:
        # CJK chars are OK if they appear in Korean context (e.g., 漢字 in academic Korean)
        non_cjk_foreign = [c for c in foreign_chars if not ('\u4E00' <= c <= '\u9FFF')]
        if len(non_cjk_foreign) >= 3:
            return False, f"foreign language detected ({len(non_cjk_foreign)} non-Korean/English chars)"

    return True, "ok"


def _strip_spurious_headings(source_text, translated_text):
    """Remove headings in translation that don't exist in the source.

    AI translators sometimes insert headings like '# 번역문' or '# Translation'
    when they receive text fragments without context. This post-processing step
    detects and removes such spurious headings.

    Args:
        source_text: Original English markdown (pre-protection, with headings)
        translated_text: Korean translated markdown

    Returns:
        Cleaned translated text with spurious headings removed
    """
    source_headings = re.findall(r'^#{1,6}\s+', source_text, re.MULTILINE)
    trans_headings = re.findall(r'^#{1,6}\s+', translated_text, re.MULTILINE)

    if len(trans_headings) <= len(source_headings):
        return translated_text  # No extra headings

    # Known AI artifact heading patterns
    _ARTIFACT_PATTERNS = [
        re.compile(r'^#{1,6}\s+번역문\s*$'),
        re.compile(r'^#{1,6}\s+[Tt]ranslat(ion|ed)(\s+[Tt]ext)?\s*$'),
        re.compile(r'^#{1,6}\s+한국어\s*(번역|버전)\s*$'),
        re.compile(r'^#{1,6}\s+Korean\s+[Tt]ranslat(ion|ed)\s*$'),
    ]

    lines = translated_text.split('\n')
    cleaned = []
    removed_count = 0

    for line in lines:
        if re.match(r'^#{1,6}\s+', line):
            if any(p.match(line) for p in _ARTIFACT_PATTERNS):
                removed_count += 1
                continue  # Skip this spurious heading
        cleaned.append(line)

    if removed_count > 0:
        print_info(f"Removed {removed_count} spurious heading(s) from translation")
        return '\n'.join(cleaned)

    return translated_text


def estimate_tokens(text):
    """Rough token estimate. English words * 1.3 approximation."""
    return int(len(text.split()) * 1.3)


def _call_translation_api(client, model, system_prompt, content, config, source_chars=0, max_tokens_override=0):
    """Call OpenAI-compatible API with streaming, progress bar, and retry logic.

    Args:
        source_chars: Length of source text for progress estimation (0 = no progress bar)
        max_tokens_override: Dynamic max_tokens value (0 = use env/default)

    Returns:
        translated text or None on failure
    """
    import time

    max_retries = config.get("translation", {}).get("max_retries", 3)
    retry_delay = config.get("translation", {}).get("retry_delay_seconds", 2)
    timeout = config.get("translation", {}).get("timeout_seconds", 300)
    temperature = float(os.getenv("TRANSLATION_TEMPERATURE", "0.3"))

    # Dynamic max_tokens: use override, then env, then calculate from source
    if max_tokens_override > 0:
        max_tokens = max_tokens_override
    else:
        env_max = int(os.getenv("TRANSLATION_MAX_TOKENS", "0"))
        if env_max > 0:
            max_tokens = env_max
        else:
            # Auto-calculate: Korean tokens ~1.8x English source tokens
            source_token_est = estimate_tokens(content)
            max_tokens = max(int(source_token_est * 1.8), 4096)

    for attempt in range(max_retries):
        try:
            print_info(f"Calling API... (attempt {attempt+1}/{max_retries}, timeout={timeout}s)")
            start_time = time.time()
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                stream=True
            )

            chunks = []
            char_count = 0
            last_report = 0
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    chunks.append(text)
                    char_count += len(text)
                    # Report progress every 500 chars
                    if char_count - last_report >= 500:
                        elapsed = time.time() - start_time
                        if source_chars > 0:
                            # Korean is ~0.7~1.0x length of English
                            estimated_total = int(source_chars * 0.85)
                            pct = min(char_count / estimated_total * 100, 99) if estimated_total > 0 else 0
                            bar_len = 20
                            filled = int(bar_len * pct / 100)
                            bar = '\u2588' * filled + '\u2591' * (bar_len - filled)
                            print(f"\r{Colors.OKCYAN}  \u21b3 [{bar}] {pct:.0f}% ({char_count:,} chars, {elapsed:.0f}s){Colors.ENDC}", end="", flush=True)
                        else:
                            print(f"\r{Colors.OKCYAN}  \u21b3 Receiving: {char_count:,} chars ({elapsed:.0f}s){Colors.ENDC}", end="", flush=True)
                        last_report = char_count

            elapsed = time.time() - start_time
            print(f"\r{Colors.OKCYAN}  \u21b3 Received: {char_count:,} chars in {elapsed:.1f}s{Colors.ENDC}          ")
            return ''.join(chunks)

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                print_warning(f"API call failed (attempt {attempt+1}/{max_retries}): {e}")
                print_info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print_error(f"API call failed after {max_retries} attempts: {e}")
                return None


async def _call_translation_api_async(client, model, system_prompt, content, config,
                                       source_chars=0, max_tokens_override=0):
    """Async version of _call_translation_api with identical logic.

    Args:
        client: AsyncOpenAI client instance
        model: Model name
        system_prompt: System prompt string
        content: Content to translate
        config: Configuration dict
        source_chars: Length of source text for progress estimation (0 = no progress bar)
        max_tokens_override: Dynamic max_tokens value (0 = use env/default)

    Returns:
        translated text or None on failure
    """
    import time
    import asyncio

    max_retries = config.get("translation", {}).get("max_retries", 3)
    retry_delay = config.get("translation", {}).get("retry_delay_seconds", 2)
    timeout = config.get("translation", {}).get("timeout_seconds", 300)
    temperature = float(os.getenv("TRANSLATION_TEMPERATURE", "0.3"))

    # Dynamic max_tokens: use override, then env, then calculate from source
    if max_tokens_override > 0:
        max_tokens = max_tokens_override
    else:
        env_max = int(os.getenv("TRANSLATION_MAX_TOKENS", "0"))
        if env_max > 0:
            max_tokens = env_max
        else:
            source_token_est = estimate_tokens(content)
            max_tokens = max(int(source_token_est * 1.8), 4096)

    for attempt in range(max_retries):
        try:
            start_time = time.time()
            stream = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                stream=True
            )

            chunks = []
            char_count = 0
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    chunks.append(text)
                    char_count += len(text)

            elapsed = time.time() - start_time
            return ''.join(chunks)

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                print_warning(f"Async API call failed (attempt {attempt+1}/{max_retries}): {e}")
                await asyncio.sleep(wait_time)
            else:
                print_error(f"Async API call failed after {max_retries} attempts: {e}")
                return None


async def _translate_chunks_parallel(client, model, system_prompt, chunks,
                                      prev_context, config):
    """Translate multiple chunks in parallel with concurrency control.

    Args:
        client: AsyncOpenAI client instance
        model: Model name
        system_prompt: Base system prompt
        chunks: List of text chunks from same section
        prev_context: Shared context from previous section
        config: Configuration dict with parallel settings

    Returns:
        List of translated chunks in original order, or None if critical failure
    """
    import asyncio

    max_workers = config.get("translation", {}).get("parallel_max_workers", 3)
    semaphore = asyncio.Semaphore(max_workers)

    async def translate_one_chunk(idx, chunk):
        """Translate single chunk with semaphore control."""
        async with semaphore:
            prompt_with_context = system_prompt
            if prev_context:
                prompt_with_context += f"\n\n[Previous context for terminology consistency: ...{prev_context}]"

            dynamic_max = max(int(estimate_tokens(chunk) * 1.8), 4096)

            result = await _call_translation_api_async(
                client, model, prompt_with_context, chunk, config,
                source_chars=len(chunk), max_tokens_override=dynamic_max
            )

            return (idx, result)

    # Create tasks for all chunks
    tasks = [translate_one_chunk(i, chunk) for i, chunk in enumerate(chunks)]

    # Execute with error handling
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    ordered_results = [None] * len(chunks)
    failed_count = 0

    for result in results:
        if isinstance(result, Exception):
            print_warning(f"Parallel chunk translation error: {result}")
            failed_count += 1
            continue

        idx, translated = result
        if translated is None:
            failed_count += 1
        else:
            ordered_results[idx] = translated

    # If too many failures, raise error to trigger fallback
    if failed_count > len(chunks) * 0.3:
        raise RuntimeError(f"Too many parallel failures: {failed_count}/{len(chunks)}")

    # Fill any remaining None values with empty strings (will fail verification)
    return [r if r is not None else "" for r in ordered_results]


def translate_md_to_korean_openai(md_path, output_dir, config, system_prompt, progress_callback=None):
    """Translate English markdown to Korean using OpenAI-compatible API.

    Pipeline: YAML分離 → OCR정리 → 코드보호 → 섹션분류 → 번역(수식OCR정리포함) → 복원/결합

    Returns:
        Path to Korean markdown file (*_ko.md) or None on failure
    """
    from pathlib import Path
    from dotenv import load_dotenv

    try:
        load_dotenv(override=True)

        api_base = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("TRANSLATION_MODEL", "gemini-claude-sonnet-4-5")

        if not api_base or not api_key:
            print_error("OPENAI_BASE_URL or OPENAI_API_KEY not set in .env")
            return None

        print_info(f"Translation model: {model}")
        print_info(f"API endpoint: {api_base}")

        # Initialize OpenAI clients (sync and async)
        try:
            from openai import OpenAI, AsyncOpenAI
            import asyncio
            client_sync = OpenAI(base_url=api_base, api_key=api_key)
            client_async = AsyncOpenAI(base_url=api_base, api_key=api_key)
        except Exception as e:
            print_error(f"Failed to initialize OpenAI client: {e}")
            return None

        # Read source markdown
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Step 1: Separate YAML frontmatter
        _, body = split_yaml_and_body(content)
        print_info("YAML frontmatter separated (will use header.yaml for output)")

        # Step 2: Clean OCR artifacts
        body = clean_ocr_artifacts(body)
        body = clean_ocr_math(body)
        print_success("OCR artifacts cleaned (including math)")

        # Step 2.5: Markdown preflight (code fence/structure cleanup)
        body, preflight_report = _markdown_preflight_for_translation(body)
        preflight_changes = sum(
            v for k, v in preflight_report.items()
            if k != "unlabeled_code_fences"
        )
        if preflight_changes > 0:
            print_info(f"Markdown preflight applied: {preflight_report}")

        # Phase 1 quality signals (measurement-only)
        quality_cfg = config.get("quality", {})
        pre_quality = compute_quality_signals(body, source_type="translated_md")
        should_fb, fb_reason = should_fallback_by_quality(pre_quality, quality_cfg)
        print_info(f"Quality(pre): {pre_quality}")
        quality_gate_enabled = quality_cfg.get("enable_gate", False)
        allow_warn_save = quality_cfg.get("allow_warn_save", True)
        if should_fb:
            if quality_gate_enabled and not allow_warn_save:
                print_error(f"Quality gate(pre) failed: {fb_reason}")
                return None
            print_warning(f"Quality gate(pre) warning: {fb_reason}")

        # Save body before protection for integrity checks later
        body_before_protection = body

        # Step 3: Protect code blocks (math is left for LLM to fix OCR artifacts)
        body, placeholders = protect_special_blocks(body)
        if placeholders:
            print_info(f"Protected {len(placeholders)} code block(s)")

        # Step 4: Classify sections
        sections = classify_sections(body)
        translatable = [(s, t) for s, t in sections if t]
        skipped = [(s, t) for s, t in sections if not t]
        print_info(f"Sections: {len(translatable)} to translate, {len(skipped)} to skip")

        # Step 5: Section-by-section translation (always, for quality)
        import time as _time
        total_chars = sum(len(s) for s, t in sections if t)
        translatable_count = sum(1 for _, t in sections if t)
        max_section_chars = config.get("translation", {}).get("max_section_chars", 5000)
        verify_enabled = config.get("translation", {}).get("verify_translation", True)

        # Parallel translation settings
        parallel_enabled = config.get("translation", {}).get("enable_parallel_translation", True)
        parallel_min_chunks = config.get("translation", {}).get("parallel_min_chunks", 2)
        max_workers = config.get("translation", {}).get("parallel_max_workers", 3)

        print_info(f"Translating {translatable_count} sections ({total_chars:,} chars)")
        if parallel_enabled:
            print_info(f"Parallel translation enabled (max {max_workers} concurrent API calls)")

        translate_start = _time.time()
        prev_context = ""
        translated_parts = []
        chars_translated = 0
        section_idx = 0

        for i, (section_text, should_translate) in enumerate(sections, 1):
            if not should_translate:
                translated_parts.append(section_text)
                continue

            section_idx += 1
            overall_pct = chars_translated / total_chars * 100 if total_chars > 0 else 0

            # Update progress callback for status tracking
            if progress_callback:
                progress_callback(section_idx, translatable_count, overall_pct)

            # Split long sections into paragraph-level chunks
            chunks = _split_long_section(section_text, max_section_chars)

            if len(chunks) == 1:
                # Single chunk section
                print_info(f"Section {section_idx}/{translatable_count} ({overall_pct:.0f}% overall, {len(section_text):,} chars)")

                prompt_with_context = system_prompt
                if prev_context:
                    prompt_with_context += f"\n\n[Previous context for terminology consistency: ...{prev_context}]"

                # Dynamic max_tokens based on source length
                dynamic_max = max(int(estimate_tokens(section_text) * 1.8), 4096)

                result = _call_translation_api(
                    client_sync, model, prompt_with_context, section_text, config,
                    source_chars=len(section_text), max_tokens_override=dynamic_max
                )
                if not result:
                    print_error(f"Section {section_idx} translation failed")
                    return None

                # Verify translation completeness
                if verify_enabled:
                    is_ok, reason = _verify_translation(section_text, result)
                    if not is_ok:
                        print_warning(f"Verification failed ({reason}), retrying section {section_idx}...")
                        retry_prompt = system_prompt + "\n\nIMPORTANT: Your previous translation was incomplete or not translated to Korean. You MUST translate ALL text into Korean (한국어). Do NOT return the original English text. Translate EVERY sentence without any omission."
                        if prev_context:
                            retry_prompt += f"\n\n[Previous context for terminology consistency: ...{prev_context}]"
                        result2 = _call_translation_api(
                            client_sync, model, retry_prompt, section_text, config,
                            source_chars=len(section_text), max_tokens_override=dynamic_max
                        )
                        if result2:
                            _, reason2 = _verify_translation(section_text, result2)
                            if reason2 == "ok" or len(result2) > len(result):
                                result = result2
                                print_success("Retry improved translation")
                            else:
                                print_warning(f"Retry did not improve ({reason2}), using best result")

                translated_parts.append(result)
                prev_context = result[-200:] if len(result) > 200 else result
                chars_translated += len(section_text)

            else:
                # Long section split into multiple chunks
                print_info(f"Section {section_idx}/{translatable_count} ({overall_pct:.0f}% overall, {len(section_text):,} chars -> {len(chunks)} chunks)")

                # TRY PARALLEL TRANSLATION FIRST
                section_results = None
                if parallel_enabled and len(chunks) >= parallel_min_chunks:
                    print_info(f"  [PARALLEL MODE: {len(chunks)} chunks with max {max_workers} workers]")
                    try:
                        section_results = asyncio.run(
                            _translate_chunks_parallel(
                                client_async, model, system_prompt, chunks,
                                prev_context, config
                            )
                        )
                        print_success(f"  Parallel translation complete")

                        # Update context from last chunk
                        if section_results:
                            last_result = section_results[-1]
                            prev_context = last_result[-200:] if len(last_result) > 200 else last_result

                    except Exception as e:
                        print_warning(f"  Parallel translation failed: {e}")
                        print_info(f"  Falling back to sequential mode...")
                        section_results = None

                # FALLBACK TO SEQUENTIAL IF PARALLEL FAILED OR DISABLED
                if section_results is None:
                    print_info(f"  [SEQUENTIAL MODE: {len(chunks)} chunks]")
                    section_results = []

                    for ci, chunk in enumerate(chunks, 1):
                        chunk_chars_before = sum(len(c) for c in chunks[:ci-1])
                        chunk_pct = (chars_translated + chunk_chars_before) / total_chars * 100 if total_chars > 0 else 0
                        print_info(f"  Chunk {ci}/{len(chunks)} ({chunk_pct:.0f}% overall, {len(chunk):,} chars)")

                        prompt_with_context = system_prompt
                        if prev_context:
                            prompt_with_context += f"\n\n[Previous context for terminology consistency: ...{prev_context}]"

                        dynamic_max = max(int(estimate_tokens(chunk) * 1.8), 4096)

                        result = _call_translation_api(
                            client_sync, model, prompt_with_context, chunk, config,
                            source_chars=len(chunk), max_tokens_override=dynamic_max
                        )
                        if not result:
                            print_error(f"Section {section_idx} chunk {ci} failed")
                            return None

                        section_results.append(result)
                        prev_context = result[-200:] if len(result) > 200 else result

                combined = '\n\n'.join(section_results)

                # Verify combined section
                if verify_enabled:
                    is_ok, reason = _verify_translation(section_text, combined)
                    if not is_ok:
                        print_warning(f"Section {section_idx} verification: {reason} (proceeding with best result)")

                translated_parts.append(combined)
                chars_translated += len(section_text)

        elapsed_total = _time.time() - translate_start
        final_body = '\n\n'.join(translated_parts)
        print_success(f"All sections translated ({elapsed_total:.0f}s total)")

        # Step 6: Restore protected blocks
        final_body = restore_special_blocks(final_body, placeholders)

        # Step 6.5: Strip spurious headings inserted by AI
        final_body = _strip_spurious_headings(body_before_protection, final_body)

        # Step 6.6: Code block integrity gate (source vs translated)
        code_ok, code_reason = _verify_code_block_integrity(body_before_protection, final_body)
        if not code_ok:
            print_warning(f"Code-block integrity check failed: {code_reason}")
            # Best-effort auto-fix: close dangling fence if odd
            if _code_fence_count(final_body) % 2 != 0:
                final_body = final_body.rstrip() + "\n\n```\n"
                print_info("Auto-fixed dangling code fence by appending closing ```")
                code_ok2, code_reason2 = _verify_code_block_integrity(body_before_protection, final_body)
                if not code_ok2:
                    print_warning(f"Code-block integrity still mismatched: {code_reason2}")

        # Step 7: Write output with header.yaml
        base_name = os.path.basename(md_path).replace('.md', '')
        ko_md_path = os.path.join(output_dir, f"{base_name}_ko.md")

        header_path = Path("header.yaml")
        header = ''
        if header_path.exists():
            with open(header_path, 'r', encoding='utf-8') as f:
                header = f.read()
        else:
            print_warning("header.yaml not found, using minimal header")
            header = '---\nlang: ko\nformat:\n  html:\n    toc: true\n    embed-resources: true\n    theme: cosmo\n---'

        with open(ko_md_path, 'w', encoding='utf-8') as f:
            f.write(header)
            if not header.endswith('\n'):
                f.write('\n')
            f.write('\n')
            f.write(final_body)

        # Save markdown quality/preflight report for UI and debugging
        try:
            post_quality = compute_quality_signals(final_body, source_type="translated_md_ko")
            post_fail, post_reason = should_fallback_by_quality(post_quality, quality_cfg)
            gate_status = "PASS"
            if post_fail:
                if quality_gate_enabled and not allow_warn_save:
                    gate_status = "FAIL"
                else:
                    gate_status = "WARN"

            lint_report = {
                "source_md": md_path,
                "output_md": ko_md_path,
                "preflight": preflight_report,
                "preflight_changes": preflight_changes,
                "quality": {
                    "pre": pre_quality,
                    "post": post_quality,
                    "gate_enabled": bool(quality_gate_enabled),
                    "allow_warn_save": bool(allow_warn_save),
                    "status": gate_status,
                    "reason": post_reason if post_fail else "ok",
                },
                "code_block_integrity": {
                    "ok": bool(code_ok),
                    "reason": code_reason,
                    "source_fences": _code_fence_count(body_before_protection),
                    "translated_fences": _code_fence_count(final_body),
                },
                "generated_at": datetime.now().isoformat(),
            }
            lint_path = os.path.join(output_dir, f"{base_name}_mdlint_report.json")
            with open(lint_path, 'w', encoding='utf-8') as rf:
                json.dump(lint_report, rf, ensure_ascii=False, indent=2)
            print_info(f"Markdown quality report saved: {lint_path}")
        except Exception as e:
            print_warning(f"Failed to save markdown quality report: {e}")

        if quality_gate_enabled and gate_status == "FAIL":
            print_error(f"Quality gate(post) failed: {post_reason}")
            try:
                os.remove(ko_md_path)
                print_warning("Removed output due to hard quality gate failure")
            except Exception:
                pass
            return None

        print_success(f"Translation saved: {ko_md_path} (quality={gate_status})")
        return ko_md_path

    except Exception as e:
        print_error(f"Translation error: {e}")
        import traceback
        print_error(traceback.format_exc())
        return None

_COVER_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_COVER_SUBDIRS = ("", "images", "figures", "assets")


def _gather_cover_candidates(output_dir, min_dimension, max_candidates):
    """폴더에서 커버 후보 이미지의 폴더 상대경로 리스트를 반환.

    루트 + images/figures/assets 서브디렉토리에서 알려진 확장자 이미지를 모으고,
    긴 변이 min_dimension 미만인 것은 제외(아이콘/로고/수식조각). 면적 내림차순,
    동률은 상대경로 문자열 순으로 정렬해 상위 max_candidates개를 반환한다.
    AI 호출 없음 — 순수 함수.
    """
    from PIL import Image

    scored = []  # (-area, relpath)
    for sub in _COVER_SUBDIRS:
        dir_path = os.path.join(output_dir, sub) if sub else output_dir
        if not os.path.isdir(dir_path):
            continue
        for fname in os.listdir(dir_path):
            if not fname.lower().endswith(_COVER_IMG_EXTS):
                continue
            abs_path = os.path.join(dir_path, fname)
            if not os.path.isfile(abs_path):
                continue
            try:
                with Image.open(abs_path) as im:
                    w, h = im.size
            except Exception:
                continue
            if max(w, h) < min_dimension:
                continue
            rel = os.path.join(sub, fname) if sub else fname
            scored.append((-(w * h), rel))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [rel for _, rel in scored[:max_candidates]]


def _downscale_to_data_url(abs_path, downscale_px):
    """이미지를 긴 변 downscale_px 이하 JPEG로 줄여 base64 data URL 반환.

    원본보다 크게 확대하지 않는다. RGBA/팔레트는 RGB로 변환.
    """
    import base64
    import io
    from PIL import Image

    with Image.open(abs_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        longest = max(w, h)
        if longest > downscale_px:
            scale = downscale_px / float(longest)
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


COVER_SELECTION_PROMPT = (
    "다음은 어떤 {doc_type} 문서에서 추출한 후보 이미지들이다(1번부터 번호 매김). "
    "컨텐츠 카드의 표지(cover)로 가장 적합하고 대표성 있는 이미지 1장을 골라라. "
    "전부 수식·표·플롯·로고·인물 증명샷처럼 표지로 부적합하면 고르지 마라. "
    'JSON 으로만 답하라: {{"choice": <후보 번호 정수 또는 null>}}'
)


def select_cover_image(output_dir, metadata, config, client=None):
    """비전 모델로 커버 이미지를 선별해 metadata['cover']에 기록한다.

    optional 스테이지 — 어떤 실패도 예외를 전파하지 않고 cover 미설정으로 종료.
    가드: doc_type=='video' / cover 이미 존재 / 후보 0장 → 비전 호출 없이 스킵.
    선택 시 폴더 상대경로를 metadata['cover']에 넣고 paper_meta.json을 저장한다.
    """
    try:
        if not metadata:
            return metadata
        if metadata.get("doc_type") == "video":
            return metadata
        if metadata.get("cover"):
            return metadata

        cov = config.get("cover_selection", {})
        max_candidates = cov.get("max_candidates", 6)
        min_dimension = cov.get("min_dimension", 200)
        downscale_px = cov.get("downscale_px", 768)
        timeout = cov.get("timeout_seconds", 60)
        max_retries = cov.get("max_retries", 2)

        candidates = _gather_cover_candidates(output_dir, min_dimension, max_candidates)
        if not candidates:
            print_info("Cover selection: no candidate images, skipping")
            return metadata

        if client is None:
            api_base = os.getenv("OPENAI_BASE_URL")
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_base or not api_key:
                print_warning("Cover selection skipped: OPENAI_BASE_URL or OPENAI_API_KEY not set")
                return metadata
            from openai import OpenAI
            client = OpenAI(base_url=api_base, api_key=api_key)

        model = os.getenv("COVER_MODEL") or os.getenv("TRANSLATION_MODEL", "gemini-claude-sonnet-4-5")
        doc_type = metadata.get("doc_type") or "document"

        content = [{"type": "text",
                    "text": COVER_SELECTION_PROMPT.format(doc_type=doc_type)}]
        for idx, rel in enumerate(candidates, start=1):
            content.append({"type": "text", "text": f"후보 {idx}:"})
            data_url = _downscale_to_data_url(os.path.join(output_dir, rel), downscale_px)
            content.append({"type": "image_url", "image_url": {"url": data_url}})

        choice = None
        last_error = None
        answered = False
        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    temperature=0.1,
                    timeout=timeout,
                )
                raw = (resp.choices[0].message.content or "").strip()
                choice = _parse_cover_choice(raw, len(candidates))
                answered = True
                break
            except Exception as e:
                last_error = e
                print_warning(f"Cover selection attempt {attempt+1} failed: {e}")

        # 모델이 "커버 없음"으로 판단한 것과 프로바이더가 죽어서 못 물어본 것은
        # 결과(cover 미설정)가 같아 로그로 구분되지 않았다. 이제 구분해 남긴다.
        if not answered:
            print_warning(
                f"Cover selection FAILED (model={model} unreachable after "
                f"{max_retries} attempts): {last_error} — cover left unset"
            )
            return metadata

        if choice is None:
            print_info("Cover selection: no suitable cover chosen")
            return metadata

        chosen_rel = candidates[choice - 1]
        metadata["cover"] = chosen_rel
        meta_path = os.path.join(output_dir, "paper_meta.json")
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            print_success(f"Cover selected: {chosen_rel}")
        except Exception as e:
            print_warning(f"Failed to persist cover to paper_meta.json: {e}")
        return metadata
    except Exception as e:
        print_warning(f"Cover selection error (continuing): {e}")
        return metadata


def _parse_cover_choice(raw, n_candidates):
    """비전 응답 문자열에서 1..n_candidates 정수 또는 None을 파싱.

    응답에서 첫 JSON 객체를 추출해 {"choice": <int|null>} 를 읽는다.
    실패/범위 밖/불리언이면 None. 절대 예외를 던지지 않는다.
    """
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        c = data.get("choice")
        if isinstance(c, bool):  # bool 은 int 의 서브타입 — 배제
            return None
        if isinstance(c, int) and 1 <= c <= n_candidates:
            return c
        return None
    except Exception:
        return None


def process_pdf_to_output_dir(pdf_path, output_dir, base_name, config, prompt, mode="paper"):
    """Process one PDF into a caller-supplied output_dir.

    mode="paper" (default) preserves the original paper pipeline exactly.
    mode="book_chapter" skips paper-only stages (web search, smart-rename,
    global duplicate check, cover selection).
    """
    try:
        pdf_name = os.path.basename(pdf_path)

        print_header(f"Processing: {pdf_name}")
        print_info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Get pipeline configuration
        pipeline = config.get("processing_pipeline", {
            "convert_to_markdown": True,
        })

        # Display pipeline configuration
        engine = os.environ.get("PDF_CONVERTER", "marker").lower()
        print_info("Pipeline configuration:")
        print_info(f"  • Converter: {engine}")
        print_info(f"  • PDF → Markdown: {'Enabled' if pipeline['convert_to_markdown'] else 'Disabled'}")
        print_info(f"  • Metadata Extraction: {'Enabled' if pipeline.get('extract_metadata', False) else 'Disabled'}")
        print_info(f"  • Web Search Enrichment: {'Enabled' if pipeline.get('enrich_with_web_search', True) else 'Disabled'}")
        print_info(f"  • Translation (Korean): {'Enabled' if pipeline.get('translate_to_korean', False) else 'Disabled'}")
        print()

        # Initialize processing status tracking
        total_stages = _count_active_stages(pipeline)
        if mode != "paper":
            # book_chapter mode skips duplicate-check and cover stages (see gating below)
            if pipeline.get("check_duplicate", True) and pipeline.get("extract_metadata", False):
                total_stages -= 1
            if pipeline.get("select_cover", True) and pipeline.get("extract_metadata", False):
                total_stages -= 1
        current_stage = 0

        # Create output directory
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print_success(f"Created output directory: {output_dir}")
        else:
            print_info(f"Output directory exists: {output_dir}")

        # Track processing results
        results = {
            "markdown": None,
            "metadata": None,
            "translation": None,
        }
        metadata = None
        duplicate_found = False

        # Step 1: PDF to MD (conditional)
        md_path = None
        if pipeline["convert_to_markdown"]:
            current_stage += 1
            write_processing_status(pdf_name, "converting", current_stage, total_stages, "PDF to Markdown")
            print_info(f"Step 1: Converting PDF to Markdown...")
            try:
                status_info = {"pdf_name": pdf_name, "stage_num": current_stage, "total_stages": total_stages}

                # URL-first path (Phase 2): for imported web PDFs, try HTML extraction first.
                used_url_first = False
                source_url = _find_source_url_sidecar(pdf_path)
                if pipeline.get("url_html_first", False) and source_url:
                    print_info(f"URL-first enabled: {source_url}")
                    md_path = _try_url_first_extraction(source_url, output_dir, base_name, pipeline)
                    if md_path:
                        used_url_first = True

                if not used_url_first:
                    with _gpu_lock():   # converter↔TTS GPU 상호배제(공유 flock)
                        md_path = convert_pdf_to_md_dispatch(pdf_path, output_dir, config, status_info=status_info)

                if md_path:
                    print_success(f"Markdown conversion complete: {md_path}")
                    results["markdown"] = "success"
                else:
                    print_error(f"Markdown conversion failed")
                    results["markdown"] = "failed"
            except Exception as e:
                print_error(f"Markdown conversion error: {e}")
                results["markdown"] = "failed"
        else:
            # Check if markdown already exists
            expected_md = os.path.join(output_dir, base_name + ".md")
            if os.path.exists(expected_md):
                md_path = expected_md
                print_info(f"Using existing markdown: {md_path}")
                results["markdown"] = "skipped"
            else:
                print_warning(f"Markdown conversion disabled and no existing file found")
                results["markdown"] = "skipped"

        # Step 1.1: Normalize heading levels (fix OCR inconsistencies)
        if pipeline.get("normalize_headings", True) and md_path and os.path.exists(md_path):
            try:
                with open(md_path, 'r', encoding='utf-8') as f:
                    md_content = f.read()
                normalized = normalize_heading_levels(md_content)
                if normalized != md_content:
                    with open(md_path, 'w', encoding='utf-8') as f:
                        f.write(normalized)
                    # Count changed headings
                    orig = _re.findall(r'^#{1,6}', md_content, _re.MULTILINE)
                    norm = _re.findall(r'^#{1,6}', normalized, _re.MULTILINE)
                    changed = sum(1 for a, b in zip(orig, norm) if a != b)
                    print_success(f"Heading levels normalized ({changed} heading(s) adjusted)")
                else:
                    print_info("Headings already consistent")
            except Exception as e:
                print_warning(f"Heading normalization skipped: {e}")

        # Step 1.2: Clean OCR math artifacts in English markdown
        if md_path and os.path.exists(md_path):
            try:
                with open(md_path, 'r', encoding='utf-8') as f:
                    md_content = f.read()
                cleaned = clean_ocr_math(md_content)
                if cleaned != md_content:
                    with open(md_path, 'w', encoding='utf-8') as f:
                        f.write(cleaned)
                    print_success("OCR math artifacts cleaned in English markdown")
                else:
                    print_info("No OCR math artifacts found")
            except Exception as e:
                print_warning(f"OCR math cleanup skipped: {e}")

        # Step 1.5: Extract metadata and optionally rename folder
        if pipeline.get("extract_metadata", False) and md_path and os.path.exists(md_path):
            current_stage += 1
            write_processing_status(pdf_name, "metadata", current_stage, total_stages, "Extracting Metadata")
            print_info("Step 1.5: Extracting paper metadata with AI...")
            try:
                metadata = extract_paper_metadata(md_path, output_dir, config)
                if metadata:
                    title_preview = (metadata.get('title') or 'N/A')[:60]
                    print_success(f"Metadata extracted - Title: {title_preview}")
                    results["metadata"] = "success"

                    # Enrich metadata with web search (venue, DOI, year, URL)
                    if pipeline.get("enrich_with_web_search", True) and mode == "paper":
                        metadata = enrich_metadata_with_web_search(metadata, output_dir, config)

                    # Smart rename if enabled
                    meta_config = config.get("metadata_extraction", {})
                    if meta_config.get("smart_rename", True) and metadata.get("title") and mode == "paper":
                        max_len = meta_config.get("max_folder_name_length", 80)
                        new_name = sanitize_folder_name(metadata["title"], max_len)
                        if new_name and new_name != base_name:
                            print_info(f"Renaming: {base_name} -> {new_name}")
                            rename_result = rename_output_directory(output_dir, new_name, base_name)
                            if rename_result:
                                output_dir, base_name = rename_result
                                # Find actual .md file (suffix may include extra spaces from original name)
                                md_path = None
                                for f in os.listdir(output_dir):
                                    if f.endswith(".md") and not f.endswith("_ko.md") and not f.endswith("_explained.md") and not "_backup_" in f:
                                        md_path = os.path.join(output_dir, f)
                                        break
                                print_success(f"Folder renamed to: {base_name}")
                            else:
                                print_warning("Folder rename failed, keeping original name")
                else:
                    print_warning("Metadata extraction failed (continuing without metadata)")
                    results["metadata"] = "failed"
            except Exception as e:
                print_error(f"Metadata extraction error: {e}")
                results["metadata"] = "failed"
        else:
            results["metadata"] = "skipped"

        # Handle Korean source: rename .md → _ko.md, skip translation
        skip_translation = False
        if results.get("metadata") == "success" and metadata:
            source_lang = metadata.get("source_language", "en")
            if source_lang == "ko" and md_path and os.path.exists(md_path):
                ko_md_dest = md_path.replace('.md', '_ko.md')
                if not os.path.exists(ko_md_dest):
                    try:
                        os.rename(md_path, ko_md_dest)
                        print_success(f"Korean source detected → {os.path.basename(ko_md_dest)}")
                        md_path = None
                        skip_translation = True
                        results["translation"] = "skipped_korean_source"
                    except Exception as e:
                        print_warning(f"Korean source rename failed: {e}")

        # Step 1.7: Duplicate check (optional, requires metadata)
        if pipeline.get("check_duplicate", True) and metadata and mode == "paper":
            current_stage += 1
            write_processing_status(pdf_name, "checking_duplicate", current_stage, total_stages, "Checking for Duplicates")
            print_info("Step 1.7: Checking for duplicate papers...")
            try:
                duplicates = check_duplicate_batch(metadata, output_dir)
                if duplicates:
                    duplicate_found = True
                    for d in duplicates:
                        print_warning(f"Duplicate detected! Same title found in: {d['location']}/{d['folder']}")
                    print_warning("Skipping translation to save resources.")
                    results["duplicate_check"] = "duplicate_found"
                    skip_translation = True
                else:
                    print_success("No duplicates found")
                    results["duplicate_check"] = "clear"
            except Exception as e:
                print_warning(f"Duplicate check error (continuing): {e}")
                results["duplicate_check"] = "error"

        # Step 1.8: Cover image selection (optional, vision)
        if pipeline.get("select_cover", True) and metadata and mode == "paper":
            current_stage += 1
            write_processing_status(pdf_name, "selecting_cover", current_stage, total_stages, "Selecting Cover Image")
            print_info("Step 1.8: Selecting cover image with vision AI...")
            try:
                metadata = select_cover_image(output_dir, metadata, config)
                results["cover_selection"] = "done"
            except Exception as e:
                print_warning(f"Cover selection error (continuing): {e}")
                results["cover_selection"] = "error"

        # Step 2: Translation (optional, skip if duplicate found)
        ko_md_path = None
        if skip_translation:
            if "translation" not in results:
                results["translation"] = "skipped_duplicate"
        elif pipeline.get("translate_to_korean", False):
            if md_path and os.path.exists(md_path):
                current_stage += 1
                write_processing_status(pdf_name, "translating", current_stage, total_stages, "Translating to Korean")
                print_info(f"Step 2: Translating to Korean...")

                _trans_stage = current_stage
                _trans_total = total_stages
                def _translation_progress(sec_idx, sec_total, pct):
                    write_processing_status(
                        pdf_name, "translating", _trans_stage, _trans_total,
                        f"Translating to Korean ({sec_idx}/{sec_total}, {pct:.0f}%)",
                        sub_progress=pct / 100.0
                    )

                try:
                    ko_md_path = translate_md_to_korean_openai(
                        md_path, output_dir, config, prompt,
                        progress_callback=_translation_progress
                    )
                    if ko_md_path:
                        print_success(f"Translation complete: {ko_md_path}")
                        results["translation"] = "success"
                    else:
                        print_warning(f"Translation failed (English files remain available)")
                        results["translation"] = "failed"
                except Exception as e:
                    print_error(f"Translation error: {e}")
                    results["translation"] = "failed"
            else:
                print_warning(f"Translation skipped: no markdown available")
                results["translation"] = "skipped"
        else:
            results["translation"] = "skipped"

        # Step 3: Move processed PDF to output directory
        print_info(f"Moving source PDF to output directory...")
        dest_pdf = os.path.join(output_dir, pdf_name)
        try:
            import shutil
            shutil.move(pdf_path, dest_pdf)
            print_success(f"Moved: {pdf_name} → {output_dir}/")
        except Exception as e:
            print_warning(f"Failed to move PDF: {e}")

        # If this run was identified as duplicate, remove intermediate output folder
        # to prevent accumulating untranslated duplicate entries in PaperFlow list.
        if duplicate_found:
            try:
                import shutil as _shutil
                _shutil.rmtree(output_dir, ignore_errors=True)
                print_info(f"Duplicate intermediate output removed: {output_dir}")
            except Exception as e:
                print_warning(f"Failed to cleanup duplicate output dir: {e}")

        # Print processing summary
        print()
        print_header("Processing Summary")
        for step, status in results.items():
            if status == "success":
                print_success(f"{step.capitalize()}: Success")
            elif status == "failed":
                print_error(f"{step.capitalize()}: Failed")
            elif isinstance(status, str) and status.startswith("skipped"):
                print_warning(f"{step.capitalize()}: Skipped")

        # Return True if at least one step succeeded
        success_count = sum(1 for s in results.values() if s == "success")
        if success_count > 0:
            write_processing_status(pdf_name, "complete", total_stages, total_stages, "Complete")
        else:
            write_processing_status(pdf_name, "error", current_stage, total_stages, "Error", error="No steps succeeded")
        return success_count > 0

    except Exception as e:
        print_error(f"Processing error: {e}")
        import traceback
        print_error(traceback.format_exc())
        write_processing_status(pdf_name, "error", 0, 0, "Error", error=str(e))
        return False


def process_single_pdf(pdf_path, config, prompt):
    """Paper entry point: compute outputs/<base_name> and process in paper mode.

    Thin wrapper preserved for backward compatibility — behavior is identical
    to the pre-refactor process_single_pdf.
    """
    pdf_name = os.path.basename(pdf_path)
    base_name = pdf_name.replace('.pdf', '').strip()
    output_dir = os.path.join("outputs", base_name)
    return process_pdf_to_output_dir(pdf_path, output_dir, base_name, config, prompt, mode="paper")


def _check_translation_api_health(config):
    """Preflight check for translation API/model when Korean translation is enabled."""
    pipeline = config.get("processing_pipeline", {})
    if not pipeline.get("translate_to_korean", False):
        return True

    api_base = os.getenv("OPENAI_BASE_URL", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("TRANSLATION_MODEL", "gemini-claude-sonnet-4-5").strip()

    if not api_base or not api_key:
        print_error("Translation precheck failed: OPENAI_BASE_URL / OPENAI_API_KEY missing")
        return False

    print_info(f"Translation precheck: model={model}, base={api_base}")

    # Quick live probe (best-effort). Default strict to prevent surprise EN-only output.
    strict = os.getenv("STRICT_TRANSLATION_HEALTHCHECK", "1") == "1"
    try:
        from openai import OpenAI
        client = OpenAI(base_url=api_base, api_key=api_key)
        client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "healthcheck"},
                {"role": "user", "content": "ok"}
            ],
            max_tokens=1,
            timeout=15,
            temperature=0,
        )
        print_success("Translation API/model healthcheck passed")
        return True
    except Exception as e:
        if strict:
            print_error(f"Translation API/model healthcheck failed: {e}")
            return False
        print_warning(f"Translation API/model healthcheck warning (non-strict): {e}")
        return True


def check_services(config):
    """Check if external services are reachable"""
    print_info("Checking dependencies...")

    engine = os.environ.get("PDF_CONVERTER", "marker").lower()

    if engine == "mineru":
        if not MINERU_AVAILABLE:
            print_error("MinerU library not installed!")
            print_info("Install it with: pip install 'mineru[all]'")
            return False
        backend = config.get("converter", {}).get("mineru", {}).get("backend", "pipeline")
        print_success(f"MinerU library is installed (backend: {backend})")
    else:
        if not MARKER_AVAILABLE:
            print_error("marker-pdf library not installed!")
            print_info("Install it with: pip install marker-pdf")
            return False
        print_success("marker-pdf library is installed")

    if not _check_translation_api_health(config):
        return False

    return True

def main():
    """Main function"""
    # Ensure .env values take precedence over inherited shell env
    # (prevents accidental OPENAI_API_KEY mismatch from parent process).
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass

    # Setup logging to file
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"paperflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Redirect stdout to both console and file
    import sys
    class TeeOutput:
        def __init__(self, *files):
            self.files = files
        def write(self, data):
            for f in self.files:
                f.write(data)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()

    log_handle = open(log_file, 'w', encoding='utf-8')
    original_stdout = sys.stdout
    sys.stdout = TeeOutput(original_stdout, log_handle)

    print_header("PaperFlow - PDF to Markdown/HTML Converter")
    print_info(f"Log file: {log_file}")

    # Load configuration
    config = load_config()
    prompt = load_prompt()

    # Check services
    if not check_services(config):
        print_error("\nService check failed. Please fix the issues above and try again.")
        log_handle.close()
        sys.stdout = original_stdout
        return 1

    print()

    # Check for PDF files in newones directory
    newones_dir = Path("newones")
    if not newones_dir.exists():
        newones_dir.mkdir()
        print_warning(f"Created 'newones' directory. Please add PDF files to process.")
        return

    pdf_files = list(newones_dir.glob("*.pdf"))

    if not pdf_files:
        print_warning("No PDF files found in 'newones' directory")
        return

    target_pdf = os.getenv("PAPERFLOW_TARGET_PDF", "").strip()
    if target_pdf:
        target_path = Path(target_pdf)
        if not target_path.is_absolute():
            target_path = (newones_dir / target_path.name).resolve()
        if not target_path.exists() or target_path.suffix.lower() != ".pdf":
            print_error(f"Target PDF not found/invalid: {target_pdf}")
            return 1
        process_list = [target_path]
        print_info(f"Target mode: processing only {target_path.name}")
    else:
        # Default behavior: process first item only (watch mode iterates one-by-one)
        process_list = [sorted(pdf_files, key=lambda p: p.name)[0]]
        print_info(f"Found {len(pdf_files)} PDF file(s) in queue; processing first: {process_list[0].name}")

    success_count = 0
    fail_count = 0

    for pdf_path in process_list:
        if process_single_pdf(str(pdf_path), config, prompt):
            success_count += 1
        else:
            fail_count += 1

    # Summary
    print_header("Processing Complete")
    print_success(f"Successfully processed: {success_count}")
    if fail_count > 0:
        print_error(f"Failed: {fail_count}")

    print_info(f"\nResults are available in the 'outputs' directory")
    print_info(f"Log saved to: {log_file}")

    # Write idle status for viewer polling
    write_processing_status(None, "idle", 0, 0, "Idle")

    # Close log file
    log_handle.close()
    sys.stdout = original_stdout

if __name__ == "__main__":
    import sys as _sys
    rc = main()
    _sys.exit(0 if rc is None else rc)
