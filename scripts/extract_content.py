#!/usr/bin/env python3
"""Universal zero-dependency content extractor for Cartograph (Knowledge Graph Architect).

Extracts clean structured text from EPUB, DOCX, HTML, Markdown, TXT, SRT/VTT subtitles,
and static HTTP(S) URLs using Python's standard library only.
For PDF, images, audio, and video files, use Antigravity's native multimodal read_file tool.

Works both as a standard CLI and as an Antigravity `run_workflow` ScriptPath script:
  CLI: python extract_content.py <input_path_or_url> [-o output.txt] [--max-chars N]
  Workflow: Args={"input": "...", "output": "...", "max_chars": 0}
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree


_BLOCK_TAGS = {
    "p", "div", "br", "hr", "li", "ul", "ol", "dd", "dt", "blockquote", "pre",
    "section", "article", "aside", "header", "footer", "figure", "figcaption",
    "table", "tr", "td", "th",
}
_HEADING_TAGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}
_SKIP_TAGS = {"head", "title", "script", "style", "noscript", "svg", "nav", "iframe"}


class _HTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.in_heading = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
        elif self.skip_depth == 0:
            if tag in _HEADING_TAGS:
                self.parts.append("\n\n" + _HEADING_TAGS[tag])
                self.in_heading = True
            elif tag == "li":
                self.parts.append("\n- ")
            elif tag in _BLOCK_TAGS:
                self.parts.append("\n\n")

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        if self.skip_depth == 0 and tag.lower() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif self.skip_depth == 0:
            if tag in _HEADING_TAGS:
                self.parts.append("\n\n")
                self.in_heading = False
            elif tag in _BLOCK_TAGS:
                self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            cleaned = re.sub(r"[ \t\r\n]+", " ", data)
            if cleaned:
                self.parts.append(cleaned)

    def get_text(self) -> str:
        raw = "".join(self.parts)
        lines = [line.strip() for line in raw.splitlines()]
        out: list[str] = []
        blank_streak = 0
        for line in lines:
            if not line:
                blank_streak += 1
                if blank_streak <= 1:
                    out.append("")
            else:
                blank_streak = 0
                out.append(line)
        return "\n".join(out).strip()


def _decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def extract_epub(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        encrypted: set[str] = set()
        if "META-INF/encryption.xml" in names:
            enc_xml = ElementTree.fromstring(zf.read("META-INF/encryption.xml"))
            encrypted = {
                unquote(el.get("URI", ""))
                for el in enc_xml.iter()
                if _local(el.tag) == "CipherReference"
            }
        container = ElementTree.fromstring(zf.read("META-INF/container.xml"))
        opf_path = next(
            el.get("full-path")
            for el in container.iter()
            if _local(el.tag) == "rootfile" and el.get("full-path")
        )
        pkg = ElementTree.fromstring(zf.read(opf_path))
        base = posixpath.dirname(opf_path)
        manifest = {
            el.get("id"): el for el in pkg.iter() if _local(el.tag) == "item"
        }
        chapters: list[str] = []
        for idx, itemref in enumerate(
            (el for el in pkg.iter() if _local(el.tag) == "itemref"), start=1
        ):
            item = manifest.get(itemref.get("idref"))
            if item is None or itemref.get("linear") == "no":
                continue
            if "html" not in (item.get("media-type") or "").lower():
                continue
            href = unquote(item.get("href", "").split("#")[0])
            name = posixpath.normpath(posixpath.join(base, href))
            if name not in names:
                continue
            if name in encrypted:
                raise ValueError(f"EPUB 文件包含 DRM 加密章节 ({name})，无法直接提取。")
            parser = _HTMLToText()
            parser.feed(_decode_bytes(zf.read(name)))
            parser.close()
            txt = parser.get_text()
            if txt:
                chapters.append(f"<!-- EPUB Section {idx}: {name} -->\n{txt}")
    return "\n\n---\n\n".join(chapters)


def extract_docx(path: Path) -> str:
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        root = ElementTree.fromstring(zf.read("word/document.xml"))
    body = root.find(f"{w}body")
    if body is None:
        return ""
    blocks: list[str] = []
    for child in body:
        tag = _local(child.tag)
        if tag == "p":
            style = ""
            ppr = child.find(f"{w}pPr")
            if ppr is not None:
                ps = ppr.find(f"{w}pStyle")
                if ps is not None:
                    style = ps.get(f"{w}val", "")
            parts: list[str] = []
            for el in child.iter():
                if el.tag == f"{w}t":
                    parts.append(el.text or "")
                elif el.tag == f"{w}tab":
                    parts.append("\t")
                elif el.tag in (f"{w}br", f"{w}cr"):
                    parts.append("\n")
            text = "".join(parts).strip()
            if not text:
                continue
            hm = re.match(r"(?:Heading|标题)\s*(\d)", style, re.IGNORECASE)
            if hm:
                lvl = min(6, max(1, int(hm.group(1))))
                blocks.append(f"{'#' * lvl} {text}")
            else:
                blocks.append(text)
        elif tag == "tbl":
            rows: list[str] = []
            for tr in child.findall(f"{w}tr"):
                cells = []
                for tc in tr.findall(f"{w}tc"):
                    cell_text = " ".join(
                        (t.text or "") for t in tc.iter(f"{w}t")
                    ).strip()
                    cells.append(cell_text)
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


def extract_subtitles(path: Path) -> str:
    text = _decode_bytes(path.read_bytes()).replace("\r\n", "\n")
    lines = text.splitlines()
    out: list[str] = []
    current_ts = ""
    buf: list[str] = []

    def flush() -> None:
        if buf:
            joined = " ".join(buf).strip()
            if joined:
                prefix = f"[{current_ts}] " if current_ts else ""
                out.append(f"{prefix}{joined}")
            buf.clear()

    ts_re = re.compile(r"^(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})\s*-->")
    for raw in lines:
        line = raw.strip()
        if not line or line.upper().startswith("WEBVTT") or line.isdigit():
            if not line:
                flush()
            continue
        m = ts_re.match(line)
        if m:
            flush()
            current_ts = m.group(1).split(".")[0].split(",")[0]
            continue
        cleaned = re.sub(r"<[^>]+>", "", line).strip()
        if cleaned:
            buf.append(cleaned)
    flush()
    return "\n".join(out)


def extract_html(path: Path) -> str:
    parser = _HTMLToText()
    parser.feed(_decode_bytes(path.read_bytes()))
    parser.close()
    return parser.get_text()


def extract_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Cartograph/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read()
    text = _decode_bytes(data)
    if "html" in ctype or "<html" in text[:1000].lower():
        parser = _HTMLToText()
        parser.feed(text)
        parser.close()
        return parser.get_text()
    return text


def extract_source(source: str) -> dict[str, Any]:
    if source.startswith(("http://", "https://")):
        content = extract_url(source)
        return {"source": source, "format": "url", "chars": len(content), "content": content}

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"未找到文件：{source}")
    ext = path.suffix.lower()
    if ext == ".epub":
        content = extract_epub(path)
    elif ext == ".docx":
        content = extract_docx(path)
    elif ext in {".html", ".htm"}:
        content = extract_html(path)
    elif ext in {".srt", ".vtt"}:
        content = extract_subtitles(path)
    elif ext in {".md", ".markdown", ".txt", ".json", ".csv", ".tsv", ".xml", ".yaml", ".yml"}:
        content = _decode_bytes(path.read_bytes())
    elif ext in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a"}:
        raise ValueError(
            f"格式 {ext} 应由 Antigravity 原生多模态 read_file 工具直接读取，无需经本脚本转文本。"
        )
    else:
        raise ValueError(f"暂不支持直接提取的格式：{ext or '(无后缀)'}")

    return {"source": str(path), "format": ext.lstrip("."), "chars": len(content), "content": content}


def run(source: str, output: str | None = None, max_chars: int = 0) -> dict[str, Any]:
    res = extract_source(source)
    content = res["content"]
    if max_chars > 0 and len(content) > max_chars:
        content = content[:max_chars] + "\n\n[... 已按 max_chars 截断 ...]"
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        summary = {
            "source": res["source"],
            "format": res["format"],
            "chars": res["chars"],
            "output": str(out_path),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    print(content)
    return {"source": res["source"], "format": res["format"], "chars": res["chars"]}


if "args" in globals() and isinstance(globals()["args"], dict):
    _a = globals()["args"]
    run(_a["input"], output=_a.get("output"), max_chars=int(_a.get("max_chars") or 0))
elif __name__ == "__main__":
    p = argparse.ArgumentParser(description="Cartograph universal zero-dependency content extractor")
    p.add_argument("input", help="File path (EPUB/DOCX/HTML/MD/TXT/SRT/VTT) or HTTP(S) URL")
    p.add_argument("-o", "--output", default=None, help="Optional output text file path")
    p.add_argument("--max-chars", type=int, default=0, help="Optional character cap (0 = unlimited)")
    ns = p.parse_args()
    try:
        run(ns.input, output=ns.output, max_chars=ns.max_chars)
    except (FileNotFoundError, ValueError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
