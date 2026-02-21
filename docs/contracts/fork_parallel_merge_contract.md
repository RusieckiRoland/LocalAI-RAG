# Fork + Parallel + Merge Contract

This document defines the snapshot-based comparison flow using:
- `fork_action`
- `parallel_roads_action`
- `merge_action`

## Core concept: snapshot determinism

A **snapshot** is a frozen dataset. The same question sent to the same snapshot must produce the same results.

In reality, the same question can return different answers across time or versions, for example:
- code repositories at different releases
- regulations that change over time
- any dataset that evolves

To preserve determinism, the system always queries a specific snapshot. Snapshots are grouped into **snapshot_sets** so users can explicitly target a concrete dataset/version at a given time.

## When comparison is needed

To compare two snapshots (e.g., version A vs version B), the pipeline uses a three‑step action set:
- `fork_action`: runs the same retrieval path for each snapshot
- `parallel_roads_action`: isolates and stores results per snapshot
- `merge_action`: merges the snapshot‑specific results into one context

## Responsibilities

### `fork_action`
- fans out execution across multiple snapshot IDs
- runs identical steps per snapshot
- does not merge results

### `parallel_roads_action`
- stores results per snapshot key (isolation)
- prevents cross‑mixing of context

### `merge_action`
- combines isolated results into one context
- labels each branch (e.g., “Branch A”, “Branch B”) so the model can compare

## Example 1 — code repo comparison

Goal: compare feature behavior between release 4.60 and 4.90.

Flow:
1) `fork_action` runs retrieval per snapshot
2) `parallel_roads_action` stores results per snapshot
3) `merge_action` builds one labeled context
4) `call_model` produces the comparison answer

## Example 2 — regulation changes

Goal: compare the wording of clauses between 2021 and 2024.

Flow:
1) `fork_action` runs retrieval per snapshot
2) `parallel_roads_action` stores results per snapshot
3) `merge_action` merges and labels
4) `call_model` summarizes differences

## YAML example

```yaml
- id: parallel_roads
  action: parallel_roads_action
  next: fork_snapshots

- id: fork_snapshots
  action: fork_action
  search_action: search_nodes
  snapshots:
    snapshot_a: "${snapshot_id}"
    snapshot_b: "${snapshot_id_b}"
  next: fetch_node_texts

- id: fetch_node_texts
  action: fetch_node_texts
  next: merge_snapshots

- id: merge_snapshots
  action: merge_action
  snapshots:
    snapshot_a: "Branch {}"
    snapshot_b: "Branch {}"
  next: call_model_compare

- id: call_model_compare
  action: call_model
  prompt_key: "compare_answer_v1"
  user_parts:
    evidence:
      source: context_blocks
      template: "### Context:\n{}\n\n"
  next: finalize
```

## Design rules

- Snapshot determinism is mandatory.
- Snapshot comparison requires isolation per branch and a labeled merge.
- `fork_action` is for execution fan‑out only.
- `parallel_roads_action` is for storage isolation only.
- `merge_action` is for context assembly only.
