#!/usr/bin/env python3
"""Move Paperflow sidecar txt files from newones/ to newones/.meta/.

- Targets: *.url.txt, *.sha256.txt
- Keeps compatibility by only moving files; runtime code has legacy fallback.
- Supports dry-run mode.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=".", help="paperflow base dir (default: current dir)")
    ap.add_argument("--dry-run", action="store_true", help="show planned moves only")
    args = ap.parse_args()

    base = Path(args.base).resolve()
    newones = base / "newones"
    meta = newones / ".meta"

    if not newones.exists():
        print(f"newones not found: {newones}")
        return 1

    patterns = ["*.url.txt", "*.sha256.txt"]
    files: list[Path] = []
    for pat in patterns:
        files.extend(sorted(newones.glob(pat)))

    if not files:
        print("No legacy sidecar files found.")
        return 0

    meta.mkdir(parents=True, exist_ok=True)

    moved = 0
    skipped = 0

    for src in files:
        dst = meta / src.name
        if dst.exists():
            skipped += 1
            print(f"SKIP exists: {src.name}")
            continue
        if args.dry_run:
            print(f"MOVE {src} -> {dst}")
            moved += 1
            continue
        shutil.move(str(src), str(dst))
        moved += 1
        print(f"MOVED {src.name}")

    print(f"done moved={moved} skipped={skipped} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
