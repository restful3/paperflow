#!/usr/bin/env python3
"""
Fix author sections in markdown files and regenerate HTML.

This script:
1. Scans all *_ko.md files in outputs/ and archives/
2. Removes code blocks that contain <sup> tags (author affiliations)
3. Re-renders HTML with Quarto

Usage:
    python fix_author_tags.py [--dry-run]
"""

import re
import subprocess
import sys
from pathlib import Path


def fix_markdown_file(md_path: Path, dry_run: bool = False) -> bool:
    """
    Remove code blocks containing <sup> tags from markdown file.

    Returns:
        True if file was modified, False otherwise
    """
    try:
        content = md_path.read_text(encoding='utf-8')
        original_content = content

        # Pattern to match code blocks containing <sup> tags
        # This matches ``` followed by content with <sup>, then closing ```
        pattern = r'```\n([\s\S]*?<sup>[\s\S]*?)\n```'

        def replace_code_block(match):
            # Extract the content inside code block
            inner_content = match.group(1)
            # Return just the content without code block markers
            return inner_content

        # Replace all matching code blocks
        modified_content = re.sub(pattern, replace_code_block, content)

        # Check if content was changed
        if modified_content != original_content:
            if not dry_run:
                md_path.write_text(modified_content, encoding='utf-8')
                print(f"✓ Fixed: {md_path.name}")
            else:
                print(f"[DRY RUN] Would fix: {md_path.name}")
            return True
        else:
            return False

    except Exception as e:
        print(f"✗ Error processing {md_path.name}: {e}")
        return False


def render_html(md_path: Path, dry_run: bool = False) -> bool:
    """
    Render HTML from markdown file using Quarto.

    Returns:
        True if rendering succeeded, False otherwise
    """
    if dry_run:
        print(f"[DRY RUN] Would render: {md_path.name} -> HTML")
        return True

    try:
        # Run quarto render in the directory containing the markdown file
        output_dir = md_path.parent
        result = subprocess.run(
            ['quarto', 'render', md_path.name],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            print(f"  → HTML rendered successfully")
            return True
        else:
            print(f"  → HTML rendering failed: {result.stderr[:200]}")
            return False

    except subprocess.TimeoutExpired:
        print(f"  → HTML rendering timed out")
        return False
    except Exception as e:
        print(f"  → HTML rendering error: {e}")
        return False


def main():
    """Main entry point."""
    dry_run = '--dry-run' in sys.argv

    if dry_run:
        print("=" * 60)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 60)
        print()

    # Find all Korean markdown files in outputs/ and archives/
    base_dir = Path(__file__).parent
    outputs_dir = base_dir / 'outputs'
    archives_dir = base_dir / 'archives'

    ko_md_files = []
    if outputs_dir.exists():
        ko_md_files.extend(outputs_dir.glob('**/*_ko.md'))
    if archives_dir.exists():
        ko_md_files.extend(archives_dir.glob('**/*_ko.md'))

    if not ko_md_files:
        print("No Korean markdown files found in outputs/ or archives/")
        return

    print(f"Found {len(ko_md_files)} Korean markdown files\n")

    # Process each file
    fixed_count = 0
    rendered_count = 0

    for md_path in sorted(ko_md_files):
        # Fix markdown
        was_fixed = fix_markdown_file(md_path, dry_run)

        if was_fixed:
            fixed_count += 1
            # Re-render HTML
            if render_html(md_path, dry_run):
                rendered_count += 1
        else:
            print(f"- Skipped: {md_path.name} (no code blocks with <sup> tags)")

    # Summary
    print()
    print("=" * 60)
    print(f"Summary:")
    print(f"  Files scanned: {len(ko_md_files)}")
    print(f"  Files fixed: {fixed_count}")
    print(f"  HTML rendered: {rendered_count}")
    if dry_run:
        print()
        print("This was a dry run. Run without --dry-run to apply changes.")
    print("=" * 60)


if __name__ == '__main__':
    main()
