---
name: md-to-html
description: Convert markdown files to self-contained HTML using Quarto. This skill should be used when the user requests to render, convert, or transform markdown files to HTML format, especially for Korean translated academic papers in the PaperFlow project.
---

# Markdown to HTML Converter

This skill converts markdown files to self-contained HTML using Quarto, following the PaperFlow project's rendering conventions.

## When to Use This Skill

Use this skill when:
- User requests to convert/render/transform a markdown file to HTML
- User asks to "make HTML from this md file"
- User wants to view a Korean translated paper (`*_ko.md`) in HTML format
- User needs a self-contained HTML with embedded images

**Trigger phrases**:
- "이 md 파일을 html로 변환해줘"
- "paper_ko.md를 html로 만들어줘"
- "한국어 번역 파일을 html로 렌더링해줘"
- "Convert this markdown to HTML"

## Prerequisites

Before rendering, verify:
1. **Quarto is installed**: Check with `which quarto`
2. **Markdown file has YAML header**: Must include `embed-resources: true` for image embedding
3. **Markdown file exists**: Verify the file path

## Rendering Workflow

### Step 1: Verify YAML Header

Check if the markdown file starts with a YAML header (between `---` delimiters). The header MUST include:

```yaml
---
format:
  html:
    embed-resources: true
---
```

**Critical setting**: `embed-resources: true` ensures images are base64-encoded and embedded directly in the HTML, creating a self-contained file.

If the file lacks a proper header, refer to `references/header_example.yaml` for the standard PaperFlow YAML configuration.

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
2. Verify file size - embedded images should significantly increase file size (e.g., 73KB → 2.2MB)
3. Confirm to user with file size information

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

## Expected Output

A successful render produces:
- **Self-contained HTML**: Single file with all images embedded as base64
- **Styled content**: Applied CSS from YAML header
- **Table of contents**: Left sidebar TOC (if `toc: true`)
- **Larger file size**: Typically 10-30x larger than original markdown due to embedded images

## PaperFlow Integration

This skill is designed for the PaperFlow project workflow:

1. **Input**: Korean translated markdown from `/paper-translator-korean` skill
2. **Process**: Render with Quarto using project's standard YAML header
3. **Output**: Self-contained HTML viewable in Streamlit app (`app.py`)

The rendered HTML files are stored alongside the markdown files in the `outputs/` directory structure and can be viewed through the PaperFlow Streamlit web interface.

## Resources

### references/

- `references/header_example.yaml`: Standard PaperFlow YAML header with all configuration options explained