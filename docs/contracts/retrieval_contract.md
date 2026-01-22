# Data Contract for `PipelineState` (Retrieval + Graph + Rerank)

This document defines the **data contract** between three retrieval-pipeline actions:

- `search_nodes`
- `expand_dependency_tree`
- `fetch_node_texts`

It also defines **security rules (ACL)** and the **reranking feature contract** (keyword today, CodeBERT-ready later).

> **Contract goal:** enable implementation **without fallbacks and without guesswork**.
> Every input/output field and every behavior must be deterministic and fail-fast where specified.

---

## Definitions

- **Seed nodes** — canonical node IDs (chunk/node IDs) returned by retrieval (`search_nodes`).
- **Expanded nodes** — seed nodes plus graph dependencies after expansion (`expand_dependency_tree`).
- **ACL / security filters** — tenant/permissions/group allowlist/tags, etc.
  Source is **`state.retrieval_filters`** and these filters are **"sacred"**.
- **Scope** — minimal context where `ID → text` is unique.
  Minimum is **`repository + branch`** (plus ACL components if they separate data).
  Therefore **`state.repository` and `state.branch` are required** for all three steps.
- **Token budget** — maximum number of tokens allowed for node-text materialization produced by `fetch_node_texts`.
  This is the budget for *retrieval context only* (independent from history/system prompt budgets).

---

## Retrieval backend abstraction (FAISS today, Weaviate-ready)

### Motivation

To keep future migrations (FAISS → Weaviate) low-risk, **no pipeline action may talk to FAISS directly**.

**All retrieval operations must go through a single backend interface**, injected via runtime (e.g. `runtime.retrieval_backend`).

This applies to:
- `semantic`
- `bm25` (even if implemented without FAISS)
- `hybrid` (even if it internally calls both semantic and bm25)

### Backend contract

The backend interface MUST support both vector and keyword-style retrieval, and must return **canonical node IDs**.

#### Request / response types

```python
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Literal

SearchType = Literal["semantic", "bm25","hybrid"]

@dataclass(frozen=True)
class SearchRequest:
    search_type: SearchType
    query: str
    top_k: int
    repository: str
    branch: str

    # Security-first filters (sacred): enforced by backend
    retrieval_filters: Dict[str, Any]

    # Optional feature flags
    active_index: Optional[str] = None

@dataclass(frozen=True)
class SearchHit:
    id: str                   # canonical node/chunk ID
    score: float              # backend-specific score
    rank: int                 # 1-based rank in that source list

@dataclass(frozen=True)
class SearchResponse:
    hits: List[SearchHit]

    # Optional debug (may be used in logs/tests)
    debug: Dict[str, Any] = None
```

#### Backend interface

```python
class IRetrievalBackend:
    def search(self, req: SearchRequest) -> SearchResponse:
        """Returns ranked canonical IDs for the given search type.

        MUST enforce retrieval_filters (ACL) before returning hits.
        MUST be deterministic for the same inputs.
        """

    def fetch_texts(
        self,
        *,
        ids: List[str],
        repository: str,
        branch: str,
        retrieval_filters: Dict[str, Any],
        active_index: str | None = None,
    ) -> Dict[str, str]:
        """Returns a mapping {id -> text}.

        MUST enforce retrieval_filters (ACL).
        MUST return only texts for IDs visible under the given scope.
        """
```

### Rules for `search_nodes` when using the backend

- `search_nodes` always performs exactly one backend call:
  - `backend.search(search_type="<semantic|bm25|hybrid>", ...)`

- The backend implementation is responsible for executing the requested search deterministically:
  - FAISS backend may internally emulate `hybrid` using `semantic + bm25 + RRF`
  - Weaviate backend may implement `hybrid` natively

**Important:** regardless of the internal implementation, the pipeline sees only canonical IDs.


---

## `search_nodes`

### Step-start cleanup (required)

At the very beginning of `search_nodes`, the action **must clear all retrieval/graph/text artifacts** from previous runs,
so there is no cross-request state leakage.

The action MUST reset these fields (set to empty values):

 - `state.retrieval_seed_nodes = []`  
 - `state.retrieval_hits = []`  
 - `state.graph_seed_nodes = []`  
 - `state.graph_expanded_nodes = []`  
 - `state.graph_edges = []`  
 - `state.graph_node_texts = []`  
 - `state.graph_debug = {}`  
 - `state.node_sexts = []` *(if present)*  
 - `state.context_blocks = []`


### Input

- `state.last_model_response` **(required)**
  - Router output after prefix stripping.
  - Contains either:
    - a plain text query (default), or
    - a payload parseable by `JsonishQueryParser` (if enabled in YAML).

- `state.branch` **(required)**

- `state.repository` **(required)**
  - Part of Scope.
  - If missing/empty → **runtime error**.

- `state.retrieval_filters` **(optional but pipeline-enforced and "sacred")**
  - ACL/tenant/permissions filters.
  - Must not be removed or overridden by parsing.

- `step.raw.query_parser` **(optional)**
  - When present, `search_nodes` parses `state.last_model_response` into:
    - `parsed_query`
    - `parsed_filters`

- `step.raw.search_type` **(required)**
  - Allowed values: `semantic` | `bm25` | `hybrid`

 `step.raw.top_k` *(optional)*  
 - If present → use it.  
 - If absent → use `pipeline.settings["top_k"]`.  
 - If still missing → **runtime error** (`top_k` is required via step or pipeline settings).

- `step.raw.rerank` **(optional; valid only for `search_type: semantic`)**
  - Allowed values:
    - missing → `none`
    - `keyword_rerank`
    - `codebert_rerank` (reserved)
  - Fail-fast rules:
    - unknown value → **runtime error**
    - `rerank != none` when `search_type != semantic` → **runtime error**

### Filter merge rules (security-first)

- `base_filters = state.retrieval_filters + repository/branch filters`
- `parsed_filters` may **only add** non-security constraints (e.g., `data_type`).
- `base_filters` always wins.

**Invariant:**
- `state.retrieval_filters` is sacred.
- Parsing may only *extend*, never remove/override.

### Behavior (fail-fast)

- Empty query after parsing/normalization → **runtime error**.

### Output

- `state.retrieval_seed_nodes: List[str]` (required)
  - Canonical IDs in ranking order.

### Invariants

- `search_nodes` MUST NOT materialize any node text.
  It MUST NOT write into `state.context_blocks`.
- `search_nodes` MUST enforce ACL during retrieval, so returned IDs are already safe.

---

## Search modes (`search_type`)

The system supports exactly three search modes:

- `semantic`
- `bm25`
- `hybrid`

No additional modes such as `semantic_rerank` are allowed.
Reranking is a **feature**, not a search mode.

---

## Hybrid (`search_type: hybrid`) — algorithm and parameters

Hybrid uses **Reciprocal Rank Fusion (RRF)** to combine:

- source A: `semantic`
- source B: `bm25`

### Input list sizes

- semantic returns a list of length `top_k`
- bm25 returns a list of length `top_k`

No `top_k * X` multipliers are used in hybrid.

### RRF formula

For each ID:

`score(ID) = Σ 1 / (rrf_k + rank_source(ID))`

- ranks are 1-based
- if an ID is missing from a source, that term is not added

### YAML parameter (ignored unless `search_type == hybrid`)

- `step.raw.rrf_k` (optional)
  - default: `60`
  - must be int `>= 1`

### Duplicates and tie-break

- IDs appearing in both sources are deduplicated and their scores are summed.
- Sorting:
  1) descending by `score`
  2) tie-break: lower semantic rank wins
  3) tie-break: lower bm25 rank wins
  4) tie-break: stable string compare by `ID`

### Output

- final hybrid result is a ranked list of IDs of length `top_k`.

---

## Reranking (feature, not a search mode)

### Rerank options

- `none` (default)
- `keyword_rerank`
- `codebert_rerank` (reserved)

### Rules (today)

- reranking is allowed **only for** `search_type: semantic`
- enabling rerank for `bm25` or `hybrid` → **runtime error**

### Reranker responsibilities

- ✅ does NOT validate ACL (ACL is enforced by `search_nodes`)
- ✅ reorders only candidates returned by `search_nodes`
- ✅ trims to `top_k`
- ❌ must not introduce new IDs

### Wide search

For `semantic` with `rerank != none`:

- retrieve `K' = top_k * widen_factor` candidates
- reranker scores and returns top `top_k`

`widen_factor`:

- configured in the reranker constructor
- default = `6`

### Scope correctness during rerank materialization

If reranking needs text materialization (for keyword/CodeBERT), it MUST use the exact same Scope as retrieval:

- `repository + branch` (and ACL components if they separate data)

This prevents `ID → text` mismatches.

---

## Unified dependency graph (C# + DB)

The system has two dependency sources:

- C# dependencies
- DB/SQL dependencies

During index build, they are merged into a **single unified graph** under `active_index`.
Therefore `expand_dependency_tree` does not choose a "graph mode" — it always expands the unified graph.

Contract requirements:

- node IDs are unique within `active_index`
- edge types may differ (C# vs DB), but are filtered via a single `edge_allowlist`
- all steps operate in the same Scope (`repository + branch + ACL`)

---

## `expand_dependency_tree`

### Input

- `state.retrieval_seed_nodes: List[str]` (required)
- `state.branch` (required)
- `state.repository` (required; empty → runtime error)
- `state.retrieval_filters` (optional but sacred; must be passed to provider)

### Expansion parameters from YAML (no guesswork)

Parameters must be provided via `*_from_settings` mappings:

- `step.raw.max_depth_from_settings` (required)
- `step.raw.max_nodes_from_settings` (required)
- `step.raw.edge_allowlist_from_settings` (required)

Fail-fast:

- missing any `*_from_settings` → runtime error
- referenced settings key missing → runtime error

### Output

- `state.graph_seed_nodes: List[str]`
- `state.graph_expanded_nodes: List[str]`
- `state.graph_edges: List[Dict[str, Any]]`
- `state.graph_debug: Dict[str, Any]`

### Minimal required schemas

`state.graph_edges` item (minimum):

```python
{
  "from_id": str,
  "to_id": str,
  "edge_type": str,
}
```

`state.graph_debug` keys always present:

```python
{
  "seed_count": int,
  "expanded_count": int,
  "edges_count": int,
  "truncated": bool,
  "reason": str,  # "ok" | "no_seeds" | "limit_reached" | ...
}
```

### Security

`expand_dependency_tree` MUST apply the same ACL filters as `search_nodes`.

---

## `fetch_node_texts`

### Purpose

`fetch_node_texts` materializes node texts under a strict token budget.

It **does not** build LLM-ready `context_blocks` formatting. It produces **structured JSON-like output**
that a separate action (e.g., `render_context_blocks`) can convert into:

- flat results list (no graph), or
- indentation-based graph view (max 3 levels), etc.

### Input

- `state.graph_expanded_nodes: List[str]` (preferred)
- `state.graph_seed_nodes: List[str]` (used if expanded list is empty)
- `state.branch` (required)
- `state.repository` (required; empty → runtime error)

### Token budget (required)

- `step.raw.budget_tokens` (optional)
  - if present → use it
  - if missing → use `floor(pipeline_settings.max_context_tokens * 0.70)`

Fail-fast:

- missing `pipeline_settings.max_context_tokens` or `<= 0` → runtime error
- computed `budget_tokens <= 0` → runtime error

Mutual exclusivity:

- `step.raw.max_chars` is NOT allowed together with `budget_tokens`.
  If both are present → runtime error.

### Prioritization strategy

- `step.raw.prioritization_mode` (optional)
  - allowed: `seed_first` | `graph_first` | `balanced`
  - missing → `balanced`
  - unknown → runtime error

 Balanced mode is defined as **deterministic interleaving**:  
 1) Build graph-only list sorted by `(depth asc, id asc)`  
 2) Interleave: `seed[0]`, `graph[0]`, `seed[1]`, `graph[1]`, ...  
 3) If one list is exhausted → append the rest from the other list.

### Output

`fetch_node_texts` produces:

- `state.node_texts: List[Dict[str, Any]]` (required)

Each item MUST contain at minimum:

```python
{
  "id": str,
  "text": str,
  "is_seed": bool,        # True if id is from retrieval_seed_nodes
  "depth": int,           # 0 for seed, >=1 for graph-expanded nodes
  "parent_id": str | None # None for seeds; for graph nodes, best-effort parent
}
```

Notes:

- `depth` and `parent_id` make it easy to later render an indented tree view.
- The contract does NOT require a perfect tree reconstruction. It only requires
  that rendering is possible and deterministic.

### Token counting and snippet policy (Option A: atomic snippets)

This contract adopts **Option A: atomic snippets**.

- A single node text snippet is **atomic**.
- If a candidate snippet does not fit in the remaining token budget,
  it is **skipped** (not partially truncated).

Stop condition:

- The action continues scanning candidates in deterministic order,
  skipping those that do not fit.
- It stops when it reaches the end of the candidate queue.

Token estimator:

- The implementation MUST use the system-wide token counter already used by pipeline budgeting
  (e.g., `runtime.token_counter`, or the equivalent shared estimator).
- The token estimator must be deterministic for the same input text.

### Invariants

- `fetch_node_texts` must enforce Scope (`repository + branch + ACL` where applicable).
- It must not materialize unbounded text and rely on a later trimming step.
- It must not modify the ID lists (seed/expanded). It only materializes text for selected IDs.

---

## Minimal happy path

1) `search_nodes` → `state.retrieval_seed_nodes`
2) `expand_dependency_tree` → `state.graph_seed_nodes`, `state.graph_expanded_nodes`, `state.graph_edges`, `state.graph_debug`
3) `fetch_node_texts` → `state.node_texts`
4) (separate action) `render_context_blocks` → builds final evidence string for the LLM
