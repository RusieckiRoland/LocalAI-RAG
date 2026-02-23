# Retrieval Access Control Policy

This document defines the access-control (ACL/classification/doc level) rules enforced during retrieval and graph expansion.

## Core Concepts
- **ACL tags (`acl_tags_any`)**: user access groups (OR semantics).
- **Classification labels (`classification_labels_all`)**: required labels (ALL/subset semantics).
- **Document level (`doc_level`)**: numeric clearance level, enforced only when the security model uses clearance levels.

## Semantics
### ACL (OR)
- Empty ACL on a document means **public**.
- A document is visible if:
  - it has no ACL tags, or
  - it shares **at least one** ACL tag with `acl_tags_any`.

### Classification (ALL / subset)
- Classification labels on a document must be a **subset** of `classification_labels_all`.
- Empty classification on a document is allowed.
- If a document contains any label not included in `classification_labels_all`, it must be excluded.

### Doc Level (clearance)
- Enforced only when `permissions.security_model.kind = "clearance_level"`.
- Document is visible if `doc_level <= user_clearance_level`.

## Enforcement Points
These rules **must** be applied in all retrieval stages:
1. `search_nodes` (semantic/bm25/hybrid)
2. `fetch_node_texts`
3. Graph expansion (e.g., dependency tree)

Security filters are applied **before** ranking, fusion, or truncation.

## Required Pipeline/Runtime Signals
Security rules are driven by:
- `permissions` in `config.json` (security_enabled, acl_enabled, security_model).
- User access context (derived from identity provider / auth policies).
- `state.retrieval_filters` containing:
  - `acl_tags_any`
  - `classification_labels_all`
  - optional clearance level / doc level constraint

Dynamic pipeline directives must **not** override these security-critical filters.

## Expected Behavior Summary
1. Retrieval filters are mandatory in every stage.
2. ACL is OR.
3. Classification is ALL/subset.
4. When `acl_enabled=true`, ACL metadata MUST be present on every document (even if empty `[]`). Missing ACL fields are invalid and must fail ingestion/import. An empty list is an explicit "public" marker by policy (not a default for missing data).
5. Empty classification = allowed.
6. Doc level enforced only for clearance model.
