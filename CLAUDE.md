# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaperFlow is a Python-based terminal tool that converts PDF documents (especially academic papers) to Markdown, translates them to Korean, and renders them as HTML. It uses:
- **marker-pdf library**: Local Python library for PDF to Markdown conversion with OCR capabilities
- **Ollama**: Local LLM server for Korean translation
- **Quarto**: Renders translated Markdown to HTML format

**Key Feature**: Fully local processing - no external API calls, all processing happens on your machine.

## Running the Application

### Quick Start (Virtual Environment - Recommended)

```bash
# First time setup
./setup_venv.sh

# Place PDF files in newones directory
cp /path/to/your/file.pdf newones/

# Run batch processing
./run_batch_venv.sh

# Check results in outputs directory
ls outputs/
```

This is the simplest way to use PaperFlow. Just drop PDFs into `newones/` and run the script. Results appear in `outputs/` with colored terminal UI showing progress.

### Manual Execution

```bash
# Activate virtual environment
source .venv/bin/activate

# Run batch processing
python main_terminal.py

# Check results
ls outputs/
```

## Architecture

### Application Structure

**Single Terminal Application**: [main_terminal.py](main_terminal.py) - CLI with colored ANSI output
- Automatically processes all PDFs in `newones/` directory
- Saves results to `outputs/{pdf_name}/` directory structure
- Shows real-time progress with colored output (green ✓, red ✗, yellow ⚠, blue ℹ, progress bars)
- Dual logging: console + timestamped log files in `logs/` directory
- **Auto-cleanup**: Moves processed PDFs from `newones/` to their output directories

### Processing Pipeline

All processing runs in the main thread with colored output:

#### 1. PDF → Markdown (`convert_pdf_to_md()` at [main_terminal.py:175](main_terminal.py#L175))
- **Library-based**: Uses marker-pdf Python library directly (NOT API server)
- **GPU Auto-detection**: Checks available GPU memory
  - If GPU available with >4GB free: Uses CUDA with float16
  - If GPU has <4GB free or unavailable: Automatically switches to CPU with float32
- **Model Loading**: Creates model dictionary with `create_model_dict(device, dtype)`
- **Conversion**: Calls `marker_single(pdf_path, output_dir, model_dict, metadata=metadata)`
- **Image Extraction**: Handles both single Image objects and lists from `rendered.images` dict
  - Fixes filename generation to avoid duplication
  - Saves images as JPEG to output directory
- **Metadata**: Makes all metadata JSON-serializable with recursive `make_serializable()` function
- Outputs: markdown file, extracted images, metadata JSON

#### 2. Markdown Chunking ([main_terminal.py:385](main_terminal.py#L385))
- **Primary**: `split_markdown_by_structure()` - Uses markdown-it-py to parse structure and split at logical boundaries
- **Fallback**: `split_text_simple()` - Token-based splitting if structure parsing fails
- Preserves markdown formatting including headers, code blocks, math equations
- Configurable chunk size (default: 5, recommended: 3-5)

#### 3. Korean Translation (`translate_md_to_korean()` at [main_terminal.py:377](main_terminal.py#L377))
- Translates each chunk via Ollama API
- Shows progress bar with percentage completion
- Writes chunks incrementally to `*_ko.md` as they complete
- Retry logic with configurable timeout/retries/delay
- Prepends `header.yaml` content to translated file for Quarto

#### 4. HTML Rendering (`render_md_to_html()` at [main_terminal.py:567](main_terminal.py#L567))
- Uses Quarto CLI to render Korean markdown to HTML
- **Important**: Runs quarto in the output directory with just filename (not full path)
- Command: `quarto render {filename}_ko.md`
- Quarto configuration in `header.yaml` specifies theme, TOC, embed-resources

#### 5. PDF Cleanup ([main_terminal.py:615](main_terminal.py#L615))
- After successful processing, moves source PDF from `newones/` to output directory
- Uses `shutil.move()` to relocate file
- Leaves `newones/` empty for next batch

### Key Dependencies

- **marker-pdf library** - Python package for local PDF processing (includes PyTorch)
- **PyTorch** - For GPU/CPU acceleration of PDF conversion
- **Pillow (PIL)** - For image extraction and manipulation
- **Ollama** - Must be running at `http://localhost:11434`
- **Quarto CLI** - Must be installed system-wide for HTML rendering
- **markdown-it-py** - For structure-aware markdown parsing

### Configuration Files

- [config.json](config.json) - Ollama URL, model name, chunk size, timeout, retries, retry delay, temperature
- [prompt.md](prompt.md) - Translation prompt for Ollama (English→Korean translation rules)
- [header.yaml](header.yaml) - Quarto HTML formatting (theme: cosmo, TOC, embedded resources)
- [requirements.txt](requirements.txt) - Python dependencies (marker-pdf, torch, pillow, requests, markdown-it-py)

### Logging System

**TeeOutput Class** ([main_terminal.py:38](main_terminal.py#L38)):
- Dual output: console + log file
- Timestamped log files: `logs/pdf2md_YYYYMMDD_HHMMSS.log`
- Captures all stdout during processing
- ANSI color codes preserved in logs

**Colored Output Functions**:
- `print_success()` - Green ✓ for successful operations
- `print_error()` - Red ✗ for errors
- `print_warning()` - Yellow ⚠ for warnings
- `print_info()` - Blue ℹ for informational messages
- Progress bars with percentage: `[████████████████████░░░░░░░░░░] 66.7%`

### Translation Strategy

The translation prompt ([prompt.md](prompt.md)) enforces:
- Preserve all Markdown structure (headers, lists, tables, links, images)
- Maintain LaTeX math syntax compatibility
- Translate technical terms with English in parentheses for clarity
- Output only Korean translation (no explanations or original text)

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

### Batch Processing Workflow

The [run_batch_venv.sh](run_batch_venv.sh) script:
1. Activates `.venv` virtual environment
2. Checks for PDF files in `newones/` directory
3. Runs [main_terminal.py](main_terminal.py) to process all PDFs
4. Terminal UI shows colored progress indicators during processing
5. Logs saved to `logs/` directory with timestamp

### GPU Memory Management

**Automatic Detection** ([main_terminal.py:186](main_terminal.py#L186)):
```python
if torch.cuda.is_available():
    gpu_mem_free = torch.cuda.mem_get_info()[0] / (1024**3)
    if gpu_mem_free < 4.0:
        device = "cpu"
        dtype = torch.float32
    else:
        device = "cuda"
        dtype = torch.float16
```

This prevents CUDA OOM errors by automatically falling back to CPU when GPU memory is insufficient.

### Image Extraction Handling

**Critical Code** ([main_terminal.py:244](main_terminal.py#L244)):
- marker-pdf returns `rendered.images` as a dict where values can be:
  - Single `PIL.Image` object
  - List of `PIL.Image` objects
- Page index keys may be already formatted strings like `_page_1_Figure_0.jpeg`
- Must check `isinstance(page_images, list)` and wrap singles in list
- Check if key starts with `_page_` to avoid filename duplication

### JSON Serialization

**Recursive Converter** ([main_terminal.py:288](main_terminal.py#L288)):
```python
def make_serializable(obj):
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(item) for item in obj]
    elif hasattr(obj, '__dict__'):
        return str(obj)
    else:
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)
```

This handles PIL Image objects and other non-serializable types in metadata.

### Quarto Path Handling

**Important**: Quarto must be run from the directory containing the markdown file with just the filename, not full path:

```python
# Correct
cwd = output_dir
cmd = ["quarto", "render", f"{pdf_name}_ko.md"]

# Wrong (causes "No valid input files" error)
cmd = ["quarto", "render", f"{output_dir}/{pdf_name}_ko.md"]
```

### Chunk Size Recommendations

- **Recommended**: 3-5 paragraphs per chunk
- **Above 10**: Performance degradation and context loss
- **Temperature**: 0.2-0.4 range for consistent translations

### Model Recommendations

From testing, ranked by translation quality:
1. **qwen3-vl:30b-a3b-instruct** ⭐ - Best quality, fast, stable
2. **gpt-oss:20b** - Fast and stable, occasionally incomplete
3. **qwen3:30b** - Good quality but slower

## Troubleshooting

### Common Issues

1. **Ollama Connection Failed**
   - Check: `ollama serve` running
   - Check: Model downloaded with `ollama pull qwen3-vl:30b-a3b-instruct`
   - Check: `config.json` has correct URL

2. **GPU Memory Issues**
   - Application auto-switches to CPU if <4GB free
   - Check other GPU processes with `nvidia-smi`

3. **Quarto Not Found**
   - Install: `sudo apt install quarto` or from https://quarto.org/
   - Verify: `which quarto`

4. **Translation Failures**
   - Increase `timeout`, `retries` in config.json
   - Reduce `Chunk_size` to process smaller sections
   - Try smaller/faster model

5. **Image Extraction Errors**
   - Check log files in `logs/` directory
   - Verify PIL/Pillow installation: `pip show pillow`

### Log Analysis

```bash
# View latest log
tail -f logs/pdf2md_*.log

# Find errors
grep "✗" logs/pdf2md_*.log

# Find warnings
grep "⚠" logs/pdf2md_*.log
```

## Project Evolution Notes

**Removed Features** (as of current version):
- GUI mode (main.py) - removed in favor of terminal-only batch processing
- API-based marker-pdf - switched to library-based approach
- PDF output - switched to HTML output for better web compatibility
- uv-based dependency management - switched to standard venv

**Key Architectural Decisions**:
1. **Library over API**: marker-pdf used as Python library for better control and offline capability
2. **Auto GPU/CPU**: Prevents crashes from OOM errors
3. **Batch Processing**: Optimized for processing multiple papers efficiently
4. **HTML Output**: More accessible and easier to style than PDF
5. **Auto-cleanup**: Keeps newones/ folder clean by moving processed files

## File Structure

```
PaperFlow/
├── main_terminal.py       # Main application (terminal UI, batch processing)
├── run_batch_venv.sh      # Execution script (activates venv, runs app)
├── setup_venv.sh          # Setup script (creates venv, installs deps)
├── config.json            # Configuration (Ollama, model, chunk size, etc.)
├── header.yaml            # Quarto HTML format settings
├── prompt.md              # Translation prompt for Ollama
├── requirements.txt       # Python dependencies
├── README.md              # User-facing documentation
├── CLAUDE.md              # This file - developer guide
├── PROJECT_STRUCTURE.md   # Project cleanup documentation
├── newones/               # Input directory (place PDFs here)
├── outputs/               # Output directory (results per PDF)
└── logs/                  # Log files (timestamped per run)
```
