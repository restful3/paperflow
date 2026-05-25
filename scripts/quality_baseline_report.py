#!/usr/bin/env python3
"""Paperflow quality baseline report (phase 1).

Scans outputs/*/*_ko.md and emits aggregate/per-file noise metrics.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime

PATTERNS = {
    "cookie": re.compile(r"쿠키를 사용합니다|쿠키 정책|cookie", re.I),
    "menu": re.compile(r"설정으로 이동하여 원하는 대로 변경할 수 있습니다|자세한 정보는 .*정책", re.I),
    "openal": re.compile(r"\bOpenAl\b"),
    "ocr_fi": re.compile(r"\bfi\s+\w+"),
    "short_noise": re.compile(r"^[A-Za-z가-힣]{1,3}$"),
    "mixed": re.compile(r"[가-힣].*[A-Za-z]{4,}|[A-Za-z]{4,}.*[가-힣]"),
}


def score_text(text: str) -> dict:
    lines = text.splitlines()
    total = max(1, len(lines))
    counts = {k: 0 for k in PATTERNS}
    for ln in lines:
        s = ln.strip()
        for k, p in PATTERNS.items():
            if p.search(s):
                counts[k] += 1
    counts["total_lines"] = total
    counts["noise_ratio"] = round((counts["cookie"] + counts["menu"] + counts["openal"] + counts["short_noise"]) / total, 4)
    return counts


def infer_source_type(folder: Path) -> str:
    meta = folder / "paper_meta.json"
    if meta.exists():
        try:
            m = json.loads(meta.read_text(encoding="utf-8", errors="ignore"))
            orig = (m.get("original_filename") or "").lower()
            if orig.startswith("web-"):
                return "webpdf"
            if orig.endswith(".pdf"):
                return "pdf"
            if (m.get("source_url_original") or "").startswith(("http://", "https://")):
                return "url"
        except Exception:
            pass
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", default="outputs")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--save", default="logs/quality_baseline_latest.json")
    args = ap.parse_args()

    base = Path(args.outputs)
    ko_files = list(base.glob("*/*_ko.md"))

    per = []
    by_type = defaultdict(lambda: {"docs": 0, "totals": defaultdict(int)})

    for f in ko_files:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        s = score_text(txt)
        stype = infer_source_type(f.parent)
        rec = {
            "file": str(f),
            "name": f.name,
            "folder": f.parent.name,
            "source_type": stype,
            **s,
        }
        per.append(rec)
        by_type[stype]["docs"] += 1
        for k, v in s.items():
            if isinstance(v, (int, float)):
                by_type[stype]["totals"][k] += v

    per_sorted = sorted(per, key=lambda x: x["noise_ratio"], reverse=True)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_docs": len(per),
        "top_noisy": per_sorted[: args.top],
        "by_source_type": {},
    }
    for t, data in by_type.items():
        docs = max(1, data["docs"])
        totals = dict(data["totals"])
        summary["by_source_type"][t] = {
            "docs": data["docs"],
            "avg_noise_ratio": round(totals.get("noise_ratio", 0.0) / docs, 4),
            "avg_cookie": round(totals.get("cookie", 0) / docs, 2),
            "avg_openal": round(totals.get("openal", 0) / docs, 2),
            "avg_mixed": round(totals.get("mixed", 0) / docs, 2),
        }

    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"docs={summary['total_docs']}")
    for t, v in summary["by_source_type"].items():
        print(f"{t}: docs={v['docs']} avg_noise_ratio={v['avg_noise_ratio']} avg_cookie={v['avg_cookie']}")
    print(f"saved={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
