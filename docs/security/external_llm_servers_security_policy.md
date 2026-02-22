# External LLM Servers Security Policy

## Purpose and scope

This policy defines the required security controls for using **external LLM endpoints** (self‑hosted or third‑party) from LocalAI‑RAG.
It applies to any configuration that sends prompts or context to a remote HTTP(S) endpoint.

## Required controls

### 1) TLS / transport security
- **TLS is mandatory** for external endpoints (`https://`).
- Certificate validation must be enabled (no insecure or self‑signed bypasses in production).
- If a private CA is required, install it in the system trust store.

### 2) API key and secret handling
- API keys must be stored in **environment variables** or a secret store (e.g., Vault, Key Vault, KMS).
- Keys must **never** be committed to the repository.
- Rotation procedures must be documented and tested.

### 3) Allowlist of hosts / base URLs
- Only **explicitly allowlisted** hostnames/base URLs may be used in production.
- Any non‑allowlisted endpoint must result in a **fail‑fast error**.

### 4) Request logging and PII redaction
- Requests and responses must be logged for audit **without** storing raw secrets or PII.
- Logs must redact:
  - API keys / Authorization headers
  - PII fields (emails, phone numbers, access tokens, secrets)
- The redaction policy must be deterministic and documented.

### 5) Rate limiting / throttling
- External calls must enforce **concurrency limits** and **retry backoff**.
- Throttling configuration must be explicit; no silent unlimited retries.

### 6) Fail‑fast configuration
- Misconfiguration (missing base URL, invalid TLS, missing key) must **raise errors** and stop the request.
- No silent fallbacks in production.

## Non‑goals

- Defining prompt format or prompt content.
- Guaranteeing model output quality.
- Replacing organization‑wide security policies.

## Out of scope

- Local‑only inference endpoints running on the same host.
- Offline / air‑gapped model execution.
