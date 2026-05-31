"""Stream-build a zip of a processed paper folder."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Iterator


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
