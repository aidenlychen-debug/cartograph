# Universal Multimodal Content Ingestion Guide

How **Cartograph** ingests any input format cleanly while preserving strict factual boundaries.

## 1. Supported Formats & Primary Paths

### Documents & Books
- **PDF (`.pdf`)**: Use native `read_file` directly — returns both OCR text and rendered page screenshots, preserving formulas, diagrams, and tables.
  - For very large PDFs (> 200 pages or > 50 MB), inspect the Table of Contents first and read by chapter/semantic unit (never splitting mid-argument).
- **EPUB (`.epub`)**: Run `scripts/extract_content.py` — reads DRM-free chapters in exact spine reading order using Python's standard library (`zipfile` + `xml.etree` + `HTMLParser`). Rejects DRM-encrypted EPUBs explicitly so gaps are reported honestly.
- **Word (`.docx`)**: Run `scripts/extract_content.py` — extracts body paragraphs, heading hierarchy, and tables via `word/document.xml`. For legacy `.doc`, ask the user to save as `.docx`.
- **Markdown / Plain Text / JSON / CSV (`.md`, `.txt`, `.json`, `.csv`)**: Read directly via `read_file` or normalize via `scripts/extract_content.py`.

### Video & Audio
- **Local video / audio files (`.mp4`, `.mov`, `.webm`, `.mp3`, `.wav`, `.m4a`)**:
  - Use native multimodal `read_file` directly to inspect visual slides, on-screen text, formulas, and spoken narration.
  - If a subtitle/transcript file (`.srt`, `.vtt`, `.txt`) accompanies the video, also run `scripts/extract_content.py` on the subtitle file to capture exact terminology, numbers, and timestamps.
- **Online video links (YouTube, Bilibili, etc.)**:
  - Never fabricate graph content from titles or metadata alone.
  - Use the `browser` subagent (or `search_web` if official transcripts/show notes exist) to read available transcripts/captions/chapters. If no transcript or accessible content is obtainable, output `【资料缺口说明】`.

### Images & Screenshots
- **Images (`.png`, `.jpg`, `.jpeg`, `.webp`)**: Read directly with native multimodal `read_file`. Extract only clearly legible text, labels, arrows, and numbers; mark illegible or ambiguous regions as `【待确认】`.

### Web URLs
- **Static articles / docs / blogs**: Use `search_web` or `scripts/extract_content.py` (when network access is available) to pull full article text cleanly.
- **JS-rendered / interactive / login-gated web pages**: Delegate to the `browser` subagent to open the page, scroll/expand full content, and return the complete text.
- **Paywalled / CAPTCHA-gated / unreachable URLs**: Stop and report `【资料缺口说明】` — never fabricate a graph from the title or URL slug.

## 2. Handling Long Books (> 300 Pages)

- Always attempt a **single unified canvas** first if the source's full core argument, key evidence, and formulas fit within the ≤ 450–500 edge budget without losing essential logic.
- If a massive reference textbook genuinely exceeds 500 edges even after legitimate deduplication and cross-MOD loose-link filtering, **do not silently drop core arguments** and **do not split without user consent** — issue a `【冲突报告】` presenting concrete scoping options.

## 3. Multi-Source Synthesis

When the user supplies multiple files or links together:
1. Extract each source separately and tag entries in the internal fact ledger with their source identifier.
2. Merge onto one canvas by default, partitioned by theme or source MOD.
3. Preserve disagreements, differing parameters, or conflicting conclusions explicitly (never silently average or merge them).
