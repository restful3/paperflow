---
name: md-to-html
description: Convert markdown files to self-contained HTML using Quarto. This skill should be used when the user requests to render, convert, or transform markdown files to HTML format, especially for Korean papers in the PaperFlow project (translations `_ko.md`, explainers `_ko_explained.md`, audio narrations `_ko_audio.md` / `_ko_audio_brief.md`).
---

# Markdown to HTML Converter

This skill converts markdown files to self-contained HTML using Quarto, following the PaperFlow project's rendering conventions.

## When to Use This Skill

Use this skill when:
- User requests to convert/render/transform a markdown file to HTML
- User asks to "make HTML from this md file"
- User wants to view a Korean paper file (`*_ko.md`, `*_ko_explained.md`, `*_ko_audio.md`) in HTML format
- User needs a self-contained HTML with embedded images

**Trigger phrases**:
- "이 md 파일을 html로 변환해줘"
- "paper_ko.md를 html로 만들어줘"
- "한국어 번역 파일을 html로 렌더링해줘"
- "Convert this markdown to HTML"

## Prerequisites

Before rendering, verify:
1. **Quarto is installed**: Check with `which quarto`
2. **Markdown file exists**: Verify the file path
3. **Input type** (determines Step 1 branch):
   - `_ko.md` / `_ko_explained.md` — normally start with a YAML header → verify/fix it
   - `_ko_audio.md` / `_ko_audio_brief.md` — **intentionally have NO YAML header** (raw-TTS design). NEVER add a header to the original file; render via a temp copy (see Step 1b)

## Rendering Workflow

### Step 1a: Verify YAML Header (files that have one)

Check if the markdown file starts with a YAML header (between `---` delimiters). The header MUST include:

```yaml
---
format:
  html:
    embed-resources: true
---
```

**Critical settings**:
- `embed-resources: true` ensures images are base64-encoded and embedded directly in the HTML, creating a self-contained file.
- **CJK word-break CSS** — Korean text breaks mid-word (글자 단위) under browser defaults. The header CSS must include, on `body`:

```css
body { word-break: keep-all; overflow-wrap: break-word; }
```

  Always the pair together: `keep-all` alone lets long English tokens/URLs overflow horizontally. If the file's existing header lacks this, add it to the header's `css:` block (this edit is allowed for YAML-headed files).

If the file lacks a proper header, refer to `references/header_example.yaml` for the standard PaperFlow YAML configuration (it includes the word-break rules).

### Step 1b: YAML-less files (audio narrations) — render a temp copy

`_ko_audio.md` / `_ko_audio_brief.md` deliberately carry no front matter (raw markdown goes straight into TTS; a YAML block would be read aloud). To render them:

1. **Do NOT modify the original file.**
2. Create a copy **in the same directory** (image paths are relative — copying elsewhere breaks them): `<name>.render.md`
3. Prepend the standard header from `references/header_example.yaml` to the copy.
4. `quarto render "<name>.render.md" --output "<name>.html"` (explicit `--output` so the HTML keeps the original basename).
5. Delete the temp copy `<name>.render.md` after rendering.

### Step 2: Run Quarto Render

Execute the Quarto render command from the **directory containing the markdown file**:

```bash
cd /path/to/markdown/directory
quarto render filename.md
```

**Important**:
- Always use the **filename only** (not full path) as the argument to `quarto render`
- Change to the file's directory first using `cd`
- This prevents Quarto's "No valid input files" error

**Example**:
```bash
# CORRECT
cd "/home/user/papers/My Paper/"
quarto render "My_Paper_ko.md"

# WRONG (will fail)
quarto render "/home/user/papers/My Paper/My_Paper_ko.md"
```

### Step 3: Verify Output

After rendering:
1. Check that the HTML file was created (same name as `.md` but with `.html` extension)
2. Verify file size - embedded images should significantly increase file size (e.g., 73KB → 2.2MB). If the source references local images but the HTML barely grew, `embed-resources` did not take effect — re-check the header
3. Verify CJK CSS landed: `grep -c 'keep-all' output.html` ≥ 1
4. If a temp `.render.md` copy was used, confirm it was deleted and the original file is byte-identical (untouched)
5. Confirm to user with file size information

## Handling Errors

### Error: "No valid input files"

**Cause**: Using full path instead of filename with `quarto render`

**Solution**: Change to the file's directory first, then use filename only

### Error: "YAML parse exception"

**Cause**: Invalid YAML syntax in the header

**Solution**:
1. Verify YAML formatting (proper indentation, colons, quotes)
2. Try with simplified header (see `references/header_example.yaml`)
3. Common issues: incorrect indentation, missing colons, unquoted special characters

### Warning: Images not displaying

**Cause**: Missing `embed-resources: true` in YAML header

**Solution**: Add or verify the `embed-resources: true` setting in the YAML header

### Warning: Korean words split across lines (한 단어가 두 줄로 쪼개짐)

**Cause**: Missing `word-break: keep-all` in the header CSS

**Solution**: Add the CJK pair (`word-break: keep-all; overflow-wrap: break-word;`) to `body` in the header's `css:` block

## Expected Output

A successful render produces:
- **Self-contained HTML**: Single file with all images embedded as base64
- **Styled content**: Applied CSS from YAML header, Korean text wrapping at word boundaries (keep-all)
- **Table of contents**: Left sidebar TOC (if `toc: true`)
- **Larger file size**: Typically 10-30x larger than original markdown due to embedded images

## PaperFlow Integration

This skill is designed for the PaperFlow project workflow:

1. **Input**: any Korean markdown in an `outputs/`/`archives/` paper folder — translation (`_ko.md`, from the batch pipeline), explainer (`_ko_explained.md`, from `paper-explainer`), or narration (`_ko_audio.md` / `_ko_audio_brief.md`, from `paper-audio-korean` / `paper-audio-brief-korean`; YAML-less by design)
2. **Process**: render with Quarto using the project's standard YAML header (temp-copy injection for YAML-less files)
3. **Output**: self-contained HTML stored alongside the markdown in the paper folder

Note: the PaperFlow web viewer (FastAPI + Alpine.js, `http://localhost:8090`) renders markdown client-side on its own — these HTML files are **not** consumed by the viewer. Use this skill when a standalone/shareable HTML is wanted (e.g. sending a file, offline reading, TTS-with-figures listening in a browser).

## Resources

### references/

- `references/header_example.yaml`: Standard PaperFlow YAML header with all configuration options explained
