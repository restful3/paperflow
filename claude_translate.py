#!/usr/bin/env python3
"""
Claude-driven translation script
Translates the LLM survey paper from English to Korean
Uses chunking to handle large files
"""

import json
import sys
from pathlib import Path

def split_by_lines(content, chunk_size=50):
    """Split content into chunks by line count"""
    lines = content.split('\n')
    chunks = []

    for i in range(0, len(lines), chunk_size):
        chunk = '\n'.join(lines[i:i+chunk_size])
        chunks.append({
            'index': i // chunk_size,
            'start_line': i,
            'end_line': min(i + chunk_size, len(lines)),
            'content': chunk
        })

    return chunks

def main():
    # File paths
    input_file = Path("outputs/A Survey on Large Language Model based Autonomous Agents/A Survey on Large Language Model based Autonomous Agents .md")
    output_file = Path("outputs/A Survey on Large Language Model based Autonomous Agents/A Survey on Large Language Model based Autonomous Agents _ko.md")

    # Read English content
    with open(input_file, 'r', encoding='utf-8') as f:
        english_content = f.read()

    print(f"✓ Loaded English markdown: {len(english_content):,} chars, {len(english_content.splitlines())} lines")

    # Split into chunks for easier translation
    chunks = split_by_lines(english_content, chunk_size=50)
    print(f"✓ Split into {len(chunks)} chunks (50 lines each)")

    # Save chunks to JSON for Claude to translate
    chunks_file = Path("/tmp/llm_survey_chunks.json")
    with open(chunks_file, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"✓ Saved chunks to: {chunks_file}")
    print(f"\nChunk breakdown:")
    for i, chunk in enumerate(chunks[:5]):  # Show first 5
        preview = chunk['content'][:100].replace('\n', ' ')
        print(f"  Chunk {i}: Lines {chunk['start_line']}-{chunk['end_line']}: {preview}...")
    print(f"  ... ({len(chunks) - 5} more chunks)")

    # Instructions for Claude
    print(f"\n" + "="*60)
    print("READY FOR TRANSLATION")
    print("="*60)
    print(f"\nClaude will now translate each chunk.")
    print(f"Input: {chunks_file}")
    print(f"Output: {output_file}")
    print(f"\nTotal chunks to translate: {len(chunks)}")

if __name__ == "__main__":
    main()
