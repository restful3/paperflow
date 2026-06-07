"""Backfill cover images for existing paper folders.

Reuses the pipeline's `select_cover_image()` (same guards: skip video / existing
cover / no candidates). Scans outputs/ and archives/ for paper_meta.json folders.

Usage:
    python3 scripts/backfill_covers.py                 # dry-run (no API calls, no writes)
    python3 scripts/backfill_covers.py --apply         # apply with vision API
    python3 scripts/backfill_covers.py --apply --workers 4
    python3 scripts/backfill_covers.py --apply --location outputs

Dry-run reports how many folders are ELIGIBLE (would call the vision API):
not video, no existing cover, and at least one size-passing candidate image.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env():
    env_path = os.path.join(REPO, ".env")
    if not os.path.exists(env_path):
        return
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()
sys.path.insert(0, REPO)
import main_terminal as mt  # noqa: E402

COVER_CONFIG = {
    "cover_selection": {
        "max_candidates": 6,
        "min_dimension": 200,
        "downscale_px": 768,
        "timeout_seconds": 90,
        "max_retries": 2,
    }
}
_COV = COVER_CONFIG["cover_selection"]


def _find_folders(locations):
    for base in locations:
        base_dir = os.path.join(REPO, base)
        if not os.path.isdir(base_dir):
            continue
        for name in sorted(os.listdir(base_dir)):
            folder = os.path.join(base_dir, name)
            if os.path.isfile(os.path.join(folder, "paper_meta.json")):
                yield base, name, folder


def _classify(folder):
    """Return (eligible: bool, reason: str) mirroring select_cover_image guards."""
    try:
        meta = json.load(open(os.path.join(folder, "paper_meta.json"), encoding="utf-8"))
    except Exception as e:
        return False, f"meta-error:{e}"
    if meta.get("doc_type") == "video":
        return False, "skip:video"
    if meta.get("cover"):
        return False, "skip:has-cover"
    candidates = mt._gather_cover_candidates(folder, _COV["min_dimension"], _COV["max_candidates"])
    if not candidates:
        return False, "skip:no-candidates"
    return True, f"eligible:{len(candidates)}-candidates"


def _apply_one(folder):
    meta_path = os.path.join(folder, "paper_meta.json")
    try:
        meta = json.load(open(meta_path, encoding="utf-8"))
    except Exception as e:
        return ("error", f"meta-load:{e}")
    before = meta.get("cover")
    meta = mt.select_cover_image(folder, meta, COVER_CONFIG)
    after = meta.get("cover")
    if after and after != before:
        return ("covered", after)
    if before:
        return ("skipped", "has-cover")
    return ("nocover", "no-suitable-or-skipped")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually call the vision API and write covers")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--location", choices=["outputs", "archives", "both"], default="both")
    args = ap.parse_args()

    locations = ["outputs", "archives"] if args.location == "both" else [args.location]
    folders = list(_find_folders(locations))
    print(f"Scanned {len(folders)} folders with paper_meta.json across {locations}")

    if not args.apply:
        elig = 0
        reasons = {}
        for base, name, folder in folders:
            ok, reason = _classify(folder)
            key = reason.split(":")[0] + ":" + reason.split(":")[1] if ":" in reason else reason
            tag = "eligible" if ok else reason.rsplit(":", 1)[0] if ":" in reason else reason
            reasons[tag] = reasons.get(tag, 0) + 1
            if ok:
                elig += 1
        print("\nDRY-RUN breakdown:")
        for k in sorted(reasons):
            print(f"  {k:18s}: {reasons[k]}")
        print(f"\n=> {elig} folders ELIGIBLE (would make {elig} vision API calls)")
        print("Run with --apply to perform backfill.")
        return

    # apply
    targets = [(b, n, f) for (b, n, f) in folders]
    print(f"Applying cover selection with {args.workers} workers...\n")
    counts = {"covered": 0, "nocover": 0, "skipped": 0, "error": 0}
    done = 0
    total = len(targets)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_apply_one, f): (b, n) for (b, n, f) in targets}
        for fut in as_completed(futs):
            base, name = futs[fut]
            try:
                status, detail = fut.result()
            except Exception as e:
                status, detail = "error", str(e)
            counts[status] = counts.get(status, 0) + 1
            done += 1
            if status == "covered":
                print(f"[{done}/{total}] COVERED  {base}/{name[:50]} -> {detail}")
            elif status == "error":
                print(f"[{done}/{total}] ERROR    {base}/{name[:50]} :: {detail}")
            elif status == "nocover" and detail == "no-suitable-or-skipped":
                print(f"[{done}/{total}] no-cover {base}/{name[:50]}")
    print("\n=== Backfill summary ===")
    for k in ("covered", "nocover", "skipped", "error"):
        print(f"  {k:8s}: {counts.get(k, 0)}")


if __name__ == "__main__":
    main()
