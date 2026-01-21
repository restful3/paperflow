#!/usr/bin/env python3
"""
Direct translation script for A Survey on LLM-based Autonomous Agents
Translates the entire markdown file to Korean using Claude.
"""

import re

def translate_to_korean(english_text):
    """
    Translate English markdown to Korean while preserving structure.
    This is a placeholder - Claude will provide the actual translation.
    """
    # This will be replaced with actual Korean translation
    return english_text

def main():
    # Read the English markdown
    input_file = "/home/restful3/workspace/paperflow/outputs/A Survey on Large Language Model based Autonomous Agents/A Survey on Large Language Model based Autonomous Agents .md"
    output_file = "/home/restful3/workspace/paperflow/outputs/A Survey on Large Language Model based Autonomous Agents/A Survey on Large Language Model based Autonomous Agents _ko.md"

    with open(input_file, 'r', encoding='utf-8') as f:
        english_content = f.read()

    print(f"Read {len(english_content)} characters from English markdown")
    print(f"Total lines: {len(english_content.splitlines())}")

    # Translate to Korean
    korean_content = translate_to_korean(english_content)

    # Prepend YAML header
    yaml_header = """---
lang: ko
format:
  html:
    toc: true
    toc-location: left
    toc-depth: 3
    theme: cosmo
    embed-resources: true
    code-fold: true
    code-tools: true
    smooth-scroll: true
    css: |
      body {
        margin-top: 0 !important;
        padding-top: 0 !important;
      }
      #quarto-header {
        display: none !important;
      }
      .quarto-title-block {
        display: none !important;
      }
      /* Center content with equal padding */
      body, #quarto-content, .content, #quarto-document-content, main, .main {
        max-width: 100% !important;
        width: 100% !important;
        margin: 0 auto !important;
        padding-left: 1em !important;
        padding-right: 1em !important;
        box-sizing: border-box !important;
      }
      .container, .container-fluid, article {
        max-width: 100% !important;
        width: 100% !important;
        margin: 0 auto !important;
        padding-left: 1em !important;
        padding-right: 1em !important;
        box-sizing: border-box !important;
      }
---

"""

    full_content = yaml_header + korean_content

    # Write the Korean markdown
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(full_content)

    print(f"Written {len(full_content)} characters to Korean markdown")
    print(f"Output file: {output_file}")

if __name__ == "__main__":
    main()
