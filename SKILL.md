---
name: knowledge-graph-architect
description: >-
  Cartograph: Autonomous Instructional Knowledge Graph & Excalidraw Synthesis Engine.
  Converts any input format (PDF, EPUB, DOCX, Markdown, TXT, video, audio, images,
  subtitles, or web URLs) into audited Mermaid Flowcharts (.mmd) and editable native
  Excalidraw (.excalidraw) canvases using multi-candidate tournament synthesis,
  a deterministic evaluation harness, and a bounded self-healing repair loop.
---

# Cartograph — Instructional Knowledge Graph & Excalidraw Synthesis Engine

A T0-grade agentic workflow that transforms arbitrary multimodal sources into high-fidelity, visually balanced instructional knowledge graphs (`.mmd` + native `.excalidraw`), backed by **Multi-Candidate Tournament Synthesis**, a **Deterministic Evaluation Harness**, and a **Bounded Self-Healing Loop**.

## Core Engineering Pillars

1. **Universal Multimodal Ingestion & Chinese-First Localization**: Ingests PDF, EPUB, DOCX, Markdown, TXT, HTML, SRT/VTT subtitles, images, audio, video, and web URLs with strict factual boundaries (`【资料缺口说明】` on inaccessible content). **Default output language is idiomatic Simplified Chinese**: foreign-language sources (English, etc.) MUST be translated and localized to natural Chinese reading habits before/during graph construction, keeping essential acronyms, frameworks, formulas, tools, and proper nouns in concise bilingual form (e.g., `投资回报率（ROI）`, `反馈回路（Feedback Loop）`) unless the user explicitly asks for English (`--lang en`).
2. **Code-Enforced Multi-Candidate Tournament Synthesis**: Uses [orchestrate_pipeline.py](./scripts/orchestrate_pipeline.py) (`run_workflow` + `parallel()`) — or structured multi-draft execution — to generate **3 architecturally distinct candidates** (`spine-first`, `taxonomy-first`, `evidence-dense`), evaluates all candidates through the identical deterministic harness, and promotes the **highest-scoring optimal edition**.
3. **Deterministic Evaluation Harness** (`scripts/eval_harness.py` + `scripts/excalidraw_deconflict.py`): Scores every candidate on a **0–100 rubric** across five auditable dimensions — Spec & Localization Compliance (30), Structural & Relation Discipline (25), Geometric Layout, Zero-Overlap & Obstacle-Free Routing Verification (20), Readability & Text Density (15), and Evidence Coverage Balance (10) — plus runs a **16-test regression self-test suite** covering both Mermaid auditing and real-Excalidraw 10-check zero-interference & styling enforcement.
4. **Bounded Self-Healing Loop**: Enforces explicit **Phase Contracts** (`Ingest & Localize → Parallel 3-Candidate Synthesis → Harness Tournament → Bounded Repair Loop → Finalize`) with a hard quality gate (`score >= 88`, `errors == 0`, `node_overlaps == 0`, `arrow_node_collisions == 0`) and a bounded repair budget (`max 3 iterations`, with stall detection).

---

## Phase Contracts & Execution Protocol

Read [architecture-spec.md](./references/architecture-spec.md) and [loop-and-tournament-protocol.md](./references/loop-and-tournament-protocol.md) before drafting candidates.

### Phase 1 — Universal Ingestion & Fact Ledger
- **PDF / Images / Video / Audio**: Read directly with native multimodal `read_file`.
- **EPUB / DOCX / HTML / SRT / VTT / MD / TXT / Static URL**: Extract via [extract_content.py](./scripts/extract_content.py).
- **Dynamic / JS Web URLs**: Delegate to the `browser` subagent.
- **Exit Gate**: Confirm full accessible scope, source type, and internal fact ledger (`Source → Point → Distilled Claim → Level → Order → Relation Tier → Edge Flag → Node ID → Container`). If critical content is unreachable, stop and issue `【资料缺口说明】`.

### Phase 2 — Multi-Candidate Architecture Synthesis (Automated Parallel Orchestrator)
For substantive inputs, invoke [orchestrate_pipeline.py](./scripts/orchestrate_pipeline.py) via `run_workflow` to automatically fan out **3 competing architectural agents in parallel**, run the deterministic tournament, and execute the bounded self-healing repair loop:

```python
run_workflow(
    ScriptPath="<skill_dir>/scripts/orchestrate_pipeline.py",
    Args={
        "source_path": "<abs_path_to_extracted_notes_or_text>",
        "stem": "<output_filename_stem>",
        "output_dir": "<workspace_output_dir>",
        "lang": "zh",
        "max_repair_rounds": 3,
    },
)
```

Or synthesize the 3 distinct Mermaid candidates directly in the scratch directory before running `eval_harness.py --tournament`:
- **Candidate A (`spine-first`)**: Maximizes horizontal causal/progressive narrative flow across modules and chapters.
- **Candidate B (`taxonomy-first`)**: Maximizes crisp top-down conceptual partitioning, parallel contrast branches, and clean vertical scannability.
- **Candidate C (`evidence-dense`)**: Maximizes explicit formula/case/quote/risk auxiliary nodes attached via local labeled dashed lines.

Every candidate MUST obey [architecture-spec.md](./references/architecture-spec.md): `flowchart LR`, **idiomatic Chinese wording by default** (bilingual parentheticals only for necessary proper terms), Klein Blue `#002FA7` high-contrast palette (`#3A3A3C` or darker text), `ROOT → all MOD` (MODs stacked top-to-bottom by default), strong chains horizontal, independent siblings vertical, in-MOD auxiliary dashed lines preserved, cross-MOD loose links filtered, zero forbidden meta-terms, and edge budget `≤ 500` (target `≤ 450`).

### Phase 3 — Harness Tournament & Bounded Self-Healing Loop
Run [eval_harness.py](./scripts/eval_harness.py) in tournament mode across all candidates:

- **Via CLI**:
  ```bash
  python <skill_dir>/scripts/eval_harness.py --tournament cand_a.mmd cand_b.mmd [cand_c.mmd] --out-excalidraw "<stem>_知识图谱.excalidraw" --out-mmd "<stem>_知识图谱.mmd"
  ```
- **Via Antigravity `run_workflow`** (zero system Python needed):
  ```python
  run_workflow(
      ScriptPath="<skill_dir>/scripts/eval_harness.py",
      Args={
          "tournament": ["<cand_a.mmd>", "<cand_b.mmd>"],
          "out_excalidraw": "<abs_path_to_output.excalidraw>",
          "out_mmd": "<abs_path_to_output.mmd>",
      },
      WaitMsBeforeAsync=10000,
  )
  ```

**Loop Contract (max 3 repair cycles)**:
1. Inspect the winning candidate's `errors`, `warnings`, `geometric_metrics`, and per-dimension `scores`.
2. If `errors > 0`, `overlaps > 0`, or `total_score < 88`: apply targeted repairs (fix syntax/IDs, split overlong labels, tighten cross-MOD noise, rebalance auxiliary nodes) and re-run `eval_harness.py`.
3. If two consecutive repair cycles improve `total_score` by `< 1.0` point (stall detection) or hit `iteration == 3`, stop iterating and report remaining trade-offs honestly.
4. If single-canvas completeness and readability fundamentally conflict beyond the 500-edge cap, stop and deliver `【冲突报告】` rather than silently dropping core arguments.

### Phase 4 — Official Excalidraw Export & Honest Verification Ledger
**PRIMARY Export Path (Official Excalidraw Engine — REQUIRED whenever Chrome/Edge + network are available)**:
After the winning `.mmd` passes the deterministic harness gate, export the final `.excalidraw` using **Excalidraw's official `@excalidraw/mermaid-to-excalidraw` (`parseMermaidToExcalidraw`) + `@excalidraw/excalidraw` (`convertToExcalidrawElements`)** engine — identical to pasting the Mermaid code into `excalidraw.com` ("Mermaid to Excalidraw" → Insert → Save to disk) so Dagre orthogonal routing, hand-drawn strokes, and Excalifont typography are 100% authentic:

- **Cross-platform Python (zero third-party packages, offline CDN cache + auto-deconflict + PNG visual proof)**:
  ```bash
  python <skill_dir>/scripts/official_excalidraw_export.py "<stem>_知识图谱.mmd" -o "<stem>_知识图谱.excalidraw" --render-dir ./visual_proofs
  ```
- **Windows PowerShell (zero Python/Node required, offline CDN cache + PNG visual proof)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -Command "& '<skill_dir>/scripts/official_excalidraw_export.ps1' -InputMmd @('<stem>_知识图谱.mmd') -OutDir '.' -RenderDir './visual_proofs'"
  ```
- **Offline CDN Cache (`resources/cdn_cache/`)**: The first run caches all `@excalidraw/mermaid-to-excalidraw@3.6.0` + `@excalidraw/excalidraw@0.18.1` ESM modules and Excalifont assets locally (`hits=130 misses=0`); all subsequent runs execute **100% offline** in seconds.
- **MANDATORY Post-Export 10-Check Zero-Interference & Styling Gate ([excalidraw_deconflict.py](./scripts/excalidraw_deconflict.py))**:
  EVERY exported `.excalidraw` MUST pass `excalidraw_deconflict.py` (auto-invoked by `official_excalidraw_export.py`, or run via `run_workflow`/CLI after `.ps1`), enforcing **all 10 zero-interference invariants** (`label_vs_node_overlaps == 0`, `label_vs_label_overlaps == 0`, `label_vs_other_arrow_collisions == 0`, `coincident_vertical_tracks == 0`, `node_text_overflows == 0`, `title_text_overflows == 0`, `node_vs_node_overlaps == 0`, `arrow_vs_node_collisions == 0`, `subgraph_containment_violations == 0`, `trunk_vs_subgraph_collisions == 0`, `subgraph_overlaps == 0`, `orthogonal_ratio == 1.0`) AND applying the high-contrast visual hierarchy (**dark gray `#4B5563`** for solid content boxes and **rounded dotted module frames** `strokeStyle: "dotted"`, `roundness: {"type": 3}`, one shade lighter **`#6B7280` `dashed` 正常虚线** for auxiliary `note` content boxes, and Klein Blue `#002FA7` for `ROOT`/`KEY`).
- **MANDATORY Photographic Visual Self-Inspection**: Render at least one high-res close-up PNG tile of the post-deconflict `.excalidraw` via Excalidraw's official `exportToBlob` (`--render-dir` / `-RenderOnly -RenderDir`), open the PNG with `read_file`, and confirm with your own eyes that orthogonal arrows, centered edge labels, and Chinese node borders are crisp and unobstructed before delivering.
- **Offline Fallback**: Only when no Chrome/Edge browser is installed at all, keep the `.excalidraw` compiled by `scripts/mermaid_to_excalidraw.py` and note in the verification ledger that the offline fallback layout was used.

Deliver the **winning optimal edition** as:
1. **Saved files**: `<stem>_知识图谱.excalidraw` (official Excalidraw export), `<stem>_知识图谱.mmd`, `<stem>_scorecard.json`, and `<stem>_知识图谱报告.md`.
2. **Structured report**:
   - **一、图谱导读** (2–4 sentences: theme, modules, horizontal strong chains, vertical branches, cross-MOD filter scope).
   - **二、多方案择优与闭环审计摘要** (compact candidate scorecard showing why the winning edition beat alternative architectures + repair loop iterations taken).
   - **三、完整 Mermaid 代码** (single complete, verified `mermaid` block).
   - **四、质量报告** (exact harness-measured counts, geometric overlap/crossing/aspect metrics, export engine used, and explicit 4-state verification ledger: Static Audit / Mermaid Parse / Official Excalidraw Export / Visual GUI Render — never claim GUI render verified unless visually inspected).

## Running Utility Scripts (Dual-Mode)

- **Official Excalidraw Export (Primary)**: [official_excalidraw_export.py](./scripts/official_excalidraw_export.py) and [official_excalidraw_export.ps1](./scripts/official_excalidraw_export.ps1) use local headless Chrome/Edge + [official_converter.html](./resources/official_converter.html) to run `@excalidraw/mermaid-to-excalidraw` + `@excalidraw/excalidraw` directly with zero Node/npm installs.
- **Deterministic Harness & Extraction**: [extract_content.py](./scripts/extract_content.py), [mermaid_to_excalidraw.py](./scripts/mermaid_to_excalidraw.py), and [eval_harness.py](./scripts/eval_harness.py) use **Python 3.8+ standard library only** and run identically via CLI or Antigravity `run_workflow(ScriptPath=..., Args={...})`.
