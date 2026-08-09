"""outputs/ · archives/ 건전성 검사 — 뷰어에 빈 카드가 쌓이기 전에 잡는다.

2026-08-09 사고: `paper_meta.json` 이 없는 폴더 66건이 누적될 때까지 아무도 몰랐다.
개별 결함보다 **감지 공백**이 진짜 문제였다. 이 스크립트가 그 공백을 메운다.
결함이 하나라도 있으면 exit 1 이므로 cron 에 그대로 걸 수 있다.

검사 항목:
  missing_meta          paper_meta.json 없음/깨짐 → 목록에서 제목·요약·썸네일 전부 공백
  failure_marker        paper_meta.failed.json — 메타 추출이 영구 실패한 흔적
  empty_folder          파일이 하나도 없는 폴더
  outputs_archives_dup  같은 이름이 outputs·archives 양쪽에 존재 (목록 중복 노출)
  unicode_dup           NFC/NFD 정규화 차이로 눈에 같아 보이는 폴더 쌍
  orphan_part           죽은 배치가 남긴 *.part (기본 2시간 이상 방치)
  slug_title            본문 H1 이 파일명 슬러그(web-…-20260604-054702)
  missing_korean_field  title_ko / abstract_ko / categories 결측

사용:
    python3 scripts/check_outputs_health.py            # 사람이 읽는 리포트
    python3 scripts/check_outputs_health.py --json     # 기계 판독용
    python3 scripts/check_outputs_health.py --quiet    # 결함 있을 때만 출력 (cron 용)
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCATIONS = ("outputs", "archives")
FAILURE_MARKER = "paper_meta.failed.json"
SLUG_H1 = re.compile(r'(-\d{8}-\d{6})|(^web-.*-\d{6})')
KOREAN_FIELDS = ("title_ko", "abstract_ko", "categories")
SKIP_MD = ("_ko_explained.md", "_explained.md", "_ko_audio.md", "_ko_audio_brief.md")


def _h1(path):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    body = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.S)
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def scan(root, part_age_hours=2.0):
    f = defaultdict(list)
    names = defaultdict(list)          # location -> folder names
    unicode_groups = defaultdict(list)  # (location, NFC name) -> raw names
    part_cutoff = time.time() - part_age_hours * 3600

    for loc in LOCATIONS:
        base = os.path.join(root, loc)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            folder = os.path.join(base, name)
            if not os.path.isdir(folder) or name.startswith("."):
                continue
            rel = f"{loc}/{name}"
            names[loc].append(name)
            unicode_groups[(loc, unicodedata.normalize("NFC", name))].append(name)

            entries = os.listdir(folder)
            if not entries:
                f["empty_folder"].append({"folder": rel})
                continue

            for e in entries:
                if e.endswith(".part") and os.path.getmtime(os.path.join(folder, e)) < part_cutoff:
                    f["orphan_part"].append({"folder": rel, "file": e})

            if FAILURE_MARKER in entries:
                f["failure_marker"].append({"folder": rel})

            meta_path = os.path.join(folder, "paper_meta.json")
            if not os.path.isfile(meta_path):
                f["missing_meta"].append({"folder": rel, "reason": "no paper_meta.json"})
                continue
            try:
                meta = json.load(open(meta_path, encoding="utf-8"))
            except Exception as e:
                f["missing_meta"].append({"folder": rel, "reason": f"unreadable: {e}"})
                continue
            if not isinstance(meta, dict) or not meta.get("title"):
                f["missing_meta"].append({"folder": rel, "reason": "no title"})
                continue

            for key in KOREAN_FIELDS:
                if meta.get(key) in (None, "", [], {}):
                    f["missing_korean_field"].append({"folder": rel, "field": key})

            for e in entries:
                if not e.endswith(".md") or e.endswith(SKIP_MD):
                    continue
                h1 = _h1(os.path.join(folder, e))
                if h1 and SLUG_H1.search(h1):
                    f["slug_title"].append({"folder": rel, "file": e, "h1": h1})

    for name in sorted(set(names["outputs"]) & set(names["archives"])):
        f["outputs_archives_dup"].append({"folder": f"outputs/{name}", "twin": f"archives/{name}"})

    for (loc, _norm), raw in sorted(unicode_groups.items()):
        if len(raw) > 1:
            f["unicode_dup"].append({"folder": f"{loc}/{raw[0]}", "variants": len(raw)})

    return {k: f.get(k, []) for k in (
        "missing_meta", "failure_marker", "empty_folder", "outputs_archives_dup",
        "unicode_dup", "orphan_part", "slug_title", "missing_korean_field")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="결함이 없으면 아무것도 출력하지 않는다 (cron)")
    ap.add_argument("--part-age-hours", type=float, default=2.0)
    ap.add_argument("--max-list", type=int, default=15)
    args = ap.parse_args()

    findings = scan(args.root, args.part_age_hours)
    total = sum(len(v) for v in findings.values())

    if args.json:
        print(json.dumps({"total_findings": total, "findings": findings},
                         ensure_ascii=False, indent=2))
        return 1 if total else 0

    if total == 0:
        if not args.quiet:
            print("✓ outputs/archives 건전성 이상 없음")
        return 0

    print(f"✗ 결함 {total}건 발견 (root={args.root})")
    for kind, items in findings.items():
        if not items:
            continue
        print(f"\n  [{kind}] {len(items)}건")
        for it in items[:args.max_list]:
            extra = {k: v for k, v in it.items() if k != "folder"}
            print(f"     - {it['folder']}" + (f"   {extra}" if extra else ""))
        if len(items) > args.max_list:
            print(f"     … 외 {len(items) - args.max_list}건")
    print("\n복구: python3 scripts/backfill_metadata.py --apply   "
          "(커버는 scripts/backfill_covers.py --apply)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
