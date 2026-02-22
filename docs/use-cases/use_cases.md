# LocalAI-RAG — Verified Runtime Use Cases

Date: 2026-02-22

This document is the maintained runtime use-case catalog verified against current code and tests.
It intentionally excludes `UC-FILE-*` style file inventory entries.

## WEB/API

### UC-WEB-V1-001 — Open UI
- Entry: `GET /`
- Code: `code_query_engine/query_server_dynamic.py`, `frontend/Rag.html`
- Tests: no dedicated `/` endpoint test

### UC-WEB-V1-002 — Load app config
- Entry: `GET /app-config/dev`, `GET /app-config/prod`
- Code: `code_query_engine/query_server_dynamic.py`, `server/app_config/app_config_service.py`, `ui_contracts/frontend_requirements/templates.json`
- Tests: `tests/api/test_search_prod_auth.py`, `tests/app_config/test_app_config_service.py`, `tests/app_config/test_templates_store.py`

### UC-WEB-V1-003 — Prod auth check
- Entry: `GET /auth-check/prod`
- Code: `code_query_engine/query_server_dynamic.py`
- Tests: `tests/api/test_search_prod_auth.py`

### UC-WEB-V1-004 — Query execution
- Entry: `POST /search/dev|prod`, `POST /query/dev|prod`
- Code: `code_query_engine/query_server_dynamic.py`, `code_query_engine/dynamic_pipeline.py`
- Tests: `tests/api/test_search_permissions.py`, `tests/api/test_search_prod_auth.py`, `tests/e2e/test_server_query_degraded_direct.py`

### UC-WEB-V1-005 — Stream and cancel
- Entry: `GET /pipeline/stream/dev|prod`, `POST /pipeline/cancel/dev|prod`
- Code: `code_query_engine/work_callback/controller.py`, `code_query_engine/work_callback/cancel_controller.py`
- Tests: `tests/mock/test_mock_server_endpoints.py`

### UC-WEB-V1-006 — Chat history CRUD + query filter
- Entry: `/chat-history/sessions*`, `/chat-history/sessions/<id>/messages*`
- Code: `code_query_engine/query_server_dynamic.py`, `code_query_engine/conversation_history/service.py`
- Tests: `tests/api/test_chat_history_mock_endpoints.py`, `tests/conversation_history/test_conversation_history_service.py`, `tests/conversation_history/test_durable_store_fallback.py`

### UC-WEB-V1-007 — Important flag and soft-delete
- Entry: `PATCH /chat-history/sessions/<id>` (`important`, `softDeleted`), `DELETE /chat-history/sessions/<id>`
- Code: `code_query_engine/query_server_dynamic.py`
- Tests: `tests/api/test_chat_history_mock_endpoints.py`

## PIPELINE

### UC-PIP-V1-001 — Rejewski retrieval flow
- Code: `pipelines/rejewski.yaml`, `pipelines/base/marian_rejewski_code_analysis_base.yaml`
- Tests: `tests/pipeline/test_engine_smoke.py`, `tests/e2e/test_pipeline_scenarios_runner.py`

### UC-PIP-V1-002 — Chuck direct answer
- Code: `pipelines/chuck.yaml`
- Tests: `tests/e2e/test_pipeline_scenarios_runner.py`

### UC-PIP-V1-003 — Snapshot comparison flow
- Code: `pipelines/shannon.yaml`, `code_query_engine/pipeline/actions/parallel_roads.py`
- Tests: `tests/pipeline/test_parallel_roads_actions.py`

### UC-PIP-V1-004 — Final answer banner handling
- Code: `code_query_engine/pipeline/actions/call_model.py`, `code_query_engine/pipeline/actions/finalize.py`, `code_query_engine/pipeline/state.py`
- Tests: `tests/pipeline/test_call_model_custom_banner.py`, `tests/pipeline/test_finalize_writes_conversation_history.py`

## RETRIEVAL

### UC-RET-V1-001 — semantic/BM25/hybrid search
- Code: `code_query_engine/pipeline/actions/search_nodes.py`, `code_query_engine/pipeline/providers/weaviate_retrieval_backend.py`
- Tests: `tests/pipeline/test_search_nodes_action_contracts.py`, `tests/pipeline/test_weaviate_retrieval_backend.py`

### UC-RET-V1-002 — query parser `jsonish_v1`
- Code: `code_query_engine/pipeline/query_parsers/jsonish_query_parser.py`
- Tests: `tests/pipeline/test_jsonish_query_parser.py`, `tests/pipeline/test_search_nodes_action_contracts.py`

### UC-RET-V1-003 — dependency tree expansion
- Code: `code_query_engine/pipeline/actions/expand_dependency_tree.py`, `code_query_engine/pipeline/providers/ports.py`
- Tests: `tests/pipeline/test_expand_dependency_tree_action.py`, `tests/integration/retrival/test_dependency_tree.py`

### UC-RET-V1-004 — fetch node texts + metadata in context
- Code: `code_query_engine/pipeline/actions/fetch_node_texts.py`
- Tests: `tests/pipeline/test_fetch_node_texts_action.py`, `tests/integration/retrival/test_fetch_node_texts.py`

### UC-RET-V1-005 — security metadata aggregation
- Fields: `classification_labels_union`, `acl_labels_union`, `doc_level_max`
- Code: `code_query_engine/pipeline/actions/fetch_node_texts.py`, `code_query_engine/pipeline/state.py`
- Tests: `tests/pipeline/test_fetch_node_texts_action.py`

### UC-RET-V1-006 — context budget management
- Code: `code_query_engine/pipeline/actions/manage_context_budget.py`
- Tests: `tests/pipeline/test_manage_context_budget_action.py`

### UC-RET-V1-007 — loop/repeat guards
- Code: `code_query_engine/pipeline/actions/loop_guard.py`, `code_query_engine/pipeline/actions/repeat_query_guard.py`
- Tests: `tests/pipeline/test_loop_guard_per_step_counter.py`, `tests/pipeline/test_repeat_query_guard_action.py`

## SECURITY

### UC-SEC-V1-001 — UserAccess resolution
- Code: `server/auth/user_access.py`, `server/auth/policies_provider.py`, `config/auth_policies.json`
- Tests: `tests/auth/test_user_access.py`

### UC-SEC-V1-002 — pipeline/snapshot access constraints
- Code: `code_query_engine/query_server_dynamic.py`, `server/pipelines/pipeline_access.py`, `server/snapshots/snapshot_registry.py`
- Tests: `tests/api/test_search_permissions.py`, `tests/snapshots/test_snapshot_registry.py`, `tests/pipeline/test_pipeline_snapshot_store.py`

## OBSERVABILITY

### UC-OBS-V1-001 — Weaviate query logging
- Flag: `WEAVIATE_QUERY_LOG=1`
- Code: `code_query_engine/weaviate_query_logger.py`, `code_query_engine/pipeline/providers/weaviate_retrieval_backend.py`
- Tests: `tests/test_weaviate_query_logger.py`

### UC-OBS-V1-002 — LLM request/response logging
- Flag: `LLM_QUERY_LOG=1`
- Code: `code_query_engine/llm_query_logger.py`, `code_query_engine/llm_server_client.py`
- Tests: `tests/test_llm_query_logger.py`

## Integrations

### UC-INT-V1-001 — command links (PlantUML + EA export)
- Code: `code_query_engine/pipeline/actions/add_command_action.py`, `server/commands/*`, `integrations/ea/*`
- Tests: `tests/commands/test_add_command_action.py`

### UC-INT-V1-002 — pipeline to PlantUML
- Code: `tools/pipeline_to_puml.py`, `code_query_engine/pipeline/loader.py`, `code_query_engine/pipeline/validator.py`
- Tests: no dedicated CLI tests
