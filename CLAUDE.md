# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

PaperFlow v2.7 - Academic paper processing pipeline + web viewer.

| Component | File | Role |
|-----------|------|------|
| **Batch Processor** | `main_terminal.py` (~2540 lines) | PDF → MD → Metadata → Web Search → Translation |
| **Web Viewer** | `viewer/app/` | FastAPI + Alpine.js viewer, RAG chatbot, markdown editor |

**Stack**: marker-pdf/MinerU (CUDA GPU), FastAPI, Alpine.js, Tailwind CSS (CDN), marked.js + KaTeX (client-side), JWT auth (HTTPOnly cookies)

## Commands

```bash
# Production (Docker Compose) - always use for testing/deployment
docker compose build && docker compose up -d              # Full rebuild
docker compose build paperflow-viewer && docker compose up -d paperflow-viewer  # Viewer only
docker compose logs -f paperflow-viewer                   # Viewer logs
docker compose logs -f paperflow-converter                # Batch logs

# Process PDFs
cp your_paper.pdf newones/        # Watch mode auto-detects

# Development (local, debugging only)
cd viewer && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Viewer URL**: `http://localhost:8090` (Docker maps 8090→8000)

## Batch Pipeline (`main_terminal.py`)

`process_single_pdf()` orchestrates 6 stages:

| # | Stage | Function | Notes |
|---|-------|----------|-------|
| 1 | PDF → MD | `convert_pdf_to_md_dispatch()` | marker-pdf or MinerU (CUDA), **VRAM cleanup critical** |
| 2 | Heading Fix | `normalize_heading_levels()` | OCR heading level correction |
| 3 | Metadata | `extract_paper_metadata()` | AI: title/authors/abstract/categories, smart folder rename |
| 4 | Web Search | `enrich_metadata_with_web_search()` | Brave Search: venue/DOI/year/URL (optional) |
| 5 | Duplicate | `check_duplicate_batch()` | AI title comparison against existing papers |
| 6 | Translation | `translate_md_to_korean_openai()` | 7-step pipeline, parallel (max 3 workers), quality verification |

**Translation pipeline**: Split YAML → Clean OCR → Protect math/code → Classify sections (skip References/Appendix) → Translate with context (200 chars overlap) → Restore blocks → Verify quality

**GPU Memory**: After PDF→MD, must `del model; gc.collect(); torch.cuda.empty_cache()`. Each PDF runs in fresh process via `run_batch_watch.sh`.

## Viewer Architecture

```
viewer/app/
├── main.py          # create_app() factory
├── config.py        # Pydantic Settings (BASE_DIR, LOGIN_*, JWT_*, BRAVE_SEARCH_API_KEY)
├── auth.py          # JWT: create_token, verify_token, set/clear_auth_cookie (HS256, 30-day)
├── dependencies.py  # get_current_user_api() → 401, get_current_user_page() → None
├── routers/
│   ├── pages.py     # HTML: /, /login, /papers, /viewer/{name}
│   └── api.py       # REST API: ~25 endpoints
├── services/
│   ├── papers.py    # Paper CRUD, file paths, metadata, progress, ratings (~680 lines)
│   ├── rag.py       # Chunk markdown → BM25 search → LLM streaming (~386 lines)
│   ├── chat.py      # Per-paper chat history JSON persistence (~187 lines)
│   └── web_search.py# Brave Search: venue/DOI pattern matching (~223 lines)
├── models/
│   └── chat.py      # Pydantic: ChatMessage, ChatHistory, ChatRequest, ChatChunk
└── templates/
    ├── base.html    # Layout: Alpine.js, Tailwind CDN, $store.darkMode, $store.lang, apiFetch()
    ├── login.html   # Auth form
    ├── papers.html  # Paper list (~1627 lines): card/list views, multi-tag search, upload, ratings
    └── viewer.html  # Paper viewer (~2609 lines): MD/PDF/Split, editor, Easy mode, TOC, chat
```

### API Endpoints (api.py)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/login` | JWT login (cookie) |
| `POST` | `/api/logout` | Clear cookie |
| `GET` | `/api/papers?tab=unread\|archived` | List papers with metadata |
| `GET` | `/api/papers/{name}/info` | Single paper metadata |
| `GET` | `/api/papers/{name}/md-ko` | Korean markdown |
| `GET` | `/api/papers/{name}/md-en` | English markdown |
| `GET` | `/api/papers/{name}/md-ko-explained` | Korean explained markdown |
| `GET` | `/api/papers/{name}/md-en-explained` | English explained markdown |
| `PUT` | `/api/papers/{name}/markdown/{md_type}` | Save edited markdown (backup + RAG cache invalidation) |
| `GET` | `/api/papers/{name}/pdf` | PDF file |
| `GET` | `/api/papers/{name}/assets/{file}` | Images/assets (subdirectory support) |
| `POST` | `/api/papers/{name}/archive` | Move to archives |
| `POST` | `/api/papers/{name}/restore` | Restore from archives |
| `DELETE` | `/api/papers/{name}` | Permanent delete |
| `POST` | `/api/papers/{name}/chat` | SSE streaming RAG chat |
| `GET` | `/api/papers/{name}/chat/history` | Chat history |
| `DELETE` | `/api/papers/{name}/chat/history` | Clear chat |
| `POST` | `/api/papers/{name}/enrich` | Web search metadata enrichment |
| `GET` | `/api/progress` | All reading progress |
| `POST` | `/api/papers/{name}/progress` | Save reading progress (0-100) |
| `GET` | `/api/ratings` | All star ratings |
| `POST` | `/api/papers/{name}/rating` | Save star rating (1-5) |
| `POST` | `/api/upload` | Upload PDF (max 200MB) |
| `DELETE` | `/api/upload/{filename}` | Delete uploaded file |
| `GET` | `/api/processing/status` | Processing queue status |
| `DELETE` | `/api/processing/queue/{file}` | Remove from queue |
| `GET` | `/api/stats` | Paper counts, disk usage |
| `GET` | `/api/logs/latest` | Latest log content |

### Frontend Components (Alpine.js)

#### viewer.html - `viewerApp()`

**Key state variables:**
- `view` ('md'/'pdf'/'split'), `hasPdf`, `hasMdKo`, `hasMdEn`
- `hasMdKoExplained`, `hasMdEnExplained`, `explainedMode` - Easy toggle (explained version)
- `mdKoContent`, `mdEnContent`, `mdKoExplainedContent`, `mdEnExplainedContent` - rendered HTML
- `rawMdKo`, `rawMdEn` - raw markdown for editor
- `editMode`, `editType`, `editContent`, `editOriginalContent`, `editDirty`, `editPreviewHtml`, `editSaving`
- `tocVisible`, `tocItems`, `activeTocId` - table of contents
- `fontScale` (0.9-1.5), `contentWidth` ('720px'/'900px'/'1200px'/'100%')
- `rating`, `hoverStar` - star rating
- `topBarVisible`, `lastScrollY` - mobile top bar auto-hide

**Key methods:**
- `loadMdForCurrentLang()` - load MD based on language + explained mode
- `toggleExplained()` - switch original/explained (3-state: gray/black/amber)
- `enterEditMode()` / `exitEditMode()` / `saveMarkdown()` - inline editor (Ctrl+S save, Esc cancel)
- `extractTocItems()` / `setupTocObserver()` - TOC from h1-h3, IntersectionObserver scroll spy
- `saveReadingPosition()` / `restoreReadingPosition()` - localStorage scroll persistence
- `activeMdContent` getter - returns content based on language + explained mode

**Math rendering pipeline**: `protectMath()` → `marked.parse()` → `restoreMath()` with KaTeX

#### viewer.html - `chatPanel()`

Floating RAG chatbot per paper:
- `messages`, `userInput`, `isStreaming` - chat state
- `sendMessage()` - POST with SSE streaming
- `loadHistory()` / `clearHistory()` - persistence
- BM25 search + conditional web search + OpenAI streaming

#### papers.html - `papersApp()`

**Key state:**
- `tab` ('unread'/'archived'), `papers`, `viewMode` ('card'/'list')
- `searchText`, `searchTags` - multi-tag chip search (AND filtering)
- `sortBy` ('date'/'title'/'rating'), `sortOrder` ('asc'/'desc')
- `serverProgress`, `serverRatings` - server-synced data
- Upload: `panel`, `uploadQueue`, `processingFiles`, `logContent`

**Card view**: Independent flex columns (not CSS Grid) with row-first distribution (`cols[i % n].push(p)`)

### papers.py Key Functions

| Function | Purpose |
|----------|---------|
| `list_papers(tab)` | List papers with full metadata |
| `get_paper_info(name)` | Single paper info (formats, metadata) |
| `get_pdf_path/get_md_ko_path/get_md_en_path` | File path resolvers |
| `get_md_ko_explained_path/get_md_en_explained_path` | Explained version paths |
| `save_markdown(name, md_type, content)` | Save with timestamped backup + RAG cache invalidation |
| `archive_paper/restore_paper/delete_paper` | Paper lifecycle |
| `save_upload(filename, data)` | Save PDF to newones/ |
| `check_duplicate_paper(pdf_path)` | AI title comparison |
| `get_all_progress/save_progress` | Reading progress (JSON file) |
| `get_all_ratings/save_rating` | Star ratings (JSON file) |

## File Naming & Detection

| Suffix | Type | Variable |
|--------|------|----------|
| `*.pdf` | PDF | `has_pdf` |
| `*.md` (not `_ko.md`, not `_explained.md`) | English MD | `has_md_en` |
| `*_ko.md` (not `_ko_explained.md`) | Korean MD | `has_md_ko` |
| `*_ko_explained.md` | Korean Explained | `has_md_ko_explained` |
| `*_explained.md` (not `_ko_explained.md`) | English Explained | `has_md_en_explained` |
| `*_backup_*.md` | Edit backup | (excluded from display) |

**Detection order matters**: `_ko_explained.md` checked before `_ko.md`, `_explained.md` before `.md`

## Output Structure

```
outputs/Sanitized Paper Title/
├── example.pdf                 # Original (moved from newones/)
├── example.md                  # English markdown
├── example_ko.md               # Korean markdown
├── example_ko_explained.md     # Korean explained (optional)
├── example_explained.md        # English explained (optional)
├── example.json                # marker-pdf/MinerU raw metadata
├── paper_meta.json             # AI+web search metadata
├── chat_history.json           # RAG chat history (auto-created)
├── chat_chunks.json            # Cached MD chunks for RAG (auto-created)
├── *_backup_YYYYMMDD_HHMMSS.md # Edit backups (auto-created)
└── *.jpeg / images/*.jpg       # Extracted images
```

## Configuration

### .env
```
PDF_CONVERTER=marker             # "marker" or "mineru"
OPENAI_BASE_URL, OPENAI_API_KEY  # OpenAI-compatible API
TRANSLATION_MODEL                 # e.g., gemini-2.5-pro
CHATBOT_MODEL                     # e.g., gpt-4o (RAG chatbot)
TRANSLATION_MAX_TOKENS, TRANSLATION_TEMPERATURE
BRAVE_SEARCH_API_KEY              # Web search enrichment (optional)
LOGIN_ID, LOGIN_PASSWORD          # Viewer auth
JWT_SECRET_KEY                    # JWT signing
```

### config.json
- `processing_pipeline`: Toggle each stage (convert_to_markdown, normalize_headings, extract_metadata, enrich_with_web_search, check_duplicate, translate_to_korean)
- `converter.mineru`: MinerU-specific settings (backend, parse_method, lang)
- `metadata_extraction`: AI settings (temperature, max_tokens, timeout, smart_rename, max_folder_name_length)
- `translation`: Retry/timeout, parallel translation (max_workers, min_chunks), verify_translation

## Implementation Gotchas

1. **VRAM cleanup is critical**: Without `del model; torch.cuda.empty_cache()` after PDF→MD, subsequent conversions OOM
2. **Client-side math**: Must `protectMath()` before `marked.parse()`, then `restoreMath()` with KaTeX rendering
3. **File suffix ordering**: `_ko_explained.md` must be checked before `_ko.md` in detection loops
4. **save_markdown()**: Must exclude `_explained.md` and `_ko_explained.md` when finding target file
5. **Card view layout**: Independent flex columns (not CSS Grid) so expanding a card only pushes down its own column
6. **Image extraction**: `rendered.images` values can be single `PIL.Image` OR list - check `isinstance(page_images, list)`
7. **JSON serialization**: Metadata has PIL Images - use `make_serializable()` recursive converter
8. **Folder naming**: Sanitized title max 80 chars, OS-forbidden chars removed, duplicates get `-2`, `-3` suffix
9. **Edit backup**: `save_markdown()` creates `_backup_YYYYMMDD_HHMMSS.md` before overwrite, deletes `chat_chunks.json` for RAG cache invalidation
10. **Explained mode scroll**: Uses separate localStorage key (`pf-scroll-{name}-{view}-{lang}-easy`) to avoid position conflicts

## Docker Services

| Service | Container | Port | GPU | Image |
|---------|-----------|------|-----|-------|
| paperflow-converter | paperflow_converter | - | Required | nvidia/cuda:12.1.0 |
| paperflow-viewer | paperflow_viewer | 8090→8000 | No | python:3.12-slim |

Both share `outputs/`, `archives/`, `newones/`, `logs/` via volume mounts. Converter image is built with `PDF_CONVERTER` ARG for selective package install.
