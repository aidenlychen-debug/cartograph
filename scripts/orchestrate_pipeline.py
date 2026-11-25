#!/usr/bin/env python3
"""Cartograph Code-Enforced Parallel Multi-Candidate Tournament & Self-Healing Loop Orchestrator.

Designed to be executed via Antigravity `run_workflow(ScriptPath=..., Args={...})`.
Enforces T0 engineering in code (not just prompt instructions):
  Phase 1: Load architectural spec + extracted source text/notes
  Phase 2: Fan out 3 parallel synthesis agents (Spine-First, Taxonomy-First, Evidence-Dense)
  Phase 3: Run deterministic `eval_harness.py` tournament across all 3 candidates
  Phase 4: Bounded Self-Healing Repair Loop (up to `max_repair_rounds`, default 3) with
           stall detection until hard quality gate passes (`valid`, 0 overlaps, 0 arrow
           collisions, score >= 88, Chinese localization verified)
  Phase 5: Export winning optimal `.mmd`, native hand-drawn `.excalidraw`, and scorecard JSON.

Args schema:
  - source_path (str, required): Absolute path to extracted source text / chapter digest
  - stem (str, required): Output filename stem (e.g. "系统思考指南")
  - output_dir (str, required): Output directory for final `.mmd`, `.excalidraw`, `.scorecard.json`
  - lang (str, optional): Target output language ("zh" default, or "en")
  - max_repair_rounds (int, optional): Max repair loop iterations (default 3)
  - model (str, optional): Model tier for synthesis agents (default "inherit")
"""

import importlib.util
import json
import sys
from pathlib import Path


def _load_harness():
    here = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    home = Path.home()
    candidates = [
        here / "eval_harness.py",
        home / ".gemini" / "config" / "skills" / "knowledge-graph-architect" / "scripts" / "eval_harness.py",
        home / ".agents" / "skills" / "knowledge-graph-architect" / "scripts" / "eval_harness.py",
    ]
    hp = next((p for p in candidates if p.exists()), None)
    if hp is None:
        raise FileNotFoundError("Cannot locate eval_harness.py")
    spec = importlib.util.spec_from_file_location("cartograph_harness", str(hp))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cartograph_harness"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_spec_text() -> str:
    here = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    home = Path.home()
    candidates = [
        here.parent / "references" / "architecture-spec.md",
        home / ".gemini" / "config" / "skills" / "knowledge-graph-architect" / "references" / "architecture-spec.md",
        home / ".agents" / "skills" / "knowledge-graph-architect" / "references" / "architecture-spec.md",
    ]
    sp = next((p for p in candidates if p.exists()), None)
    return sp.read_text(encoding="utf-8") if sp else ""


_a = args
source_path = Path(_a["source_path"])
stem = str(_a["stem"])
output_dir = Path(_a["output_dir"])
lang = str(_a.get("lang") or "zh")
max_repair_rounds = int(_a.get("max_repair_rounds", 3))
model_tier = _a.get("model") or "inherit"

output_dir.mkdir(parents=True, exist_ok=True)
scratch_dir = output_dir / ".cartograph_candidates" / stem
scratch_dir.mkdir(parents=True, exist_ok=True)

phase("Phase 1: Load Specification & Source Material")
source_text = source_path.read_text(encoding="utf-8")
spec_text = _load_spec_text()
harness = _load_harness()
log(f"Loaded source ({len(source_text):,} chars) and architecture spec ({len(spec_text):,} chars); lang={lang}")

lang_rule = (
    "【强制默认中文规则】全部标题、观点、解释、案例与关系标签必须翻译并改写为地道、流畅的简体中文（符合中文阅读习惯）；仅在必要处保留关键英文术语/缩写/公式括号标注（如“投资回报率（ROI）”“反馈回路（Feedback Loop）”），严禁保留整句英文。"
    if lang == "zh"
    else "Output in clear English while preserving exact terminology and formulas."
)

strategies = [
    (
        "candidate_a_spine",
        "Spine-First Progressive（强推演链优先）",
        "策略偏向：优先将每章/每节的因果推导、步骤演进与问题→机制→结论连成清晰的横向强逻辑链（实线带精准动词标签），全部二级模块（MOD）默认沿 ROOT 右侧自上而下纵向分布，同 MOD 内保留必要证据/案例虚线，严格过滤跨 MOD 松散线。",
    ),
    (
        "candidate_b_taxonomy",
        "Taxonomy-First Modular（清晰纵向分层优先）",
        "策略偏向：优先突出清晰的二级模块（MOD）与三级主题（SUB）纵向结构层次，并列概念与对比维度上下分明展开，仅对确有硬因果/步骤依赖的节点横向成链，最大限度减少跨支线长连线与交叉，确保极高视觉舒展度。",
    ),
    (
        "candidate_c_evidence",
        "Evidence-Dense Synthesis（高密度证据案例优先）",
        "策略偏向：在保证所有二级模块自上而下清晰分布与核心横向推演链的同时，将书中的关键数据、公式、代表性案例、反例与实操边界提取为独立的局部辅助节点（note 样式），用带具体标签（如 案例/证据/公式/反驳/边界）的虚线就近挂载到被支持观点旁。",
    ),
]

MERMAID_SCHEMA = {
    "type": "object",
    "properties": {
        "mermaid": {"type": "string", "description": "Complete, standalone Mermaid flowchart LR code (without markdown fences)"},
        "guide": {"type": "string", "description": "2-4 sentence Chinese guide summarizing the graph architecture and cross-MOD filtering"},
        "omitted_cross_mod": {"type": "array", "items": {"type": "string"}, "description": "Typical loose cross-MOD links intentionally omitted"},
    },
    "required": ["mermaid", "guide", "omitted_cross_mod"],
}

phase("Phase 2: Parallel 3-Candidate Architecture Synthesis")

def make_synthesis_prompt(name: str, label: str, bias: str) -> str:
    return f"""你是 Cartograph 知识图谱架构师。请严格遵守以下完整规范，为给定资料生成方案【{label}】的完整 Mermaid `flowchart LR` 代码。

{lang_rule}

{bias}

关键硬性工程红线（触发即淘汰）：
1. 第一行必须是 `flowchart LR`，节点文本与子图标题用英文双引号，换行只用 `<br/>`，每行只写一条连线。
2. ROOT 在最左侧且直连全部 `MOD_*`；**默认全部 `MOD_*` 沿 ROOT 右侧自上而下纵向排布（不要把所有 MOD 串联成横向长龙）**，各 MOD 内部强递进链横向展开。
3. 严禁连接 subgraph ID；严禁出现「认知块」「分组容器」「分组1」等内部占位词；严禁使用泛化标签「相关」「关联」；所有节点必须分配 `class`（root/mod/sub/k/key/note）；必须定义克莱因蓝 `#002FA7` 配色与外框 `style B01 ...`。
4. 控制单节点不超过 6 行、每行约 14–22 个汉字，总边数 ≤ 450（硬上限 500），不可省略或截断。

=== 完整架构规范 ===
{spec_text}

=== 源资料内容 ===
{source_text}

请通过 finish 工具返回 JSON（mermaid 字段只放纯 Mermaid 代码，不要包 ```mermaid 围栏）。"""


candidate_results = await parallel(
    strategies,
    lambda s: agent(
        make_synthesis_prompt(s[0], s[1], s[2]),
        schema=MERMAID_SCHEMA,
        role=f"Synthesize {s[0]}",
        model=model_tier,
    ),
)

cand_paths = []
cand_meta = {}
for (cname, clabel, _), res in zip(strategies, candidate_results):
    mmd_text = harness._extract_mermaid(res["mermaid"]).strip()
    p = scratch_dir / f"{cname}.mmd"
    p.write_text(mmd_text, encoding="utf-8")
    cand_paths.append(str(p))
    cand_meta[p.name] = {"label": clabel, "guide": res["guide"], "omitted_cross_mod": res["omitted_cross_mod"]}
    log(f"Drafted {cname}: {len(mmd_text.splitlines())} lines")

phase("Phase 3: Deterministic Evaluation Harness Tournament")
out_mmd = output_dir / f"{stem}_知识图谱.mmd"
out_exc = output_dir / f"{stem}_知识图谱.excalidraw"

tourney = harness.run_tournament(
    cand_paths,
    out_excalidraw=str(out_exc),
    out_mmd=str(out_mmd),
    lang=lang,
)
log(f"Initial Tournament Winner: {tourney['winner']} | score={tourney['winner_score']} | gate={tourney['winner_gate_passed']}")

phase("Phase 4: Bounded Self-Healing Repair Loop")
repair_history = []
current_mmd_path = out_mmd
current_score = tourney["winner_score"]
current_detail = tourney["winner_detail"]
current_gate = tourney["winner_gate_passed"]

for rnd in range(1, max_repair_rounds + 1):
    repairs = current_detail.get("repairs") or []
    if current_gate and current_score >= 95.0 and not repairs:
        log(f"Repair loop not needed: champion already passed gate at {current_score}/100 with 0 repairs.")
        break
    if current_gate and not repairs:
        log(f"Champion passed gate at {current_score}/100 with 0 repairs.")
        break

    log(f"Repair Round {rnd}/{max_repair_rounds}: score={current_score}, repairs={len(repairs)}")
    cur_src = current_mmd_path.read_text(encoding="utf-8")
    repair_prompt = f"""你是 Cartograph 图谱自愈修复工程师。当前最优候选图谱在确定性评估基座（Eval Harness）中的得分为 {current_score}/100（门禁通过={current_gate}）。

请严格修复以下全部诊断问题，同时 100% 保留原有知识与事实、不得删除核心论点、不得退化为英文（lang={lang}）：

=== 评估基座诊断出的待修复项 ===
{json.dumps(repairs, ensure_ascii=False, indent=2)}

=== 当前维度得分与几何指标 ===
scores: {json.dumps(current_detail['scores'], ensure_ascii=False)}
geometry: {json.dumps(current_detail['geometry'], ensure_ascii=False)}
readability: {json.dumps(current_detail['readability'], ensure_ascii=False)}

=== 当前完整 Mermaid 代码 ===
{cur_src}

请通过 finish 工具返回修复后的完整 Mermaid 代码（不要省略或截断，不要包 ```mermaid 围栏）。"""

    fixed = await agent(
        repair_prompt,
        schema={"type": "object", "properties": {"mermaid": {"type": "string"}, "changes": {"type": "string"}}, "required": ["mermaid", "changes"]},
        role=f"Repair Round {rnd} ({stem})",
        model=model_tier,
    )
    cand_repair_path = scratch_dir / f"repair_round_{rnd}.mmd"
    cand_repair_path.write_text(harness._extract_mermaid(fixed["mermaid"]).strip(), encoding="utf-8")
    eval_res = harness.run_tournament(
        [str(cand_repair_path)],
        out_excalidraw=str(out_exc) if True else None,
        lang=lang,
    )
    new_score = eval_res["winner_score"]
    new_gate = eval_res["winner_gate_passed"]
    delta = round(new_score - current_score, 2)
    repair_history.append({
        "round": rnd,
        "prev_score": current_score,
        "new_score": new_score,
        "delta": delta,
        "gate_passed": new_gate,
        "changes": fixed["changes"],
    })
    log(f"Repair Round {rnd} result: {current_score} -> {new_score} (delta={delta:+}), gate={new_gate}")

    if new_score > current_score or (new_gate and not current_gate):
        out_mmd.write_text(cand_repair_path.read_text(encoding="utf-8"), encoding="utf-8")
        current_score = new_score
        current_gate = new_gate
        current_detail = eval_res["winner_detail"]
    else:
        # Restore previous better Excalidraw compilation and stop on non-improvement
        harness.run_tournament([str(out_mmd)], out_excalidraw=str(out_exc), lang=lang)
        log(f"Repair Round {rnd} did not improve score; kept previous champion ({current_score}) and stopped.")
        break

    if current_gate and (delta < 1.0 or not current_detail.get("repairs")):
        log(f"Converged at round {rnd}: score={current_score}, gate_passed={current_gate}")
        break

phase("Phase 5: Save Final Scorecard")
winner_meta = cand_meta.get(tourney["winner"], {})
final_scorecard = {
    "stem": stem,
    "lang": lang,
    "initial_winner": tourney["winner"],
    "initial_leaderboard": tourney["leaderboard"],
    "repair_rounds_executed": len(repair_history),
    "repair_history": repair_history,
    "final_score": current_score,
    "final_gate_passed": current_gate,
    "winner_guide": winner_meta.get("guide", ""),
    "omitted_cross_mod": winner_meta.get("omitted_cross_mod", []),
    "final_detail": current_detail,
    "outputs": {
        "mermaid": str(out_mmd),
        "excalidraw": str(out_exc),
    },
}
scorecard_path = output_dir / f"{stem}_scorecard.json"
scorecard_path.write_text(json.dumps(final_scorecard, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "stem": stem,
    "initial_winner": tourney["winner"],
    "final_score": current_score,
    "final_gate_passed": current_gate,
    "repair_rounds": len(repair_history),
    "nodes": current_detail["audit"]["nodes"],
    "edges": current_detail["audit"]["total_edges"],
    "node_overlaps": current_detail["geometry"]["node_overlaps"],
    "arrow_node_collisions": current_detail["geometry"]["arrow_node_collisions"],
    "edge_crossings": current_detail["geometry"]["edge_crossings"],
    "cjk_node_ratio": current_detail["readability"]["cjk_node_ratio"],
    "scorecard": str(scorecard_path),
    "mermaid": str(out_mmd),
    "excalidraw": str(out_exc),
}, ensure_ascii=False, indent=2))
