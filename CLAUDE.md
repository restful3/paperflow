# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaperFlow is a Python-based tool that converts PDF documents (especially academic papers) to Markdown, translates them to Korean, and renders them as HTML. It consists of two main components:

1. **Batch Processor** ([main_terminal.py](main_terminal.py)) - Converts PDFs to Korean HTML
2. **Web Viewer** ([app.py](app.py)) - Streamlit app for viewing converted papers

**Technology Stack**:
- **marker-pdf library**: Local Python library for PDF to Markdown conversion with OCR capabilities
- **Ollama**: Local LLM server for Korean translation
- **Quarto**: Renders translated Markdown to HTML format
- **Streamlit**: Web interface for viewing results

**Key Feature**: Fully local processing - no external API calls, all processing happens on your machine.

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

**Web Viewer (Recommended)**:
```bash
./run_app.sh
# Opens browser at http://localhost:8501
# View Korean (HTML) and English (PDF) versions side-by-side
```

**Direct file access**:
```bash
firefox outputs/your_paper/your_paper_ko.html
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

#### 2. Web Viewer ([app.py](app.py))
Streamlit-based viewing interface:
- **Tab Navigation**: Separate tabs for "읽을 논문" (unread) and "읽은 논문" (archived)
- Scans `outputs/` and `archives/` directories for papers
- Grid layout with paper cards showing available formats
- **Paper Management**: Three-button layout with confirmation dialogs
  - Unread papers: `[📖 보기] [✅ 완료] [🗑️ 삭제]`
  - Archived papers: `[📖 보기] [↩️ 복원] [🗑️ 삭제]`
  - Actions:
    - "✅ 완료": Move paper from `outputs/` to `archives/`
    - "↩️ 복원": Move paper from `archives/` to `outputs/`
    - "🗑️ 삭제": Permanently delete paper (shows folder size, requires confirmation)
  - Detail view sidebar: Separate buttons for archive/restore and delete
  - All destructive actions require confirmation dialogs
- Tabbed viewer: Korean (HTML) and English (PDF) side-by-side
- Uses `streamlit-pdf-viewer` component for PDF rendering
- Session state management for navigation (list view ↔ detail view)
- Responsive design with gradient UI styling
- Login authentication with session persistence

### Batch Processing Pipeline

The pipeline executes 4 stages for each PDF (see `process_single_pdf()` at [main_terminal.py:648](main_terminal.py#L648)):

#### 1. PDF → Markdown (`convert_pdf_to_md()` at [main_terminal.py:175](main_terminal.py#L175))
- **GPU-only mode**: Requires CUDA GPU, checks memory before loading models
- Uses marker-pdf library with `PdfConverter` (device="cuda", dtype=torch.float16)
- Extracts text, images (JPEG), and metadata (JSON-serializable)
- **Critical VRAM cleanup**: After conversion, deletes models and calls `torch.cuda.empty_cache()` to free ~4-8GB VRAM for next PDF

#### 2. Markdown Chunking (`split_markdown_by_structure()` at [main_terminal.py:367](main_terminal.py#L367))
- Primary: Structure-aware splitting using markdown-it-py (preserves headers, code blocks, math)
- Fallback: Simple token-based splitting if parsing fails
- Configurable chunk size (default: 5 tokens, recommended: 3-5)

#### 3. Korean Translation (`translate_md_to_korean()` at [main_terminal.py:517](main_terminal.py#L517))
- Translates chunks via Ollama API with retry logic
- Writes incrementally to `*_ko.md` with `header.yaml` prepended
- **Critical Ollama cleanup** ([main_terminal.py:572-588](main_terminal.py#L572-L588)): Sends `keep_alive: 0` to unload model and free ~22GB VRAM

#### 4. HTML Rendering (`render_md_to_html()` at [main_terminal.py:607](main_terminal.py#L607))
- **Important**: Runs `quarto render {filename}_ko.md` from the output directory (not full path)
- Quarto config in `header.yaml`: theme, TOC, embedded resources

#### 5. Cleanup
- Moves source PDF from `newones/` to output directory
- Leaves `newones/` empty for next batch (or watch mode detection)

### Configuration Files

Critical configuration files in project root:

- **[config.json](config.json)**: Ollama URL, model name, chunk size, timeout/retries, temperature
- **[prompt.md](prompt.md)**: Translation prompt enforcing markdown preservation and LaTeX→Typst math conversion
- **[header.yaml](header.yaml)**: Quarto HTML format (theme: cosmo, TOC, embed-resources: true)
- **[requirements.txt](requirements.txt)**: Python dependencies

### Runtime Dependencies

Must be available at runtime:
- **Ollama service**: Running at `http://localhost:11434` with model downloaded (e.g., `ollama pull qwen3-vl:30b-a3b-instruct`)
- **Quarto CLI**: System-wide installation for HTML rendering
- **CUDA GPU**: Required for marker-pdf (no CPU fallback)

### Output Structure

For `example.pdf` placed in `newones/`, creates:
```
outputs/example/
  ├── example.pdf           # Original PDF (moved from newones/)
  ├── example.json          # Metadata from marker-pdf
  ├── example.md            # English markdown
  ├── example_ko.md         # Korean translated markdown
  ├── example_ko.html       # Rendered Korean HTML ⭐
  └── *.jpeg                # Extracted images
```

The HTML file is self-contained with embedded images and CSS (configured via `embed-resources: true` in header.yaml).

## Development Notes

### Script Workflows

**[run_batch.sh](run_batch.sh)**: One-time batch processing
- Activates `.venv`, checks for PDFs in `newones/`, runs `main_terminal.py` once

**[run_batch_watch.sh](run_batch_watch.sh)**: Continuous watch mode
- Monitors `newones/` directory using `inotifywait`
- Triggers batch processing when new PDFs appear
- Waits for processing to complete before watching again
- Ideal for automated workflows

**[run_app.sh](run_app.sh)**: Streamlit viewer
- Activates `.venv`, kills existing Streamlit on port 8501, launches `app.py`

### Multiple PDF Processing

Main loop at [main_terminal.py:814](main_terminal.py#L814):
- Processes all PDFs in `newones/` sequentially in a `for` loop
- **Dual GPU Memory Management** prevents CUDA OOM:
  1. After PDF→MD: Frees ~4-8GB VRAM (marker-pdf models)
  2. After Translation: Frees ~22GB VRAM (Ollama model unload)
- Critical for processing multiple large PDFs without crashes

### GPU Memory Management (Critical for Batch Processing)

**Why This Matters**: Processing multiple PDFs requires careful VRAM management to prevent CUDA OOM errors.

**Two-Stage Cleanup Pattern**:

1. **After PDF→MD** ([main_terminal.py:306-340](main_terminal.py#L306-L340)):
   ```python
   del model_dict, converter, rendered
   gc.collect()
   torch.cuda.empty_cache()
   torch.cuda.synchronize()
   ```
   Frees ~4-8GB VRAM from marker-pdf models

2. **After Translation** ([main_terminal.py:572-588](main_terminal.py#L572-L588)):
   ```python
   requests.post(f"{ollama_url}/api/generate",
                 json={"model": model_name, "keep_alive": 0})
   ```
   Sends `keep_alive: 0` to unload Ollama model, freeing ~22GB VRAM

**Result**: Total ~26-30GB freed per PDF cycle, enabling sequential processing of multiple large PDFs.

**Debug Commands**:
```bash
# Monitor GPU in real-time
watch -n 1 nvidia-smi

# Check cleanup messages in logs
grep "GPU memory" logs/paperflow_*.log
```

### Implementation Gotchas

**1. Quarto Path Handling** ([main_terminal.py:616-624](main_terminal.py#L616-L624))
```python
# CORRECT: Run from output dir with filename only
subprocess.run(["quarto", "render", f"{filename}_ko.md"], cwd=output_dir)

# WRONG: Full path causes "No valid input files" error
subprocess.run(["quarto", "render", f"{output_dir}/{filename}_ko.md"])
```

**2. Image Extraction** ([main_terminal.py:239-244](main_terminal.py#L239-L244))
- `rendered.images` dict values can be single `PIL.Image` OR list of Images
- Must check `isinstance(page_images, list)` and wrap if needed
- Keys may already be formatted strings like `_page_1_Figure_0.jpeg`

**3. JSON Serialization** ([main_terminal.py:283](main_terminal.py#L283))
- Metadata contains non-serializable objects (PIL Images, etc.)
- Use recursive `make_serializable()` function to convert to strings

**4. Logging** ([main_terminal.py:758-771](main_terminal.py#L758-L771))
- `TeeOutput` class redirects stdout to both console and log file
- Timestamped logs: `logs/paperflow_YYYYMMDD_HHMMSS.log`
- ANSI color codes preserved in files

### Translation Configuration

**Chunk Size** (config.json):
- Recommended: 3-5 tokens per chunk
- Above 10: Performance degradation and context loss

**Temperature** (config.json):
- Recommended: 0.2-0.4 for consistent translations

**Model Recommendations** (tested):
1. `qwen3-vl:30b-a3b-instruct` ⭐ - Best quality, fast, stable
2. `gpt-oss:20b` - Fast and stable, occasionally incomplete
3. `qwen3:30b` - Good quality but slower

## Troubleshooting

### Startup Checks

Before processing, the system checks dependencies (see `check_services()` at [main_terminal.py:710](main_terminal.py#L710)):
- marker-pdf library installed
- Ollama service reachable at configured URL
- Translation model available in Ollama

### Common Issues

**Ollama Connection Failed**:
```bash
# Start Ollama service
ollama serve

# Download model (in another terminal)
ollama pull qwen3-vl:30b-a3b-instruct

# Verify model is available
ollama list
```

**GPU Memory Issues**:
- Application requires CUDA GPU (no CPU fallback)
- VRAM automatically released between PDFs (see GPU Memory Management section)
- Check competing GPU processes: `nvidia-smi`

**Quarto Not Found**:
```bash
# Ubuntu/Debian
sudo apt install quarto

# Or download from https://quarto.org/
which quarto  # Verify installation
```

**Translation Failures**:
- Increase `timeout` and `retries` in config.json
- Reduce `Chunk_size` for smaller sections
- Try smaller/faster model

### Log Analysis

```bash
# View live log
tail -f logs/paperflow_*.log

# Find errors/warnings/GPU info
grep "✗" logs/paperflow_*.log
grep "⚠" logs/paperflow_*.log
grep "GPU memory" logs/paperflow_*.log
```

## Key Architectural Decisions

1. **Two-Component Design**: Separate batch processor and web viewer for flexibility
2. **Library over API**: marker-pdf used as Python library for better control and offline operation
3. **GPU-Only Mode**: Requires CUDA GPU (no CPU fallback) for performance
4. **Explicit VRAM Management**: Two-stage memory cleanup enables batch processing of multiple large PDFs
5. **Auto-cleanup**: Moves processed PDFs from `newones/` to output dirs to prevent re-processing
6. **Watch Mode**: Continuous monitoring for automated workflows
7. **Self-contained HTML**: Embedded images and CSS for portability

## Project Structure

```
PaperFlow/
├── main_terminal.py       # Batch processor (PDF → Korean HTML)
├── app.py                 # Streamlit web viewer
├── run_batch.sh           # One-time batch processing
├── run_batch_watch.sh     # Continuous watch mode
├── run_app.sh             # Launch Streamlit viewer
├── setup_venv.sh          # Setup script (creates .venv)
├── config.json            # Ollama/model configuration
├── header.yaml            # Quarto HTML format
├── prompt.md              # Translation prompt
├── requirements.txt       # Python dependencies
├── newones/               # Input: place PDFs here
├── outputs/               # Output: unread papers (to be read)
├── archives/              # Output: read papers (archived)
└── logs/                  # Processing logs
```
