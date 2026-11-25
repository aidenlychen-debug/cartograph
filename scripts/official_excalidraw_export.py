#!/usr/bin/env python3
"""Cartograph Official Excalidraw Exporter + Offline CDN Cache + Real PNG Visual Verifier.

Zero third-party Python dependencies (Python 3.8+ stdlib only) and zero Node.js/npm required.
Uses locally installed Chrome, Edge, or Chromium in headless mode to execute the EXACT
official `@excalidraw/mermaid-to-excalidraw@3.6.0` (`elbow: true`) and
`@excalidraw/excalidraw@0.18.1` (`convertToExcalidrawElements` + `exportToBlob`) pipeline:

  1. Local `/npm/*` transparent disk cache (`resources/cdn_cache/`) -> works 100% offline once warmed!
  2. Official Mermaid -> Excalidraw (`elbow: true`, 100% orthogonal elbow arrows)
  3. Automatic real-Excalidraw zero-interference deconfliction & hard gate (`excalidraw_deconflict.py`)
  4. Optional real rasterized PNG close-up tile rendering via Excalidraw's own `exportToBlob`
     for photographic visual verification (`--render-dir <dir>` or `--render-only`).

Usage:
  python official_excalidraw_export.py input.mmd [-o output.excalidraw] [--render-dir ./previews]
  python official_excalidraw_export.py --render-only a.excalidraw b.excalidraw --render-dir ./previews
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def find_browser_binary() -> str | None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return str(path)
    return None


def _extract_mermaid(raw: str) -> str:
    m = re.search(r"```mermaid\s*\n(.*?)\n```", raw, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else raw.strip()


def _cache_fetch_npm(cache_dir: Path, url_path: str) -> tuple[bytes, str]:
    """Serve `/npm/...` from persistent local disk cache; fetch once from cdn.jsdelivr.net on miss."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url_path.encode("utf-8")).hexdigest()[:32]
    body_p = cache_dir / f"{key}.bin"
    meta_p = cache_dir / f"{key}.meta.json"
    if body_p.exists() and meta_p.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        return body_p.read_bytes(), meta.get("content_type", "application/javascript; charset=utf-8")

    remote_url = "https://cdn.jsdelivr.net" + url_path
    req = urllib.request.Request(remote_url, headers={"User-Agent": "Cartograph/2.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type", "application/javascript; charset=utf-8")
    body_p.write_bytes(data)
    meta_p.write_text(json.dumps({"path": url_path, "content_type": ctype}), encoding="utf-8")
    return data, ctype


def run_pipeline(
    jobs: list[dict[str, Any]],
    *,
    mode: str = "export",
    render_dir: Path | None = None,
    timeout_sec: int = 120,
    browser_bin: str | None = None,
) -> list[dict[str, Any]]:
    browser = browser_bin or find_browser_binary()
    if not browser:
        raise RuntimeError(
            "No local Chrome, Edge, or Chromium binary found. "
            "Install Chrome/Edge or fall back to scripts/mermaid_to_excalidraw.py."
        )

    skill_root = Path(__file__).resolve().parent.parent
    html_path = skill_root / "resources" / "official_converter.html"
    cache_dir = skill_root / "resources" / "cdn_cache"
    if not html_path.exists():
        raise FileNotFoundError(f"Missing converter template: {html_path}")
    html_bytes = html_path.read_bytes()

    if render_dir:
        render_dir.mkdir(parents=True, exist_ok=True)

    mmd_payloads: list[bytes] = []
    if mode in ("export", "export_and_render"):
        for j in jobs:
            mmd_payloads.append(_extract_mermaid(Path(j["src"]).read_text(encoding="utf-8")).encode("utf-8"))

    state: dict[str, Any] = {
        "done": threading.Event(),
        "error": None,
        "results": [{} for _ in jobs],
        "cache_hits": 0,
        "cache_misses": 0,
    }

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import excalidraw_deconflict as _ed

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self._send(200, html_bytes, "text/html; charset=utf-8")
            elif parsed.path == "/config":
                self._send(200, json.dumps({"mode": mode}).encode("utf-8"), "application/json; charset=utf-8")
            elif parsed.path == "/jobs":
                data = [{"idx": i, "name": j["name"], "focus": j.get("focus", "")} for i, j in enumerate(jobs)]
                self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            elif parsed.path == "/mmd":
                qs = urllib.parse.parse_qs(parsed.query)
                idx = int(qs.get("idx", ["0"])[0])
                self._send(200, mmd_payloads[idx], "text/plain; charset=utf-8")
            elif parsed.path == "/final_excalidraw":
                qs = urllib.parse.parse_qs(parsed.query)
                idx = int(qs.get("idx", ["0"])[0])
                dst = Path(jobs[idx]["dst"])
                self._send(200, dst.read_bytes(), "application/json; charset=utf-8")
            elif parsed.path.startswith("/npm/"):
                try:
                    full_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
                    key = hashlib.sha256(full_path.encode("utf-8")).hexdigest()[:32]
                    if (cache_dir / f"{key}.bin").exists():
                        state["cache_hits"] += 1
                    else:
                        state["cache_misses"] += 1
                    data, ctype = _cache_fetch_npm(cache_dir, full_path)
                    self._send(200, data, ctype)
                except Exception as exc:
                    self._send(502, f"Cache proxy error: {exc}".encode("utf-8"))
            else:
                self._send(404, b"Not Found")

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            if parsed.path == "/result":
                qs = urllib.parse.parse_qs(parsed.query)
                idx = int(qs.get("idx", ["0"])[0])
                dst = Path(jobs[idx]["dst"])
                dst.parent.mkdir(parents=True, exist_ok=True)
                doc = json.loads(raw.decode("utf-8"))
                dst.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
                deconflict_res = _ed.process_file(dst, dst)
                state["results"][idx].update({
                    "input": str(jobs[idx]["src"]),
                    "output": str(dst),
                    "elements": len(doc.get("elements", [])),
                    "bytes": dst.stat().st_size,
                    "deconflict_audit": deconflict_res.get("after"),
                })
                self._send(200, b"OK")
            elif parsed.path == "/png":
                qs = urllib.parse.parse_qs(parsed.query)
                idx = int(qs.get("idx", ["0"])[0])
                tile = qs.get("tile", ["closeup"])[0]
                out_dir = render_dir or Path(jobs[idx]["dst"]).parent
                png_path = out_dir / f"{jobs[idx]['name']}_{tile}.png"
                png_path.write_bytes(raw)
                state["results"][idx].setdefault("previews", []).append(str(png_path))
                self._send(200, b"OK")
            elif parsed.path == "/log":
                print(f"[cartograph-official] {raw.decode('utf-8', errors='replace')}", file=sys.stderr, flush=True)
                self._send(200, b"OK")
            elif parsed.path == "/error":
                state["error"] = raw.decode("utf-8", errors="replace")
                state["done"].set()
                self._send(200, b"OK")
            elif parsed.path == "/done":
                state["done"].set()
                self._send(200, b"OK")
            else:
                self._send(404, b"Not Found")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    profile_dir = tempfile.mkdtemp(prefix="cartograph_chrome_")
    proc: subprocess.Popen[bytes] | None = None
    try:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            f"http://127.0.0.1:{port}/",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finished = state["done"].wait(timeout=timeout_sec)
        if not finished:
            raise TimeoutError(f"Timed out after {timeout_sec}s waiting for official Excalidraw pipeline.")
        if state["error"]:
            raise RuntimeError(f"Official Excalidraw pipeline failed: {state['error']}")
        return state["results"]
    finally:
        server.shutdown()
        server.server_close()
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cartograph Official Excalidraw Exporter & PNG Visual Verifier")
    parser.add_argument("inputs", nargs="+", help="One or more .mmd files (or .excalidraw files with --render-only)")
    parser.add_argument("-o", "--output", default=None, help="Output .excalidraw path (single input only)")
    parser.add_argument("--out-dir", default=None, help="Output directory for batch exports")
    parser.add_argument("--render-dir", default=None, help="Render close-up verification PNGs into this directory")
    parser.add_argument("--render-only", action="store_true", help="Only render verification PNGs for existing .excalidraw inputs")
    parser.add_argument("--focus", default="", help="Optional text substring to center the close-up PNG tile on")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds (default 120)")
    parser.add_argument("--browser", default=None, help="Explicit Chrome/Edge/Chromium executable path")
    ns = parser.parse_args()

    if ns.output and len(ns.inputs) != 1:
        parser.error("-o/--output can only be used with a single input file.")

    jobs: list[dict[str, Any]] = []
    for raw_in in ns.inputs:
        src = Path(raw_in).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Input file not found: {src}")
        if ns.render_only:
            dst = src
        elif ns.output:
            dst = Path(ns.output).resolve()
        elif ns.out_dir:
            dst = Path(ns.out_dir).resolve() / f"{src.stem}.excalidraw"
        else:
            dst = src.with_suffix(".excalidraw")
        jobs.append({"src": str(src), "dst": str(dst), "name": src.stem, "focus": ns.focus})

    mode = "render" if ns.render_only else ("export_and_render" if ns.render_dir else "export")
    render_dir = Path(ns.render_dir).resolve() if ns.render_dir else None
    results = run_pipeline(jobs, mode=mode, render_dir=render_dir, timeout_sec=ns.timeout, browser_bin=ns.browser)
    print(json.dumps({"engine": "official:@excalidraw/mermaid-to-excalidraw@3.6.0", "mode": mode, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
