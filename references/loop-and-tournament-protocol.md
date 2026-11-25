# Harness, Bounded Loop & Multi-Candidate Tournament Protocol

This protocol governs how **Cartograph** guarantees T0-grade reliability, prevents single-shot LLM drift, and provably selects the optimal knowledge graph edition.

## 1. Multi-Candidate Tournament Mechanism

Single-pass generation suffers from structural lock-in: the first tree layout an LLM picks is rarely optimal for both causal flow and visual balance. Therefore, for any substantive input (> 1,500 characters or > 3 sections), Cartograph synthesizes **multiple distinct architectural candidates** and runs them through a deterministic tournament:

| Candidate Strategy | Architectural Bias | Best Suited For |
|---|---|---|
| **Candidate A (`spine-first`)** | Prioritizes long, explicit horizontal causal/deductive chains (`K_1 → K_2 → K_3`) and strong cross-MOD progression spines. | Arguments, books, essays, research narratives, causal analyses. |
| **Candidate B (`taxonomy-first`)** | Prioritizes crisp vertical categorization (`MOD → SUB → parallel K branches`), sharp contrast pairs, and minimal edge crossings. | Reference courses, frameworks, comparative evaluations, SOPs. |
| **Candidate C (`evidence-dense`, optional)** | Separates claims from proof/cases/formulas/risks using dedicated local dashed auxiliary nodes (`E_*`, `R_*`, `M_*`) attached immediately beside supported claims. | Scientific works, technical specs, case postmortems, multi-source syntheses. |

### Selection Policy
1. Run `scripts/eval_harness.py --tournament <cand_a.mmd> <cand_b.mmd> [cand_c.mmd]`.
2. Any candidate with `errors > 0` or `budget_ok == False` is disqualified unless repaired in the loop.
3. Rank surviving candidates by **Total Harness Score (0–100)**, breaking ties by:
   - Fewer geometric node overlaps (`node_overlaps == 0`)
   - Fewer edge crossings (`edge_crossings`)
   - Higher evidence/auxiliary attachment ratio without violating cross-MOD discipline
4. Optionally **synthesize a hybrid champion** combining the winning candidate's layout geometry with any unique high-value evidence nodes found in runner-up candidates, then re-verify the champion through the harness!

---

## 2. Deterministic Evaluation Harness Rubric (100 Points)

`scripts/eval_harness.py` compiles every candidate into full Excalidraw geometry and scores it deterministically:

| Dimension | Max Points | Automated Checks |
|---|---|---|
| **1. Spec & Syntax Compliance** | **30** | `flowchart LR` header, unique valid IDs, zero reserved keywords, zero subgraph-endpoint edges, zero forbidden internal meta-terms, all nodes styled with `class`, edge budget `≤ 500` (bonus for `≤ 450`). |
| **2. Structural & Relation Discipline** | **25** | `ROOT` connects directly to all `MOD_*` nodes, balanced hierarchy depth, labeled strong-logic & dashed auxiliary edges (no generic `"相关"` labels), controlled cross-MOD ratio (`≤ 15%` of total edges unless justified). |
| **3. Geometric Layout & Visual Clarity** | **20** | Compiled `.excalidraw` canvas verified for **zero node-to-node overlaps**, **zero subgraph-to-subgraph overlaps**, **100% subgraph containment** (every member node strictly inside its subgraph box), low edge-crossing rate, and balanced canvas aspect ratio. |
| **4. Readability & Typography Density** | **15** | Line count per node (`≤ 6` lines), semantic line length (`≤ 26` CJK-equivalent width units per line), clean `<br/>` breaks, absence of empty or filler labels. |
| **5. Evidence & Auxiliary Fidelity** | **10** | Presence of grounded local dashed auxiliary links (`证据`/`案例`/`解释`/`公式`/`风险`/`边界`) and key conclusion emphasis (`class ... key`). |

---

## 3. Bounded Self-Healing Loop (`max_iterations = 3`)

```text
[Phase 2: Multi-Candidate Drafts]
              │
              ▼
[Phase 3: Harness Tournament & Score]
              │
     ┌────────┴────────┐
     │ Gate Passed?    │  Gate: errors == 0 AND node_overlaps == 0
     │                 │        AND subgraph_overlaps == 0 AND score >= 88
     ├── YES ──────────┼─────────────────────────────▶ [Phase 4: Deliver Champion]
     │                 │
     └── NO ───────────▼
       [Diagnose Top-3 Deductions from Harness JSON]
                       │
                       ▼
       [Targeted Repair of Champion Mermaid]
                       │
                       ▼
       [Re-run eval_harness.py & Compare Delta]
                       │
       ┌───────────────┴───────────────┐
       │ iteration >= 3 OR delta < 1.0 │── YES ──▶ [Stop & Report Remaining Trade-offs]
       └───────────────┬───────────────┘
                       └── NO ──▶ (Next Repair Cycle)
```

### Repair Priority Order
1. **Hard Errors first**: Undefined endpoints, subgraph-ID edges, duplicate IDs, forbidden terms, budget > 500.
2. **Geometric Defects second**: Overlong unwrapped lines causing wide boxes, dense cross-MOD lines causing crossings.
3. **Semantic & Pedagogical Polish third**: Replace vague labels (`相关`) with precise labels (`证据`/`因果`/`对比`/`边界`), elevate core claims to `key` class, verify no fact was dropped during editing.

---

## 4. Regression Self-Test Mode

`eval_harness.py --self-test` executes an internal battery of positive and negative unit tests (golden fixture pass, duplicate-ID rejection, subgraph-edge rejection, forbidden-term rejection, overlap detector sanity check, tournament winner ranking) to verify the harness itself remains intact after any script edits.
