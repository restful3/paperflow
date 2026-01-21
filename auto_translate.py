#!/usr/bin/env python3
"""
Automatic translation using Ollama API
Translates the entire English markdown to Korean in chunks
"""

import json
import requests
import time
from pathlib import Path

def call_ollama(prompt, model="qwen3-vl:30b-a3b-instruct", url="http://localhost:11434"):
    """Call Ollama API for translation"""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }

    try:
        response = requests.post(
            f"{url}/api/generate",
            json=payload,
            timeout=400
        )
        response.raise_for_status()
        result = response.json()
        return result.get("response", "")
    except Exception as e:
        print(f"✗ Ollama API error: {e}")
        return None

def translate_chunk(chunk_text, prompt_template):
    """Translate a single chunk"""
    full_prompt = prompt_template + "\n\n" + chunk_text
    return call_ollama(full_prompt)

def main():
    # Load configuration
    with open("config.json", 'r') as f:
        config = json.load(f)

    with open("prompt.md", 'r') as f:
        prompt_template = f.read()

    with open("header.yaml", 'r') as f:
        yaml_header = f.read()

    # File paths
    input_file = Path("outputs/A Survey on Large Language Model based Autonomous Agents/A Survey on Large Language Model based Autonomous Agents .md")
    output_file = Path("outputs/A Survey on Large Language Model based Autonomous Agents/A Survey on Large Language Model based Autonomous Agents _ko.md")

    # Read English content
    with open(input_file, 'r', encoding='utf-8') as f:
        english_content = f.read()

    print(f"✓ Loaded: {len(english_content):,} chars, {len(english_content.splitlines())} lines")
    print(f"✓ Model: {config['model_name']}")
    print(f"✓ Chunk size: {config['Chunk_size']} tokens")

    # Split into chunks (by lines for simplicity)
    lines = english_content.split('\n')
    chunk_size = 30  # Process 30 lines at a time
    chunks = []

    for i in range(0, len(lines), chunk_size):
        chunk_lines = lines[i:i+chunk_size]
        chunks.append('\n'.join(chunk_lines))

    print(f"✓ Split into {len(chunks)} chunks ({chunk_size} lines each)")

    # Translate each chunk
    translated_chunks = []

    for i, chunk in enumerate(chunks):
        print(f"\n[{i+1}/{len(chunks)}] Translating lines {i*chunk_size}-{min((i+1)*chunk_size, len(lines))}...")

        translation = translate_chunk(chunk, prompt_template)

        if translation:
            translated_chunks.append(translation)
            print(f"✓ Translated {len(translation)} chars")
        else:
            print(f"✗ Translation failed, using original")
            translated_chunks.append(chunk)

        # Small delay to avoid overloading Ollama
        time.sleep(0.5)

    # Combine all translations
    full_translation = '\n'.join(translated_chunks)

    # Write to output file with YAML header
    output_content = yaml_header + "\n\n" + full_translation

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output_content)

    print(f"\n{'='*60}")
    print(f"✓ TRANSLATION COMPLETE")
    print(f"{'='*60}")
    print(f"Output: {output_file}")
    print(f"Size: {len(output_content):,} chars")
    print(f"Lines: {len(output_content.splitlines())}")

if __name__ == "__main__":
    main()
