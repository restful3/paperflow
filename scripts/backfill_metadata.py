"""Backfill paper_meta.json for folders that have none (or a failure marker).

Without paper_meta.json the viewer list renders a completely blank card — no
Korean title, no abstract, no categories, no thumbnail (`_paper_info()` sets every
metadata field to None). This sweeps for those folders and repairs them.

Two repair strategies, cheapest first:

1. **twin**   — an identically-named folder in the *other* location already has a
   valid paper_meta.json (the outputs/ copy is a stale partial of an archived
   document). Copy it verbatim; no API call, no guessing.
2. **extract** — no twin: re-run the pipeline's own `extract_paper_metadata()`
   on the folder's source markdown.

Never renames folders (`process_single_pdf`'s smart_rename is deliberately not
invoked — renaming would break viewer state keyed by folder name).

Usage:
    python3 scripts/backfill_metadata.py                 # dry-run (no API calls, no writes)
    python3 scripts/backfill_metadata.py --apply
    python3 scripts/backfill_metadata.py --apply --location outputs
    python3 scripts/backfill_metadata.py --apply --limit 10
"""
import argparse
import json
import os
import shutil
import sys

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

LOCATIONS = ("outputs", "archives")
SKIP_SUFFIXES = ("_ko_explained.md", "_explained.md", "_ko_audio.md", "_ko_audio_brief.md")


def _source_md(folder):
    """Pick the markdown to extract from: prefer the original, else the Korean."""
    mds = [
        f for f in sorted(os.listdir(folder))
        if f.endswith(".md") and not f.endswith(SKIP_SUFFIXES) and "_backup_" not in f
    ]
    if not mds:
        return None
    return next((f for f in mds if not f.endswith("_ko.md")), mds[0])


def _valid_meta(path):
    try:
        m = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    return m if isinstance(m, dict) and m.get("title") else None


def _find_broken(locations):
    """Yield (location, name, folder) for folders needing repair."""
    for base in locations:
        base_dir = os.path.join(REPO, base)
        if not os.path.isdir(base_dir):
            continue
        for name in sorted(os.listdir(base_dir)):
            folder = os.path.join(base_dir, name)
            if not os.path.isdir(folder) or name.startswith("."):
                continue
            meta = os.path.join(folder, "paper_meta.json")
            failed = os.path.join(folder, mt.METADATA_FAILURE_MARKER)
            if not os.path.isfile(meta) or os.path.isfile(failed):
                yield base, name, folder


def _find_twin(location, name):
    """A same-named folder in the other location holding usable metadata."""
    for other in LOCATIONS:
        if other == location:
            continue
        cand = os.path.join(REPO, other, name, "paper_meta.json")
        if os.path.isfile(cand) and _valid_meta(cand):
            return cand
    return None


def _plan(location, name, folder):
    if _valid_meta(os.path.join(folder, "paper_meta.json")):
        return "skip:already-valid", None
    twin = _find_twin(location, name)
    if twin:
        return "twin", twin
    src = _source_md(folder)
    if not src:
        return "skip:no-source-md", None
    return "extract", src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write paper_meta.json")
    ap.add_argument("--location", action="append", choices=LOCATIONS,
                    help="restrict to a location (repeatable)")
    ap.add_argument("--limit", type=int, help="process at most N folders")
    args = ap.parse_args()

    locations = args.location or list(LOCATIONS)
    targets = [(loc, name, folder, *_plan(loc, name, folder))
               for loc, name, folder in _find_broken(locations)]

    counts = {}
    for _, _, _, action, _hint in targets:
        counts[action] = counts.get(action, 0) + 1
    print(f"검사 대상 {len(targets)}건: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    todo = [t for t in targets if t[3] in ("twin", "extract")]
    if args.limit:
        todo = todo[:args.limit]

    if not args.apply:
        for loc, name, _folder, action, hint in todo:
            print(f"  [{action:<7}] {loc}/{name[:60]}"
                  + (f"   <- {os.path.relpath(hint, REPO)}" if action == "twin" else f"   <- {hint}"))
        for loc, name, _folder, action, _h in targets:
            if action.startswith("skip"):
                print(f"  [{action}] {loc}/{name[:60]}")
        print(f"\n복구 가능 {len(todo)}건. 실제 반영하려면 --apply 를 붙이세요.")
        return 0

    config = mt.load_config()
    ok = fail = 0
    for loc, name, folder, action, hint in todo:
        dest = os.path.join(folder, "paper_meta.json")
        try:
            if action == "twin":
                shutil.copy2(hint, dest)
                meta = _valid_meta(dest)
                # folder_name must describe THIS folder, not the twin's
                if meta is not None:
                    meta["folder_name"] = name
                    json.dump(meta, open(dest, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=2)
                print(f"  ✓ twin    {loc}/{name[:58]}")
            else:
                meta = mt.extract_paper_metadata(os.path.join(folder, hint), folder, config)
                if not meta:
                    fail += 1
                    print(f"  ✗ extract {loc}/{name[:58]}")
                    continue
                print(f"  ✓ extract {loc}/{name[:58]}  ({str(meta.get('title_ko'))[:40]})")
            mt._clear_metadata_failure_marker(folder)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  ✗ {action:<7} {loc}/{name[:50]}: {e}")

    print(f"\n완료: 성공 {ok} / 실패 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
