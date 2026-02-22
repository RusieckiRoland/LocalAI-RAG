# Security Documentation Index

## Core Documents (this folder)
1. `external_llm_servers_security_policy.md`  
   External LLM server selection policy, security checks, override/no-server notices, and local fallback rules.

2. `retrieval_access_control_policy.md`  
   ACL/classification/doc-level semantics and enforcement points across retrieval and graph expansion.

3. `permissions_and_identity_provider.md`  
   Identity provider, permissions config, and access-context derivation used to build retrieval filters.

---

## Related Documents (outside this folder)
- `docs/contracts/authorization_contract.md`  
  Formal security model contract (classification/clearance/ACL semantics and requirements).

- `docs/tests/retrieval_integration_tests.md`  
  Security scenarios and expected behavior for ACL/classification/clearance in retrieval/graph.

- `docs/tests/retrieval_integration_tests_spec.md`  
  Implementation-oriented integration test specification, including security requirements.

- `docs/adr/adr-0003-retrieval-model-and-multi-stage-retrieval-pipeline.md`  
  Security filtering in multi-stage retrieval (filters before ranking).

- `docs/adr/adr-0004-replace-faiss-with-weaviate.md`  
  Mandatory metadata/ACL filtering invariants for retrieval backend.

- `docs/adr/adr-0005-retrieval-backend-abstraction-and-injection.md`  
  Security-critical filters must be enforced in each stage.

- `docs/adr/adr-0007-static-pipeline-config-and-dynamic-runtime-directives-via-inbox-dispatcher.md`  
  Dynamic directives must not override security filters.
