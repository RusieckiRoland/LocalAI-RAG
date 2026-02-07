# pipeline_to_puml – Expansion Plan (DRAFT / NOTES)

Location: `code_query_engine/tools/pipeline_to_puml.py`  
Status: **VERY EARLY DRAFT – NOT IMPLEMENTED, NOT TESTED**

> ⚠️ **Important notice**
>
> This document describes early design thoughts only.
> The ideas below are **not implemented**, **not tested**, and **not guaranteed to work**.
>  
> The document is intentionally kept in the repository so that:
> - we do not forget the idea,
> - we can later evaluate whether such a tool is actually useful,
> - future work can start from written reasoning instead of rediscovering it.
>
> This is a **developer thinking artifact**, not a finished design and not a commitment.

---

## 1. Why this tool exists (idea stage)

The intention behind this tool is exploratory.

We are experimenting with the idea of a small CLI utility that could help us **reason about YAML pipelines** in two dimensions:

1) **Visualization** – generate a PlantUML diagram for quick, human-friendly inspection.  
2) **Heuristic analysis** – run lightweight checks to detect obvious inconsistencies or missing elements.

At this stage, this is **only an idea under consideration**, not a validated approach.

---

## 2. Current state (what exists today)

At the moment, the tool:
- loads a pipeline YAML via `PipelineLoader` (including `extends` merge support),
- generates a `.puml` diagram:
  - nodes represent pipeline steps (`step_id` + `action`),
  - edges are derived deterministically from:
    - `next: <step>`
    - `on_*: <step>` (edge label = key without `on_`),
  - the entry point is visualized using `settings.entry_step_id`.

This functionality itself should be treated as **experimental** and subject to change.

---

## 3. Intended direction (ideas, not decisions)

The following sections describe **potential future directions**, not approved plans.

### 3.1 Heuristic pipeline analysis (concept only)

Possible heuristic checks we *might* explore in the future:

**A) Prompt coverage**
- Detect `call_model` steps without `prompt_key`.
- Optionally verify that referenced prompts exist.
- Optionally verify that prompt templates match pipeline expectations.

**B) Router / prefix_router consistency**
- If `prefix_router` is used:
  - verify that prefixes are defined and non-empty,
  - check that routing branches (`on_bm25`, `on_other`, etc.) exist,
  - optionally check whether the router prompt instructs the model to emit expected prefixes.

**C) Retrieval flow sanity**
- Heuristically check that retrieval steps exist before answer generation.
- Ensure that pipelines do not terminate without a finalization/persist step.

**D) History flow sanity**
- Verify that `load_conversation_history` appears in a reasonable place.
- Detect obviously incorrect history usage patterns.

**E) Action awareness**
- Detect steps that reference actions unknown to the current ActionRegistry.

All of the above are **ideas only**, with unknown cost/benefit ratio.

---

## 4. Output expectations (if this ever happens)

If developed further, the tool *could* produce:
- a `.puml` diagram,
- a heuristic report (console / optional JSON).

Exit codes *might* be used for CI integration, but this is **not decided**.

---

## 5. Implementation sketch (very rough)

If the idea survives evaluation, a possible structure could be:

- `pipeline_to_puml.py` – CLI entry point
- `pipeline_heuristics.py` – heuristic checks
- `diagnostics.py` – shared diagnostic structures

This is a **sketch**, not a design.

---

## 6. Non-goals (explicitly stated)

At this stage, we explicitly do **not** aim for:
- full static analysis of prompt semantics,
- deep validation replacing runtime checks,
- cross-pipeline global analysis,
- production-grade guarantees.

---

## 7. Why this document exists

This file exists to:
- capture early reasoning,
- document thought process,
- avoid losing potentially useful ideas,
- support later evaluation of whether this tool is worth building at all.

It is **not** a promise of future functionality.

---

## 8. Summary

- This document is a **draft note**, not a specification.
- The tool is **experimental** and **unfinished**.
- No guarantees are provided.
- The idea may be abandoned entirely if it proves unnecessary or too complex.
