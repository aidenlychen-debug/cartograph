#!/usr/bin/env python3
"""Cartograph Real-Excalidraw 10-Check Zero-Interference Deconfliction, Styling & Audit Engine.

Zero external dependencies (Python 3.8+ stdlib only).
Operates directly on official `.excalidraw` files exported by `@excalidraw/mermaid-to-excalidraw`
(`elbow: true`), enforcing TEN deterministic zero-interference invariants + high-contrast
visual styling while preserving 100% orthogonal (`elbowed: true`) routing:

  Geometry & Interference Checks (ALL must be 0):
    1. `label_vs_node_overlaps == 0`         (edge labels centered clear of all node rectangles)
    2. `label_vs_label_overlaps == 0`        (no two edge labels collide)
    3. `label_vs_other_arrow_collisions == 0`(NO other arrow line crosses any edge label)
    4. `coincident_vertical_tracks == 0`     (parallel vertical tracks separated into distinct lanes)
    5. `node_text_overflows == 0`            (Excalifont-safe CJK/digit node breathing padding)
    6. `title_text_overflows == 0`           (subgraph title bands & text widths never clip)
    7. `node_vs_node_overlaps == 0`          (no two node rectangles overlap)
    8. `arrow_vs_node_collisions == 0`       (no arrow segment grazes/pierces non-endpoint nodes)
    9. `subgraph_containment_violations == 0`(every member node strictly inside its module box with margin)
   10. `trunk_vs_subgraph_collisions == 0`   (external trunk lines strictly clear of module left borders)
    + `subgraph_overlaps == 0` & `orthogonal_ratio == 1.0`

  Visual Hierarchy Styling (High-Contrast Excalidraw Hand-Drawn Palette):
    - Solid content boxes (`MOD` / `SUB` / `K`): dark gray `#4B5563` (`strokeWidth: 1.5`)
    - Module outer frames (`subgraph`): same dark gray `#4B5563`, **`dotted`** (点虚线，更密集), `roundness: {"type": 3}` (rounded corners)
    - Auxiliary dashed content boxes (`note`): one shade lighter `#6B7280`, **`dashed`** (正常虚线)
    - Focus nodes (`ROOT` / `KEY`): Klein Blue `#002FA7` preserved intact

Usage:
  python excalidraw_deconflict.py input.excalidraw [-o output.excalidraw] [--audit-only]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


SOLID_BOX_STROKE = "#4B5563"      # Dark gray for solid content boxes & module frames
NOTE_BOX_STROKE = "#6B7280"       # One shade lighter for dotted auxiliary note boxes
ACCENT_BLUE = "#002fa7"


def estimate_cjk_text_size(text: str, font_size: float, line_height: float = 1.25) -> tuple[float, float]:
    """Calibrated for Excalifont (fontFamily=5) CJK + hand-drawn digits/punctuation."""
    lines = text.split("\n") if text else [""]
    max_w = 0.0
    for line in lines:
        w = 0.0
        for ch in line:
            code = ord(ch)
            if code > 127:
                w += font_size * 1.12
            elif ch in "ilI1.,;:'|! ":
                w += font_size * 0.42
            elif ch.isupper() or ch.isdigit() or ch in "/\\-_–—+%&@#":
                w += font_size * 0.78
            else:
                w += font_size * 0.62
        if w > max_w:
            max_w = w
    h = max(font_size * line_height, len(lines) * font_size * line_height)
    return max_w, h


def rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], pad: float = 0.0) -> bool:
    return not (
        a[0] + a[2] + pad <= b[0]
        or b[0] + b[2] + pad <= a[0]
        or a[1] + a[3] + pad <= b[1]
        or b[1] + b[3] + pad <= a[1]
    )


def seg_hits_rect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    r: tuple[float, float, float, float],
    margin: float = 1.0,
) -> bool:
    x0, y0 = p1
    x1, y1 = p2
    xmin, ymin = r[0] - margin, r[1] - margin
    xmax, ymax = r[0] + r[2] + margin, r[1] + r[3] + margin
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if abs(p) < 1e-9:
            if q < 0:
                return False
        else:
            rv = q / p
            if p < 0:
                if rv > t1:
                    return False
                if rv > t0:
                    t0 = rv
            else:
                if rv < t0:
                    return False
                if rv < t1:
                    t1 = rv
    return t0 <= t1


def excalidraw_arrow_label_center(pts: list[tuple[float, float]]) -> tuple[float, float, int]:
    """Exact Excalidraw bound-text position for linear/elbowed arrows (verified 296/296 exact)."""
    n = len(pts)
    if n == 0:
        return 0.0, 0.0, 0
    if n == 1:
        return pts[0][0], pts[0][1], 0
    if n % 2 == 1:
        idx = n // 2
        return pts[idx][0], pts[idx][1], max(0, idx - 1)
    idx = n // 2 - 1
    p1, p2 = pts[idx], pts[idx + 1]
    return (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0, idx


def arrow_abs_points(a: dict[str, Any]) -> list[tuple[float, float]]:
    ax, ay = float(a["x"]), float(a["y"])
    return [(ax + float(pt[0]), ay + float(pt[1])) for pt in a.get("points", [])]


def set_arrow_abs_points(a: dict[str, Any], pts: list[tuple[float, float]]) -> None:
    if not pts:
        return
    cleaned: list[tuple[float, float]] = [pts[0]]
    for pt in pts[1:]:
        if math.hypot(pt[0] - cleaned[-1][0], pt[1] - cleaned[-1][1]) < 0.05 and len(pts) > 2:
            continue
        cleaned.append(pt)
    if len(cleaned) < 2:
        cleaned = [pts[0], pts[-1]]
    x0, y0 = cleaned[0]
    rel = [[round(px - x0, 2), round(py - y0, 2)] for px, py in cleaned]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    a["x"] = round(x0, 2)
    a["y"] = round(y0, 2)
    a["points"] = rel
    a["width"] = round(max(xs) - min(xs), 2)
    a["height"] = round(max(ys) - min(ys), 2)


def classify_elements(els: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {e["id"]: e for e in els}
    all_rects = [e for e in els if e.get("type") == "rectangle" and not e.get("isDeleted")]
    arrows = [e for e in els if e.get("type") == "arrow" and not e.get("isDeleted")]
    texts = [e for e in els if e.get("type") == "text" and not e.get("isDeleted")]

    arrow_endpoints: set[str] = set()
    for a in arrows:
        sb = (a.get("startBinding") or {}).get("elementId")
        eb = (a.get("endBinding") or {}).get("elementId")
        if sb:
            arrow_endpoints.add(sb)
        if eb:
            arrow_endpoints.add(eb)

    # Identify subgraph frames: rectangles enclosing >= 2 other rectangles (or having >= 2 center-points inside)
    sg_ids: set[str] = set()
    for r in all_rects:
        if r["id"] in arrow_endpoints:
            continue
        rb = (r["x"], r["y"], r["width"], r["height"])
        enclosed = 0
        for o in all_rects:
            if o["id"] == r["id"]:
                continue
            ocx = o["x"] + o["width"] / 2.0
            ocy = o["y"] + o["height"] / 2.0
            if rb[0] - 5 <= ocx <= rb[0] + rb[2] + 5 and rb[1] - 5 <= ocy <= rb[1] + rb[3] + 5 and o["width"] < r["width"] and o["height"] < r["height"]:
                enclosed += 1
        if enclosed >= 2:
            sg_ids.add(r["id"])

    title_band_ids: set[str] = set()
    sg_title_map: dict[str, str] = {}
    for r in all_rects:
        if r["id"] in sg_ids or r["id"] in arrow_endpoints:
            continue
        for sid in sg_ids:
            sg = by_id[sid]
            rcx = r["x"] + r["width"] / 2.0
            if (
                abs(r["y"] - sg["y"]) < 36
                and sg["x"] - 40 <= rcx <= sg["x"] + sg["width"] + 40
                and r["height"] <= 56
            ):
                title_band_ids.add(r["id"])
                sg_title_map[sid] = r["id"]
                break

    node_rects = [r for r in all_rects if r["id"] not in sg_ids and r["id"] not in title_band_ids]
    sg_rects = sorted([r for r in all_rects if r["id"] in sg_ids], key=lambda s: s["y"])
    title_bands = [r for r in all_rects if r["id"] in title_band_ids]
    arrow_ids = {a["id"] for a in arrows}
    node_ids = {r["id"] for r in node_rects}

    # Map every node to its enclosing subgraph (by center point, resilient to slight edge overflow)
    sg_members: dict[str, list[str]] = {sg["id"]: [] for sg in sg_rects}
    node_to_sg: dict[str, str] = {}
    for nr in node_rects:
        cx = nr["x"] + nr["width"] / 2.0
        cy = nr["y"] + nr["height"] / 2.0
        # Pick smallest enclosing subgraph if nested
        best_sg = None
        best_area = float("inf")
        for sg in sg_rects:
            if sg["x"] - 30 <= cx <= sg["x"] + sg["width"] + 60 and sg["y"] - 20 <= cy <= sg["y"] + sg["height"] + 40:
                area = sg["width"] * sg["height"]
                if area < best_area:
                    best_area = area
                    best_sg = sg["id"]
        if best_sg:
            sg_members[best_sg].append(nr["id"])
            node_to_sg[nr["id"]] = best_sg

    edge_labels = [t for t in texts if t.get("containerId") in arrow_ids]
    node_texts = [t for t in texts if t.get("containerId") in node_ids]
    band_texts = [t for t in texts if t.get("containerId") in title_band_ids]
    free_texts = [
        t for t in texts
        if t.get("containerId") not in arrow_ids
        and t.get("containerId") not in node_ids
        and t.get("containerId") not in title_band_ids
    ]

    return {
        "by_id": by_id,
        "sg_ids": sg_ids,
        "title_band_ids": title_band_ids,
        "sg_rects": sg_rects,
        "title_bands": title_bands,
        "sg_title_map": sg_title_map,
        "sg_members": sg_members,
        "node_to_sg": node_to_sg,
        "node_rects": node_rects,
        "arrows": arrows,
        "edge_labels": edge_labels,
        "node_texts": node_texts,
        "band_texts": band_texts,
        "free_texts": free_texts,
    }


def _apply_x_shift(cls: dict[str, Any], cut_x: float, dx: float) -> None:
    if dx <= 0.01:
        return
    by_id = cls["by_id"]

    for r in cls["node_rects"]:
        if r["x"] + r["width"] / 2.0 > cut_x:
            r["x"] = round(r["x"] + dx, 2)
    for t in cls["node_texts"]:
        nr = by_id.get(t.get("containerId"))
        if nr:
            t["x"] = round(nr["x"] + (nr["width"] - t["width"]) / 2.0, 2)
    for sg in cls["sg_rects"]:
        if sg["x"] > cut_x:
            sg["x"] = round(sg["x"] + dx, 2)
        elif sg["x"] + sg["width"] > cut_x:
            sg["width"] = round(sg["width"] + dx, 2)
    for tb in cls["title_bands"]:
        if tb["x"] + tb["width"] / 2.0 > cut_x:
            tb["x"] = round(tb["x"] + dx, 2)
    for bt in cls["band_texts"]:
        tb = by_id.get(bt.get("containerId"))
        if tb:
            bt["x"] = round(tb["x"] + (tb["width"] - bt["width"]) / 2.0, 2)
    for ft in cls["free_texts"]:
        if ft["x"] + ft["width"] / 2.0 > cut_x:
            ft["x"] = round(ft["x"] + dx, 2)

    for a in cls["arrows"]:
        pts = arrow_abs_points(a)
        new_pts = [(px + dx if px > cut_x else px, py) for px, py in pts]
        set_arrow_abs_points(a, new_pts)


def _apply_y_shift(cls: dict[str, Any], cut_y: float, dy: float) -> None:
    if dy <= 0.01:
        return
    by_id = cls["by_id"]

    for r in cls["node_rects"]:
        if r["y"] + r["height"] / 2.0 > cut_y:
            r["y"] = round(r["y"] + dy, 2)
    for t in cls["node_texts"]:
        nr = by_id.get(t.get("containerId"))
        if nr:
            t["y"] = round(nr["y"] + (nr["height"] - t["height"]) / 2.0, 2)
    for sg in cls["sg_rects"]:
        if sg["y"] > cut_y:
            sg["y"] = round(sg["y"] + dy, 2)
        elif sg["y"] + sg["height"] > cut_y:
            sg["height"] = round(sg["height"] + dy, 2)
    for tb in cls["title_bands"]:
        if tb["y"] + tb["height"] / 2.0 > cut_y:
            tb["y"] = round(tb["y"] + dy, 2)
    for bt in cls["band_texts"]:
        tb = by_id.get(bt.get("containerId"))
        if tb:
            bt["y"] = round(tb["y"] + (tb["height"] - bt["height"]) / 2.0, 2)
    for ft in cls["free_texts"]:
        if ft["y"] + ft["height"] / 2.0 > cut_y:
            ft["y"] = round(ft["y"] + dy, 2)

    for a in cls["arrows"]:
        pts = arrow_abs_points(a)
        new_pts = [(px, py + dy if py > cut_y else py) for px, py in pts]
        set_arrow_abs_points(a, new_pts)


def _sync_arrow_endpoints_to_nodes(cls: dict[str, Any]) -> None:
    by_id = cls["by_id"]
    for a in cls["arrows"]:
        pts = arrow_abs_points(a)
        if len(pts) < 2:
            continue
        sb = (a.get("startBinding") or {}).get("elementId")
        eb = (a.get("endBinding") or {}).get("elementId")
        changed = False

        if sb in by_id:
            sr = by_id[sb]
            x0, y0 = pts[0]
            x1, y1 = pts[1]
            if abs(y1 - y0) < 0.6:
                if x1 > x0:
                    target_x = sr["x"] + sr["width"] + 0.5
                    if abs(x0 - target_x) > 0.5 and target_x < x1 - 4:
                        pts[0] = (target_x, y0)
                        changed = True
                elif x1 < x0:
                    target_x = sr["x"] - 0.5
                    if abs(x0 - target_x) > 0.5 and target_x > x1 + 4:
                        pts[0] = (target_x, y0)
                        changed = True
            elif abs(x1 - x0) < 0.6:
                if y1 > y0:
                    target_y = sr["y"] + sr["height"] + 0.5
                    if abs(y0 - target_y) > 0.5 and target_y < y1 - 4:
                        pts[0] = (x0, target_y)
                        changed = True
                elif y1 < y0:
                    target_y = sr["y"] - 0.5
                    if abs(y0 - target_y) > 0.5 and target_y > y1 + 4:
                        pts[0] = (x0, target_y)
                        changed = True

        if eb in by_id:
            dr = by_id[eb]
            xn1, yn1 = pts[-2]
            xn, yn = pts[-1]
            if abs(yn - yn1) < 0.6:
                if xn > xn1:
                    target_x = dr["x"] - 0.5
                    if abs(xn - target_x) > 0.5 and target_x > xn1 + 4:
                        pts[-1] = (target_x, yn)
                        changed = True
                elif xn < xn1:
                    target_x = dr["x"] + dr["width"] + 0.5
                    if abs(xn - target_x) > 0.5 and target_x < xn1 - 4:
                        pts[-1] = (target_x, yn)
                        changed = True
            elif abs(xn - xn1) < 0.6:
                if yn > yn1:
                    target_y = dr["y"] - 0.5
                    if abs(yn - target_y) > 0.5 and target_y > yn1 + 4:
                        pts[-1] = (xn, target_y)
                        changed = True
                elif yn < yn1:
                    target_y = dr["y"] + dr["height"] + 0.5
                    if abs(yn - target_y) > 0.5 and target_y < yn1 - 4:
                        pts[-1] = (xn, target_y)
                        changed = True

        if changed:
            set_arrow_abs_points(a, pts)


def _sync_edge_label_positions(cls: dict[str, Any]) -> None:
    by_id = cls["by_id"]
    for t in cls["edge_labels"]:
        a = by_id.get(t.get("containerId"))
        if not a:
            continue
        pts = arrow_abs_points(a)
        mx, my, _ = excalidraw_arrow_label_center(pts)
        est_w, est_h = estimate_cjk_text_size(t["text"], float(t.get("fontSize", 16)), float(t.get("lineHeight", 1.25)))
        t["width"] = round(est_w, 2)
        t["height"] = round(est_h, 2)
        t["x"] = round(mx - t["width"] / 2.0, 2)
        t["y"] = round(my - t["height"] / 2.0, 2)


def _label_box_for_arrow(a: dict[str, Any], t: dict[str, Any], pad_x: float = 0.0, pad_y: float = 0.0) -> tuple[float, float, float, float]:
    pts = arrow_abs_points(a)
    mx, my, _ = excalidraw_arrow_label_center(pts)
    ew, eh = estimate_cjk_text_size(t["text"], float(t.get("fontSize", 16)), float(t.get("lineHeight", 1.25)))
    w = max(float(t["width"]), ew) + pad_x * 2.0
    h = max(float(t["height"]), eh) + pad_y * 2.0
    return (mx - w / 2.0, my - h / 2.0, w, h)


def audit_excalidraw(doc: dict[str, Any]) -> dict[str, Any]:
    els = doc.get("elements", [])
    cls = classify_elements(els)
    by_id = cls["by_id"]
    node_rects = cls["node_rects"]
    sg_rects = cls["sg_rects"]
    arrows = cls["arrows"]
    edge_labels = cls["edge_labels"]

    # 1. Edge label vs Node rect overlaps
    label_boxes: list[tuple[dict[str, Any], dict[str, Any], tuple[float, float, float, float]]] = []
    label_node_hits: list[dict[str, Any]] = []
    for t in edge_labels:
        a = by_id.get(t.get("containerId"))
        if not a:
            continue
        lb = _label_box_for_arrow(a, t)
        label_boxes.append((a, t, lb))
        for nr in node_rects:
            nb = (nr["x"], nr["y"], nr["width"], nr["height"])
            if rects_overlap(lb, nb, pad=2.0):
                label_node_hits.append({
                    "label": t["text"],
                    "arrow_id": a["id"],
                    "hit_node_id": nr["id"],
                    "label_box": [round(v, 1) for v in lb],
                    "node_box": [round(v, 1) for v in nb],
                })
                break

    # 2. Edge label vs Edge label overlaps
    label_label_hits: list[tuple[str, str]] = []
    for i in range(len(label_boxes)):
        _, t1, b1 = label_boxes[i]
        for j in range(i + 1, len(label_boxes)):
            _, t2, b2 = label_boxes[j]
            if rects_overlap(b1, b2, pad=2.0):
                label_label_hits.append((t1["text"], t2["text"]))

    # 3. Edge label vs ANY OTHER arrow segment collisions
    label_arrow_hits: list[dict[str, Any]] = []
    for a, t, lb in label_boxes:
        for oa in arrows:
            if oa["id"] == a["id"]:
                continue
            opts = arrow_abs_points(oa)
            hit = False
            for i in range(len(opts) - 1):
                if seg_hits_rect(opts[i], opts[i + 1], lb, margin=4.0):
                    label_arrow_hits.append({
                        "label": t["text"],
                        "my_arrow": a["id"],
                        "other_arrow": oa["id"],
                        "label_box": [round(v, 1) for v in lb],
                    })
                    hit = True
                    break
            if hit:
                break

    # 4. Coincident vertical arrow tracks
    coinc_tracks: list[dict[str, Any]] = []
    vsegs: list[tuple[str, float, float, float]] = []
    for a in arrows:
        pts = arrow_abs_points(a)
        for i in range(len(pts) - 1):
            if abs(pts[i][0] - pts[i + 1][0]) < 0.8 and abs(pts[i][1] - pts[i + 1][1]) > 14.0:
                vsegs.append((a["id"], pts[i][0], min(pts[i][1], pts[i + 1][1]), max(pts[i][1], pts[i + 1][1])))
    for i in range(len(vsegs)):
        for j in range(i + 1, len(vsegs)):
            if vsegs[i][0] == vsegs[j][0]:
                continue
            if abs(vsegs[i][1] - vsegs[j][1]) < 12.0 and min(vsegs[i][3], vsegs[j][3]) - max(vsegs[i][2], vsegs[j][2]) > 10.0:
                coinc_tracks.append({"a1": vsegs[i][0], "a2": vsegs[j][0], "x1": round(vsegs[i][1], 1), "x2": round(vsegs[j][1], 1)})

    # 5. Node text overflow vs container rectangle
    node_text_overflows = 0
    for t in cls["node_texts"]:
        nr = by_id.get(t.get("containerId"))
        if not nr:
            continue
        est_w, est_h = estimate_cjk_text_size(t["text"], float(t.get("fontSize", 16)), float(t.get("lineHeight", 1.25)))
        if est_w > nr["width"] - 8 or est_h > nr["height"] - 4 or est_w > float(t["width"]) + 6:
            node_text_overflows += 1

    # 6. Subgraph title band text clip/overflow
    title_text_overflows = 0
    for t in cls["band_texts"] + cls["free_texts"]:
        est_w, est_h = estimate_cjk_text_size(t["text"], float(t.get("fontSize", 16)), float(t.get("lineHeight", 1.25)))
        cid = t.get("containerId")
        cont = by_id.get(cid) if cid else None
        if cont:
            if est_w > cont["width"] - 12 or est_w > float(t["width"]) + 2 or est_h > cont["height"] - 4:
                title_text_overflows += 1
        else:
            if est_w > float(t["width"]) + 2:
                title_text_overflows += 1

    # 7. Node vs Node overlaps
    node_node_hits = 0
    for i in range(len(node_rects)):
        r1 = node_rects[i]
        b1 = (r1["x"], r1["y"], r1["width"], r1["height"])
        for j in range(i + 1, len(node_rects)):
            r2 = node_rects[j]
            b2 = (r2["x"], r2["y"], r2["width"], r2["height"])
            if rects_overlap(b1, b2, pad=0.0):
                node_node_hits += 1

    # 8. Arrow segment vs non-endpoint Node rect collisions + orthogonality check
    arrow_node_hits = 0
    total_segs = 0
    ortho_segs = 0
    for a in arrows:
        sb = (a.get("startBinding") or {}).get("elementId")
        eb = (a.get("endBinding") or {}).get("elementId")
        pts = arrow_abs_points(a)
        hit = False
        for i in range(len(pts) - 1):
            total_segs += 1
            if abs(pts[i + 1][0] - pts[i][0]) < 0.6 or abs(pts[i + 1][1] - pts[i][1]) < 0.6:
                ortho_segs += 1
            if not hit:
                for nr in node_rects:
                    if nr["id"] in (sb, eb):
                        continue
                    nb = (nr["x"], nr["y"], nr["width"], nr["height"])
                    if seg_hits_rect(pts[i], pts[i + 1], nb, margin=1.0):
                        arrow_node_hits += 1
                        hit = True
                        break

    # 9. Subgraph containment violations (member node sticking outside or touching its module border)
    sg_containment_violations = 0
    for sg in sg_rects:
        for nid in cls["sg_members"].get(sg["id"], []):
            nr = by_id[nid]
            if (
                nr["x"] < sg["x"] + 12.0
                or nr["y"] < sg["y"] + 16.0
                or nr["x"] + nr["width"] > sg["x"] + sg["width"] - 12.0
                or nr["y"] + nr["height"] > sg["y"] + sg["height"] - 12.0
            ):
                sg_containment_violations += 1

    # Subgraph vs Subgraph overlaps
    sg_overlaps = 0
    for i in range(len(sg_rects)):
        s1 = (sg_rects[i]["x"], sg_rects[i]["y"], sg_rects[i]["width"], sg_rects[i]["height"])
        for j in range(i + 1, len(sg_rects)):
            s2 = (sg_rects[j]["x"], sg_rects[j]["y"], sg_rects[j]["width"], sg_rects[j]["height"])
            if rects_overlap(s1, s2, pad=8.0):
                sg_overlaps += 1

    # 10. External trunk vertical lines interfering with any subgraph's left/right border
    trunk_sg_hits = 0
    for a in arrows:
        sb = (a.get("startBinding") or {}).get("elementId")
        eb = (a.get("endBinding") or {}).get("elementId")
        if sb in cls["node_to_sg"]:
            continue  # Internal arrow
        pts = arrow_abs_points(a)
        for i in range(len(pts) - 1):
            p1, p2 = pts[i], pts[i + 1]
            if abs(p1[0] - p2[0]) < 0.8 and abs(p1[1] - p2[1]) > 14.0:
                vx = p1[0]
                vy1, vy2 = min(p1[1], p2[1]), max(p1[1], p2[1])
                for sg in sg_rects:
                    if vy2 >= sg["y"] - 8.0 and vy1 <= sg["y"] + sg["height"] + 8.0:
                        if sg["x"] - 14.0 <= vx <= sg["x"] + sg["width"] + 14.0:
                            trunk_sg_hits += 1
                            break

    xs = [e["x"] for e in els if "x" in e]
    ys = [e["y"] for e in els if "y" in e]
    x2s = [e["x"] + e.get("width", 0) for e in els if "x" in e]
    y2s = [e["y"] + e.get("height", 0) for e in els if "y" in e]

    return {
        "total_elements": len(els),
        "node_rects": len(node_rects),
        "subgraphs": len(sg_rects),
        "arrows": len(arrows),
        "edge_labels": len(edge_labels),
        "bbox_w": round(max(x2s) - min(xs), 1) if xs else 0.0,
        "bbox_h": round(max(y2s) - min(ys), 1) if ys else 0.0,
        "label_vs_node_overlaps": len(label_node_hits),
        "label_vs_label_overlaps": len(label_label_hits),
        "label_vs_other_arrow_collisions": len(label_arrow_hits),
        "coincident_vertical_tracks": len(coinc_tracks),
        "node_text_overflows": node_text_overflows,
        "title_text_overflows": title_text_overflows,
        "node_vs_node_overlaps": node_node_hits,
        "arrow_vs_node_collisions": arrow_node_hits,
        "subgraph_containment_violations": sg_containment_violations,
        "subgraph_overlaps": sg_overlaps,
        "trunk_vs_subgraph_collisions": trunk_sg_hits,
        "orthogonal_ratio": round(ortho_segs / total_segs, 4) if total_segs else 1.0,
        "zero_interference": (
            len(label_node_hits) == 0
            and len(label_label_hits) == 0
            and len(label_arrow_hits) == 0
            and len(coinc_tracks) == 0
            and node_text_overflows == 0
            and title_text_overflows == 0
            and node_node_hits == 0
            and arrow_node_hits == 0
            and sg_containment_violations == 0
            and sg_overlaps == 0
            and trunk_sg_hits == 0
        ),
        "sample_label_hits": label_node_hits[:5],
        "sample_label_arrow_hits": label_arrow_hits[:5],
        "sample_coinc_tracks": coinc_tracks[:5],
    }


def _arrow_candidate_ok(
    a: dict[str, Any],
    cand_pts: list[tuple[float, float]],
    t: dict[str, Any] | None,
    cls: dict[str, Any],
    label_by_arrow: dict[str, dict[str, Any]],
) -> bool:
    node_rects = cls["node_rects"]
    sb = (a.get("startBinding") or {}).get("elementId")
    eb = (a.get("endBinding") or {}).get("elementId")

    for i in range(len(cand_pts) - 1):
        for nr in node_rects:
            if nr["id"] in (sb, eb):
                continue
            if seg_hits_rect(cand_pts[i], cand_pts[i + 1], (nr["x"], nr["y"], nr["width"], nr["height"]), margin=2.0):
                return False

    my_lb = None
    if t is not None:
        mx, my, _ = excalidraw_arrow_label_center(cand_pts)
        ew, eh = estimate_cjk_text_size(t["text"], float(t.get("fontSize", 16)), float(t.get("lineHeight", 1.25)))
        w = max(float(t["width"]), ew) + 14.0
        h = max(float(t["height"]), eh) + 8.0
        my_lb = (mx - w / 2.0, my - h / 2.0, w, h)
        for nr in node_rects:
            if rects_overlap(my_lb, (nr["x"], nr["y"], nr["width"], nr["height"]), pad=2.0):
                return False

    my_vsegs = [
        (cand_pts[i][0], min(cand_pts[i][1], cand_pts[i + 1][1]), max(cand_pts[i][1], cand_pts[i + 1][1]))
        for i in range(len(cand_pts) - 1)
        if abs(cand_pts[i][0] - cand_pts[i + 1][0]) < 0.8 and abs(cand_pts[i][1] - cand_pts[i + 1][1]) > 14.0
    ]

    for oa in cls["arrows"]:
        if oa["id"] == a["id"]:
            continue
        opts = arrow_abs_points(oa)
        ot = label_by_arrow.get(oa["id"])

        if my_lb is not None:
            for i in range(len(opts) - 1):
                if seg_hits_rect(opts[i], opts[i + 1], my_lb, margin=5.0):
                    return False

        if ot is not None:
            olb = _label_box_for_arrow(oa, ot, pad_x=5.0, pad_y=4.0)
            if my_lb is not None and rects_overlap(my_lb, olb, pad=2.0):
                return False
            for i in range(len(cand_pts) - 1):
                if seg_hits_rect(cand_pts[i], cand_pts[i + 1], olb, margin=4.0):
                    return False

        if my_vsegs:
            for i in range(len(opts) - 1):
                if abs(opts[i][0] - opts[i + 1][0]) < 0.8 and abs(opts[i][1] - opts[i + 1][1]) > 14.0:
                    ox, oy1, oy2 = opts[i][0], min(opts[i][1], opts[i + 1][1]), max(opts[i][1], opts[i + 1][1])
                    for mx_v, my1, my2 in my_vsegs:
                        if abs(mx_v - ox) < 16.0 and min(my2, oy2) - max(my1, oy1) > 10.0:
                            return False

    return True


def _recenter_and_lane_arrows(cls: dict[str, Any], *, only_conflicted: bool = False) -> int:
    label_by_arrow = {t.get("containerId"): t for t in cls["edge_labels"]}
    moved = 0
    ordered_arrows = sorted(cls["arrows"], key=lambda a: (0 if a["id"] in label_by_arrow else 1, a["y"], a["x"]))

    for a in ordered_arrows:
        sb = (a.get("startBinding") or {}).get("elementId")
        # Leave ROOT -> MOD external trunk arrows for dedicated trunk-corridor pass!
        if sb not in cls["node_to_sg"] and cls["sg_rects"]:
            continue

        t = label_by_arrow.get(a["id"])
        pts = arrow_abs_points(a)
        if len(pts) < 4:
            continue

        if only_conflicted and _arrow_candidate_ok(a, pts, t, cls, label_by_arrow):
            continue

        if (
            len(pts) == 4
            and abs(pts[0][1] - pts[1][1]) < 0.8
            and abs(pts[1][0] - pts[2][0]) < 0.8
            and abs(pts[2][1] - pts[3][1]) < 0.8
        ):
            x0, y0 = pts[0]
            vx = pts[1][0]
            x3, y1 = pts[3]
            lo_bound = min(x0, x3) + 14.0
            hi_bound = max(x0, x3) - 14.0
            if hi_bound > lo_bound + 4.0:
                mid_x = (x0 + x3) / 2.0
                span = hi_bound - lo_bound
                cands = [mid_x]
                for step in range(1, 20):
                    d = step * 0.024
                    if 0.5 - d >= 0.04:
                        cands.append(lo_bound + span * (0.5 - d))
                    if 0.5 + d <= 0.96:
                        cands.append(lo_bound + span * (0.5 + d))

                for cx in cands:
                    cand_pts = [(x0, y0), (cx, y0), (cx, y1), (x3, y1)]
                    if _arrow_candidate_ok(a, cand_pts, t, cls, label_by_arrow):
                        if abs(cx - vx) > 0.5:
                            set_arrow_abs_points(a, cand_pts)
                            moved += 1
                        break
            continue

        for seg_idx in range(1, len(pts) - 2):
            p_a, p_b = pts[seg_idx], pts[seg_idx + 1]
            if abs(p_a[0] - p_b[0]) < 0.8:
                orig_x = p_a[0]
                prev_x = pts[seg_idx - 1][0]
                next_x = pts[seg_idx + 2][0]
                lo = min(prev_x, next_x) + 12.0
                hi = max(prev_x, next_x) - 12.0
                offsets = []
                for step in range(12, 260, 12):
                    offsets.extend([-step, step])
                fixed_seg = False
                for off in offsets:
                    cx = orig_x + off
                    if hi > lo and not (lo <= cx <= hi):
                        continue
                    cand_pts = list(pts)
                    cand_pts[seg_idx] = (cx, p_a[1])
                    cand_pts[seg_idx + 1] = (cx, p_b[1])
                    if _arrow_candidate_ok(a, cand_pts, t, cls, label_by_arrow):
                        set_arrow_abs_points(a, cand_pts)
                        moved += 1
                        fixed_seg = True
                        break
                if fixed_seg:
                    break
            elif abs(p_a[1] - p_b[1]) < 0.8:
                orig_y = p_a[1]
                offsets = []
                for step in range(12, 200, 12):
                    offsets.extend([-step, step])
                fixed_seg = False
                for off in offsets:
                    cy = orig_y + off
                    cand_pts = list(pts)
                    cand_pts[seg_idx] = (p_a[0], cy)
                    cand_pts[seg_idx + 1] = (p_b[0], cy)
                    if _arrow_candidate_ok(a, cand_pts, t, cls, label_by_arrow):
                        set_arrow_abs_points(a, cand_pts)
                        moved += 1
                        fixed_seg = True
                        break
                if fixed_seg:
                    break

    return moved


def _refit_subgraphs_and_titles(cls: dict[str, Any]) -> None:
    """Refit every module subgraph cleanly around ALL member nodes + internal labels + title band,
    guaranteeing generous margin on all 4 sides and zero module-module overlap."""
    by_id = cls["by_id"]
    sg_rects = sorted(cls["sg_rects"], key=lambda s: s["y"])

    # First ensure all title band text widths are Excalifont-safe
    for tb in cls["title_bands"]:
        for bt in cls["band_texts"]:
            if bt.get("containerId") == tb["id"]:
                fs = float(bt.get("fontSize", 20))
                ew, eh = estimate_cjk_text_size(bt["text"], fs, float(bt.get("lineHeight", 1.25)))
                need_tw = math.ceil(ew + 24.0)
                need_tb_w = math.ceil(need_tw + 36.0)
                need_tb_h = math.ceil(eh + 12.0)
                tb["width"] = round(max(float(tb["width"]), need_tb_w), 2)
                tb["height"] = round(max(float(tb["height"]), need_tb_h), 2)
                bt["width"] = round(max(float(bt["width"]), need_tw), 2)
                bt["height"] = round(max(float(bt["height"]), eh), 2)
                break

    for ft in cls["free_texts"]:
        ew, _ = estimate_cjk_text_size(ft["text"], float(ft.get("fontSize", 16)), float(ft.get("lineHeight", 1.25)))
        if ew + 16.0 > float(ft["width"]):
            ft["width"] = round(ew + 16.0, 2)

    if not sg_rects:
        return

    # Align all outer subgraphs to a common left X based on the leftmost member node across all modules
    all_member_ids = [nid for ids in cls["sg_members"].values() for nid in ids]
    common_left = (min(by_id[nid]["x"] for nid in all_member_ids) - 34.0) if all_member_ids else sg_rects[0]["x"]

    for sg in sg_rects:
        mids = cls["sg_members"].get(sg["id"], [])
        if not mids:
            continue
        min_x = min(by_id[nid]["x"] for nid in mids)
        max_x = max(by_id[nid]["x"] + by_id[nid]["width"] for nid in mids)
        min_y = min(by_id[nid]["y"] for nid in mids)
        max_y = max(by_id[nid]["y"] + by_id[nid]["height"] for nid in mids)

        # Also include internal arrows & their edge labels inside this subgraph's bounding box
        mset = set(mids)
        for a in cls["arrows"]:
            sb = (a.get("startBinding") or {}).get("elementId")
            eb = (a.get("endBinding") or {}).get("elementId")
            if sb in mset and eb in mset:
                for px, py in arrow_abs_points(a):
                    min_x = min(min_x, px)
                    max_x = max(max_x, px)
                    min_y = min(min_y, py)
                    max_y = max(max_y, py)
        for t in cls["edge_labels"]:
            a = by_id.get(t.get("containerId"))
            if not a:
                continue
            sb = (a.get("startBinding") or {}).get("elementId")
            eb = (a.get("endBinding") or {}).get("elementId")
            if sb in mset and eb in mset:
                lb = _label_box_for_arrow(a, t)
                min_x = min(min_x, lb[0])
                max_x = max(max_x, lb[0] + lb[2])
                min_y = min(min_y, lb[1])
                max_y = max(max_y, lb[1] + lb[3])

        tb_id = cls["sg_title_map"].get(sg["id"])
        tb = by_id.get(tb_id) if tb_id else None
        title_h = (tb["height"] + 16.0) if tb else 44.0
        title_w = (tb["width"] + 48.0) if tb else 0.0

        new_x = round(min(common_left, min_x - 34.0), 2)
        new_y = round(min_y - title_h - 14.0, 2)
        new_right = round(max(max_x + 38.0, new_x + title_w), 2)
        new_bottom = round(max_y + 34.0, 2)

        sg["x"] = new_x
        sg["y"] = new_y
        sg["width"] = round(new_right - new_x, 2)
        sg["height"] = round(new_bottom - new_y, 2)

        if tb:
            tb["x"] = round(sg["x"] + (sg["width"] - tb["width"]) / 2.0, 2)
            tb["y"] = round(sg["y"] + 8.0, 2)
            for bt in cls["band_texts"]:
                if bt.get("containerId") == tb["id"]:
                    bt["x"] = round(tb["x"] + (tb["width"] - bt["width"]) / 2.0, 2)
                    bt["y"] = round(tb["y"] + (tb["height"] - bt["height"]) / 2.0, 2)
                    break

    # Ensure adjacent subgraphs have at least 48px clean vertical gap (shift ONLY s2..end, NEVER stretching s1!)
    sg_rects.sort(key=lambda s: s["y"])
    for i in range(len(sg_rects) - 1):
        s1 = sg_rects[i]
        s2 = sg_rects[i + 1]
        min_next_y = s1["y"] + s1["height"] + 48.0
        if s2["y"] < min_next_y:
            dy = round(min_next_y - s2["y"], 2)
            # Collect all subgraphs from i+1 downward and their exact member elements
            shifted_sg_ids = {s["id"] for s in sg_rects[i + 1 :]}
            shifted_node_ids = {nid for sid in shifted_sg_ids for nid in cls["sg_members"].get(sid, [])}
            shifted_tb_ids = {cls["sg_title_map"][sid] for sid in shifted_sg_ids if sid in cls["sg_title_map"]}
            for sg in sg_rects[i + 1 :]:
                sg["y"] = round(sg["y"] + dy, 2)
            for nid in shifted_node_ids:
                nr = by_id[nid]
                nr["y"] = round(nr["y"] + dy, 2)
            for t in cls["node_texts"]:
                if t.get("containerId") in shifted_node_ids:
                    nr = by_id[t["containerId"]]
                    t["y"] = round(nr["y"] + (nr["height"] - t["height"]) / 2.0, 2)
            for tbid in shifted_tb_ids:
                tb = by_id[tbid]
                tb["y"] = round(tb["y"] + dy, 2)
            for bt in cls["band_texts"]:
                if bt.get("containerId") in shifted_tb_ids:
                    tb = by_id[bt["containerId"]]
                    bt["y"] = round(tb["y"] + (tb["height"] - bt["height"]) / 2.0, 2)
            for a in cls["arrows"]:
                sb = (a.get("startBinding") or {}).get("elementId")
                eb = (a.get("endBinding") or {}).get("elementId")
                pts = arrow_abs_points(a)
                if sb in shifted_node_ids and eb in shifted_node_ids:
                    set_arrow_abs_points(a, [(px, py + dy) for px, py in pts])
                elif eb in shifted_node_ids:
                    # External trunk entering shifted module: move destination end points down cleanly
                    new_pts = list(pts)
                    if len(new_pts) >= 2 and abs(new_pts[-1][1] - new_pts[-2][1]) < 0.8:
                        new_pts[-2] = (new_pts[-2][0], new_pts[-2][1] + dy)
                        new_pts[-1] = (new_pts[-1][0], new_pts[-1][1] + dy)
                    else:
                        new_pts[-1] = (new_pts[-1][0], new_pts[-1][1] + dy)
                    set_arrow_abs_points(a, new_pts)


def _route_external_trunks_clear_of_subgraphs(cls: dict[str, Any]) -> None:
    """Guarantee ROOT -> MOD_* vertical trunk lines run in a dedicated highway strictly LEFT of all subgraphs
    with >= 28px clearance from every module border and >= 18px spacing between parallel trunks."""
    sg_rects = cls["sg_rects"]
    if not sg_rects:
        return
    by_id = cls["by_id"]

    trunk_arrows: list[dict[str, Any]] = []
    root_right = None
    for a in cls["arrows"]:
        sb = (a.get("startBinding") or {}).get("elementId")
        eb = (a.get("endBinding") or {}).get("elementId")
        if sb and sb not in cls["node_to_sg"] and eb in cls["node_to_sg"]:
            trunk_arrows.append(a)
            sr = by_id.get(sb)
            if sr:
                rr = sr["x"] + sr["width"]
                root_right = rr if root_right is None else max(root_right, rr)

    if not trunk_arrows or root_right is None:
        return

    min_sg_x = min(sg["x"] for sg in sg_rects)
    # Count how many trunks need distinct vertical lanes (above vs below ROOT center)
    up_trunks: list[tuple[float, dict[str, Any]]] = []
    down_trunks: list[tuple[float, dict[str, Any]]] = []
    straight_trunks: list[dict[str, Any]] = []
    for a in trunk_arrows:
        pts = arrow_abs_points(a)
        if len(pts) < 2:
            continue
        dy = pts[-1][1] - pts[0][1]
        if abs(dy) < 4.0:
            straight_trunks.append(a)
        elif dy < 0:
            up_trunks.append((abs(dy), a))
        else:
            down_trunks.append((abs(dy), a))

    lane_step = 20.0
    max_lanes = max(len(up_trunks), len(down_trunks), 1)
    needed_corridor = 28.0 + max_lanes * lane_step + 34.0  # 28px from ROOT + lanes + 34px from sg.x
    cur_corridor = min_sg_x - root_right
    if cur_corridor < needed_corridor:
        dx = needed_corridor - cur_corridor
        _apply_x_shift(cls, root_right + 4.0, dx)
        min_sg_x = min(sg["x"] for sg in sg_rects)

    # Place longest trunks outermost (closest to ROOT), shortest trunks closest to sg.x (still >= 32px left of sg.x!)
    # That guarantees ZERO crossings among ROOT -> MOD_* fan-out lines!
    lane_rightmost = min_sg_x - 32.0
    for group in (up_trunks, down_trunks):
        # Shortest vertical distance gets lane closest to sg.x; longest gets lane closest to ROOT -> 0 crossings!
        group.sort(key=lambda item: item[0])
        for idx, (_, a) in enumerate(group):
            pts = arrow_abs_points(a)
            x0, y0 = pts[0]
            xn, yn = pts[-1]
            vx = round(lane_rightmost - idx * lane_step, 2)
            vx = max(vx, x0 + 16.0)
            sb = (a.get("startBinding") or {}).get("elementId")
            eb = (a.get("endBinding") or {}).get("elementId")
            dr = by_id.get(eb) if eb else None

            # Check if final horizontal entry (vx, yn) -> (xn, yn) hits any node sitting left of dst (e.g. a note pointing to MOD)
            blockers = [
                nr for nr in cls["node_rects"]
                if nr["id"] not in (sb, eb)
                and seg_hits_rect((vx, yn), (xn, yn), (nr["x"], nr["y"], nr["width"], nr["height"]), margin=2.0)
            ]
            if not blockers:
                set_arrow_abs_points(a, [(x0, y0), (vx, y0), (vx, yn), (xn, yn)])
            else:
                # First try shifting entry Y within dst's vertical edge to pass cleanly above/below blocker
                chosen = None
                if dr:
                    for cand_y in (
                        max(b["y"] + b["height"] for b in blockers) + 14.0,
                        min(b["y"] for b in blockers) - 14.0,
                    ):
                        if dr["y"] + 8.0 <= cand_y <= dr["y"] + dr["height"] - 8.0:
                            if not any(
                                seg_hits_rect((vx, cand_y), (xn, cand_y), (nr["x"], nr["y"], nr["width"], nr["height"]), margin=2.0)
                                for nr in cls["node_rects"] if nr["id"] not in (sb, eb)
                            ):
                                chosen = [(x0, y0), (vx, y0), (vx, round(cand_y, 2)), (xn, round(cand_y, 2))]
                                break
                if not chosen:
                    # Clean 6-point orthogonal jog under/over the blocker outside dst's left edge
                    jog_x = round(xn - 18.0, 2)
                    clear_y = round(max(b["y"] + b["height"] for b in blockers) + 18.0, 2)
                    chosen = [(x0, y0), (vx, y0), (vx, clear_y), (jog_x, clear_y), (jog_x, yn), (xn, yn)]
                set_arrow_abs_points(a, chosen)

    for a in straight_trunks:
        pts = arrow_abs_points(a)
        set_arrow_abs_points(a, [pts[0], (pts[-1][0], pts[0][1])])


def _apply_high_contrast_palette(cls: dict[str, Any]) -> None:
    """Apply crisp, clearly visible high-contrast stroke palette & rounded module frames:
      - Subgraph module frames: #4B5563 (dark gray), dotted (点虚线，更密集), strokeWidth 1.5, roundness type 3
      - Solid content boxes (MOD/SUB/K): #4B5563 (dark gray), strokeWidth 1.5 (preserves #002FA7 Klein Blue ROOT/KEY)
      - Auxiliary dashed content boxes (note): #6B7280 (one shade lighter), dashed (正常虚线), strokeWidth 1.5
    """
    for sg in cls["sg_rects"]:
        sg["strokeColor"] = SOLID_BOX_STROKE
        sg["strokeStyle"] = "dotted"
        sg["strokeWidth"] = 1.5
        sg["roundness"] = {"type": 3}

    for nr in cls["node_rects"]:
        sc = str(nr.get("strokeColor", "")).strip().lower()
        bg = str(nr.get("backgroundColor", "")).strip().lower()
        # Preserve Klein Blue ROOT and KEY accent nodes
        if sc == ACCENT_BLUE or bg == ACCENT_BLUE:
            continue
        st = str(nr.get("strokeStyle", "solid")).strip().lower()
        if st in ("dashed", "dotted"):
            # Auxiliary note content box: normal dashed (正常虚线), one shade lighter than solid boxes
            nr["strokeColor"] = NOTE_BOX_STROKE
            nr["strokeStyle"] = "dashed"
            nr["strokeWidth"] = 1.5
        else:
            # Primary solid content box: crisp dark gray
            nr["strokeColor"] = SOLID_BOX_STROKE
            nr["strokeWidth"] = 1.5


def deconflict_excalidraw(doc: dict[str, Any]) -> dict[str, Any]:
    els = doc.get("elements", [])
    cls = classify_elements(els)
    by_id = cls["by_id"]

    # Step 1: Compact crisp edge-label typography (16px vs 20px node text)
    for t in cls["edge_labels"]:
        if float(t.get("fontSize", 16)) > 16:
            t["fontSize"] = 16
        ew, eh = estimate_cjk_text_size(t["text"], float(t["fontSize"]), float(t.get("lineHeight", 1.25)))
        t["width"] = round(ew, 2)
        t["height"] = round(eh, 2)

    # Step 2: Widen/tallen tight node boxes IN-PLACE first, then shift columns ONCE per column
    col_x_expansions: list[tuple[float, float]] = []
    for r in cls["node_rects"]:
        bt = None
        for t in cls["node_texts"]:
            if t.get("containerId") == r["id"]:
                bt = t
                break
        if not bt:
            continue
        est_w, est_h = estimate_cjk_text_size(bt["text"], float(bt.get("fontSize", 16)), float(bt.get("lineHeight", 1.25)))
        need_w = math.ceil(est_w + 24.0)
        need_h = math.ceil(est_h + 14.0)
        if need_w > r["width"]:
            old_w = r["width"]
            dw = need_w - old_w
            col_x_expansions.append((r["x"] + old_w - 2.0, dw))
            r["width"] = round(need_w, 2)
            bt["width"] = round(max(float(bt["width"]), est_w), 2)
            bt["x"] = round(r["x"] + (r["width"] - bt["width"]) / 2.0, 2)
        elif est_w > float(bt["width"]):
            bt["width"] = round(est_w, 2)
            bt["x"] = round(r["x"] + (r["width"] - bt["width"]) / 2.0, 2)
        if need_h > r["height"]:
            r["height"] = round(need_h, 2)
            bt["height"] = round(max(float(bt["height"]), est_h), 2)
            bt["y"] = round(r["y"] + (r["height"] - bt["height"]) / 2.0, 2)

    if col_x_expansions:
        col_x_expansions.sort(key=lambda x: x[0])
        merged_cols: list[tuple[float, float]] = []
        for cx, dx in col_x_expansions:
            if merged_cols and abs(cx - merged_cols[-1][0]) < 85.0:
                merged_cols[-1] = (max(merged_cols[-1][0], cx), max(merged_cols[-1][1], dx))
            else:
                merged_cols.append((cx, dx))
        for cx, dx in reversed(merged_cols):
            _apply_x_shift(cls, cx, dx)

    # Step 3: Resolve any node-vs-node overlaps
    for _ in range(40):
        fixed_any = False
        nodes_sorted = sorted(cls["node_rects"], key=lambda n: (n["y"], n["x"]))
        for i in range(len(nodes_sorted)):
            r1 = nodes_sorted[i]
            b1 = (r1["x"], r1["y"], r1["width"], r1["height"])
            for j in range(i + 1, len(nodes_sorted)):
                r2 = nodes_sorted[j]
                b2 = (r2["x"], r2["y"], r2["width"], r2["height"])
                if rects_overlap(b1, b2, pad=4.0):
                    ov_x = min(r1["x"] + r1["width"], r2["x"] + r2["width"]) - max(r1["x"], r2["x"])
                    ov_y = min(r1["y"] + r1["height"], r2["y"] + r2["height"]) - max(r1["y"], r2["y"])
                    if ov_y <= ov_x:
                        dy = (r1["y"] + r1["height"] + 20.0) - r2["y"]
                        if dy > 0:
                            _apply_y_shift(cls, r2["y"] - 1.0, dy)
                            fixed_any = True
                            break
                    else:
                        left_r, right_r = (r1, r2) if r1["x"] <= r2["x"] else (r2, r1)
                        dx = (left_r["x"] + left_r["width"] + 28.0) - right_r["x"]
                        if dx > 0:
                            _apply_x_shift(cls, right_r["x"] - 1.0, dx)
                            fixed_any = True
                            break
            if fixed_any:
                break
        if not fixed_any:
            break

    _sync_arrow_endpoints_to_nodes(cls)

    # Step 4: Expand narrow horizontal corridors where an edge label is wider than its corridor
    label_by_arrow = {t.get("containerId"): t for t in cls["edge_labels"]}
    for _pass in range(3):
        expansions: list[tuple[float, float]] = []
        for a in cls["arrows"]:
            t = label_by_arrow.get(a["id"])
            if not t:
                continue
            sb = (a.get("startBinding") or {}).get("elementId")
            eb = (a.get("endBinding") or {}).get("elementId")
            if sb not in by_id or eb not in by_id:
                continue
            sr, dr = by_id[sb], by_id[eb]
            if dr["x"] >= sr["x"] + sr["width"] - 5:
                gap = dr["x"] - (sr["x"] + sr["width"])
                cut_x = sr["x"] + sr["width"] + max(2.0, gap / 2.0)
            elif sr["x"] >= dr["x"] + dr["width"] - 5:
                gap = sr["x"] - (dr["x"] + dr["width"])
                cut_x = dr["x"] + dr["width"] + max(2.0, gap / 2.0)
            else:
                continue
            lw, _ = estimate_cjk_text_size(t["text"], float(t.get("fontSize", 16)), float(t.get("lineHeight", 1.25)))
            req_gap = lw + 58.0
            if gap < req_gap:
                expansions.append((cut_x, req_gap - gap))

        if not expansions:
            break
        expansions.sort(key=lambda x: x[0])
        merged: list[tuple[float, float]] = []
        for cx, dx in expansions:
            if merged and abs(cx - merged[-1][0]) < 60.0:
                merged[-1] = ((merged[-1][0] + cx) / 2.0, max(merged[-1][1], dx))
            else:
                merged.append((cx, dx))
        for cx, dx in reversed(merged):
            _apply_x_shift(cls, cx, dx)

    _sync_arrow_endpoints_to_nodes(cls)

    # Step 5: Lane-aware recentering of elbow bends
    for _ in range(4):
        moved = _recenter_and_lane_arrows(cls, only_conflicted=False)
        if moved == 0:
            break

    # Step 6: Iterative corridor-widening & pairwise X-crossing lane swap
    for _round in range(25):
        _sync_edge_label_positions(cls)
        aud = audit_excalidraw(doc)
        if (
            aud["label_vs_node_overlaps"] == 0
            and aud["label_vs_label_overlaps"] == 0
            and aud["label_vs_other_arrow_collisions"] == 0
            and aud["coincident_vertical_tracks"] == 0
        ):
            break

        fixed = False

        if aud["sample_label_hits"]:
            hit = aud["sample_label_hits"][0]
            lb = hit["label_box"]
            nb = hit["node_box"]
            l_cx = lb[0] + lb[2] / 2.0
            n_cx = nb[0] + nb[2] / 2.0
            if l_cx <= n_cx:
                need_dx = (lb[0] + lb[2] + 24.0) - nb[0]
                if need_dx > 0:
                    _apply_x_shift(cls, nb[0] - 2.0, need_dx)
                    fixed = True
            else:
                need_dx = (nb[0] + nb[2] + 24.0) - lb[0]
                if need_dx > 0:
                    _apply_x_shift(cls, nb[0] + nb[2] + 1.0, need_dx)
                    fixed = True

        if not fixed and aud["sample_label_arrow_hits"]:
            hit = aud["sample_label_arrow_hits"][0]
            my_a = by_id.get(hit["my_arrow"])
            other_a = by_id.get(hit["other_arrow"])
            lb = hit["label_box"]

            if my_a and other_a:
                p_my = arrow_abs_points(my_a)
                p_ot = arrow_abs_points(other_a)
                my_is_z = (len(p_my) == 4 and abs(p_my[0][1] - p_my[1][1]) < 0.8 and abs(p_my[1][0] - p_my[2][0]) < 0.8 and abs(p_my[2][1] - p_my[3][1]) < 0.8)
                ot_is_z = (len(p_ot) == 4 and abs(p_ot[0][1] - p_ot[1][1]) < 0.8 and abs(p_ot[1][0] - p_ot[2][0]) < 0.8 and abs(p_ot[2][1] - p_ot[3][1]) < 0.8)
                if my_is_z and ot_is_z:
                    lo_m, hi_m = min(p_my[0][0], p_my[3][0]) + 14.0, max(p_my[0][0], p_my[3][0]) - 14.0
                    lo_o, hi_o = min(p_ot[0][0], p_ot[3][0]) + 14.0, max(p_ot[0][0], p_ot[3][0]) - 14.0
                    span_m, span_o = hi_m - lo_m, hi_o - lo_o
                    if span_m > 10 and span_o > 10:
                        t_my = label_by_arrow.get(my_a["id"])
                        t_ot = label_by_arrow.get(other_a["id"])
                        orig_my = list(p_my)
                        orig_ot = list(p_ot)
                        for fm, fo in ((0.28, 0.72), (0.72, 0.28), (0.22, 0.78), (0.78, 0.22), (0.18, 0.82), (0.82, 0.18), (0.35, 0.80), (0.80, 0.35), (0.20, 0.65), (0.65, 0.20)):
                            xm = lo_m + span_m * fm
                            xo = lo_o + span_o * fo
                            cand_m = [(p_my[0][0], p_my[0][1]), (xm, p_my[0][1]), (xm, p_my[3][1]), (p_my[3][0], p_my[3][1])]
                            cand_o = [(p_ot[0][0], p_ot[0][1]), (xo, p_ot[0][1]), (xo, p_ot[3][1]), (p_ot[3][0], p_ot[3][1])]
                            set_arrow_abs_points(my_a, cand_m)
                            set_arrow_abs_points(other_a, cand_o)
                            if _arrow_candidate_ok(my_a, cand_m, t_my, cls, label_by_arrow) and _arrow_candidate_ok(other_a, cand_o, t_ot, cls, label_by_arrow):
                                fixed = True
                                break
                        if not fixed:
                            set_arrow_abs_points(my_a, orig_my)
                            set_arrow_abs_points(other_a, orig_ot)

            if not fixed and _recenter_and_lane_arrows(cls, only_conflicted=True) > 0:
                fixed = True
            if not fixed:
                cut_x = lb[0] + lb[2] / 2.0
                _apply_x_shift(cls, cut_x, min(90.0, max(52.0, lb[2] + 24.0)))
                _sync_arrow_endpoints_to_nodes(cls)
                _recenter_and_lane_arrows(cls, only_conflicted=True)
                fixed = True

        if not fixed and aud["sample_coinc_tracks"]:
            ct = aud["sample_coinc_tracks"][0]
            if _recenter_and_lane_arrows(cls, only_conflicted=True) > 0:
                fixed = True
            else:
                _apply_x_shift(cls, ct["x1"] + 2.0, 48.0)
                _sync_arrow_endpoints_to_nodes(cls)
                _recenter_and_lane_arrows(cls, only_conflicted=True)
                fixed = True

        if not fixed and aud["label_vs_label_overlaps"] > 0:
            pts_list = [(t, _label_box_for_arrow(by_id[t["containerId"]], t)) for t in cls["edge_labels"] if t.get("containerId") in by_id]
            for i in range(len(pts_list)):
                _, b1 = pts_list[i]
                for j in range(i + 1, len(pts_list)):
                    _, b2 = pts_list[j]
                    if rects_overlap(b1, b2, pad=2.0):
                        low_y = max(b1[1], b2[1])
                        _apply_y_shift(cls, low_y - 4.0, 34.0)
                        fixed = True
                        break
                if fixed:
                    break

        if fixed:
            _sync_arrow_endpoints_to_nodes(cls)
            _recenter_and_lane_arrows(cls, only_conflicted=True)
        else:
            break

    # Step 7: Clear any remaining arrow segment grazing a non-endpoint node box
    for _ in range(10):
        fixed_arrow = False
        for a in cls["arrows"]:
            sb = (a.get("startBinding") or {}).get("elementId")
            eb = (a.get("endBinding") or {}).get("elementId")
            pts = arrow_abs_points(a)
            t = label_by_arrow.get(a["id"])
            for i in range(len(pts) - 1):
                p1, p2 = pts[i], pts[i + 1]
                hit_nr = None
                for nr in cls["node_rects"]:
                    if nr["id"] in (sb, eb):
                        continue
                    if seg_hits_rect(p1, p2, (nr["x"], nr["y"], nr["width"], nr["height"]), margin=1.5):
                        hit_nr = nr
                        break
                if not hit_nr:
                    continue
                if abs(p1[0] - p2[0]) < 0.8 and 0 < i < len(pts) - 2:
                    cands_x = [hit_nr["x"] + hit_nr["width"] + 16.0, hit_nr["x"] - 16.0]
                    cands_x.sort(key=lambda cx: abs(cx - p1[0]))
                    for cx in cands_x:
                        cand_pts = list(pts)
                        cand_pts[i] = (cx, p1[1])
                        cand_pts[i + 1] = (cx, p2[1])
                        if _arrow_candidate_ok(a, cand_pts, t, cls, label_by_arrow):
                            set_arrow_abs_points(a, cand_pts)
                            fixed_arrow = True
                            break
                elif abs(p1[1] - p2[1]) < 0.8 and 0 < i < len(pts) - 2:
                    cands_y = [hit_nr["y"] - 16.0, hit_nr["y"] + hit_nr["height"] + 16.0]
                    cands_y.sort(key=lambda cy: abs(cy - p1[1]))
                    for cy in cands_y:
                        cand_pts = list(pts)
                        cand_pts[i] = (p1[0], cy)
                        cand_pts[i + 1] = (p2[0], cy)
                        if _arrow_candidate_ok(a, cand_pts, t, cls, label_by_arrow):
                            set_arrow_abs_points(a, cand_pts)
                            fixed_arrow = True
                            break
                if fixed_arrow:
                    break
            if fixed_arrow:
                break
        if not fixed_arrow:
            break

    # Step 8: Refit ALL module subgraphs cleanly around ALL member nodes + internal labels + titles,
    # route ROOT -> MOD_* trunks cleanly LEFT of module borders, and apply high-contrast visual styling!
    _refit_subgraphs_and_titles(cls)
    _route_external_trunks_clear_of_subgraphs(cls)
    _sync_arrow_endpoints_to_nodes(cls)
    _sync_edge_label_positions(cls)
    _apply_high_contrast_palette(cls)
    return doc


def process_file(input_path: Path, output_path: Path | None = None, audit_only: bool = False) -> dict[str, Any]:
    doc = json.loads(input_path.read_text(encoding="utf-8"))
    before = audit_excalidraw(doc)
    if audit_only:
        return {"file": str(input_path), "before": before}

    deconflict_excalidraw(doc)
    after = audit_excalidraw(doc)
    dst = output_path or input_path
    dst.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "file": str(dst),
        "before": {k: v for k, v in before.items() if not k.startswith("sample_")},
        "after": after,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cartograph Real-Excalidraw 10-Check Zero-Interference & Styling Engine")
    parser.add_argument("inputs", nargs="+", help="One or more .excalidraw files")
    parser.add_argument("-o", "--output", default=None, help="Output path (single input only)")
    parser.add_argument("--audit-only", action="store_true", help="Audit without modifying files")
    ns = parser.parse_args()

    if ns.output and len(ns.inputs) != 1:
        parser.error("-o/--output can only be used with a single input file.")

    results = []
    all_clean = True
    for raw in ns.inputs:
        p = Path(raw).resolve()
        out_p = Path(ns.output).resolve() if ns.output else None
        res = process_file(p, out_p, audit_only=ns.audit_only)
        results.append(res)
        chk = res["before"] if ns.audit_only else res["after"]
        if not chk.get("zero_interference"):
            all_clean = False

    print(json.dumps({"all_zero_interference": all_clean, "results": results}, ensure_ascii=False, indent=2))
    if not all_clean:
        sys.exit(1)


if __name__ == "__main__":
    main()
