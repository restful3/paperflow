#!/usr/bin/env python3
"""
Translate remaining untranslated English sections of GPT-4 Technical Report _ko.md
Lines 1012-2531 are untranslated English that need to be translated to Korean.
"""

import os
import re
import time
import sys
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
)
MODEL = os.getenv("TRANSLATION_MODEL", "gpt-5.2")
TEMPERATURE = float(os.getenv("TRANSLATION_TEMPERATURE", "0.3"))

FILE_PATH = "outputs/GPT-4 Technical Report/GPT-4 Technical Report_ko.md"

# Translation prompt
SYSTEM_PROMPT = """You are an expert academic paper translator. Translate the following English text from an academic AI paper (GPT-4 Technical Report) into Korean.

Rules:
1. Translate ALL text to Korean, including GPT-4 example responses and prompts
2. Preserve ALL markdown formatting exactly (headings, bold, italic, lists, links, images, HTML tags like <span>, <sup>, <br>)
3. Preserve ALL tables exactly as they are - translate table captions/descriptions but NOT the data inside table cells (numbers, exam names, percentages stay in English)
4. Preserve ALL math equations ($...$, $$...$$) exactly
5. Preserve ALL code blocks (```...```) exactly
6. Preserve ALL image references (![](...)) exactly
7. Preserve ALL anchor references and links exactly
8. Use formal Korean (합니다체)
9. Keep technical terms in both Korean and English on first use, e.g., "강화 학습(Reinforcement Learning)"
10. Do NOT add, remove, or reorder any content
11. Do NOT translate proper nouns like model names (GPT-4, GPT-3.5), dataset names (MMLU, HumanEval), organization names (OpenAI)
12. Translate section headings but keep the original formatting (###, ##, etc.)
13. Return ONLY the translated text, no explanations"""


def split_into_sections(lines):
    """Split lines into sections based on ## or ### headings."""
    sections = []
    current_section = []
    current_start = 0

    for i, line in enumerate(lines):
        # Check if this is a heading line (## or ###)
        stripped = line.strip()
        if stripped.startswith('## ') or stripped.startswith('### '):
            if current_section:
                sections.append({
                    'start': current_start,
                    'lines': current_section
                })
            current_section = [line]
            current_start = i
        else:
            current_section.append(line)

    if current_section:
        sections.append({
            'start': current_start,
            'lines': current_section
        })

    return sections


def merge_small_sections(sections, max_chars=3000, max_merge_chars=12000):
    """Merge small consecutive sections into larger chunks for efficiency."""
    merged = []
    current_chunk = []
    current_chars = 0

    for section in sections:
        section_text = '\n'.join(section['lines'])
        section_chars = len(section_text)

        if section_chars > max_merge_chars:
            # Large section - send alone
            if current_chunk:
                merged.append(current_chunk)
                current_chunk = []
                current_chars = 0
            merged.append([section])
        elif current_chars + section_chars > max_merge_chars:
            # Would exceed limit - flush current chunk
            if current_chunk:
                merged.append(current_chunk)
            current_chunk = [section]
            current_chars = section_chars
        else:
            current_chunk.append(section)
            current_chars += section_chars

    if current_chunk:
        merged.append(current_chunk)

    return merged


def is_table_only_section(text):
    """Check if a section is primarily a data table that shouldn't be translated."""
    lines = text.strip().split('\n')
    table_lines = sum(1 for l in lines if l.strip().startswith('|'))
    non_empty_lines = sum(1 for l in lines if l.strip())
    if non_empty_lines == 0:
        return False
    return table_lines / non_empty_lines > 0.8


def translate_chunk(text, chunk_num, total_chunks, retries=3):
    """Translate a chunk of text using the API."""
    print(f"\n--- Translating chunk {chunk_num}/{total_chunks} ({len(text)} chars) ---")

    for attempt in range(retries):
        try:
            # Estimate tokens needed (Korean is ~1.5-2x English in tokens)
            estimated_tokens = int(len(text) / 2.5 * 2.0)
            max_tokens = max(4096, min(estimated_tokens, 16384))

            response = client.chat.completions.create(
                model=MODEL,
                temperature=TEMPERATURE,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text}
                ]
            )

            translated = response.choices[0].message.content

            # Basic validation
            if len(translated) < len(text) * 0.3:
                print(f"  WARNING: Translation too short ({len(translated)} vs {len(text)}), retrying...")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue

            print(f"  OK: {len(text)} -> {len(translated)} chars")
            return translated

        except Exception as e:
            print(f"  ERROR (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
            else:
                print(f"  FAILED after {retries} attempts, keeping original")
                return text

    return text


def main():
    # Read the file
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    print(f"Total lines in file: {len(all_lines)}")

    # Lines are 1-indexed in the file, 0-indexed in the list
    # Untranslated section: lines 1012-2531 (1-indexed) = indices 1011-2530
    start_idx = 1011  # line 1012 (0-indexed)
    end_idx = 2531    # line 2532 (0-indexed, exclusive)

    # Verify boundaries
    print(f"Start line ({start_idx+1}): {all_lines[start_idx].strip()[:80]}")
    print(f"End line ({end_idx+1}): {all_lines[end_idx].strip()[:80]}")

    untranslated_lines = [line.rstrip('\n') for line in all_lines[start_idx:end_idx]]
    print(f"Untranslated lines: {len(untranslated_lines)}")

    # Split into sections
    sections = split_into_sections(untranslated_lines)
    print(f"Found {len(sections)} sections")

    # Merge small sections into chunks
    chunks = merge_small_sections(sections)
    print(f"Merged into {len(chunks)} translation chunks")

    # Translate each chunk
    translated_chunks = []
    for i, chunk_sections in enumerate(chunks):
        chunk_text = '\n'.join(
            '\n'.join(s['lines']) for s in chunk_sections
        )

        translated = translate_chunk(chunk_text, i + 1, len(chunks))
        translated_chunks.append(translated)

        # Small delay between API calls
        if i < len(chunks) - 1:
            time.sleep(1)

    # Reassemble the file
    translated_block = '\n'.join(translated_chunks)
    translated_lines = translated_block.split('\n')

    # Build the new file
    new_lines = []
    # Part 1: Already translated Korean (lines 1-1011)
    new_lines.extend(all_lines[:start_idx])
    # Part 2: Newly translated content
    for line in translated_lines:
        new_lines.append(line + '\n')
    # Part 3: Already translated Korean (lines 2532+)
    new_lines.extend(all_lines[end_idx:])

    # Write the updated file
    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"\nDone! Updated file with {len(new_lines)} lines (was {len(all_lines)})")
    print(f"Translated {len(untranslated_lines)} lines -> {len(translated_lines)} lines")


if __name__ == '__main__':
    main()
