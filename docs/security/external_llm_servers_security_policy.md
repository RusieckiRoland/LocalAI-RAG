# External LLM Servers Security Policy

This document defines the security rules for selecting an external LLM server (from `ServersLLM.json`) before each request.

## Goals
- Enforce security constraints derived from retrieval metadata.
- Allow deterministic fallback behavior when the default server does not comply.
- Keep local model usage independent from server availability.

## Required State Signals
Before each LLM call, the system must evaluate:
- `classification_labels_union: List[str]`
- `acl_labels_union: List[str]`
- `doc_level_max: Optional[int]`

These values are aggregated during retrieval and attached to the runtime `state`.

## Server Definition Fields
Each server in `ServersLLM.json` can define:
- `allowed_doc_level` (int | null): maximum document level the server is allowed to process.
- `allowed_acl_labels` (list[str]): explicit ACL labels allowed for this server.
- `allowed_classification_labels` (list[str]): explicit classification labels allowed for this server.
- `is_trusted_server` (bool): if true, security checks are skipped entirely for that server.
- `is_trusted_for_all_acl` (bool): if true and `allowed_acl_labels` is empty, the server is trusted for all ACL labels.

## Selection Rules
1. **Default server selection**
   - If external servers are enabled (`serverLLM=true`), choose the server with `default:true`.
   - If multiple servers have `default:true`, the first in `ServersLLM.json` is used.

2. **Security checks (per request)**
   - If `is_trusted_server=true`, the server is accepted without checks.
   - Otherwise:
     - `allowed_doc_level` must be defined and must be **>=** `doc_level_max` (when `doc_level_max` is set).
     - `acl_labels_union` must be fully contained in `allowed_acl_labels`.
       - Exception: if `allowed_acl_labels` is empty and `is_trusted_for_all_acl=true`, ACL check passes.
     - `classification_labels_union` must be fully contained in `allowed_classification_labels`.

3. **Fallback behavior**
   - If the default server fails security checks, the system scans the remaining servers in list order.
   - The first server that satisfies security requirements is selected.
   - If no external server satisfies the policy:
     - If the local model is enabled (`enable_model_path_analysis=true`), use it as fallback.
     - Otherwise, no analysis is performed.

## Override and Error Notices
When the default server is not used, the system must set:
- `llm_server_security_override_notice` in pipeline state.

This notice is prepended to the final answer during `finalize`.

### Default Messages (config)
Default messages are defined in `config.json`:
```json
{
  "llm_server_security_messages_default": {
    "override_notice": {
      "neutral": "LLM server was changed because the default server does not satisfy security policy.",
      "translated": "Zmieniono serwer LLM, ponieważ domyślny serwer nie spełnia polityki bezpieczeństwa."
    },
    "no_server_notice": {
      "neutral": "Analysis was not performed because no LLM server satisfies security policy.",
      "translated": "Nie wykonano analizy, ponieważ żaden serwer LLM nie spełnia polityki bezpieczeństwa."
    }
  }
}
```

### Pipeline Overrides
Pipelines may override these messages via pipeline settings:
```yaml
llm_server_security_messages:
  override_notice:
    neutral: "Custom override notice..."
    translated: "Niestandardowy komunikat..."
  no_server_notice:
    neutral: "Custom no-server notice..."
    translated: "Niestandardowy komunikat..."
```

## Local Model Enablement
Local model usage is controlled independently from server access:
- `serverLLM` controls whether external servers are allowed.
- `enable_model_path_analysis` controls whether the local analysis model is available.

If both are enabled, the system uses servers first and falls back to local model only when security policy blocks all servers.

