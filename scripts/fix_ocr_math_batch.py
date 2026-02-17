#!/usr/bin/env python3
"""Batch fix OCR math artifacts in all existing markdown files.

Applies clean_ocr_math() from main_terminal.py to all .md files in
outputs/ and archives/ directories. Skips backup files.

Usage:
    python scripts/fix_ocr_math_batch.py          # dry-run (show what would change)
    python scripts/fix_ocr_math_batch.py --apply   # actually apply fixes
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main_terminal import clean_ocr_math


def main():
    parser = argparse.ArgumentParser(description="Batch fix OCR math artifacts in markdown files")
    parser.add_argument("--apply", action="store_true", help="Apply fixes (default is dry-run)")
    args = parser.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs = [os.path.join(base, d) for d in ("outputs", "archives")]

    fixed = 0
    scanned = 0

    for search_dir in dirs:
        if not os.path.isdir(search_dir):
            continue
        for root, _, files in os.walk(search_dir):
            for f in files:
                if not f.endswith(".md") or "_backup_" in f:
                    continue
                scanned += 1
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                cleaned = clean_ocr_math(content)
                if cleaned != content:
                    rel = os.path.relpath(path, base)
                    if args.apply:
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(cleaned)
                        print(f"  Fixed: {rel}")
                    else:
                        # Show diff stats
                        diff_chars = sum(1 for a, b in zip(content, cleaned) if a != b)
                        len_diff = len(content) - len(cleaned)
                        print(f"  Would fix: {rel} ({diff_chars} chars changed, {len_diff:+d} length)")
                    fixed += 1

    mode = "Fixed" if args.apply else "Would fix"
    print(f"\nScanned {scanned} files. {mode} {fixed} file(s).")
    if not args.apply and fixed > 0:
        print("Run with --apply to apply fixes.")


if __name__ == "__main__":
    main()
