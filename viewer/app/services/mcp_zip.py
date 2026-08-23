"""Stream-build a zip of a processed paper folder."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Iterator
import json


_CHUNK_SIZE = 64 * 1024


def build_zip_stream(
    paper_dir: Path,
    *,
    include_pdf: bool,
    include_translation: bool,
    job_meta: dict,
) -> Iterator[bytes]:
    """Yield zip bytes in chunks. Caller provides StreamingResponse wrapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # README first
        readme = (
            "PaperFlow MCP zip export\n"
            f"job_id: {job_meta.get('job_id','?')}\n"
            f"paper: {paper_dir.name}\n"
            f"include_pdf: {include_pdf}\n"
            f"include_translation: {include_translation}\n"
        )
        zf.writestr("README.txt", readme)

        for entry in sorted(paper_dir.iterdir()):
            if entry.is_file():
                name = entry.name
                # Skip backup files and source sidecars
                if "_backup_" in name or name.endswith(".url.txt") or name.endswith(".mcp.json"):
                    continue
                # PDF gated
                if name.lower().endswith(".pdf") and not include_pdf:
                    continue
                # _ko.md, _ko_explained.md, _ko_audio.md gated by include_translation
                lower = name.lower()
                if lower.endswith("_ko.md") and not include_translation:
                    continue
                if lower.endswith("_ko_explained.md") and not include_translation:
                    continue
                if lower.endswith("_ko_audio.md") and not include_translation:
                    continue
                if lower.endswith("_ko_audio_brief.md") and not include_translation:
                    continue
                zf.write(entry, arcname=name)
            elif entry.is_dir() and entry.name in ("images",):
                for img in sorted(entry.iterdir()):
                    if img.is_file():
                        zf.write(img, arcname=f"{entry.name}/{img.name}")

    # Stream the in-memory buffer in chunks
    buf.seek(0)
    while True:
        chunk = buf.read(_CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


def build_book_zip_stream(
    book_dir: Path,
    *,
    include_pdf: bool,
    include_md: bool,
    include_translation: bool,
    include_explained: bool,
    include_assets: bool,
    job_meta: dict,
) -> Iterator[bytes]:
    """Yield zip bytes for a processed book folder."""
    meta = {}
    meta_path = book_dir / "book_meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    chapters = meta.get("chapters") or []
    chapter_ids = [
        ch.get("chapter_id") for ch in sorted(
            chapters,
            key=lambda c: (c.get("order") if c.get("order") is not None else 10**9,
                           c.get("chapter_id") or ""),
        )
        if ch.get("chapter_id")
    ]
    if not chapter_ids:
        chapter_ids = sorted(p.name for p in book_dir.iterdir() if p.is_dir())

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "kind": "paperflow_book_export",
            "job_id": job_meta.get("job_id"),
            "book_id": meta.get("book_id") or job_meta.get("book_id"),
            "book_slug": book_dir.name,
            "include_pdf": include_pdf,
            "include_md": include_md,
            "include_translation": include_translation,
            "include_explained": include_explained,
            "include_assets": include_assets,
            "chapters": chapter_ids,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if meta_path.is_file():
            zf.write(meta_path, arcname="book_meta.json")

        for idx, cid in enumerate(chapter_ids, 1):
            cdir = book_dir / cid
            if not cdir.is_dir():
                continue
            prefix = f"chapters/{idx:02d}_{cid}"
            for entry in sorted(cdir.iterdir()):
                if entry.is_file():
                    name = entry.name
                    lower = name.lower()
                    if "_backup_" in name or name.endswith(".url.txt") or name.endswith(".mcp.json"):
                        continue
                    if lower.endswith(".pdf") and not include_pdf:
                        continue
                    if lower.endswith(".md"):
                        if not include_md:
                            continue
                        is_translation = (
                            lower.endswith("_ko.md")
                            or lower.endswith("_ko_audio.md")
                            or lower.endswith("_ko_audio_brief.md")
                        )
                        is_explained = lower.endswith("_explained.md")
                        if is_translation and not include_translation:
                            continue
                        if is_explained and not include_explained:
                            continue
                    zf.write(entry, arcname=f"{prefix}/{name}")
                elif entry.is_dir() and include_assets:
                    for asset in sorted(entry.rglob("*")):
                        if asset.is_file():
                            rel = asset.relative_to(cdir)
                            zf.write(asset, arcname=f"{prefix}/{rel}")

    buf.seek(0)
    while True:
        chunk = buf.read(_CHUNK_SIZE)
        if not chunk:
            return
        yield chunk
