#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

export RUN_INTEGRATION_TESTS=1
: "${INTEGRATION_EMBED_MODEL:=models/embedding/e5-base-v2}"
: "${INTEGRATION_BUNDLE_GLOB:=Release_FAKE_ENTERPRISE_*.zip}"
export RAG_PIPELINE_TRACE_FILE=1
export RAG_PIPELINE_TRACE_DIR="log/integration/retrival/pipeline_traces"

python -m pytest -o addopts= -m integration tests/integration/retrival "$@"
