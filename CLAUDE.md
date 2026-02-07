# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaperFlow is an academic paper processing pipeline with a web viewer. Two components:

1. **Batch Processor** (`main_terminal.py`) - PDF → Markdown → Metadata → Korean Translation
2. **FastAPI Viewer** (`viewer/app/`) - Web interface with Alpine.js frontend, RAG chatbot, paper management

**Stack**: marker-pdf (CUDA GPU), FastAPI, Alpine.js, Tailwind CSS (CDN), marked.js + KaTeX (client-side), JWT auth (HTTPOnly cookies)

## Commands

```bash
# Production (Docker Compose) - always use for testing/deployment
docker compose up -d              # Start all services
docker compose build && docker compose up -d  # Rebuild after code changes
docker compose logs -f viewer     # View viewer logs
docker compose logs -f batch      # View batch processor logs
docker compose exec viewer bash   # Shell into viewer container

# Development (local, debugging only)
./setup_venv.sh                   # First time setup
source .venv/bin/activate && python main_terminal.py  # Batch processor
cd viewer && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload  # Viewer

# Process PDFs
cp your_paper.pdf newones/        # Watch mode auto-detects

# GPU debugging
docker compose exec batch nvidia-smi
```

**Viewer URL**: `http://localhost:8000` (Docker maps 8090→8000)

## Architecture

### Batch Processing Pipeline (`main_terminal.py`, ~2200 lines)

Each PDF goes through `process_single_pdf()`:

1. **PDF → Markdown** (`convert_pdf_to_md`) - marker-pdf with CUDA, critical VRAM cleanup after
2. **Heading Normalization** (`normalize_heading_levels`) - Fix OCR heading inconsistencies
3. **Metadata Extraction** (`extract_paper_metadata`) - OpenAI API extracts title/authors/abstract/categories, renames folder to sanitized title
4. **Web Search Enrichment** (`enrich_metadata_with_web_search`) - Brave Search for venue/DOI/year/URL
5. **Korean Translation** (`translate_md_to_korean_openai`) - 7-step pipeline: split YAML → clean OCR → protect math/code → classify sections (skip References) → translate with context → restore blocks → verify quality

**GPU Memory**: After PDF→MD, must `del model; gc.collect(); torch.cuda.empty_cache()` to free ~4-8GB VRAM. Each PDF runs in a fresh process via `run_batch_watch.sh`.

### FastAPI Viewer (`viewer/app/`)

```
viewer/app/
├── main.py          # App factory (create_app)
├── config.py        # Pydantic Settings from .env
├── auth.py          # JWT create/verify/cookie (HS256, 30-day expiry)
├── dependencies.py  # get_current_user_api(), get_current_user_page()
├── routers/
│   ├── pages.py     # HTML routes: /, /login, /papers, /viewer/{name}
│   └── api.py       # REST API: ~15 endpoints (papers, chat, upload, progress)
├── services/
│   ├── papers.py    # Paper CRUD, metadata loading, file serving
│   ├── rag.py       # RAG pipeline: chunk markdown → BM25 search → LLM streaming
│   ├── chat.py      # Chat history persistence (per-paper JSON files)
│   └── web_search.py # Brave Search API, venue/DOI pattern matching
├── models/
│   └── chat.py      # Pydantic models: ChatMessage, ChatHistory, ChatRequest, ChatChunk
└── templates/
    ├── base.html    # Alpine.js + Tailwind CDN, dark mode store, apiFetch() helper
    ├── login.html   # Auth form
    ├── papers.html  # Papers list: multi-tag chip search, card/list views, upload
    └── viewer.html  # Paper viewer: MD-KO/MD-EN/PDF/Split, TOC, reading progress
```

### Frontend Patterns (Alpine.js)

- **State management**: Alpine.js `x-data` component functions (`papersApp()`, `viewerApp()`)
- **Rendering**: Client-side only - marked.js parses MD, KaTeX renders math (protectMath → parse → restoreMath)
- **Dark mode**: `$store.darkMode` with localStorage persistence
- **Language toggle**: `$store.lang` (EN/KO) switches UI and paper titles
- **API calls**: `apiFetch()` in base.html wraps fetch with credentials + auto-redirect on 401
- **Toast notifications**: `showToast(msg, type)` global function
- **Search**: Multi-tag chip system with AND filtering + free text in `papers.html`

### Key API Endpoints (`api.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/papers?tab=unread\|archived` | GET | List papers with metadata |
| `/api/papers/{name}/chat` | POST | SSE streaming RAG chat |
| `/api/papers/{name}/enrich` | POST | Web search metadata enrichment |
| `/api/papers/{name}/progress` | POST | Save reading progress (0-100) |
| `/api/upload` | POST | Upload PDF (max 200MB) |
| `/api/papers/{name}/archive` | POST | Move to archives |
| `/api/papers/{name}` | DELETE | Permanent deletion |

## Configuration

### .env
```
LOGIN_ID, LOGIN_PASSWORD          # Viewer auth
JWT_SECRET_KEY                    # JWT signing
OPENAI_BASE_URL, OPENAI_API_KEY  # OpenAI-compatible API
TRANSLATION_MODEL                 # e.g., gemini-2.5-pro
TRANSLATION_MAX_TOKENS, TRANSLATION_TEMPERATURE
BRAVE_SEARCH_API_KEY              # Web search enrichment (optional)
```

### config.json
- `processing_pipeline`: Toggle each stage (convert_to_markdown, normalize_headings, extract_metadata, enrich_with_web_search, translate_to_korean)
- `metadata_extraction`: AI settings (temperature, max_tokens, timeout, smart_rename)
- `translation`: Retry/timeout settings, parallel translation (max_workers, min_chunks), verify_translation

## Output Structure
```
outputs/Sanitized Paper Title/
├── example.pdf          # Original (moved from newones/)
├── example.md           # English markdown
├── example_ko.md        # Korean markdown (if translate_to_korean=true)
├── paper_meta.json      # Metadata (title, authors, abstract, categories, venue, DOI)
├── example.json         # marker-pdf raw metadata
├── chat_history.json    # RAG chat history (created on first chat)
├── chat_chunks.json     # Cached markdown chunks for RAG
└── *.jpeg               # Extracted images
```

## Implementation Gotchas

1. **Image extraction** (`main_terminal.py`): `rendered.images` values can be single `PIL.Image` OR list - must check `isinstance(page_images, list)`
2. **JSON serialization** (`main_terminal.py`): Metadata contains PIL Images and other non-serializable objects - use `make_serializable()` recursive converter
3. **Folder naming**: Sanitized title max 80 chars, OS-forbidden chars removed, duplicates get `-2`, `-3` suffix
4. **Translation sections**: References/Appendix auto-detected and skipped; code blocks and math equations protected with placeholders during translation
5. **VRAM cleanup is critical**: Without explicit `del model; torch.cuda.empty_cache()` after PDF→MD, subsequent conversions will OOM
6. **Client-side math**: Must protect math delimiters (`$$`, `$`, `\[`, `\(`) from marked.js before rendering, then restore and render with KaTeX
7. **Card view layout**: Uses independent flex columns (not CSS Grid) so expanding a card only pushes down its own column, with row-first distribution (`cols[i % n].push(p)`)

## Docker Services

| Service | Container | Port | Base Image | GPU |
|---------|-----------|------|------------|-----|
| paperflow-converter | batch | - | nvidia/cuda:12.1.0 | Required |
| paperflow-viewer | viewer | 8090→8000 | python:3.12-slim | No |

Both share `outputs/`, `archives/`, `newones/`, `logs/` via volume mounts.
