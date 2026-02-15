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
    if pipeline.get("translate_to_korean", False):
        count += 1
    return max(count, 1)

def write_processing_status(filename, stage, stage_num, total_stages, stage_label, error=None, detail=None):
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
            "translate_to_korean": False,
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
    default_prompt = """You are a professional academic translator. Translate the given English Markdown text into Korean.

**Critical - Completeness:**
- Translate EVERY sentence completely. Do NOT skip, omit, summarize, or condense any content.
- The translation must cover 100% of the source text. Every paragraph, every sentence must appear in the output.
- If the input has N paragraphs, the output MUST also have N paragraphs.
- Do NOT add any content that is not in the original text.
- Do NOT add any headings (#, ##, ###, etc.) that do not exist in the source text.
- If the text begins mid-sentence (a continuation), translate it starting from exactly where it begins — do NOT prepend any title or heading.
- Never replace content with "..." or "(이하 생략)" or similar.
- Translate figure/table captions and footnotes fully.

**Core Rules:**
- Use formal Korean academic writing style (합니다체).
- **Strictly preserve all Markdown structure**: headers (#, ##, ###), bold/italics, lists, tables, links, image references.
- **Preserve all mathematical equations** ($...$, $$...$$, LaTeX) exactly as-is. Do NOT modify or convert any math notation.
- **Preserve all code blocks** (```...```) exactly as-is.
- **Preserve all citations** ([1], (Smith et al., 2023), <sup>1</sup>) unchanged.
- Translate table cell text only; preserve all table delimiters (|, ---).
- Fix incorrect table syntax during translation if needed.

**Terminology:**
- On first occurrence of a technical term, use format: 한국어 번역 (English term)
  - Example: 머신러닝 (machine learning), 신경망 (neural network)
- After first occurrence, use the Korean term consistently.
- Keep widely-used English terms as-is: API, GPU, CPU, CUDA, REST, HTTP, JSON, etc.

**Style:**
- Prefer natural, contextual Korean over literal translation.
- Output ONLY the translated Korean text. No explanations, comments, or original English.
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
  "publication_year": 2025
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
- Return ONLY the JSON object. No markdown formatting, no code blocks, no explanation.
- If you cannot determine a field, use null for strings or [] for arrays."""


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
                max_tokens=max_tokens,
                timeout=timeout
            )

            result_text = response.choices[0].message.content.strip()
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
                sidecar = os.path.join("newones", f"{original_filename}.url.txt")
                if os.path.isfile(sidecar):
                    with open(sidecar, "r", encoding="utf-8") as sf:
                        src_url = sf.read().strip()
                    if src_url.startswith(("http://", "https://")):
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

            return metadata

        except json.JSONDecodeError as e:
            print_warning(f"JSON parse error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_delay)
        except Exception as e:
            print_warning(f"Metadata extraction API error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                wait_time = retry_delay * (attempt + 1)
                time.sleep(wait_time)

    print_error("Metadata extraction failed after all retries")
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


def check_duplicate_batch(metadata, current_output_dir):
    """Check if paper with same title already exists in outputs/ or archives/.

    Returns list of matching papers: [{title, folder, location}]
    Returns empty list if no duplicates or on error (fail-open).
    """
    title = metadata.get("title", "")
    if not title or len(title) < 5:
        return []

    norm_title = _normalize_title(title)
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
# MD → [YAML분리] → [OCR정리] → [섹션분류] → [수식보호] → [번역] → [복원/결합]
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


def protect_special_blocks(text):
    """Replace code blocks and math with placeholders before translation.

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

    # Display math ($$...$$)
    text = re.sub(
        r'\$\$[\s\S]*?\$\$',
        lambda m: _replace(m, 'MATH_BLOCK'),
        text
    )

    # Inline math ($...$) - avoid matching dollar signs in text
    text = re.sub(
        r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)',
        lambda m: _replace(m, 'INLINE_MATH'),
        text
    )

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

    Pipeline: YAML分離 → OCR정리 → 수식보호 → 섹션분류 → 번역 → 복원/결합

    Returns:
        Path to Korean markdown file (*_ko.md) or None on failure
    """
    from pathlib import Path
    from dotenv import load_dotenv

    try:
        load_dotenv()

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
        print_success("OCR artifacts cleaned")

        # Save body before protection for spurious heading detection later
        body_before_protection = body

        # Step 3: Protect code blocks and math
        body, placeholders = protect_special_blocks(body)
        if placeholders:
            print_info(f"Protected {len(placeholders)} special block(s) (code/math)")

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

        print_success(f"Translation saved: {ko_md_path}")
        return ko_md_path

    except Exception as e:
        print_error(f"Translation error: {e}")
        import traceback
        print_error(traceback.format_exc())
        return None

def process_single_pdf(pdf_path, config, prompt):
    """Process single PDF file with configurable pipeline"""
    try:
        pdf_name = os.path.basename(pdf_path)
        base_name = pdf_name.replace('.pdf', '').strip()  # Remove trailing/leading whitespace

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
        current_stage = 0

        # Create output directory
        output_dir = os.path.join("outputs", base_name)
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
        duplicate_found = False

        # Step 1: PDF to MD (conditional)
        md_path = None
        if pipeline["convert_to_markdown"]:
            current_stage += 1
            write_processing_status(pdf_name, "converting", current_stage, total_stages, "PDF to Markdown")
            print_info(f"Step 1: Converting PDF to Markdown...")
            try:
                status_info = {"pdf_name": pdf_name, "stage_num": current_stage, "total_stages": total_stages}
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
                    if pipeline.get("enrich_with_web_search", True):
                        metadata = enrich_metadata_with_web_search(metadata, output_dir, config)

                    # Smart rename if enabled
                    meta_config = config.get("metadata_extraction", {})
                    if meta_config.get("smart_rename", True) and metadata.get("title"):
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
        if pipeline.get("check_duplicate", True) and metadata:
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
                        f"Translating to Korean ({sec_idx}/{sec_total}, {pct:.0f}%)"
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

    return True

def main():
    """Main function"""
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

    print_info(f"Found {len(pdf_files)} PDF file(s) to process")

    # Process only the first PDF to avoid CUDA context pollution
    # Watch mode script will call this program multiple times for multiple PDFs
    success_count = 0
    fail_count = 0

    # Process first PDF only
    if pdf_files:
        pdf_path = pdf_files[0]
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
    main()
