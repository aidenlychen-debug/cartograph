#!/usr/bin/env python3
"""Cartograph Deterministic Evaluation Harness, Tournament Selector & Regression Suite.

Zero external dependencies (Python 3.8+ standard library only).
Provides T0-grade harness engineering for instructional knowledge graphs:
  1. Five-dimension deterministic scoring rubric (0-100):
     - Spec & Localization Compliance (30): syntax, IDs, rules, budget, Chinese-first check
     - Structural & Relation Discipline (25): ROOT->MOD, labels, cross-MOD discipline
     - Geometric Layout & Routing Clarity (20): AABB overlap, containment, arrow-node
       collisions on actual routed polylines, edge crossings, aspect ratio
     - Readability & Typography Density (15): line count, CJK visual width, non-empty
     - Evidence & Auxiliary Fidelity (10): local dashed evidence + key conclusions
  2. Multi-Candidate Tournament Selector (`--tournament`): evaluates 2+ architectural
     candidates head-to-head and promotes the highest-scoring optimal `.mmd` + `.excalidraw`.
  3. Built-in 16-Test Regression Self-Test (`--self-test`).

Dual-mode execution (CLI or Antigravity `run_workflow` ScriptPath):
  CLI:
    python eval_harness.py --self-test
    python eval_harness.py input.mmd [--lang zh|en] [--out-excalidraw out.excalidraw]
    python eval_harness.py --tournament a.mmd b.mmd [c.mmd] --lang zh --out-excalidraw best.excalidraw --out-mmd best.mmd
  Workflow:
    Args={"self_test": True}
    Args={"input": "...", "lang": "zh", "out_excalidraw": "..."}
    Args={"tournament": ["a.mmd", "b.mmd"], "lang": "zh", "out_excalidraw": "...", "out_mmd": "..."}
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


QUALITY_GATE_SCORE = 88.0
VAGUE_LABELS = {"相关", "关联", "有关", "联系", "related", "link"}


def _load_compiler() -> Any:
    here = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    home = Path.home()
    candidates = [
        here / "mermaid_to_excalidraw.py",
        home / ".gemini" / "config" / "skills" / "knowledge-graph-architect" / "scripts" / "mermaid_to_excalidraw.py",
        home / ".agents" / "skills" / "knowledge-graph-architect" / "scripts" / "mermaid_to_excalidraw.py",
    ]
    mod_path = next((p for p in candidates if p.exists()), None)
    if mod_path is None:
        raise FileNotFoundError("Cannot locate sibling mermaid_to_excalidraw.py")
    spec = importlib.util.spec_from_file_location("cartograph_compiler", str(mod_path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cartograph_compiler"] = mod
    spec.loader.exec_module(mod)
    return mod


def _aabb_overlap(ax: float, ay: float, aw: float, ah: float, bx: float, by: float, bw: float, bh: float, margin: float = 0.0) -> bool:
    return not (
        ax + aw + margin <= bx
        or bx + bw + margin <= ax
        or ay + ah + margin <= by
        or by + bh + margin <= ay
    )


def _ccw(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (cy - ay) * (bx - ax) - (by - ay) * (cx - ax)


def _segments_cross(p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float], p4: tuple[float, float]) -> bool:
    if p1 == p3 or p1 == p4 or p2 == p3 or p2 == p4:
        return False
    d1 = _ccw(p1[0], p1[1], p2[0], p2[1], p3[0], p3[1])
    d2 = _ccw(p1[0], p1[1], p2[0], p2[1], p4[0], p4[1])
    d3 = _ccw(p3[0], p3[1], p4[0], p4[1], p1[0], p1[1])
    d4 = _ccw(p3[0], p3[1], p4[0], p4[1], p2[0], p2[1])
    return ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))


def _cjk_line_units(line: str) -> float:
    return sum(1.0 if ord(ch) > 127 else 0.55 for ch in line)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _extract_mermaid(raw: str) -> str:
    fence = re.search(r"```mermaid\s*\n(.*?)\n```", raw, re.DOTALL | re.IGNORECASE)
    return fence.group(1) if fence else raw


def evaluate_mermaid_source(
    mermaid_src: str,
    compiler: Any,
    label: str = "candidate",
    lang: str = "zh",
) -> dict[str, Any]:
    g = compiler.parse_mermaid(mermaid_src)
    audit = compiler.audit_graph(g)
    excalidraw_doc = compiler.to_excalidraw(g)

    # --- Geometric verification on laid-out graph ---
    nodes = list(g.nodes.values())
    node_overlaps = 0
    for i in range(len(nodes)):
        a = nodes[i]
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            if _aabb_overlap(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h, margin=-1.0):
                node_overlaps += 1

    outer_sgs = [sg for sg in g.subgraphs.values() if sg.parent is None and sg.w > 0 and sg.h > 0]
    sg_overlaps = 0
    for i in range(len(outer_sgs)):
        a = outer_sgs[i]
        for j in range(i + 1, len(outer_sgs)):
            b = outer_sgs[j]
            if _aabb_overlap(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h, margin=-1.0):
                sg_overlaps += 1

    outside_container = 0
    for n in nodes:
        if n.outer_subgraph and n.outer_subgraph in g.subgraphs:
            sg = g.subgraphs[n.outer_subgraph]
            if n.x < sg.x - 1 or n.y < sg.y - 1 or (n.x + n.w) > (sg.x + sg.w + 1) or (n.y + n.h) > (sg.y + sg.h + 1):
                outside_container += 1

    # Check routed polylines for crossings AND arrow-through-node collisions
    routed = compiler.compute_arrow_routes(g)
    all_segs: list[tuple[int, tuple[float, float], tuple[float, float]]] = []
    arrow_node_collisions = 0
    for r_idx, (e, pts) in enumerate(routed):
        obstacles = [n for nid, n in g.nodes.items() if nid != e.src and nid != e.dst]
        for k in range(len(pts) - 1):
            p1, p2 = pts[k], pts[k + 1]
            all_segs.append((r_idx, p1, p2))
            for ob in obstacles:
                if compiler._segment_hits_box(p1, p2, ob.x, ob.y, ob.w, ob.h, margin=2.0):
                    arrow_node_collisions += 1

    edge_crossings = 0
    for i in range(len(all_segs)):
        r1, a1, a2 = all_segs[i]
        for j in range(i + 1, len(all_segs)):
            r2, b1, b2 = all_segs[j]
            if r1 != r2 and _segments_cross(a1, a2, b1, b2):
                edge_crossings += 1

    if nodes:
        min_x = min(n.x for n in nodes)
        min_y = min(n.y for n in nodes)
        max_x = max(n.x + n.w for n in nodes)
        max_y = max(n.y + n.h for n in nodes)
        canvas_w = round(max_x - min_x, 1)
        canvas_h = round(max_y - min_y, 1)
        aspect_ratio = round(canvas_w / max(1.0, canvas_h), 2)
    else:
        canvas_w, canvas_h, aspect_ratio = 0.0, 0.0, 1.0

    # --- Readability & Chinese-first localization metrics ---
    over_line_nodes = 0
    over_width_nodes = 0
    empty_label_nodes = 0
    cjk_nodes = 0
    english_only_nodes: list[str] = []
    for n in nodes:
        if not n.label.strip():
            empty_label_nodes += 1
            continue
        lines = n.label.split("\n")
        if len(lines) > 6:
            over_line_nodes += 1
        if any(_cjk_line_units(ln) > 28.0 for ln in lines):
            over_width_nodes += 1
        if _has_cjk(n.label):
            cjk_nodes += 1
        elif re.search(r"[A-Za-z]{4,}", n.label):
            english_only_nodes.append(n.id)

    cjk_node_ratio = round(cjk_nodes / max(1, len(nodes)), 3)
    vague_edge_labels = [e.label for e in g.edges if e.label.strip().lower() in VAGUE_LABELS]
    unlabeled_dashed = sum(1 for e in g.edges if e.style == "dashed" and not e.label.strip())
    key_nodes = sum(1 for n in nodes if n.cls == "key")
    total_edges = max(1, audit["total_edges"])
    cross_mod_ratio = round(audit["cross_mod_edges"] / total_edges, 3)

    # --- 5-Dimension Scoring Rubric (100 pts) ---
    repairs: list[str] = []

    # 1. Spec & Localization Compliance (30)
    s_spec = 30.0
    s_spec -= len(audit["errors"]) * 12.0
    s_spec -= len(audit["warnings"]) * 2.5
    if audit["total_edges"] > 450:
        s_spec -= 3.0
    if lang == "zh" and len(nodes) >= 3 and cjk_node_ratio < 0.85:
        penalty = min(12.0, round((0.85 - cjk_node_ratio) * 20.0, 1))
        s_spec -= penalty
        repairs.append(
            f"[LOCALIZATION] 默认中文模式要求先按中文阅读习惯意译：当前中文节点占比仅 {cjk_node_ratio:.1%}，"
            f"检测到 {len(english_only_nodes)} 个纯英文节点（如 {english_only_nodes[:5]}），请翻译为地道中文并按需括号保留术语。"
        )
    s_spec = max(0.0, round(s_spec, 1))
    for err in audit["errors"]:
        repairs.append(f"[HARD ERROR] {err}")

    # 2. Structural & Relation Discipline (25)
    s_rel = 25.0
    if vague_edge_labels:
        s_rel -= min(8.0, len(vague_edge_labels) * 2.5)
        repairs.append(f"[RELATION] 发现 {len(vague_edge_labels)} 条泛化标签（如 '相关'），请改为具体关系（证据/案例/因果/解释）。")
    if unlabeled_dashed:
        s_rel -= min(6.0, unlabeled_dashed * 2.0)
        repairs.append(f"[RELATION] 有 {unlabeled_dashed} 条局部虚线缺少关系标签。")
    if cross_mod_ratio > 0.18:
        s_rel -= min(8.0, (cross_mod_ratio - 0.18) * 30.0)
        repairs.append(f"[RELATION] 跨 MOD 连线占比偏高 ({cross_mod_ratio:.1%})，建议清理非必要跨区松散关联。")
    if audit["logic_edges"] == 0 and len(nodes) > 6:
        s_rel -= 5.0
        repairs.append("[RELATION] 缺少显式横向强逻辑递进边。")
    s_rel = max(0.0, round(s_rel, 1))

    # 3. Geometric Layout & Visual Clarity (20)
    s_geo = 20.0
    if node_overlaps > 0:
        s_geo -= min(12.0, node_overlaps * 4.0)
        repairs.append(f"[GEOMETRY] 检测到 {node_overlaps} 处节点重叠。")
    if sg_overlaps > 0:
        s_geo -= min(8.0, sg_overlaps * 4.0)
        repairs.append(f"[GEOMETRY] 检测到 {sg_overlaps} 处外层分组框重叠。")
    if outside_container > 0:
        s_geo -= min(6.0, outside_container * 2.0)
        repairs.append(f"[GEOMETRY] 有 {outside_container} 个节点超出所属分组容器边界。")
    if arrow_node_collisions > 0:
        s_geo -= min(6.0, arrow_node_collisions * 2.0)
        repairs.append(f"[GEOMETRY] 有 {arrow_node_collisions} 处箭头穿箱碰撞，建议缩短跨行连线或调整层级归属。")
    crossing_rate = edge_crossings / max(1, len(routed))
    if crossing_rate > 0.35:
        s_geo -= min(5.0, round((crossing_rate - 0.35) * 8.0, 1))
        repairs.append(f"[GEOMETRY] 箭头交叉率偏高 ({edge_crossings} 处交叉)，建议精简跨分支长连线。")
    if aspect_ratio > 4.5 or aspect_ratio < 0.2:
        s_geo -= 2.0
        repairs.append(f"[GEOMETRY] 画布宽高比 ({aspect_ratio}) 较为极端。")
    s_geo = max(0.0, round(s_geo, 1))

    # 4. Readability & Typography Density (15)
    s_read = 15.0
    if over_line_nodes > 0:
        s_read -= min(6.0, over_line_nodes * 1.5)
        repairs.append(f"[READABILITY] 有 {over_line_nodes} 个节点超过 6 行，建议拆分或精简。")
    if over_width_nodes > 0:
        s_read -= min(6.0, over_width_nodes * 1.0)
        repairs.append(f"[READABILITY] 有 {over_width_nodes} 个节点存在超长单行（>28 汉字宽度），建议用 <br/> 语义换行。")
    if empty_label_nodes > 0:
        s_read -= min(5.0, empty_label_nodes * 2.5)
        repairs.append(f"[READABILITY] 有 {empty_label_nodes} 个空文本节点。")
    s_read = max(0.0, round(s_read, 1))

    # 5. Evidence & Auxiliary Fidelity (10)
    s_evid = 10.0
    if audit["aux_dashed_edges"] == 0 and len(nodes) > 8:
        s_evid -= 4.0
        repairs.append("[FIDELITY] 缺少局部辅助虚线（证据/案例/解释），请确认未误删局部论据。")
    if key_nodes == 0 and len(nodes) > 5:
        s_evid -= 3.0
        repairs.append("[FIDELITY] 未使用 `key` 样式高亮核心结论节点。")
    s_evid = max(0.0, round(s_evid, 1))

    total_score = round(s_spec + s_rel + s_geo + s_read + s_evid, 1)
    lang_ok = (lang != "zh") or (len(nodes) < 3) or (cjk_node_ratio >= 0.85)
    gate_passed = (
        audit["valid"]
        and lang_ok
        and node_overlaps == 0
        and sg_overlaps == 0
        and outside_container == 0
        and arrow_node_collisions == 0
        and total_score >= QUALITY_GATE_SCORE
    )

    return {
        "candidate": label,
        "lang": lang,
        "gate_passed": gate_passed,
        "total_score": total_score,
        "scores": {
            "spec_compliance": s_spec,
            "relation_discipline": s_rel,
            "geometric_layout": s_geo,
            "readability_density": s_read,
            "evidence_fidelity": s_evid,
        },
        "audit": audit,
        "geometry": {
            "node_overlaps": node_overlaps,
            "subgraph_overlaps": sg_overlaps,
            "outside_container_nodes": outside_container,
            "arrow_node_collisions": arrow_node_collisions,
            "edge_crossings": edge_crossings,
            "canvas_width": canvas_w,
            "canvas_height": canvas_h,
            "aspect_ratio": aspect_ratio,
            "excalidraw_elements": len(excalidraw_doc["elements"]),
        },
        "readability": {
            "over_line_nodes": over_line_nodes,
            "over_width_nodes": over_width_nodes,
            "vague_edge_labels": len(vague_edge_labels),
            "unlabeled_dashed": unlabeled_dashed,
            "key_nodes": key_nodes,
            "cross_mod_ratio": cross_mod_ratio,
            "cjk_node_ratio": cjk_node_ratio,
            "english_only_nodes": len(english_only_nodes),
        },
        "repairs": repairs,
        "_excalidraw_doc": excalidraw_doc,
        "_mermaid_src": mermaid_src,
    }


def _strip_internal(res: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def run_tournament(
    paths: list[str],
    out_excalidraw: str | None = None,
    out_mmd: str | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    compiler = _load_compiler()
    evaluated: list[dict[str, Any]] = []
    for p_str in paths:
        p = Path(p_str)
        if not p.exists():
            raise FileNotFoundError(f"Candidate file not found: {p_str}")
        src = _extract_mermaid(p.read_text(encoding="utf-8"))
        res = evaluate_mermaid_source(src, compiler, label=p.name, lang=lang)
        res["path"] = str(p)
        evaluated.append(res)

    ranked = sorted(
        evaluated,
        key=lambda r: (
            1 if r["gate_passed"] else 0,
            1 if r["audit"]["valid"] else 0,
            1 if r["geometry"]["node_overlaps"] == 0 and r["geometry"]["subgraph_overlaps"] == 0 else 0,
            -r["geometry"]["arrow_node_collisions"],
            r["total_score"],
            -r["geometry"]["edge_crossings"],
        ),
        reverse=True,
    )
    winner = ranked[0]

    artifacts: dict[str, str] = {}
    if out_excalidraw:
        out_e = Path(out_excalidraw)
        out_e.parent.mkdir(parents=True, exist_ok=True)
        out_e.write_text(json.dumps(winner["_excalidraw_doc"], ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts["excalidraw"] = str(out_e)
    if out_mmd:
        out_m = Path(out_mmd)
        out_m.parent.mkdir(parents=True, exist_ok=True)
        if Path(winner["path"]).resolve() != out_m.resolve():
            shutil.copy2(winner["path"], out_m)
        artifacts["mermaid"] = str(out_m)

    summary = {
        "mode": "tournament" if len(paths) > 1 else "single",
        "lang": lang,
        "quality_gate_threshold": QUALITY_GATE_SCORE,
        "winner": winner["candidate"],
        "winner_score": winner["total_score"],
        "winner_gate_passed": winner["gate_passed"],
        "artifacts": artifacts,
        "leaderboard": [
            {
                "rank": idx + 1,
                "candidate": r["candidate"],
                "total_score": r["total_score"],
                "gate_passed": r["gate_passed"],
                "valid": r["audit"]["valid"],
                "nodes": r["audit"]["nodes"],
                "total_edges": r["audit"]["total_edges"],
                "node_overlaps": r["geometry"]["node_overlaps"],
                "arrow_node_collisions": r["geometry"]["arrow_node_collisions"],
                "edge_crossings": r["geometry"]["edge_crossings"],
                "cjk_node_ratio": r["readability"]["cjk_node_ratio"],
                "scores": r["scores"],
                "repairs": r["repairs"],
            }
            for idx, r in enumerate(ranked)
        ],
        "winner_detail": _strip_internal(winner),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def run_self_test() -> dict[str, Any]:
    compiler = _load_compiler()
    here = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    home = Path.home()
    golden_candidates = [
        here.parent / "examples" / "golden-reference.mmd",
        home / ".gemini" / "config" / "skills" / "knowledge-graph-architect" / "examples" / "golden-reference.mmd",
        home / ".agents" / "skills" / "knowledge-graph-architect" / "examples" / "golden-reference.mmd",
    ]
    golden_path = next((p for p in golden_candidates if p.exists()), None)
    if golden_path is None:
        raise FileNotFoundError("Cannot locate examples/golden-reference.mmd")
    golden_src = golden_path.read_text(encoding="utf-8")

    tests: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        tests.append({"test": name, "passed": bool(condition), "detail": detail})

    # Test 1: Golden fixture passes gate with high score, 0 overlaps & 0 arrow collisions
    r1 = evaluate_mermaid_source(golden_src, compiler, label="golden", lang="zh")
    check(
        "golden_passes_gate",
        r1["gate_passed"] and r1["total_score"] >= 90.0 and r1["geometry"]["node_overlaps"] == 0 and r1["geometry"]["arrow_node_collisions"] == 0,
        f"score={r1['total_score']}, overlaps={r1['geometry']['node_overlaps']}, arrow_hits={r1['geometry']['arrow_node_collisions']}",
    )

    # Test 2: Duplicate ID rejected
    dup_src = golden_src + '\n    K_01("重复节点")\n'
    r2 = evaluate_mermaid_source(dup_src, compiler, label="dup_id", lang="zh")
    check("rejects_duplicate_node_id", not r2["audit"]["valid"], f"errors={r2['audit']['errors']}")

    # Test 3: Edge targeting subgraph ID rejected
    sg_edge_src = golden_src + "\n    ROOT --> B01\n"
    r3 = evaluate_mermaid_source(sg_edge_src, compiler, label="sg_edge", lang="zh")
    check("rejects_subgraph_endpoint_edge", not r3["audit"]["valid"], f"errors={r3['audit']['errors']}")

    # Test 4: Forbidden internal label rejected
    bad_lbl_src = golden_src.replace("模块一：反馈回路与系统动力学", "认知块1：系统动力学")
    r4 = evaluate_mermaid_source(bad_lbl_src, compiler, label="forbidden_label", lang="zh")
    check("rejects_forbidden_internal_term", not r4["audit"]["valid"], f"errors={r4['audit']['errors']}")

    # Test 5: Vague '相关' label penalized
    vague_src = golden_src.replace("-.->|案例|", "-.->|相关|")
    r5 = evaluate_mermaid_source(vague_src, compiler, label="vague_label", lang="zh")
    check(
        "penalizes_vague_edge_label",
        r5["scores"]["relation_discipline"] < r1["scores"]["relation_discipline"],
        f"golden_rel={r1['scores']['relation_discipline']}, vague_rel={r5['scores']['relation_discipline']}",
    )

    # Test 6: Tournament ranks clean golden strictly above degraded variant
    check(
        "tournament_ranks_golden_above_vague",
        r1["total_score"] > r5["total_score"],
        f"golden={r1['total_score']} > vague={r5['total_score']}",
    )

    # Test 7: Untranslated English-only diagram fails Chinese-first gate when lang="zh"
    en_src = """flowchart LR
    classDef root fill:#002FA7,stroke:#002FA7,color:#FFFFFF
    classDef mod fill:#F5F5F7,stroke:#4B5563,color:#1D1D1F
    classDef k fill:#FFFFFF,stroke:#4B5563,color:#3A3A3C
    ROOT["System Thinking Overview"]
    subgraph B01["Feedback Loop Basics"]
        MOD_01["01 | Core Dynamics"]
        K_01("Reinforcing loops amplify change over time")
        K_02("Balancing loops stabilize system behavior")
    end
    ROOT --> MOD_01
    MOD_01 --> K_01
    K_01 -->|balances| K_02
    class ROOT root
    class MOD_01 mod
    class K_01,K_02 k
    style B01 fill:#FFFFFF,stroke:#4B5563,stroke-width:1.5px,stroke-dasharray:6 4,color:#3A3A3C
"""
    r7 = evaluate_mermaid_source(en_src, compiler, label="untranslated_en", lang="zh")
    check(
        "rejects_untranslated_english_in_zh_mode",
        (not r7["gate_passed"]) and r7["readability"]["cjk_node_ratio"] == 0.0,
        f"gate={r7['gate_passed']}, cjk_ratio={r7['readability']['cjk_node_ratio']}, score={r7['total_score']}",
    )

    # Test 8: Obstacle-avoiding detour routing avoids passing through intermediate node
    detour_src = """flowchart LR
    classDef root fill:#002FA7,stroke:#002FA7,color:#FFFFFF
    classDef mod fill:#F5F5F7,stroke:#D1D5DB,color:#1D1D1F
    classDef k fill:#FFFFFF,stroke:#E5E5E5,color:#3A3A3C
    classDef key fill:#FFFFFF,stroke:#002FA7,color:#002FA7
    classDef note fill:#FFFFFF,stroke:#D1D5DB,stroke-dasharray:4 4,color:#3A3A3C
    ROOT["绕障路由自测"]
    subgraph B01["三步推演与跨步注释"]
        MOD_01["01｜推演链"]
        K_01("第一步：提出假设")
        K_02("第二步：实验验证")
        K_03["第三步：核心结论"]
        E_01("补充证据：跳过中间节点直指结论")
    end
    ROOT --> MOD_01
    MOD_01 --> K_01
    K_01 -->|验证| K_02
    K_02 -->|得出| K_03
    K_01 -.->|远距回指| K_03
    E_01 -.->|证据| K_03
    class ROOT root
    class MOD_01 mod
    class K_01,K_02 k
    class K_03 key
    class E_01 note
    style B01 fill:#FFFFFF,stroke:#D1D5DB,stroke-width:1px,stroke-dasharray:6 4,color:#3A3A3C
"""
    r8 = evaluate_mermaid_source(detour_src, compiler, label="detour_test", lang="zh")
    check(
        "obstacle_avoiding_routing_zero_collisions",
        r8["geometry"]["arrow_node_collisions"] == 0,
        f"arrow_hits={r8['geometry']['arrow_node_collisions']}, score={r8['total_score']}",
    )

    # Tests 9-12: Real-Excalidraw zero-interference deconfliction regression suite
    import excalidraw_deconflict as _ed

    # Synthetic Excalidraw fixture reproducing all 3 real-world defects:
    # (a) wall-hugging elbow bend 18px from dst box causing bound CJK label overlap
    # (b) tight CJK node width causing node_text_overflows
    # (c) vertical node-vs-node overlap between n1 and n3
    synth_doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": [
            {"id": "n1", "type": "rectangle", "x": 100, "y": 50, "width": 140, "height": 80, "isDeleted": False},
            {"id": "t1", "type": "text", "containerId": "n1", "x": 105, "y": 65, "width": 130, "height": 50, "fontSize": 20, "lineHeight": 1.25, "text": "核心机制与边界条件\n动态平衡法则", "isDeleted": False},
            {"id": "n2", "type": "rectangle", "x": 420, "y": 130, "width": 150, "height": 90, "isDeleted": False},
            {"id": "t2", "type": "text", "containerId": "n2", "x": 425, "y": 145, "width": 140, "height": 50, "fontSize": 20, "lineHeight": 1.25, "text": "系统结构与高杠杆干预\n核心结论", "isDeleted": False},
            {"id": "n3", "type": "rectangle", "x": 100, "y": 115, "width": 140, "height": 70, "isDeleted": False},
            {"id": "t3", "type": "text", "containerId": "n3", "x": 105, "y": 130, "width": 130, "height": 25, "fontSize": 20, "lineHeight": 1.25, "text": "重叠测试节点", "isDeleted": False},
            {
                "id": "a1", "type": "arrow", "x": 240.5, "y": 90, "width": 179.0, "height": 85,
                "points": [[0, 0], [161.5, 0], [161.5, 85], [179.0, 85]],
                "elbowed": True, "roundness": None,
                "startBinding": {"elementId": "n1", "focus": 0, "gap": 1},
                "endBinding": {"elementId": "n2", "focus": 0, "gap": 1},
                "isDeleted": False,
            },
            {
                "id": "tl1", "type": "text", "containerId": "a1", "x": 342, "y": 120, "width": 120, "height": 25,
                "fontSize": 20, "lineHeight": 1.25, "text": "推导核心结论", "isDeleted": False,
            },
        ],
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    before_deconf = _ed.audit_excalidraw(synth_doc)
    _ed.deconflict_excalidraw(synth_doc)
    after_deconf = _ed.audit_excalidraw(synth_doc)

    check(
        "deconflict_fixes_wall_hugging_elbow_label",
        before_deconf["label_vs_node_overlaps"] >= 1 and after_deconf["label_vs_node_overlaps"] == 0,
        f"before={before_deconf['label_vs_node_overlaps']} -> after={after_deconf['label_vs_node_overlaps']}",
    )
    check(
        "deconflict_fixes_cjk_node_text_overflow",
        before_deconf["node_text_overflows"] >= 1 and after_deconf["node_text_overflows"] == 0,
        f"before={before_deconf['node_text_overflows']} -> after={after_deconf['node_text_overflows']}",
    )
    check(
        "deconflict_fixes_node_vs_node_overlap",
        before_deconf["node_vs_node_overlaps"] >= 1 and after_deconf["node_vs_node_overlaps"] == 0,
        f"before={before_deconf['node_vs_node_overlaps']} -> after={after_deconf['node_vs_node_overlaps']}",
    )
    check(
        "deconflict_preserves_orthogonality_and_zero_interference",
        after_deconf["orthogonal_ratio"] == 1.0 and after_deconf["zero_interference"] is True,
        f"ortho={after_deconf['orthogonal_ratio']}, zero_interference={after_deconf['zero_interference']}",
    )

    # Tests 13-14: X-crossing label-vs-other-arrow + coincident tracks + clipped subgraph title band
    xcross_doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": [
            {"id": "sg1", "type": "rectangle", "x": 40, "y": 20, "width": 820, "height": 560, "isDeleted": False},
            {"id": "tb1", "type": "rectangle", "x": 180, "y": 25, "width": 460, "height": 35, "strokeColor": "transparent", "isDeleted": False},
            {"id": "tbt1", "type": "text", "containerId": "tb1", "x": 190, "y": 30, "width": 440, "height": 25, "fontSize": 20, "lineHeight": 1.25, "text": "第一章：2020/2024/2026 系统架构与反馈机制总览", "isDeleted": False},
            {"id": "na", "type": "rectangle", "x": 80, "y": 100, "width": 200, "height": 90, "isDeleted": False},
            {"id": "ta", "type": "text", "containerId": "na", "x": 95, "y": 130, "width": 170, "height": 25, "fontSize": 18, "lineHeight": 1.25, "text": "核心前置条件", "isDeleted": False},
            {"id": "nb", "type": "rectangle", "x": 80, "y": 380, "width": 200, "height": 90, "isDeleted": False},
            {"id": "tb", "type": "text", "containerId": "nb", "x": 95, "y": 410, "width": 170, "height": 25, "fontSize": 18, "lineHeight": 1.25, "text": "辅助约束边界", "isDeleted": False},
            {"id": "nc", "type": "rectangle", "x": 490, "y": 240, "width": 200, "height": 90, "isDeleted": False},
            {"id": "tc", "type": "text", "containerId": "nc", "x": 505, "y": 270, "width": 170, "height": 25, "fontSize": 18, "lineHeight": 1.25, "text": "数据与反例", "isDeleted": False},
            {"id": "nd", "type": "rectangle", "x": 490, "y": 410, "width": 200, "height": 90, "isDeleted": False},
            {"id": "td", "type": "text", "containerId": "nd", "x": 505, "y": 440, "width": 170, "height": 25, "fontSize": 18, "lineHeight": 1.25, "text": "核心系统结论", "isDeleted": False},
            {
                "id": "ax1", "type": "arrow", "x": 280.5, "y": 145, "width": 209.0, "height": 310,
                "points": [[0, 0], [104.5, 0], [104.5, 310], [209.0, 310]],
                "elbowed": True, "roundness": None,
                "startBinding": {"elementId": "na", "focus": 0, "gap": 1},
                "endBinding": {"elementId": "nd", "focus": 0, "gap": 1},
                "isDeleted": False,
            },
            {
                "id": "tlx1", "type": "text", "containerId": "ax1", "x": 350, "y": 290, "width": 68, "height": 20,
                "fontSize": 16, "lineHeight": 1.25, "text": "交叉路径", "isDeleted": False,
            },
            {
                "id": "ax2", "type": "arrow", "x": 280.5, "y": 425, "width": 209.0, "height": 140,
                "points": [[0, 0], [106.5, 0], [106.5, -140], [209.0, -140]],
                "elbowed": True, "roundness": None,
                "startBinding": {"elementId": "nb", "focus": 0, "gap": 1},
                "endBinding": {"elementId": "nc", "focus": 0, "gap": 1},
                "isDeleted": False,
            },
            {
                "id": "tlx2", "type": "text", "containerId": "ax2", "x": 370, "y": 345, "width": 36, "height": 20,
                "fontSize": 16, "lineHeight": 1.25, "text": "反例", "isDeleted": False,
            },
        ],
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    bx = _ed.audit_excalidraw(xcross_doc)
    _ed.deconflict_excalidraw(xcross_doc)
    ax = _ed.audit_excalidraw(xcross_doc)

    check(
        "deconflict_fixes_x_crossing_arrow_vs_label",
        bx["label_vs_other_arrow_collisions"] >= 1
        and bx["coincident_vertical_tracks"] >= 1
        and ax["label_vs_other_arrow_collisions"] == 0
        and ax["coincident_vertical_tracks"] == 0,
        f"lbl_vs_arrow: {bx['label_vs_other_arrow_collisions']}->{ax['label_vs_other_arrow_collisions']}, coinc: {bx['coincident_vertical_tracks']}->{ax['coincident_vertical_tracks']}",
    )
    check(
        "deconflict_fixes_clipped_subgraph_title_band",
        bx["title_text_overflows"] >= 1 and ax["title_text_overflows"] == 0 and ax["zero_interference"] is True,
        f"title_overflow: {bx['title_text_overflows']}->{ax['title_text_overflows']}, zero_interference={ax['zero_interference']}",
    )

    # Tests 15-16: Module containment + trunk clearance + high-contrast dark-gray / dotted / rounded palette
    mod_doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": [
            {"id": "root", "type": "rectangle", "x": 20, "y": 260, "width": 160, "height": 80, "strokeColor": "#002FA7", "backgroundColor": "#002FA7", "strokeStyle": "solid", "isDeleted": False},
            {"id": "troot", "type": "text", "containerId": "root", "x": 30, "y": 288, "width": 140, "height": 24, "fontSize": 20, "lineHeight": 1.25, "text": "总纲", "isDeleted": False},
            {"id": "sg1", "type": "rectangle", "x": 240, "y": 40, "width": 440, "height": 200, "strokeColor": "#D1D5DB", "strokeStyle": "dashed", "roundness": None, "isDeleted": False},
            {"id": "m1", "type": "rectangle", "x": 260, "y": 80, "width": 140, "height": 60, "strokeColor": "#D1D5DB", "strokeStyle": "solid", "isDeleted": False},
            {"id": "tm1", "type": "text", "containerId": "m1", "x": 270, "y": 98, "width": 120, "height": 24, "fontSize": 18, "lineHeight": 1.25, "text": "模块一", "isDeleted": False},
            {"id": "nt1", "type": "rectangle", "x": 540, "y": 80, "width": 180, "height": 80, "strokeColor": "#E5E5E5", "strokeStyle": "dashed", "isDeleted": False},
            {"id": "tnt1", "type": "text", "containerId": "nt1", "x": 550, "y": 100, "width": 160, "height": 24, "fontSize": 16, "lineHeight": 1.25, "text": "辅助案例超框测试", "isDeleted": False},
            {"id": "sg2", "type": "rectangle", "x": 240, "y": 260, "width": 440, "height": 180, "strokeColor": "#D1D5DB", "strokeStyle": "dashed", "roundness": None, "isDeleted": False},
            {"id": "m2", "type": "rectangle", "x": 260, "y": 300, "width": 140, "height": 60, "strokeColor": "#002FA7", "strokeStyle": "solid", "isDeleted": False},
            {"id": "tm2", "type": "text", "containerId": "m2", "x": 270, "y": 318, "width": 120, "height": 24, "fontSize": 18, "lineHeight": 1.25, "text": "核心结论", "isDeleted": False},
            {"id": "m2b", "type": "rectangle", "x": 450, "y": 300, "width": 140, "height": 60, "strokeColor": "#D1D5DB", "strokeStyle": "solid", "isDeleted": False},
            {"id": "tm2b", "type": "text", "containerId": "m2b", "x": 460, "y": 318, "width": 120, "height": 24, "fontSize": 18, "lineHeight": 1.25, "text": "子节点", "isDeleted": False},
            {
                "id": "tr1", "type": "arrow", "x": 180.5, "y": 290, "width": 79.0, "height": 180,
                "points": [[0, 0], [59.5, 0], [59.5, -180], [79.0, -180]],
                "elbowed": True, "roundness": None,
                "startBinding": {"elementId": "root", "focus": 0, "gap": 1},
                "endBinding": {"elementId": "m1", "focus": 0, "gap": 1},
                "isDeleted": False,
            },
            {
                "id": "tr2", "type": "arrow", "x": 180.5, "y": 310, "width": 79.0, "height": 20,
                "points": [[0, 0], [59.5, 0], [59.5, 20], [79.0, 20]],
                "elbowed": True, "roundness": None,
                "startBinding": {"elementId": "root", "focus": 0, "gap": 1},
                "endBinding": {"elementId": "m2", "focus": 0, "gap": 1},
                "isDeleted": False,
            },
        ],
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    bm = _ed.audit_excalidraw(mod_doc)
    _ed.deconflict_excalidraw(mod_doc)
    am = _ed.audit_excalidraw(mod_doc)
    els_by_id = {e["id"]: e for e in mod_doc["elements"]}

    check(
        "deconflict_fixes_subgraph_containment_and_trunk_clearance",
        bm["subgraph_containment_violations"] >= 1
        and bm["trunk_vs_subgraph_collisions"] >= 1
        and am["subgraph_containment_violations"] == 0
        and am["trunk_vs_subgraph_collisions"] == 0
        and am["subgraph_overlaps"] == 0
        and am["zero_interference"] is True,
        f"contain: {bm['subgraph_containment_violations']}->{am['subgraph_containment_violations']}, trunk: {bm['trunk_vs_subgraph_collisions']}->{am['trunk_vs_subgraph_collisions']}",
    )
    check(
        "deconflict_applies_high_contrast_rounded_and_dotted_palette",
        els_by_id["sg1"]["strokeColor"] == "#4B5563"
        and els_by_id["sg1"]["strokeStyle"] == "dotted"
        and els_by_id["sg1"]["roundness"] == {"type": 3}
        and els_by_id["m1"]["strokeColor"] == "#4B5563"
        and els_by_id["nt1"]["strokeColor"] == "#6B7280"
        and els_by_id["nt1"]["strokeStyle"] == "dashed"
        and els_by_id["m2"]["strokeColor"] == "#002FA7",
        f"sg={els_by_id['sg1']['strokeColor']}/{els_by_id['sg1']['strokeStyle']}/{els_by_id['sg1']['roundness']}, solid={els_by_id['m1']['strokeColor']}, note={els_by_id['nt1']['strokeColor']}/{els_by_id['nt1']['strokeStyle']}",
    )

    all_passed = all(t["passed"] for t in tests)
    result = {
        "mode": "self_test",
        "all_passed": all_passed,
        "passed_count": sum(1 for t in tests if t["passed"]),
        "total_tests": len(tests),
        "tests": tests,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if "args" in globals() and isinstance(globals()["args"], dict):
    _a = globals()["args"]
    _lang = str(_a.get("lang") or "zh")
    if _a.get("self_test"):
        _res = run_self_test()
        if not _res["all_passed"]:
            raise RuntimeError("Harness self-test failed")
    elif _a.get("tournament"):
        run_tournament(
            list(_a["tournament"]),
            out_excalidraw=_a.get("out_excalidraw"),
            out_mmd=_a.get("out_mmd"),
            lang=_lang,
        )
    elif _a.get("input"):
        run_tournament(
            [_a["input"]],
            out_excalidraw=_a.get("out_excalidraw"),
            out_mmd=_a.get("out_mmd"),
            lang=_lang,
        )
    else:
        raise ValueError("Provide `self_test`, `tournament`, or `input` in Args.")
elif __name__ == "__main__":
    p = argparse.ArgumentParser(description="Cartograph Deterministic Evaluation Harness & Tournament Selector")
    p.add_argument("input", nargs="?", default=None, help="Single .mmd file to evaluate")
    p.add_argument("--tournament", nargs="+", default=None, help="Two or more candidate .mmd files to rank")
    p.add_argument("--lang", choices=("zh", "en"), default="zh", help="Target output language (default: zh)")
    p.add_argument("--out-excalidraw", default=None, help="Write winning candidate to .excalidraw")
    p.add_argument("--out-mmd", default=None, help="Copy winning candidate to .mmd")
    p.add_argument("--self-test", action="store_true", help="Run built-in 16-test regression suite")
    ns = p.parse_args()
    try:
        if ns.self_test:
            res = run_self_test()
            sys.exit(0 if res["all_passed"] else 1)
        elif ns.tournament:
            res = run_tournament(ns.tournament, out_excalidraw=ns.out_excalidraw, out_mmd=ns.out_mmd, lang=ns.lang)
            sys.exit(0 if res["winner_gate_passed"] else 1)
        elif ns.input:
            res = run_tournament([ns.input], out_excalidraw=ns.out_excalidraw, out_mmd=ns.out_mmd, lang=ns.lang)
            sys.exit(0 if res["winner_gate_passed"] else 1)
        else:
            p.print_help()
            sys.exit(2)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
