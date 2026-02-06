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

**Deployment**: This project is deployed and tested using **Docker Compose**. All testing and operational commands should use Docker Compose.

## Quick Reference

**Common Commands** (Docker Compose):
```bash
# Start all services (batch processor + FastAPI viewer)
docker compose up -d

# View logs
docker compose logs -f

# Stop all services
docker compose down

# Restart services
docker compose restart

# Process PDFs (copy to newones/ directory)
cp your_paper.pdf newones/
# → Processing starts automatically (watch mode)

# Access viewer
# Open browser at http://localhost:8000

# Check GPU usage
docker compose exec batch nvidia-smi

# Execute commands in batch container
docker compose exec batch bash

# Execute commands in viewer container
docker compose exec viewer bash

# Rebuild after code changes
docker compose build
docker compose up -d
```

**Development Commands** (without Docker):
```bash
# Only use these for local development/debugging
source .venv/bin/activate
python main_terminal.py

# Monitor logs
tail -f logs/paperflow_*.log
```

## Running the Application

### Production Deployment (Docker Compose - Recommended)

**⚠️ IMPORTANT**: This project is designed to run with **Docker Compose**. All testing and production deployments should use Docker Compose commands.

**Initial Setup**:
```bash
# Build and start all services
docker compose up -d
```

**Normal Operation**:
```bash
# Add PDFs to process (watch mode runs automatically)
cp /path/to/your/file.pdf newones/
# → Batch processor automatically detects and processes new PDFs

# Access FastAPI viewer
# Open browser at http://localhost:8000

# View logs
docker compose logs -f

# View batch processor logs only
docker compose logs -f batch

# View viewer logs only
docker compose logs -f viewer

# Stop services
docker compose down

# Restart services
docker compose restart
```

**Rebuilding After Code Changes**:
```bash
docker compose build
docker compose up -d
```

### Development Mode (Local Python - For Debugging Only)

**Initial Setup**:
```bash
# First time setup (creates .venv and installs dependencies)
./setup_venv.sh
```

**Batch Processing**:
```bash
# Option 1: Watch Mode (Recommended)
./run_batch_watch.sh

# Option 2: Single Run
cp /path/to/your/file.pdf newones/
./run_batch.sh

# Option 3: Manual execution (for debugging)
source .venv/bin/activate
python main_terminal.py
```

**FastAPI Viewer**:
```bash
cd viewer
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Note**: Development mode is useful for debugging but **Docker Compose should be used for all testing and production deployments**.

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
  - Search by title, authors, abstract, categories
  - Sort by name, title, or size (ascending/descending)
- **Viewing Modes**:
  - HTML viewer: iframe display of rendered papers
  - PDF viewer: iframe display of source PDFs
  - Markdown viewer: Marked.js client-side rendering with client-side rendering
  - Split view: Side-by-side HTML + PDF comparison
- **Mobile Optimizations** (2026-02-06):
  - **Auto-Hide Top Bar**: Scroll-based automatic hide/show on mobile (< 768px)
    - Scroll down → Top bar hides smoothly (gains ~140px of screen space)
    - Scroll up → Top bar shows immediately for navigation
    - Tap-to-toggle for iframe views (HTML/PDF)
    - Always accessible: 3-second idle timer auto-shows bar
    - Desktop unchanged: Feature only active on mobile devices
  - Responsive layout optimizations for small screens
  - Touch-friendly button sizes (≥44px WCAG standard)
- **UI Features**:
  - Dark Mode: CSS injection for theme switching with localStorage persistence
  - Language Toggle: EN/KO switching for UI and paper titles
  - Font Size Control: 5 preset levels (90%-150%) with localStorage persistence
  - TOC Toggle: Show/hide table of contents in HTML view
- **No AI Agent**: AI features removed in PaperFlow v2.0
- Clean, responsive UI with Alpine.js reactive components
- RESTful API backend with Jinja2 templates

### Batch Processing Pipeline

The pipeline executes 4 stages for each PDF (see `process_single_pdf()` in [main_terminal.py](main_terminal.py)):

#### 1. PDF → Markdown (`convert_pdf_to_md()`)
- **GPU-only mode**: Requires CUDA GPU, checks memory before loading models
- Uses marker-pdf library with `PdfConverter` (device="cuda", dtype=torch.float16)
- Extracts text, images (JPEG), and metadata (JSON-serializable)
- **Critical VRAM cleanup**: After conversion, deletes models and calls `torch.cuda.empty_cache()` to free ~4-8GB VRAM

#### 2. Metadata Extraction (`extract_paper_metadata()`)
- **AI-powered extraction**: Uses OpenAI-compatible API to extract paper metadata
- Extracts: title, authors, abstract, publication info, categories
- **Smart folder renaming**: Renames output directory from PDF filename to sanitized paper title
  - Removes OS-forbidden characters: `/ \ : * ? " < > |`
  - Truncates to 80 chars at word boundary, appends `-2`, `-3` for duplicates
- Saves metadata as `paper_meta.json` in output directory
- **Optional**: Can be disabled via `config.json` (`extract_metadata: false`)

#### 3. Korean Translation (`translate_md_to_korean_openai()`)
- **AI-powered translation**: Uses OpenAI-compatible API (e.g., GPT-4, Gemini)
- **7-step pipeline**:
  1. Split YAML header from body
  2. Clean OCR artifacts (page numbers, hyphens, copyright lines)
  3. Protect special blocks (code, math equations) with placeholders
  4. Classify sections (translate body, skip References/Appendix)
  5. Section-by-section translation with context preservation
  6. Restore protected blocks
  7. Write Korean markdown with `header.yaml`
- **Quality assurance**:
  - Automatic verification (length ratio, heading/paragraph counts)
  - Retry logic with enhanced prompt if verification fails
  - Streaming API with progress bar (500 chars interval)
- **Optional**: Can be disabled via `config.json` (`translate_to_korean: false`)
- Output: `{filename}_ko.md`

#### 4. HTML Rendering (`render_md_to_html()`)
- **Important**: Runs `quarto render {filename}.md` from the output directory (not full path)
- Renders both English and Korean markdown to HTML
- Quarto config in `header.yaml`: theme, TOC, embedded resources
- **Automatic Fallback**: If YAML parsing fails, retries with simplified header
  - Detects "YAML parse exception" or "Error running Lua" in stderr
  - Creates temporary file with simple YAML header (no complex CSS)
  - Ensures HTML is always generated even if custom styling fails
- Output: `{filename}.html` (English), `{filename}_ko.html` (Korean)

#### 5. Cleanup
- Moves source PDF from `newones/` to output directory
- Leaves `newones/` empty for next batch (or watch mode detection)

### Configuration Files

Critical configuration files in project root:

- **[config.json](config.json)**: Pipeline configuration
  - `processing_pipeline`: Enable/disable each stage (convert_to_markdown, extract_metadata, translate_to_korean, render_to_html)
  - `metadata_extraction`: AI extraction settings (temperature, tokens, timeouts, smart_rename)
  - `translation`: Translation settings (retries, timeout, preserve_english_html, max_section_chars, verify_translation)
- **[header.yaml](header.yaml)**: Quarto HTML format
  - `toc: true` with `toc-location: left` and `toc-depth: 3`
  - `theme: cosmo`, `embed-resources: true` (self-contained HTML)
  - Custom CSS for layout and styling
- **[requirements.txt](requirements.txt)**: Python dependencies
- **[.env](.env)**: Environment variables
  - FastAPI viewer authentication: `LOGIN_ID`, `LOGIN_PASSWORD`, `JWT_SECRET_KEY`
  - OpenAI-compatible API: `OPENAI_BASE_URL`, `OPENAI_API_KEY`
  - Translation settings: `TRANSLATION_MODEL` (e.g., gpt-4o, gemini-2.5-pro), `TRANSLATION_MAX_TOKENS`, `TRANSLATION_TEMPERATURE`
- **prompt.md** (optional): Custom translation prompt (overrides default academic translation prompt)

### Runtime Dependencies

Must be available at runtime:
- **Quarto CLI**: System-wide installation for HTML rendering
- **CUDA GPU**: Required for marker-pdf (no CPU fallback)
- **OpenAI-compatible API**: Required for metadata extraction and translation
  - Can be OpenAI API, local proxy (e.g., LiteLLM), or any compatible endpoint
  - Configured via `OPENAI_BASE_URL` and `OPENAI_API_KEY` in `.env`

### Output Structure

For `example.pdf` placed in `newones/`, creates:
```
outputs/Sanitized Paper Title/  # Renamed from PDF filename (if extract_metadata=true)
  ├── example.pdf                # Original PDF (moved from newones/)
  ├── example.json               # Metadata from marker-pdf
  ├── paper_meta.json            # Paper metadata (title, authors, abstract) ⭐
  ├── example.md                 # English markdown
  ├── example.html               # English HTML ⭐
  ├── example_ko.md              # Korean markdown (if translate_to_korean=true)
  ├── example_ko.html            # Korean HTML (if translate_to_korean=true) ⭐
  └── *.jpeg                     # Extracted images
```

**Notes:**
- Folder name is the sanitized paper title (max 80 chars) if `extract_metadata: true`
- HTML files are self-contained with embedded images and CSS (configured via `embed-resources: true` in header.yaml)
- Korean files are only generated if `translate_to_korean: true` in `config.json`

## Development Notes

### Docker Compose Workflow (Production)

**⚠️ IMPORTANT**: Always use Docker Compose commands for testing and production.

**Services**:
- **batch**: Batch processor running in watch mode (automatically processes new PDFs)
- **viewer**: FastAPI viewer running on port 8000

**Common Operations**:
```bash
# Start all services
docker compose up -d

# View batch processor logs
docker compose logs -f batch

# View viewer logs
docker compose logs -f viewer

# Restart batch processor
docker compose restart batch

# Execute command in batch container
docker compose exec batch python main_terminal.py

# Access batch container shell
docker compose exec batch bash

# Rebuild after code changes
docker compose build
docker compose up -d
```

**Watch Mode**: The batch service runs in watch mode by default, continuously monitoring the `newones/` directory for new PDFs.

### Script Workflows (Development Only)

**Note**: These scripts are for local development only. **Use Docker Compose for all testing**.

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

**Note on Translation Memory:**
- Translation uses OpenAI-compatible API (no local GPU required)
- API calls are stateless and don't consume local VRAM
- Only marker-pdf conversion requires GPU memory management

**Debug Commands** (Docker Compose):
```bash
# Monitor GPU in real-time (from host)
watch -n 1 nvidia-smi

# Monitor GPU from batch container
docker compose exec batch nvidia-smi

# Check cleanup messages in logs
docker compose logs batch | grep "GPU memory"

# Or check log files directly
grep "GPU memory" logs/paperflow_*.log
```

**Debug Commands** (Development mode):
```bash
# Monitor GPU in real-time
watch -n 1 nvidia-smi

# Check cleanup messages in logs
grep "GPU memory" logs/paperflow_*.log
```

### Mobile UI Features (FastAPI Viewer)

**Auto-Hide Top Bar on Scroll** (Implemented 2026-02-06):

**Purpose**: Maximize content viewing area on mobile devices by automatically hiding the top bar during reading.

**Implementation Details**:
- **File**: [viewer/app/templates/viewer.html](viewer/app/templates/viewer.html)
- **Mobile-Only**: Feature only active on viewports < 768px (Tailwind `md:` breakpoint)
- **Hybrid Strategy**:
  - **Markdown views (MD-KO, MD-EN)**: Scroll-based auto-hide with direction detection
    - 50px scroll threshold to prevent false triggers
    - 50ms debounce for smooth performance
    - Accumulator pattern prevents jittery behavior
    - 3-second idle timer to auto-show bar after inactivity
  - **Iframe views (HTML, PDF, Split)**: Tap-to-toggle mechanism
    - Single tap on content toggles bar visibility
    - Manual toggle disables auto-hide for 3 seconds
- **CSS Animations**: GPU-accelerated `translateY(-100%)` for smooth 300ms transitions
- **State Management**: Alpine.js reactive state with 8 variables tracking scroll position, timers, and visibility
- **Space Gained**: ~140px on mobile (26% of iPhone SE screen height)

**Technical Patterns**:
```javascript
// State variables in viewerApp()
topBarVisible: true,           // Current visibility
lastScrollY: 0,                // Last scroll position
scrollDelta: 0,                // Accumulated scroll delta
SCROLL_THRESHOLD: 50,          // Min px to trigger hide/show
scrollTimer: null,             // Debounce timer
idleTimer: null,               // Auto-show timer after inactivity
isManuallyToggled: false,      // Disable auto-hide after manual toggle
manualToggleTimer: null,       // Timer to reset manual toggle flag

// Helper methods
isMobile()                     // Check if viewport < 768px
setupScrollListener(view)      // Attach scroll listener for markdown views
detachScrollListener()         // Remove scroll listener
handleMarkdownScroll(event)    // Scroll direction detection with debouncing
toggleTopBarManual()           // Manual toggle for iframe views
ensureTopBarVisible()          // Force show bar (for opening menus)
closeMobileMenu()              // Close hamburger menu when bar hides
```

**CSS Classes**:
- `.mobile-top-bar`: Sticky positioning with smooth transitions
- `.mobile-top-bar-hidden`: Transform and opacity for hide animation
- `.viewer-content-mobile`: Dynamic height adjustment when bar hidden
- `.bar-visible`: Content area height adjustment

**User Experience**:
- Natural behavior matching Safari mobile pattern
- Always accessible: Scroll up or wait 3 seconds to show bar
- Hamburger menu and font size buttons ensure bar is visible when opened
- Desktop experience completely unchanged

**Performance Optimizations**:
- 50ms debounce prevents excessive re-renders
- 50px threshold ignores micro-scrolling
- CSS transforms use GPU acceleration
- Event listeners properly cleaned up on view switch

### Implementation Gotchas

**1. Quarto Path Handling** ([main_terminal.py:1232-1300](main_terminal.py#L1232-L1300))
```python
# CORRECT: Run from output dir with filename only
subprocess.run(["quarto", "render", f"{filename}.md"], cwd=output_dir)
subprocess.run(["quarto", "render", f"{filename}_ko.md"], cwd=output_dir)

# WRONG: Full path causes "No valid input files" error
subprocess.run(["quarto", "render", f"{output_dir}/{filename}.md"])
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
- OpenAI-compatible API configuration (OPENAI_BASE_URL, OPENAI_API_KEY in `.env`)
  - Only checked if `extract_metadata` or `translate_to_korean` is enabled

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
2. **4-Stage Pipeline**: PDF → MD → Metadata → Translation → HTML (metadata and translation optional)
3. **Library over API**: marker-pdf used as Python library for better control and offline operation
4. **GPU-Only Mode**: Requires CUDA GPU (no CPU fallback) for PDF conversion performance
5. **Explicit VRAM Management**: GPU cleanup after PDF→MD conversion enables batch processing
6. **AI-Powered Features**: OpenAI-compatible API for metadata extraction and translation
7. **Smart Section Classification**: Automatic detection of References/Appendix sections to skip translation
8. **Quality Verification**: Automatic translation completeness checking with retry logic
9. **Auto-cleanup**: Moves processed PDFs from `newones/` to output dirs to prevent re-processing
10. **Watch Mode**: Continuous monitoring for automated workflows
11. **Self-contained HTML**: Embedded images and CSS for portability (both English and Korean)
12. **FastAPI + Alpine.js**: Modern web stack with JWT authentication (replaced Streamlit)

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
- ~~app.py~~ (Streamlit viewer - replaced with FastAPI viewer)
- ~~agent/~~ (AI agent directory - replaced with direct API integration)
- ~~.sessions/~~ (Streamlit session files)
- ~~run_app.sh~~ (Streamlit launcher)
- ~~*_translate.py scripts~~ (experimental translation helpers - replaced with integrated translation)
- ~~Mac support files~~ (*_mac.sh, main_terminal_mac.py)

**Note:** `prompt.md` is optional - if present, it overrides the default translation prompt
