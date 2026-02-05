# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaperFlow is a Python-based tool that converts PDF documents (especially academic papers) to Markdown and renders them as HTML with a web-based viewer. It consists of two main components:

1. **Batch Processor** ([main_terminal.py](main_terminal.py)) - Converts PDFs to HTML
2. **FastAPI Viewer** (viewer/app/) - Web interface for viewing and managing papers

**Technology Stack**:
- **marker-pdf library**: Local Python library for PDF to Markdown conversion with OCR capabilities
- **Quarto**: Renders Markdown to HTML format
- **FastAPI**: Web API and viewer interface with Alpine.js frontend

**Key Feature**: Fully local processing with GPU acceleration for PDF conversion.

## Quick Reference

**Common Commands**:
```bash
# Initial setup
./setup_venv.sh

# Process PDFs (watch mode - recommended)
./run_batch_watch.sh
cp your_paper.pdf newones/  # In another terminal

# Process PDFs (single run)
cp your_paper.pdf newones/
./run_batch.sh

# View results
cd viewer && uvicorn app.main:app --host 0.0.0.0 --port 8000

# Debug/development
source .venv/bin/activate
python main_terminal.py

# Monitor logs
tail -f logs/paperflow_*.log

# Check GPU usage
watch -n 1 nvidia-smi
```

## Running the Application

### Initial Setup

```bash
# First time setup (creates .venv and installs dependencies)
./setup_venv.sh
```

### Batch Processing

**Option 1: Watch Mode (Recommended for continuous processing)**
```bash
# Runs in background, automatically processes new PDFs
./run_batch_watch.sh

# Add PDFs from another terminal
cp /path/to/your/file.pdf newones/
# → Processing starts automatically
```

**Option 2: Single Run**
```bash
# Process all PDFs in newones/ once
cp /path/to/your/file.pdf newones/
./run_batch.sh
```

**Manual execution** (for debugging):
```bash
source .venv/bin/activate
python main_terminal.py
```

### Viewing Results

**FastAPI Viewer (Recommended)**:
```bash
cd viewer
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Opens browser at http://localhost:8000
# View HTML and PDF versions with paper management
```

**Direct file access**:
```bash
firefox outputs/your_paper/your_paper.html
```

## Architecture

### Two-Component System

#### 1. Batch Processor ([main_terminal.py](main_terminal.py))
Terminal-based PDF conversion pipeline:
- Processes all PDFs in `newones/` directory sequentially
- Saves results to `outputs/{pdf_name}/` directory structure
- Colored terminal UI (green ✓, red ✗, yellow ⚠, blue ℹ, progress bars)
- Dual logging: console + timestamped files in `logs/`
- **Auto-cleanup**: Moves processed PDFs from `newones/` to output directories
- **GPU memory management**: Explicit VRAM cleanup between PDFs for batch processing

#### 2. FastAPI Viewer (viewer/app/)
Alpine.js-based web interface:
- **JWT Authentication**: HTTPOnly cookies with login/logout
- **Paper Management**:
  - Lists papers from `outputs/` (unread) and `archives/` (read)
  - Archive, restore, and delete operations with confirmation
  - Paper metadata display (title, size, dates)
- **Viewing Modes**:
  - HTML viewer: iframe display of rendered papers
  - PDF viewer: iframe display of source PDFs
  - Markdown viewer: Marked.js client-side rendering
  - Split view: Side-by-side HTML + PDF comparison
- **Dark Mode**: CSS injection for theme switching
- **TOC Toggle**: Show/hide table of contents
- **No AI Agent**: AI features removed in PaperFlow v2.0
- Clean, responsive UI with Alpine.js reactive components
- RESTful API backend with Jinja2 templates

### Batch Processing Pipeline

The pipeline executes 2 stages for each PDF (see `process_single_pdf()` in [main_terminal.py](main_terminal.py)):

#### 1. PDF → Markdown (`convert_pdf_to_md()`)
- **GPU-only mode**: Requires CUDA GPU, checks memory before loading models
- Uses marker-pdf library with `PdfConverter` (device="cuda", dtype=torch.float16)
- Extracts text, images (JPEG), and metadata (JSON-serializable)
- **Critical VRAM cleanup**: After conversion, deletes models and calls `torch.cuda.empty_cache()` to free ~4-8GB VRAM

#### 2. Markdown → HTML (`render_md_to_html()`)
- **Important**: Runs `quarto render {filename}.md` from the output directory (not full path)
- Direct English markdown rendering (no translation)
- Quarto config in `header.yaml`: theme, TOC, embedded resources
- **Automatic Fallback**: If YAML parsing fails, retries with simplified header
  - Detects "YAML parse exception" or "Error running Lua" in stderr
  - Creates temporary file with simple YAML header (no complex CSS)
  - Ensures HTML is always generated even if custom styling fails

#### 3. Cleanup
- Moves source PDF from `newones/` to output directory
- Leaves `newones/` empty for next batch (or watch mode detection)

**Removed Stages** (PaperFlow v2.0):
- ~~Markdown chunking~~ (no longer needed without translation)
- ~~Korean translation~~ (removed entirely)

### Configuration Files

Critical configuration files in project root:

- **[config.json](config.json)**: Pipeline configuration (convert_to_markdown, render_to_html)
- **[header.yaml](header.yaml)**: Quarto HTML format
  - `toc: true` with `toc-location: left` and `toc-depth: 3`
  - `theme: cosmo`, `embed-resources: true` (self-contained HTML)
  - Custom CSS for layout and styling
- **[requirements.txt](requirements.txt)**: Python dependencies
- **[.env](.env)**: FastAPI viewer authentication (LOGIN_ID, LOGIN_PASSWORD, JWT_SECRET_KEY)

### Runtime Dependencies

Must be available at runtime:
- **Quarto CLI**: System-wide installation for HTML rendering
- **CUDA GPU**: Required for marker-pdf (no CPU fallback)

**Removed** (PaperFlow v2.0):
- ~~Ollama service~~ (no longer needed)

### Output Structure

For `example.pdf` placed in `newones/`, creates:
```
outputs/example/
  ├── example.pdf           # Original PDF (moved from newones/)
  ├── example.json          # Metadata from marker-pdf
  ├── example.md            # English markdown
  ├── example.html          # Rendered HTML ⭐
  └── *.jpeg                # Extracted images
```

**Changed** (PaperFlow v2.0):
- `example_ko.md` → removed (no translation)
- `example_ko.html` → `example.html` (English HTML rendering)

The HTML file is self-contained with embedded images and CSS (configured via `embed-resources: true` in header.yaml).

## Development Notes

### Script Workflows

**[run_batch.sh](run_batch.sh)**: One-time batch processing
- Activates `.venv`, checks for PDFs in `newones/`, runs `main_terminal.py` once

**[run_batch_watch.sh](run_batch_watch.sh)**: Continuous watch mode
- Monitors `newones/` directory using polling (checks every 5 seconds)
- Triggers batch processing when new PDFs appear
- Processes each PDF in a separate Python process to prevent CUDA context pollution
- Waits for processing to complete before watching again
- Ideal for automated workflows

**FastAPI Viewer**: Manual startup
```bash
cd viewer
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Or with hot reload: uvicorn app.main:app --reload
```

### PDF Processing Strategy

Main processing in [main_terminal.py](main_terminal.py):
- **Single PDF per run**: Processes only the first PDF in `newones/` directory to avoid CUDA context pollution
- **Watch mode handles multiple PDFs**: `run_batch_watch.sh` calls Python script repeatedly for each PDF
- **GPU Memory Management** prevents CUDA OOM:
  - After PDF→MD: Frees ~4-8GB VRAM (marker-pdf models)
- **Clean process per PDF**: Each PDF processed in fresh Python process prevents memory accumulation

### GPU Memory Management

**Why This Matters**: Processing multiple PDFs requires careful VRAM management to prevent CUDA OOM errors.

**Cleanup Pattern**:

**After PDF→MD** (in `convert_pdf_to_md()`):
```python
del model_dict, converter, rendered
gc.collect()
torch.cuda.empty_cache()
torch.cuda.synchronize()
```
Frees ~4-8GB VRAM from marker-pdf models

**Removed** (PaperFlow v2.0):
- ~~Ollama model unload~~ (translation removed)

**Debug Commands**:
```bash
# Monitor GPU in real-time
watch -n 1 nvidia-smi

# Check cleanup messages in logs
grep "GPU memory" logs/paperflow_*.log
```

### Implementation Gotchas

**1. Quarto Path Handling** ([main_terminal.py:634-641](main_terminal.py#L634-L641))
```python
# CORRECT: Run from output dir with filename only
subprocess.run(["quarto", "render", f"{filename}_ko.md"], cwd=output_dir)

# WRONG: Full path causes "No valid input files" error
subprocess.run(["quarto", "render", f"{output_dir}/{filename}_ko.md"])
```

**2. Image Extraction** ([main_terminal.py:254-289](main_terminal.py#L254-L289))
- `rendered.images` dict values can be single `PIL.Image` OR list of Images
- Must check `isinstance(page_images, list)` and wrap if needed
- Keys may already be formatted strings like `_page_1_Figure_0.jpeg`

**3. JSON Serialization** ([main_terminal.py:301-317](main_terminal.py#L301-L317))
- Metadata contains non-serializable objects (PIL Images, etc.)
- Use recursive `make_serializable()` function to convert to strings

**4. Logging** ([main_terminal.py:863-876](main_terminal.py#L863-L876))
- `TeeOutput` class redirects stdout to both console and log file
- Timestamped logs: `logs/paperflow_YYYYMMDD_HHMMSS.log`
- ANSI color codes preserved in files

**5. Streamlit Session Files** ([app.py:35-48](app.py#L35-L48))
- Session files stored in `.sessions/` directory (not project root)
- Format: `.sessions/session_{uuid}.json`
- Auto-login: Session files checked on app startup for seamless re-login
- Function `get_session_file()` manages session file paths

**6. Fullscreen Button & TOC Implementation** ([app.py:835-908](app.py#L835-L908))
- **Fullscreen Button**: Injected into HTML content only for single-view mode (`dual_view=False`)
  - Fixed position button (top-right, z-index: 9999) to stay visible during scrolling
  - Cross-browser support: Standard API + `-webkit-` (Safari) + `-ms-` (IE11) prefixes
  - IIFE (Immediately Invoked Function Expression) to avoid global namespace pollution
  - Dynamic button text/color changes based on fullscreen state
  - Inserted before `</body>` tag (or appended if no body tag exists)
- **TOC Visibility Control** ([app.py:785-817](app.py#L785-L817)):
  - CSS hides TOC in normal iframe mode (`display: none`)
  - CSS shows TOC only in fullscreen mode using `:fullscreen` pseudo-class
  - Cross-browser pseudo-class support: `:-webkit-full-screen`, `:-moz-full-screen`, `:-ms-fullscreen`, `:fullscreen`
  - Requires `toc: true` in `header.yaml` to generate TOC in HTML

**7. PDF Viewer with TOC Support** ([app.py:928-1053](app.py#L928-L1053))
- **Implementation** (Updated 2025-11-10):
  - Uses `streamlit-pdf-viewer` component for reliable PDF display
  - Single view mode: height=2000px for comfortable reading (increased from 800px)
  - Dual view mode: height=3000px for side-by-side comparison
  - Renders text for searchability (`render_text=True`)
- **Table of Contents (TOC) Feature** ([app.py:900-925](app.py#L900-L925)):
  - `extract_pdf_toc()` function extracts bookmarks from PDF using PyPDF2
  - "📑 목차 표시" checkbox appears only if PDF has bookmarks (in sidebar)
  - TOC displayed in sidebar with clickable navigation buttons
  - Supports nested bookmark levels with indentation
  - Uses `scroll_to_page` parameter to jump to selected page
  - Session state preserves selected page across reruns
- **Sidebar Controls** (Single view mode only):
  - "📄 PDF 정보" section shows file size
  - "📥 다운로드" button for PDF download (full width)
  - "📑 목차 표시" toggle for PDFs with bookmarks
  - All PDF controls consolidated in sidebar for clean main view
- **User Experience**:
  - Clean main content area (no controls at top)
  - Optional TOC navigation for PDFs with bookmarks
  - Download PDF to view in native PDF reader
  - In-app viewer with optimized height for comfortable reading
- **Technical Notes**:
  - PyPDF2 library handles bookmark extraction
  - Graceful fallback if PDF has no bookmarks
  - `show_controls_in_sidebar` parameter controls UI layout
  - Sidebar controls only in single view mode (dual view shows controls inline)

**8. iPad Toast Notification** ([app.py:908-961](app.py#L908-L961))
- Detects iPad using `navigator.userAgent` regex: `/iPad/.test(navigator.userAgent)`
- Shows toast message on fullscreen entry: "전체화면 종료: 상단 버튼을 클릭하세요"
- Toast implementation:
  - Fixed position at top center with high z-index (10000)
  - Slide-down animation on entry, reverse on exit
  - Auto-dismisses after 3 seconds
  - Uses CSS `@keyframes` for smooth animation
- Purpose: iPad browsers don't support ESC key for fullscreen exit, so users need clear guidance

**9. Markdown Editing with YAML Preservation** ([app.py:1097-1200](app.py#L1097-L1200))
- **Session State Management**:
  - `st.session_state.md_edit_mode`: Per-file dict storing edit mode status
  - `st.session_state.md_original_content`: Per-file dict storing original content for restore
- **YAML Splitting** (`split_yaml_and_body()` at [app.py:1056-1076](app.py#L1056-L1076)):
  - Detects YAML frontmatter between `---` delimiters
  - Separates header (YAML) from body (markdown content)
  - Returns tuple: (yaml_header, body_content)
- **Save Functionality** (`save_markdown()` at [app.py:1079-1094](app.py#L1079-L1094)):
  - Recombines YAML header with edited body
  - Writes to file as UTF-8
  - Updates `md_original_content` in session state after successful save
- **UI Implementation** (Updated 2025-11-10):
  - **Sidebar Toggle**: "📝 편집 모드" section in sidebar (consistent with PDF controls)
  - **Single toggle button**: "✏️ 편집" (in read mode) or "👁️ 읽기" (in edit mode)
  - Button type changes: primary (blue) for edit button, secondary (gray) for read button
  - `show_toggle_in_sidebar` parameter controls UI layout (default False for backward compatibility)
  - Edit mode shows `st.text_area` with height=600px for markdown editing
  - Info banner: "💡 **편집 모드**: YAML 헤더는 자동 보존됩니다. 본문만 수정하세요."
  - Save (💾) and Restore (🔄) buttons in edit mode
  - Restore requires double-click confirmation to prevent accidental data loss
  - **Improved UX**: Single button in sidebar, clean main content area

## Troubleshooting

### Startup Checks

Before processing, the system checks dependencies (see `check_services()` in [main_terminal.py](main_terminal.py)):
- marker-pdf library installed

**Removed** (PaperFlow v2.0):
- ~~Ollama service check~~ (translation removed)

### Common Issues

**GPU Memory Issues**:
- Application requires CUDA GPU (no CPU fallback)
- VRAM automatically released after PDF→MD conversion
- Check competing GPU processes: `nvidia-smi`

**Quarto Not Found**:
```bash
# Ubuntu/Debian
sudo apt install quarto

# Or download from https://quarto.org/
which quarto  # Verify installation
```

### Log Analysis

```bash
# View live log
tail -f logs/paperflow_*.log

# Find errors/warnings/GPU info
grep "✗" logs/paperflow_*.log
grep "⚠" logs/paperflow_*.log
grep "GPU memory" logs/paperflow_*.log
```

### Known Issues

**PDF Scroll Position Reset on Sidebar Toggle**:
- **Issue**: In split view mode, toggling the Streamlit sidebar causes the PDF viewer to reset to the first page
- **Cause**: Streamlit reruns the entire script when sidebar is toggled, causing `streamlit-pdf-viewer` component to re-render from scratch
- **Component Limitation**: `streamlit-pdf-viewer` does not support `key` parameter for state preservation and does not expose current scroll position
- **Potential Solutions**:
  1. Use `@st.fragment` decorator to isolate PDF viewer from sidebar reruns
  2. Upgrade to newer version of `streamlit-pdf-viewer` (currently `>=0.0.15`, v0.0.23+ has scroll-related fixes)
  3. Implement manual page tracking with `scroll_to_page` parameter (requires user input)
- **Workaround**: Avoid toggling sidebar while reading PDFs; use keyboard shortcuts or keep sidebar state consistent

## Key Architectural Decisions

1. **Two-Component Design**: Separate batch processor and web viewer for flexibility
2. **2-Stage Pipeline**: Simplified from 4-stage (PDF → MD → HTML, no translation)
3. **Library over API**: marker-pdf used as Python library for better control and offline operation
4. **GPU-Only Mode**: Requires CUDA GPU (no CPU fallback) for performance
5. **Explicit VRAM Management**: GPU cleanup after PDF→MD conversion enables batch processing
6. **Auto-cleanup**: Moves processed PDFs from `newones/` to output dirs to prevent re-processing
7. **Watch Mode**: Continuous monitoring for automated workflows
8. **Self-contained HTML**: Embedded images and CSS for portability
9. **FastAPI + Alpine.js**: Modern web stack with JWT authentication (replaced Streamlit)

## Project Structure

```
PaperFlow/
├── main_terminal.py       # Batch processor (PDF → HTML)
├── run_batch.sh           # One-time batch processing
├── run_batch_watch.sh     # Continuous watch mode
├── setup_venv.sh          # Setup script (creates .venv)
├── config.json            # Pipeline configuration
├── header.yaml            # Quarto HTML format
├── requirements.txt       # Python dependencies
├── .env                   # FastAPI viewer authentication
├── viewer/                # FastAPI web viewer
│   ├── app/               # FastAPI application
│   │   ├── main.py        # Application entry point
│   │   ├── routers/       # API routes
│   │   ├── templates/     # Jinja2 HTML templates
│   │   └── services/      # Business logic
│   └── requirements.txt   # Viewer dependencies
├── newones/               # Input: place PDFs here
├── outputs/               # Output: unread papers (to be read)
├── archives/              # Output: read papers (archived)
└── logs/                  # Processing logs (timestamped)
```

**Removed** (PaperFlow v2.0):
- ~~app.py~~ (Streamlit viewer)
- ~~prompt.md~~ (translation prompt)
- ~~agent/~~ (AI agent directory)
- ~~.sessions/~~ (Streamlit session files)
- ~~run_app.sh~~ (Streamlit launcher)
- ~~*_translate.py scripts~~ (experimental translation helpers)
- ~~Mac support files~~ (*_mac.sh, main_terminal_mac.py)
