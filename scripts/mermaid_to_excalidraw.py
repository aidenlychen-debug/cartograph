#!/usr/bin/env python3
"""Cartograph Mermaid Flowchart Auditor & Native Excalidraw v2 (.excalidraw) Compiler.

Zero external dependencies (Python 3.8+ standard library only).
Parses `flowchart LR` Mermaid files, runs full static audit against Cartograph
architecture & budget rules, computes a clean non-overlapping LR hierarchical
layout (strong chains horizontal, independent branches vertical, local auxiliary
dashed nodes placed beside their supported nodes), and writes a directly importable
`.excalidraw` v2 JSON canvas file.

Works both as a standard CLI and as an Antigravity `run_workflow` ScriptPath script:
  CLI: python mermaid_to_excalidraw.py input.mmd [-o output.excalidraw] [--audit-only]
  Workflow: Args={"input": "...", "output": "...", "audit_only": False}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RESERVED_IDS = {
    "end", "subgraph", "class", "classdef", "style", "linkstyle",
    "click", "graph", "flowchart", "direction", "default",
}
FORBIDDEN_TERMS = ("认知块", "分组容器", "分组1", "分组 1")

DEFAULT_CLASS_STYLES: dict[str, dict[str, Any]] = {
    "root": {"fill": "#002FA7", "stroke": "#002FA7", "stroke_width": 2, "color": "#FFFFFF", "font_size": 28, "dashed": False},
    "mod":  {"fill": "#F5F5F7", "stroke": "#D1D5DB", "stroke_width": 1.5, "color": "#1D1D1F", "font_size": 22, "dashed": False},
    "sub":  {"fill": "#FFFFFF", "stroke": "#D1D5DB", "stroke_width": 1.5, "color": "#1D1D1F", "font_size": 18, "dashed": False},
    "k":    {"fill": "#FFFFFF", "stroke": "#E5E5E5", "stroke_width": 1.2, "color": "#3A3A3C", "font_size": 16, "dashed": False},
    "key":  {"fill": "#FFFFFF", "stroke": "#002FA7", "stroke_width": 2, "color": "#002FA7", "font_size": 17, "dashed": False},
    "note": {"fill": "#FFFFFF", "stroke": "#D1D5DB", "stroke_width": 1, "color": "#3A3A3C", "font_size": 15, "dashed": True},
}


@dataclass
class Node:
    id: str
    label: str
    shape: str = "round"  # "round" for ("..."), "rect" for ["..."]
    subgraph: str | None = None
    outer_subgraph: str | None = None
    cls: str | None = None
    order: int = 0
    # Layout coordinates
    x: float = 0.0
    y: float = 0.0
    w: float = 200.0
    h: float = 64.0


@dataclass
class Edge:
    src: str
    dst: str
    style: str = "solid"  # "solid" | "dashed" | "thick"
    label: str = ""
    order: int = 0


@dataclass
class Subgraph:
    id: str
    title: str
    parent: str | None = None
    direction: str | None = None
    nodes: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    style: dict[str, Any] = field(default_factory=dict)
    order: int = 0
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


@dataclass
class Graph:
    header: str = ""
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    subgraphs: dict[str, Subgraph] = field(default_factory=dict)
    class_defs: dict[str, dict[str, Any]] = field(default_factory=dict)
    node_styles: dict[str, dict[str, Any]] = field(default_factory=dict)
    duplicate_nodes: list[str] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)


def _parse_style_props(prop_str: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for part in prop_str.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "fill":
            out["fill"] = v
        elif k == "stroke":
            out["stroke"] = v
        elif k == "stroke-width":
            m = re.match(r"([0-9.]+)", v)
            if m:
                out["stroke_width"] = float(m.group(1))
        elif k == "stroke-dasharray":
            out["dashed"] = True
        elif k == "color":
            out["color"] = v
        elif k == "font-size":
            m = re.match(r"([0-9.]+)", v)
            if m:
                # Scale Mermaid px slightly for crisp Excalidraw legibility
                raw_fs = float(m.group(1))
                out["font_size"] = max(14, min(28, round(raw_fs * 0.85)))
    return out


def _clean_label(raw: str) -> str:
    txt = raw.strip()
    if len(txt) >= 2 and txt[0] == '"' and txt[-1] == '"':
        txt = txt[1:-1]
    txt = txt.replace("\\\"", '"').replace("&quot;", '"')
    txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.IGNORECASE)
    return txt.strip()


def parse_mermaid(text: str) -> Graph:
    g = Graph()
    lines = text.replace("\r\n", "\n").splitlines()
    sg_stack: list[str] = []
    node_order = 0
    edge_order = 0
    sg_order = 0

    def current_sg() -> str | None:
        return sg_stack[-1] if sg_stack else None

    def outer_sg() -> str | None:
        return sg_stack[0] if sg_stack else None

    def register_node(nid: str, label: str, shape: str) -> None:
        nonlocal node_order
        if nid in g.nodes:
            g.duplicate_nodes.append(nid)
            if label and not g.nodes[nid].label:
                g.nodes[nid].label = label
            return
        node_order += 1
        n = Node(
            id=nid,
            label=label,
            shape=shape,
            subgraph=current_sg(),
            outer_subgraph=outer_sg(),
            order=node_order,
        )
        g.nodes[nid] = n
        if current_sg():
            g.subgraphs[current_sg()].nodes.append(nid)

    # Regex patterns
    re_classdef = re.compile(r"^classDef\s+([A-Za-z0-9_-]+)\s+(.+)$")
    re_class = re.compile(r"^class\s+([A-Za-z0-9_,\s-]+?)\s+([A-Za-z0-9_-]+)\s*$")
    re_style = re.compile(r"^style\s+([A-Za-z0-9_-]+)\s+(.+)$")
    re_subgraph = re.compile(r'^subgraph\s+([A-Za-z0-9_]+)\s*(?:\[\s*"((?:[^"\\]|\\.)*)"\s*\]|\[([^\]]+)\])?\s*$')
    re_direction = re.compile(r"^direction\s+(LR|RL|TB|TD|BT)\s*$", re.IGNORECASE)
    re_edge = re.compile(
        r'^([A-Za-z0-9_]+)\s*(-->|-\.->|==>)\s*(?:\|([^|]*)\|\s*)?([A-Za-z0-9_]+)\s*$'
    )
    re_edge_mid = re.compile(
        r'^([A-Za-z0-9_]+)\s*(?:--\s*"?([^"-]+?)"?\s*-->|-\.\s*"?([^".]+?)"?\s*\.->)\s*([A-Za-z0-9_]+)\s*$'
    )
    re_node_round = re.compile(r'^([A-Za-z0-9_]+)\(\s*"((?:[^"\\]|\\.)*)"\s*\)\s*$')
    re_node_rect = re.compile(r'^([A-Za-z0-9_]+)\[\s*"((?:[^"\\]|\\.)*)"\s*\]\s*$')
    re_node_plain_round = re.compile(r'^([A-Za-z0-9_]+)\(([^()]+)\)\s*$')
    re_node_plain_rect = re.compile(r'^([A-Za-z0-9_]+)\[([^\[\]]+)\]\s*$')

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if not g.header:
            g.header = line
            continue
        if line == "end":
            if sg_stack:
                sg_stack.pop()
            else:
                g.parse_warnings.append("发现多余的 `end` 语句。")
            continue

        m = re_classdef.match(line)
        if m:
            g.class_defs[m.group(1)] = _parse_style_props(m.group(2))
            continue

        m = re_class.match(line)
        if m:
            cls_name = m.group(2).strip()
            for nid in re.split(r"[,\s]+", m.group(1).strip()):
                if nid and nid in g.nodes:
                    g.nodes[nid].cls = cls_name
            continue

        m = re_style.match(line)
        if m:
            target_id, props = m.group(1), _parse_style_props(m.group(2))
            if target_id in g.subgraphs:
                g.subgraphs[target_id].style.update(props)
            else:
                g.node_styles[target_id] = props
            continue

        m = re_subgraph.match(line)
        if m:
            sg_id = m.group(1)
            sg_title = _clean_label(m.group(2) or m.group(3) or sg_id)
            parent = current_sg()
            sg_order += 1
            sg = Subgraph(id=sg_id, title=sg_title, parent=parent, order=sg_order)
            g.subgraphs[sg_id] = sg
            if parent:
                g.subgraphs[parent].children.append(sg_id)
            sg_stack.append(sg_id)
            continue

        m = re_direction.match(line)
        if m:
            if current_sg():
                g.subgraphs[current_sg()].direction = m.group(1).upper()
            continue

        m = re_edge.match(line)
        if m:
            edge_order += 1
            arrow = m.group(2)
            estyle = "dashed" if arrow == "-.->" else ("thick" if arrow == "==>" else "solid")
            label = _clean_label(m.group(3) or "")
            g.edges.append(Edge(src=m.group(1), dst=m.group(4), style=estyle, label=label, order=edge_order))
            continue

        m = re_edge_mid.match(line)
        if m:
            edge_order += 1
            is_dashed = "-." in line
            label = _clean_label(m.group(2) or m.group(3) or "")
            g.edges.append(Edge(src=m.group(1), dst=m.group(4), style="dashed" if is_dashed else "solid", label=label, order=edge_order))
            continue

        m = re_node_round.match(line)
        if m:
            register_node(m.group(1), _clean_label(m.group(2)), "round")
            continue

        m = re_node_rect.match(line)
        if m:
            register_node(m.group(1), _clean_label(m.group(2)), "rect")
            continue

        m = re_node_plain_round.match(line)
        if m:
            register_node(m.group(1), _clean_label(m.group(2)), "round")
            continue

        m = re_node_plain_rect.match(line)
        if m:
            register_node(m.group(1), _clean_label(m.group(2)), "rect")
            continue

        g.parse_warnings.append(f"未识别语句（已忽略）：{line[:80]}")

    if sg_stack:
        g.parse_warnings.append(f"存在未闭合的 subgraph：{sg_stack}")
    return g


def audit_graph(g: Graph) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = list(g.parse_warnings)

    if g.header.strip() != "flowchart LR":
        errors.append(f"首行必须为 `flowchart LR`，当前为 `{g.header}`。")

    if g.duplicate_nodes:
        errors.append(f"存在重复定义的节点 ID：{sorted(set(g.duplicate_nodes))}")

    for nid in g.nodes:
        if nid.lower() in RESERVED_IDS:
            errors.append(f"节点 ID 使用了 Mermaid 保留字：{nid}")

    for sg in g.subgraphs.values():
        for bad in FORBIDDEN_TERMS:
            if bad in sg.title:
                errors.append(f"subgraph {sg.id} 标题包含禁止内部术语 `{bad}`：{sg.title}")

    for n in g.nodes.values():
        for bad in FORBIDDEN_TERMS:
            if bad in n.label:
                warnings.append(f"节点 {n.id} 文本包含疑似内部术语 `{bad}`")

    # Classify edges & check endpoints
    structure_edges = 0
    logic_edges = 0
    aux_dashed_edges = 0
    cross_mod_edges = 0
    labeled_edges = 0

    for e in g.edges:
        if e.src in g.subgraphs or e.dst in g.subgraphs:
            errors.append(f"禁止连线到 subgraph ID：{e.src} -> {e.dst}")
            continue
        if e.src not in g.nodes:
            errors.append(f"边起点节点未定义：{e.src}")
            continue
        if e.dst not in g.nodes:
            errors.append(f"边终点节点未定义：{e.dst}")
            continue
        if e.label:
            labeled_edges += 1
        s_mod = g.nodes[e.src].outer_subgraph
        d_mod = g.nodes[e.dst].outer_subgraph
        if s_mod and d_mod and s_mod != d_mod:
            cross_mod_edges += 1

        if e.style == "dashed":
            aux_dashed_edges += 1
        elif e.label:
            logic_edges += 1
        else:
            # Structural hierarchy edges: ROOT->MOD, MOD->SUB, SUB->H4/K, etc.
            if e.src == "ROOT" or e.src.startswith(("MOD_", "SUB_", "H4_", "H5_")):
                structure_edges += 1
            else:
                logic_edges += 1

    # Check ROOT -> all MOD_*
    mod_ids = [nid for nid in g.nodes if nid.startswith("MOD_")]
    if "ROOT" in g.nodes and mod_ids:
        root_targets = {e.dst for e in g.edges if e.src == "ROOT"}
        missing_mods = [m for m in mod_ids if m not in root_targets]
        if missing_mods:
            warnings.append(f"ROOT 未直接连接以下 MOD 节点：{missing_mods}")

    unstyled = [nid for nid, n in g.nodes.items() if not n.cls and nid not in g.node_styles]
    if unstyled:
        warnings.append(f"有 {len(unstyled)} 个节点未分配样式 class：{unstyled[:8]}")

    total_edges = len(g.edges)
    if total_edges > 500:
        errors.append(f"总边数 {total_edges} 超过硬上限 500。")
    elif total_edges > 450:
        warnings.append(f"总边数 {total_edges} 超过推荐目标 450（仍在硬上限 500 内）。")

    outer_sgs = [sg for sg in g.subgraphs.values() if sg.parent is None]
    return {
        "valid": len(errors) == 0,
        "nodes": len(g.nodes),
        "outer_subgraphs": len(outer_sgs),
        "total_subgraphs": len(g.subgraphs),
        "structure_edges": structure_edges,
        "logic_edges": logic_edges,
        "aux_dashed_edges": aux_dashed_edges,
        "cross_mod_edges": cross_mod_edges,
        "total_edges": total_edges,
        "labeled_edges": labeled_edges,
        "budget_ok": total_edges <= 500,
        "errors": errors,
        "warnings": warnings,
    }


def _resolve_node_style(g: Graph, n: Node) -> dict[str, Any]:
    # Infer fallback class from ID prefix if unspecified
    fallback_cls = "k"
    if n.id == "ROOT":
        fallback_cls = "root"
    elif n.id.startswith("MOD_"):
        fallback_cls = "mod"
    elif n.id.startswith(("SUB_", "H4_", "H5_")):
        fallback_cls = "sub"
    elif n.id.startswith(("E_", "N_", "R_")):
        fallback_cls = "note"

    cls_name = n.cls or fallback_cls
    style = dict(DEFAULT_CLASS_STYLES.get(cls_name, DEFAULT_CLASS_STYLES["k"]))
    if cls_name in g.class_defs:
        style.update(g.class_defs[cls_name])
    if n.id in g.node_styles:
        style.update(g.node_styles[n.id])
    return style


def _measure_text(text: str, font_size: float) -> tuple[float, float]:
    lines = text.split("\n") if text else [""]
    max_w = 0.0
    for line in lines:
        w = 0.0
        for ch in line:
            code = ord(ch)
            if code > 127:
                w += font_size * 1.06
            elif ch in "ilI1.,;:'|! ":
                w += font_size * 0.36
            elif ch.isupper():
                w += font_size * 0.70
            else:
                w += font_size * 0.58
        if w > max_w:
            max_w = w
    line_h = font_size * 1.32
    total_h = max(line_h, len(lines) * line_h)
    return max_w, total_h


def _size_all_nodes(g: Graph) -> None:
    for n in g.nodes.values():
        st = _resolve_node_style(g, n)
        fs = float(st.get("font_size", 16))
        tw, th = _measure_text(n.label, fs)
        pad_x = 44.0 if n.id == "ROOT" else 34.0
        pad_y = 28.0 if n.id == "ROOT" else 22.0
        n.w = max(140.0, math.ceil(tw + pad_x))
        n.h = max(52.0, math.ceil(th + pad_y))


def _layout_subgraph(g: Graph, sg_id: str) -> tuple[float, float]:
    """Layout nodes inside one outer MOD subgraph (and any nested subgraphs) locally starting at (0, 0).

    Follows Cartograph layout semantics:
    - Solid structural + strong-logic edges expand left-to-right (columns).
    - Independent siblings stack top-to-bottom (rows).
    - Local dashed auxiliary nodes (evidence/examples/notes) attach neatly beside the node they support.
    """
    sg = g.subgraphs[sg_id]
    member_ids: list[str] = list(sg.nodes)
    for child_sg_id in sg.children:
        member_ids.extend(g.subgraphs[child_sg_id].nodes)
    member_set = set(member_ids)
    if not member_ids:
        return 300.0, 140.0

    # Build directed adjacency for solid internal edges
    solid_out: dict[str, list[str]] = defaultdict(list)
    solid_in: dict[str, list[str]] = defaultdict(list)
    dashed_links: list[Edge] = []
    for e in g.edges:
        if e.src in member_set and e.dst in member_set:
            if e.style == "dashed":
                dashed_links.append(e)
            else:
                solid_out[e.src].append(e.dst)
                solid_in[e.dst].append(e.src)

    # Identify pure auxiliary nodes (no solid incoming & no solid outgoing, only dashed links)
    aux_attach: dict[str, list[str]] = defaultdict(list)
    aux_nodes: set[str] = set()
    for nid in member_ids:
        if not solid_in[nid] and not solid_out[nid]:
            # Find first dashed link partner inside this subgraph
            for e in dashed_links:
                if e.src == nid and e.dst != nid:
                    aux_attach[e.dst].append(nid)
                    aux_nodes.add(nid)
                    break
                if e.dst == nid and e.src != nid:
                    aux_attach[e.src].append(nid)
                    aux_nodes.add(nid)
                    break

    # Primary tree roots inside this subgraph: nodes with no solid_in and not pure aux
    roots = [
        nid for nid in sorted(member_ids, key=lambda x: g.nodes[x].order)
        if not solid_in[nid] and nid not in aux_nodes
    ]
    if not roots:
        roots = [sorted(member_ids, key=lambda x: g.nodes[x].order)[0]]

    # Build a clean spanning tree (each node gets one primary parent) for non-overlapping row placement
    tree_children: dict[str, list[str]] = defaultdict(list)
    visited: set[str] = set()

    def build_tree(u: str) -> None:
        visited.add(u)
        # Solid children in original definition order
        for v in sorted(solid_out[u], key=lambda x: g.nodes[x].order):
            if v not in visited and v not in aux_nodes:
                tree_children[u].append(v)
                build_tree(v)
        # Pure auxiliary nodes supporting u attach right after u
        for a in sorted(aux_attach[u], key=lambda x: g.nodes[x].order):
            if a not in visited:
                visited.add(a)
                tree_children[u].append(a)

    for r in roots:
        if r not in visited:
            build_tree(r)
    # Catch any disconnected nodes
    for nid in sorted(member_ids, key=lambda x: g.nodes[x].order):
        if nid not in visited:
            roots.append(nid)
            build_tree(nid)

    # Assign column depth (longest solid path from root, bounded to avoid cycles)
    col: dict[str, int] = {r: 0 for r in roots}
    # BFS / relaxation on tree + solid DAG
    for _ in range(len(member_ids) + 1):
        changed = False
        for u, chs in tree_children.items():
            if u not in col:
                continue
            for v in chs:
                if col.get(v, -1) < col[u] + 1:
                    col[v] = col[u] + 1
                    changed = True
        if not changed:
            break
    # Also respect non-tree solid forward edges (only if they don't create cycles)
    for _ in range(min(8, len(member_ids))):
        changed = False
        for e in g.edges:
            if e.src in member_set and e.dst in member_set and e.style != "dashed":
                if e.src in col and e.dst in col and col[e.dst] <= col[e.src]:
                    # Only push forward if dst is not an ancestor of src
                    if col[e.src] + 1 < len(member_ids):
                        col[e.dst] = col[e.src] + 1
                        changed = True
        if not changed:
            break

    # Compute column widths
    col_widths: dict[int, float] = defaultdict(float)
    for nid in member_ids:
        c = col.get(nid, 0)
        col_widths[c] = max(col_widths[c], g.nodes[nid].w)

    col_gap = 78.0
    row_gap = 26.0
    pad_left = 34.0
    pad_top = 64.0
    pad_right = 38.0
    pad_bottom = 34.0

    col_x: dict[int, float] = {}
    cur_x = pad_left
    max_col = max(col_widths.keys()) if col_widths else 0
    for c in range(max_col + 1):
        col_x[c] = cur_x
        cur_x += col_widths.get(c, 0.0) + col_gap

    # Compute subtree heights recursively for zero overlap
    sub_h: dict[str, float] = {}

    def calc_height(u: str) -> float:
        chs = tree_children.get(u, [])
        if not chs:
            sub_h[u] = g.nodes[u].h
            return sub_h[u]
        total_ch = sum(calc_height(v) for v in chs) + row_gap * (len(chs) - 1)
        sub_h[u] = max(g.nodes[u].h, total_ch)
        return sub_h[u]

    for r in roots:
        calc_height(r)

    def assign_pos(u: str, top_y: float) -> None:
        n = g.nodes[u]
        n.x = col_x[col.get(u, 0)]
        chs = tree_children.get(u, [])
        if not chs:
            n.y = top_y + (sub_h[u] - n.h) / 2.0
            return
        total_ch = sum(sub_h[v] for v in chs) + row_gap * (len(chs) - 1)
        child_y = top_y + (sub_h[u] - total_ch) / 2.0
        for v in chs:
            assign_pos(v, child_y)
            child_y += sub_h[v] + row_gap
        # Vertically center parent against its children's centers
        first_c = g.nodes[chs[0]]
        last_c = g.nodes[chs[-1]]
        mid_y = ((first_c.y + first_c.h / 2.0) + (last_c.y + last_c.h / 2.0)) / 2.0
        n.y = max(top_y, mid_y - n.h / 2.0)

    cur_y = pad_top
    for r in roots:
        assign_pos(r, cur_y)
        cur_y += sub_h[r] + row_gap * 1.4

    # Compute tight bounding box for nested subgraphs (if any) and outer subgraph
    for child_sg_id in sg.children:
        csg = g.subgraphs[child_sg_id]
        if csg.nodes:
            min_x = min(g.nodes[i].x for i in csg.nodes) - 20
            min_y = min(g.nodes[i].y for i in csg.nodes) - 44
            max_x = max(g.nodes[i].x + g.nodes[i].w for i in csg.nodes) + 20
            max_y = max(g.nodes[i].y + g.nodes[i].h for i in csg.nodes) + 20
            csg.x, csg.y, csg.w, csg.h = min_x, min_y, max_x - min_x, max_y - min_y

    max_right = max(g.nodes[i].x + g.nodes[i].w for i in member_ids)
    max_bottom = max(g.nodes[i].y + g.nodes[i].h for i in member_ids)
    title_w, _ = _measure_text(sg.title, 18.0)
    sg.w = max(max_right + pad_right, title_w + 64.0)
    sg.h = max_bottom + pad_bottom
    return sg.w, sg.h


def layout_graph(g: Graph) -> None:
    _size_all_nodes(g)

    outer_sgs = sorted(
        [sg for sg in g.subgraphs.values() if sg.parent is None],
        key=lambda s: s.order,
    )
    free_nodes = [
        n for n in sorted(g.nodes.values(), key=lambda x: x.order)
        if n.outer_subgraph is None and n.id != "ROOT"
    ]

    # Layout each outer subgraph locally
    for sg in outer_sgs:
        _layout_subgraph(g, sg.id)

    root_node = g.nodes.get("ROOT")
    start_x = (root_node.w + 150.0) if root_node else 60.0
    sg_gap_y = 64.0

    # Place outer subgraphs cleanly stacked vertically to the right of ROOT
    cur_y = 40.0
    for sg in outer_sgs:
        sg.x = start_x
        sg.y = cur_y
        # Offset all member nodes & child subgraphs
        member_ids = list(sg.nodes)
        for csg_id in sg.children:
            csg = g.subgraphs[csg_id]
            csg.x += sg.x
            csg.y += sg.y
            member_ids.extend(csg.nodes)
        for nid in member_ids:
            g.nodes[nid].x += sg.x
            g.nodes[nid].y += sg.y
        cur_y += sg.h + sg_gap_y

    # Place any ungrouped nodes below
    for n in free_nodes:
        n.x = start_x
        n.y = cur_y
        cur_y += n.h + 32.0

    # Position ROOT vertically centered on the left
    if root_node:
        total_bottom = max(40.0 + root_node.h, cur_y - sg_gap_y)
        root_node.x = 40.0
        root_node.y = max(40.0, (40.0 + total_bottom) / 2.0 - root_node.h / 2.0)


def _stable_id(seed_str: str) -> str:
    return hashlib.sha1(seed_str.encode("utf-8")).hexdigest()[:16]


def _stable_seed(seed_str: str) -> int:
    return int(hashlib.sha1(seed_str.encode("utf-8")).hexdigest()[:8], 16) % 2_000_000_000


def _base_element(
    eid: str,
    etype: str,
    x: float,
    y: float,
    w: float,
    h: float,
    now_ms: int,
    *,
    roughness: int = 1,
) -> dict[str, Any]:
    return {
        "id": eid,
        "type": etype,
        "x": round(x, 2),
        "y": round(y, 2),
        "width": round(w, 2),
        "height": round(h, 2),
        "angle": 0,
        "strokeColor": "#1D1D1F",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1.5,
        "strokeStyle": "solid",
        "roughness": roughness,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": _stable_seed(eid + ":seed"),
        "version": 1,
        "versionNonce": _stable_seed(eid + ":nonce"),
        "isDeleted": False,
        "boundElements": [],
        "updated": now_ms,
        "link": None,
        "locked": False,
    }


def _anchor_point(src: Node, dst: Node) -> tuple[tuple[float, float], tuple[float, float]]:
    sx, sy = src.x + src.w / 2.0, src.y + src.h / 2.0
    dx, dy = dst.x + dst.w / 2.0, dst.y + dst.h / 2.0
    vx, vy = dx - sx, dy - sy

    if abs(vx) >= abs(vy) * 0.7:
        if vx >= 0:
            return (src.x + src.w, sy), (dst.x, dy)
        return (src.x, sy), (dst.x + dst.w, dy)
    if vy >= 0:
        return (sx, src.y + src.h), (dx, dst.y)
    return (sx, src.y), (dx, dst.y + dst.h)


def _segment_hits_box(
    p1: tuple[float, float],
    p2: tuple[float, float],
    bx: float,
    by: float,
    bw: float,
    bh: float,
    margin: float = 4.0,
) -> bool:
    """Liang-Barsky line-segment vs AABB intersection test."""
    x0, y0 = p1
    x1, y1 = p2
    xmin, ymin = bx - margin, by - margin
    xmax, ymax = bx + bw + margin, by + bh + margin
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if abs(p) < 1e-9:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return False
                if r < t1:
                    t1 = r
    return t0 <= t1


def _route_hits_count(pts: list[tuple[float, float]], obstacles: list[Node]) -> int:
    hits = 0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        for ob in obstacles:
            if _segment_hits_box(a, b, ob.x, ob.y, ob.w, ob.h, margin=4.0):
                hits += 1
    return hits


def route_arrow(sn: Node, dn: Node, all_nodes: dict[str, Node]) -> list[tuple[float, float]]:
    """Compute a clean arrow polyline; automatically detours orthogonally if straight line hits any node."""
    p1, p2 = _anchor_point(sn, dn)
    obstacles = [n for nid, n in all_nodes.items() if nid != sn.id and nid != dn.id]
    direct = [p1, p2]
    if _route_hits_count(direct, obstacles) == 0:
        return direct

    x1, y1 = p1
    x2, y2 = p2
    mid_x = (x1 + x2) / 2.0
    mid_y = (y1 + y2) / 2.0

    # Collect blocking boxes to compute clean outer top/bottom/gutter detour channels
    blockers = [ob for ob in obstacles if _segment_hits_box(p1, p2, ob.x, ob.y, ob.w, ob.h, margin=6.0)]
    top_channel = (min(ob.y for ob in blockers) - 24.0) if blockers else (min(y1, y2) - 40.0)
    bot_channel = (max(ob.y + ob.h for ob in blockers) + 24.0) if blockers else (max(y1, y2) + 40.0)
    right_gutter = (max(ob.x + ob.w for ob in blockers) + 28.0) if blockers else (max(x1, x2) + 40.0)
    left_gutter = (min(ob.x for ob in blockers) - 28.0) if blockers else (min(x1, x2) - 40.0)

    candidates: list[list[tuple[float, float]]] = [
        [p1, (mid_x, y1), (mid_x, y2), p2],
        [p1, (x1, top_channel), (x2, top_channel), p2],
        [p1, (x1, bot_channel), (x2, bot_channel), p2],
        [p1, (x1 + 24.0, y1), (x1 + 24.0, top_channel), (x2 - 24.0, top_channel), (x2 - 24.0, y2), p2],
        [p1, (x1 + 24.0, y1), (x1 + 24.0, bot_channel), (x2 - 24.0, bot_channel), (x2 - 24.0, y2), p2],
        [p1, (right_gutter, y1), (right_gutter, y2), p2],
        [p1, (left_gutter, y1), (left_gutter, y2), p2],
    ]

    def route_cost(pts: list[tuple[float, float]]) -> tuple[int, float]:
        h = _route_hits_count(pts, obstacles)
        length = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
        return (h, length)

    best = min(candidates, key=route_cost)
    if route_cost(best)[0] < route_cost(direct)[0]:
        return best
    return direct


def compute_arrow_routes(g: Graph) -> list[tuple[Edge, list[tuple[float, float]]]]:
    """Return routed polylines for all valid edges in a laid-out graph."""
    routes: list[tuple[Edge, list[tuple[float, float]]]] = []
    for e in g.edges:
        if e.src in g.nodes and e.dst in g.nodes:
            routes.append((e, route_arrow(g.nodes[e.src], g.nodes[e.dst], g.nodes)))
    return routes


def to_excalidraw(g: Graph, *, style_mode: str = "hand-drawn") -> dict[str, Any]:
    """Compile laid-out graph to native Excalidraw v2 JSON.

    style_mode:
      - "hand-drawn" (default): authentic Excalidraw look (roughness=1, fontFamily=5 Excalifont)
      - "clean": crisp architectural look (roughness=0, fontFamily=2 Helvetica)
    """
    layout_graph(g)
    now_ms = int(time.time() * 1000)
    roughness = 0 if style_mode == "clean" else 1
    font_family = 2 if style_mode == "clean" else 5
    elements: list[dict[str, Any]] = []
    node_rect_map: dict[str, dict[str, Any]] = {}

    # 1. Subgraph containers (back layer)
    all_sgs = sorted(g.subgraphs.values(), key=lambda s: (0 if s.parent is None else 1, s.order))
    for sg in all_sgs:
        if sg.w <= 0 or sg.h <= 0:
            continue
        rid = _stable_id(f"sg_rect:{sg.id}")
        rect = _base_element(rid, "rectangle", sg.x, sg.y, sg.w, sg.h, now_ms, roughness=roughness)
        rect["backgroundColor"] = sg.style.get("fill", "#FFFFFF")
        rect["strokeColor"] = sg.style.get("stroke", "#D1D5DB")
        rect["strokeWidth"] = float(sg.style.get("stroke_width", 1))
        rect["strokeStyle"] = "dashed"
        rect["roundness"] = {"type": 3}
        elements.append(rect)

        tid = _stable_id(f"sg_title:{sg.id}")
        fs = 18
        tw, th = _measure_text(sg.title, fs)
        txt = _base_element(tid, "text", sg.x + 18, sg.y + 14, tw + 8, th, now_ms, roughness=roughness)
        txt["strokeColor"] = sg.style.get("color", "#3A3A3C")
        txt["text"] = sg.title
        txt["originalText"] = sg.title
        txt["fontSize"] = fs
        txt["fontFamily"] = font_family
        txt["textAlign"] = "left"
        txt["verticalAlign"] = "top"
        txt["containerId"] = None
        txt["autoResize"] = True
        txt["lineHeight"] = 1.25
        elements.append(txt)

    # 2. Node rectangles + bound text
    for n in sorted(g.nodes.values(), key=lambda x: x.order):
        st = _resolve_node_style(g, n)
        rid = _stable_id(f"node_rect:{n.id}")
        tid = _stable_id(f"node_text:{n.id}")
        fs = int(st.get("font_size", 16))
        tw, th = _measure_text(n.label, fs)

        rect = _base_element(rid, "rectangle", n.x, n.y, n.w, n.h, now_ms, roughness=roughness)
        rect["backgroundColor"] = st.get("fill", "#FFFFFF")
        rect["strokeColor"] = st.get("stroke", "#E5E5E5")
        rect["strokeWidth"] = float(st.get("stroke_width", 1.5))
        rect["strokeStyle"] = "dashed" if st.get("dashed") else "solid"
        rect["roundness"] = {"type": 3} if n.shape == "round" else None
        rect["boundElements"] = [{"id": tid, "type": "text"}]
        node_rect_map[n.id] = rect
        elements.append(rect)

        text_align = "center" if n.id == "ROOT" else "left"
        tx = n.x + (n.w - tw) / 2.0 if text_align == "center" else n.x + 16.0
        ty = n.y + (n.h - th) / 2.0
        txt = _base_element(tid, "text", tx, ty, min(n.w - 24, tw + 4), th, now_ms, roughness=roughness)
        txt["strokeColor"] = st.get("color", "#3A3A3C")
        txt["text"] = n.label
        txt["originalText"] = n.label
        txt["fontSize"] = fs
        txt["fontFamily"] = font_family
        txt["textAlign"] = text_align
        txt["verticalAlign"] = "middle"
        txt["containerId"] = rid
        txt["autoResize"] = True
        txt["lineHeight"] = 1.25
        elements.append(txt)

    # 3. Arrows + optional bound edge labels (using obstacle-avoiding routing)
    for e, route_pts in compute_arrow_routes(g):
        if e.src not in node_rect_map or e.dst not in node_rect_map:
            continue
        s_rect = node_rect_map[e.src]
        d_rect = node_rect_map[e.dst]
        x1, y1 = route_pts[0]
        rel_pts = [[round(px - x1, 2), round(py - y1, 2)] for px, py in route_pts]
        xs = [p[0] for p in rel_pts]
        ys = [p[1] for p in rel_pts]
        bw = max(xs) - min(xs)
        bh = max(ys) - min(ys)

        aid = _stable_id(f"edge:{e.order}:{e.src}:{e.dst}")
        arrow = _base_element(aid, "arrow", x1, y1, bw, bh, now_ms, roughness=roughness)
        is_strong_labeled = (e.style != "dashed" and bool(e.label))
        arrow["strokeColor"] = "#002FA7" if is_strong_labeled else "#8E8E93"
        arrow["strokeWidth"] = 2.0 if (e.style == "thick" or is_strong_labeled) else 1.5
        arrow["strokeStyle"] = "dashed" if e.style == "dashed" else "solid"
        is_multi_seg = len(rel_pts) > 2
        # Never apply curved Catmull-Rom roundness (type 2) to multi-point orthogonal detours,
        # otherwise Excalidraw twists/loops splines around 90-degree corners.
        arrow["roundness"] = None if is_multi_seg else {"type": 2}
        arrow["elbowed"] = False
        arrow["points"] = rel_pts
        arrow["lastCommittedPoint"] = None
        if is_multi_seg:
            arrow["startBinding"] = None
            arrow["endBinding"] = None
        else:
            arrow["startBinding"] = {"elementId": s_rect["id"], "focus": 0, "gap": 4}
            arrow["endBinding"] = {"elementId": d_rect["id"], "focus": 0, "gap": 4}
        arrow["startArrowhead"] = None
        arrow["endArrowhead"] = "arrow"

        if not is_multi_seg:
            s_rect["boundElements"].append({"id": aid, "type": "arrow"})
            d_rect["boundElements"].append({"id": aid, "type": "arrow"})

        if e.label:
            lid = _stable_id(f"edge_lbl:{e.order}:{e.src}:{e.dst}")
            arrow["boundElements"].append({"id": lid, "type": "text"})
            elements.append(arrow)

            lfs = 14
            ltw, lth = _measure_text(e.label, lfs)
            # Place label at midpoint of the longest segment of the routed arrow
            best_seg = max(
                range(len(route_pts) - 1),
                key=lambda idx: math.hypot(route_pts[idx + 1][0] - route_pts[idx][0], route_pts[idx + 1][1] - route_pts[idx][1]),
            )
            mx = (route_pts[best_seg][0] + route_pts[best_seg + 1][0]) / 2.0
            my = (route_pts[best_seg][1] + route_pts[best_seg + 1][1]) / 2.0
            lbl = _base_element(lid, "text", mx - ltw / 2.0, my - lth / 2.0, ltw + 6, lth, now_ms, roughness=roughness)
            lbl["strokeColor"] = "#3A3A3C"
            lbl["backgroundColor"] = "#FFFFFF"
            lbl["text"] = e.label
            lbl["originalText"] = e.label
            lbl["fontSize"] = lfs
            lbl["fontFamily"] = font_family
            lbl["textAlign"] = "center"
            lbl["verticalAlign"] = "middle"
            lbl["containerId"] = aid
            lbl["autoResize"] = True
            lbl["lineHeight"] = 1.2
            elements.append(lbl)
        else:
            elements.append(arrow)

    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {
            "gridSize": None,
            "viewBackgroundColor": "#ffffff",
        },
        "files": {},
    }


def run(input_path: str, output_path: str | None = None, audit_only: bool = False) -> dict[str, Any]:
    in_p = Path(input_path)
    if not in_p.exists():
        raise FileNotFoundError(f"未找到 Mermaid 文件：{input_path}")
    raw = in_p.read_text(encoding="utf-8")
    # Strip surrounding markdown code fences if present
    fence = re.search(r"```mermaid\s*\n(.*?)\n```", raw, re.DOTALL | re.IGNORECASE)
    mermaid_src = fence.group(1) if fence else raw

    g = parse_mermaid(mermaid_src)
    report = audit_graph(g)

    if not audit_only:
        out_p = Path(output_path) if output_path else in_p.with_suffix(".excalidraw")
        out_p.parent.mkdir(parents=True, exist_ok=True)
        excalidraw_doc = to_excalidraw(g)
        out_p.write_text(json.dumps(excalidraw_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output"] = str(out_p)
        report["excalidraw_elements"] = len(excalidraw_doc["elements"])

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if "args" in globals() and isinstance(globals()["args"], dict):
    _a = globals()["args"]
    run(_a["input"], output_path=_a.get("output"), audit_only=bool(_a.get("audit_only", False)))
elif __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cartograph Mermaid Auditor & Excalidraw v2 Compiler")
    parser.add_argument("input", help="Path to .mmd or Markdown file containing ```mermaid block")
    parser.add_argument("-o", "--output", default=None, help="Output .excalidraw file path")
    parser.add_argument("--audit-only", action="store_true", help="Only run static audit without writing output")
    ns = parser.parse_args()
    try:
        res = run(ns.input, output_path=ns.output, audit_only=ns.audit_only)
        if not res["valid"]:
            sys.exit(1)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
