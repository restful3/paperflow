"""PDF 1페이지 상단 밴드를 카드 커버로 백필한다.

`select_cover_image()` 는 폴더 안의 이미지 중에서만 고르고, 표·플롯·로고·인물
증명샷은 의도적으로 거절한다. 그래서 arXiv 논문처럼 그림이 전부 표·플롯인
문서, 그리고 이미지가 아예 없는 문서(뉴스레터·텍스트 블로그)는 영구히 썸네일이
없다 — 2026-08-18 기준 992건 중 164건이 그랬다.

그런 문서에는 **원본 PDF 1페이지 상단**이 가장 유용한 썸네일이다. 제목·저자·
리드 사진이 그대로 보여서 카드에서 문서를 식별할 수 있다. 세로 페이지를 중앙
크롭하면 본문 한가운데가 잡혀 읽을 수 없으므로 **상단을 16:9 로 잘라낸다.**

`cover_source: "pdf_page1"` 을 함께 기록하므로 나중에 전부 되돌릴 수 있다:

    python3 - <<'EOF'
    import json,os
    for loc in ('outputs','archives'):
        for d in os.listdir(loc):
            p=os.path.join(loc,d,'paper_meta.json')
            if not os.path.isfile(p): continue
            m=json.load(open(p,encoding='utf-8'))
            if m.get('cover_source')=='pdf_page1':
                m.pop('cover',None); m.pop('cover_source',None)
                json.dump(m,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
    EOF

사용:
    python3 scripts/backfill_pdf_page_covers.py                 # dry-run
    python3 scripts/backfill_pdf_page_covers.py --apply
    python3 scripts/backfill_pdf_page_covers.py --apply --location outputs --limit 10
"""
import argparse
import json
import os
import subprocess
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCATIONS = ("outputs", "archives")
COVER_NAME = "cover_page1.jpg"
CARD_W, CARD_H = 16, 9          # 뷰어 카드 비율(aspect-video)
RENDER_DPI = "110"
MIN_INK_RATIO = 0.005           # 상단 밴드가 이보다 비어 있으면 백지로 보고 건너뛴다


def _pick_pdf(folder):
    """폴더의 PDF 중 가장 큰 것(본문일 가능성이 가장 높다). 없으면 None."""
    best = None
    best_size = -1
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for fn in names:
        if not fn.lower().endswith(".pdf"):
            continue
        path = os.path.join(folder, fn)
        if not os.path.isfile(path):
            continue
        size = os.path.getsize(path)
        if size > best_size:
            best, best_size = fn, size
    return best


def _render_cover(folder, pdf_name):
    """PDF 1페이지 상단을 16:9 로 잘라 images/cover_page1.jpg 로 저장.

    성공하면 폴더 상대경로, 백지/실패면 None. 예외를 밖으로 던지지 않는다.
    """
    from PIL import Image
    import numpy as np

    src = os.path.join(folder, pdf_name)
    try:
        with tempfile.TemporaryDirectory() as td:
            base = os.path.join(td, "pg")
            subprocess.run(
                ["pdftoppm", "-jpeg", "-r", RENDER_DPI, "-f", "1", "-l", "1", src, base],
                check=True, capture_output=True, timeout=120,
            )
            jpgs = [f for f in sorted(os.listdir(td)) if f.lower().endswith(".jpg")]
            if not jpgs:
                return None
            with Image.open(os.path.join(td, jpgs[0])) as im:
                page = im.convert("RGB").copy()
    except Exception:
        return None

    band_h = max(1, int(page.width * CARD_H / CARD_W))
    band = page.crop((0, 0, page.width, min(band_h, page.height)))

    # 잉크가 거의 없으면(백지 표지 등) 커버로 쓰지 않는다.
    arr = np.asarray(band.convert("L"))
    if float((arr < 200).mean()) < MIN_INK_RATIO:
        return None

    target_w = 1280
    band = band.resize((target_w, max(1, round(target_w * CARD_H / CARD_W))))
    out_dir = os.path.join(folder, "images")
    os.makedirs(out_dir, exist_ok=True)
    band.save(os.path.join(out_dir, COVER_NAME), "JPEG", quality=86)
    return os.path.join("images", COVER_NAME)


def _write_cover(folder, rel):
    meta_path = os.path.join(folder, "paper_meta.json")
    meta = json.load(open(meta_path, encoding="utf-8"))
    meta["cover"] = rel
    meta["cover_source"] = "pdf_page1"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _needs_cover(folder, meta):
    if meta.get("cover"):
        return False
    poster = (meta.get("video") or {}).get("poster")
    if poster and os.path.isfile(os.path.join(folder, poster)):
        return False
    return True


def _targets(locations):
    """(location, name, folder, pdf_name) — 커버가 없고 PDF 가 있는 폴더만."""
    out = []
    for loc in locations:
        base = os.path.join(REPO, loc)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            folder = os.path.join(base, name)
            meta_path = os.path.join(folder, "paper_meta.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                meta = json.load(open(meta_path, encoding="utf-8"))
            except Exception:
                continue
            if not _needs_cover(folder, meta):
                continue
            pdf = _pick_pdf(folder)
            if not pdf:
                continue
            out.append((loc, name, folder, pdf))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--location", action="append", choices=LOCATIONS)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    targets = _targets(args.location or list(LOCATIONS))
    if args.limit:
        targets = targets[:args.limit]
    print(f"대상 {len(targets)}건 (커버 없음 + 원본 PDF 있음)")

    if not args.apply:
        for loc, name, _folder, pdf in targets[:20]:
            print(f"  [{loc}] {name[:56]}  <- {pdf[:40]}")
        if len(targets) > 20:
            print(f"  … 외 {len(targets)-20}건")
        print("\n실제 반영하려면 --apply 를 붙이세요.")
        return 0

    ok = blank = 0
    for loc, name, folder, pdf in targets:
        rel = _render_cover(folder, pdf)
        if not rel:
            blank += 1
            print(f"  · skip  [{loc}] {name[:52]} (1페이지 렌더 실패/백지)")
            continue
        _write_cover(folder, rel)
        ok += 1
        print(f"  ✓ cover [{loc}] {name[:52]}")
    print(f"\n완료: 적용 {ok} / 건너뜀 {blank}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
