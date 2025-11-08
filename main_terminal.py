#!/usr/bin/env python3
import json
import os
import subprocess
import requests
import time
from pathlib import Path
from markdown_it import MarkdownIt
import base64
from datetime import datetime
import sys

# Marker-pdf imports
try:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    MARKER_AVAILABLE = True
except ImportError:
    MARKER_AVAILABLE = False

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

def load_config():
    """Load config.json or return defaults"""
    default_config = {
        "ollama_url": "http://localhost:11434",
        "Chunk_size": 5,
        "timeout": 200,
        "retries": 100,
        "retry_delay": 10,
        "temperature": 0.3,
        "model_name": "qwen3-vl:30b-a3b-instruct"
    }

    try:
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for key in default_config:
                    if key in loaded:
                        default_config[key] = loaded[key]
    except Exception as e:
        print_warning(f"Config load failed, using defaults: {e}")

    return default_config

def load_prompt():
    """Load prompt.md or return default"""
    default_prompt = """I am a professional technical translator who converts English Markdown documents into Korean.

**Translation Rules:**

- Accurately translate English sentences into clear and natural Korean.
- **Strictly maintain the original Markdown structure.**
- Do not change headers (`#`, `##`, `###`), bold/italics (`**`, `*`, `_`), lists (`-`, `*`), tables (`|`, `---`), or links/image URLs.
- Translate only internal text, captions, and descriptions.
- Structure the table format accurately so it can be rendered correctly.
-- **If the table syntax is incorrect, correct it during conversion.**
- For all mathematical equations enclosed in `$`, `$$`:
-- **Preserves mathematical content intact.**
-- **Converts LaTeX syntax to Typst-compatible mathematical syntax** while preserving the intent of the equation (e.g., `$ frac{a}{b}$` → `$ a / b $`, inline; `$$x^2$$` → `$ x^2 $`, single line with spaces; matrices and special functions should be converted to their Typst-equivalent syntax).
-- **Translates only the text surrounding equations.**
-- **If the LaTeX syntax is incorrect, correct it during conversion.**
- **Translates only the text content inside tables.** Preserves all markers and delimiters.
- **Special terms (e.g., API, motor, bearing) and proper nouns must be followed by the original English text in parentheses.**
- In cases of ambiguity, a natural and contextual translation is preferred over a literal translation.
- Leave blank lines for untranslatable parts. Never include the original English text or apologies/explanations.
- **Only the translated Korean text is output.** No explanations, commentaries, or original English text are included.
- **The original English text or other languages are never output.**
- If the input is already in Korean or another language, it is passed on as is without modification.

**Additional Guidelines for Mathematical Equations:**

- **LaTeX → Typst Conversion:**
- Replace LaTeX commands with their Typst equivalents (e.g., `frac{a}{b}` → `a / b` for inline commands, `frac(a, b)` for display commands, following Typst conventions).
-- Adjust delimiters ($...$, $$...$$ → $ ... $, or $$ ... $$).
- Preserve function names and variables.
- Map matrices, arrays, and special functions to Typst's built-in functions.
- When in doubt, use Typst's math mode syntax for readability and logical consistency.

Translate this English Markdown text into Korean, following the rules above."""

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

        # Save markdown
        md_path = os.path.join(output_dir, os.path.basename(pdf_path).replace('.pdf', '.md'))
        print_info(f"Saving markdown to: {md_path}")
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

def split_markdown_by_structure(content, max_tokens=800):
    """Split markdown by structure"""
    md = MarkdownIt()
    tokens = md.parse(content)

    chunks = []
    current_chunk = []
    current_token_count = 0
    heading_level = None

    for token in tokens:
        if token.type == 'heading_open':
            if current_chunk and current_token_count > max_tokens * 0.8:
                chunk_text = ' '.join(current_chunk)
                chunks.append(chunk_text)
                current_chunk = []
                current_token_count = 0

            try:
                heading_level = int(token.tag[1])
            except Exception:
                heading_level = 1
            continue

        if token.type == 'inline':
            text_content = token.content

            if heading_level is not None:
                heading_markup = '#' * heading_level
                line = f"{heading_markup} {text_content}"
                token_count = len(text_content.split()) + heading_level

                if current_token_count + token_count > max_tokens and current_chunk:
                    chunk_text = ' '.join(current_chunk)
                    chunks.append(chunk_text)
                    current_chunk = []
                    current_token_count = 0

                current_chunk.append(line)
                current_token_count += token_count
                heading_level = None
            else:
                token_count = len(text_content.split())

                if current_token_count + token_count > max_tokens and current_chunk:
                    chunk_text = ' '.join(current_chunk)
                    chunks.append(chunk_text)
                    current_chunk = []
                    current_token_count = 0

                current_chunk.append(text_content)
                current_token_count += token_count

        elif token.type in ['paragraph_open', 'bullet_list_open', 'ordered_list_open']:
            if current_chunk and current_token_count > max_tokens * 0.8:
                chunk_text = ' '.join(current_chunk)
                chunks.append(chunk_text)
                current_chunk = []
                current_token_count = 0

    if current_chunk:
        chunk_text = ' '.join(current_chunk)
        chunks.append(chunk_text)

    # Refine chunks
    refined_chunks = []
    for chunk in chunks:
        token_count = len(chunk.split())
        if token_count > max_tokens:
            paragraphs = chunk.split('\n\n')
            sub_chunk = []
            sub_token_count = 0

            for para in paragraphs:
                para_tokens = len(para.split())
                if sub_token_count + para_tokens > max_tokens and sub_chunk:
                    refined_chunks.append('\n\n'.join(sub_chunk))
                    sub_chunk = []
                    sub_token_count = 0

                sub_chunk.append(para)
                sub_token_count += para_tokens

            if sub_chunk:
                refined_chunks.append('\n\n'.join(sub_chunk))
        else:
            refined_chunks.append(chunk)

    return refined_chunks

def split_text_simple(text, max_tokens=800):
    """Simple text splitting (fallback)"""
    tokens = text.split()
    chunks = []
    current_chunk = []
    current_token_count = 0

    for token in tokens:
        if current_token_count + 1 > max_tokens:
            if current_chunk:
                chunks.append(' '.join(current_chunk))
                current_chunk = []
                current_token_count = 0

        current_chunk.append(token)
        current_token_count += 1

    if current_chunk:
        chunks.append(' '.join(current_chunk))

    return chunks

def translate_chunk(chunk, ollama_url, model_name, prompt, timeout, retries, retry_delay, temperature):
    """Translate single chunk"""
    for attempt in range(retries):
        try:
            response = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model_name,
                    "prompt": f"{prompt}\n\n{chunk}",
                    "stream": False,
                    "options": {"temperature": temperature}
                },
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                return result.get('response', '').strip()

        except requests.exceptions.Timeout:
            print_warning(f"Timeout (attempt {attempt + 1}/{retries}): {timeout}s exceeded")
            if attempt < retries - 1:
                print_info(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print_error("Max retries exceeded")
                return None
        except Exception as e:
            print_warning(f"Translation error (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                print_info(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print_error("Max retries exceeded")
                return None

    return None

def translate_md_to_korean(md_path, output_dir, config, prompt):
    """Translate MD to Korean"""
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # Split content
        try:
            chunks = split_markdown_by_structure(md_content, max_tokens=config["Chunk_size"])
            print_info(f"Structure-based splitting: {len(chunks)} chunks (size: {config['Chunk_size']} tokens)")
        except Exception as e:
            print_warning(f"Structure split failed, using simple split: {e}")
            chunks = split_text_simple(md_content, max_tokens=config["Chunk_size"])
            print_info(f"Simple splitting: {len(chunks)} chunks (size: {config['Chunk_size']} tokens)")

        # Create output file with header
        ko_md_path = md_path.replace('.md', '_ko.md')

        with open(ko_md_path, 'w', encoding='utf-8') as f:
            try:
                header_path = Path("header.yaml")
                if header_path.exists():
                    with open(header_path, 'r', encoding='utf-8') as hf:
                        header = hf.read()
                    f.write(header.rstrip() + '\n\n')
            except Exception as e:
                print_warning(f"header.yaml load failed: {e}")

        # Translate chunks
        for i, chunk in enumerate(chunks, 1):
            print_progress(i-1, len(chunks), f"Translating chunk {i}/{len(chunks)}")

            translated = None
            while not translated:
                translated = translate_chunk(
                    chunk,
                    config["ollama_url"],
                    config["model_name"],
                    prompt,
                    config["timeout"],
                    config["retries"],
                    config["retry_delay"],
                    config["temperature"]
                )
                if translated:
                    with open(ko_md_path, 'a', encoding='utf-8') as f:
                        f.write(translated + '\n\n')
                        f.flush()
                    print_progress(i, len(chunks), f"Chunk {i}/{len(chunks)} completed")
                else:
                    print_warning(f"Chunk {i}/{len(chunks)} failed. Retrying in {config['retry_delay']}s...")
                    time.sleep(config["retry_delay"])

        print()  # New line after progress

        # Unload Ollama model to free GPU memory for next PDF
        try:
            print_info("Unloading Ollama model to free GPU memory...")
            unload_response = requests.post(
                f"{config['ollama_url']}/api/generate",
                json={
                    "model": config["model_name"],
                    "keep_alive": 0  # Unload immediately
                },
                timeout=10
            )
            if unload_response.status_code == 200:
                print_success("Ollama model unloaded successfully")
            else:
                print_warning(f"Ollama unload returned status {unload_response.status_code}")
        except Exception as e:
            print_warning(f"Failed to unload Ollama model: {e}")

        return ko_md_path

    except Exception as e:
        print_error(f"MD translation error: {e}")

        # Try to unload model even on error
        try:
            requests.post(
                f"{config['ollama_url']}/api/generate",
                json={"model": config["model_name"], "keep_alive": 0},
                timeout=5
            )
        except:
            pass

        return None

def render_md_to_html(ko_md_path):
    """Render MD to HTML using Quarto"""
    try:
        print_info(f"Running Quarto to render HTML...")

        # Use absolute path for ko_md_path
        ko_md_path_abs = os.path.abspath(ko_md_path)
        output_dir = os.path.dirname(ko_md_path_abs)

        # Quarto needs just the filename when running in the directory
        md_filename = os.path.basename(ko_md_path_abs)
        cmd = ["quarto", "render", md_filename]

        print_info(f"Command: {' '.join(cmd)}")
        print_info(f"Working directory: {output_dir}")
        print_info(f"Target file: {md_filename}")

        result = subprocess.run(cmd, cwd=output_dir, capture_output=True, text=True)

        if result.returncode == 0:
            html_output = ko_md_path.replace('_ko.md', '_ko.html')
            if os.path.exists(html_output):
                print_success(f"HTML file created: {os.path.getsize(html_output) / 1024:.2f} KB")
            return html_output
        else:
            print_error(f"Quarto rendering failed (exit code: {result.returncode})")
            print_error(f"STDERR: {result.stderr}")
            if result.stdout:
                print_info(f"STDOUT: {result.stdout}")
            return None

    except FileNotFoundError:
        print_error(f"Quarto command not found. Is Quarto installed?")
        print_info(f"Install: https://quarto.org/")
        return None
    except Exception as e:
        print_error(f"PDF rendering error: {e}")
        import traceback
        print_error(traceback.format_exc())
        return None

def process_single_pdf(pdf_path, config, prompt):
    """Process single PDF file"""
    try:
        pdf_name = os.path.basename(pdf_path)
        base_name = pdf_name.replace('.pdf', '').strip()  # Remove trailing/leading whitespace

        print_header(f"Processing: {pdf_name}")
        print_info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Create output directory
        output_dir = os.path.join("outputs", base_name)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print_success(f"Created output directory: {output_dir}")
        else:
            print_info(f"Output directory exists: {output_dir}")

        # Step 1: PDF to MD
        print_info(f"Step 1/3: Converting PDF to Markdown...")
        md_path = convert_pdf_to_md(pdf_path, output_dir)

        if md_path:
            print_success(f"Markdown conversion complete: {md_path}")
        else:
            print_error(f"Markdown conversion failed")
            return False

        # Step 2: Translate to Korean
        print_info(f"Step 2/3: Translating to Korean...")
        ko_md_path = translate_md_to_korean(md_path, output_dir, config, prompt)

        if ko_md_path:
            print_success(f"Korean translation complete: {ko_md_path}")
        else:
            print_error(f"Korean translation failed")
            return False

        # Step 3: Render to HTML
        print_info(f"Step 3/3: Rendering to HTML...")
        html_output = render_md_to_html(ko_md_path)

        if html_output:
            print_success(f"HTML rendering complete: {html_output}")
        else:
            print_warning(f"HTML rendering failed (markdown is still available)")

        # Step 4: Move processed PDF to output directory
        print_info(f"Moving source PDF to output directory...")
        dest_pdf = os.path.join(output_dir, pdf_name)
        try:
            import shutil
            shutil.move(pdf_path, dest_pdf)
            print_success(f"Moved: {pdf_name} → {output_dir}/")
        except Exception as e:
            print_warning(f"Failed to move PDF: {e}")

        return True

    except Exception as e:
        print_error(f"Processing error: {e}")
        return False

def check_services(config):
    """Check if external services are reachable"""
    print_info("Checking dependencies...")

    # Check Marker-pdf library
    if not MARKER_AVAILABLE:
        print_error("marker-pdf library not installed!")
        print_info("Install it with: pip install -r requirements.txt")
        return False
    else:
        print_success("marker-pdf library is installed")

    # Check Ollama
    try:
        response = requests.get(f"{config['ollama_url']}/api/tags", timeout=5)
        if response.status_code == 200:
            print_success(f"Ollama service is reachable at {config['ollama_url']}")
            # Check if model exists
            data = response.json()
            models = [m['name'] for m in data.get('models', [])]
            if config['model_name'] in models:
                print_success(f"Model '{config['model_name']}' is available")
            else:
                print_warning(f"Model '{config['model_name']}' not found in Ollama")
                print_info(f"Available models: {', '.join(models[:5])}")
        else:
            print_warning(f"Ollama service returned status {response.status_code}")
    except requests.exceptions.Timeout:
        print_warning(f"Ollama service at {config['ollama_url']} is slow to respond")
    except requests.exceptions.ConnectionError:
        print_error(f"Cannot connect to Ollama at {config['ollama_url']}")
        print_error("Please check if Ollama service is running")
        print_info("Start Ollama with: ollama serve")
        return False
    except Exception as e:
        print_warning(f"Ollama check failed: {e}")

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

    print_header("PaperFlow - PDF to Korean Markdown Converter")
    print_info(f"Log file: {log_file}")

    # Load configuration
    config = load_config()
    prompt = load_prompt()

    print_info(f"Ollama URL: {config['ollama_url']}")
    print_info(f"Model: {config['model_name']}")
    print_info(f"Chunk size: {config['Chunk_size']}")
    print_info(f"Temperature: {config['temperature']}")
    print()

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

    # Close log file
    log_handle.close()
    sys.stdout = original_stdout

if __name__ == "__main__":
    main()
