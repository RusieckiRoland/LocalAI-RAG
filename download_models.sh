#!/usr/bin/env bash
# Download all required models into ./models/*
# Run this script from the repository root.
#
# This script is designed to be idempotent:
# - existing non-empty files are skipped,
# - missing files are downloaded,
# - failed downloads are reported,
# - final verification checks all required files.

set -uo pipefail

# ---------------------------------------------------------------------------
# Report state
# ---------------------------------------------------------------------------

DOWNLOADED=()
SKIPPED=()
ERRORS=()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WGET_RETRIES="${WGET_RETRIES:-3}"
WGET_TIMEOUT_SECONDS="${WGET_TIMEOUT_SECONDS:-30}"

CODE_DIR="models/code_analysis/Codestral"
EMBD_DIR="models/embedding/e5-base-v2"
EN_PL_DIR="models/translation/en_pl/Helsinki_NLPopus_mt_en_pl"
PL_EN_DIR="models/translation/pl_en/Helsinki_NLPopus_mt_pl_en"

CODE_MODEL_FILE="Codestral-22B-v0.1-Q6_K.gguf"
CODE_MODEL_URL="https://huggingface.co/bartowski/Codestral-22B-v0.1-GGUF/resolve/main/Codestral-22B-v0.1-Q6_K.gguf?download=true"

HF_EMBEDDING_REPO="intfloat/e5-base-v2"

HF_EMBEDDING_FILES=(
  "model.safetensors"
  "config.json"
  "modules.json"
  "1_Pooling/config.json"
  "sentence_bert_config.json"
  "tokenizer.json"
  "tokenizer_config.json"
  "special_tokens_map.json"
  "vocab.txt"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

absolute_path() {
  local path="$1"

  if command -v realpath >/dev/null 2>&1; then
    realpath "$path" 2>/dev/null || printf '%s\n' "$path"
    return 0
  fi

  printf '%s\n' "$path"
}

add_downloaded() {
  DOWNLOADED+=("$(absolute_path "$1")")
}

add_skipped() {
  SKIPPED+=("$(absolute_path "$1")")
}

add_error() {
  ERRORS+=("$1")
}

need_bin() {
  local bin="$1"

  if ! command -v "$bin" >/dev/null 2>&1; then
    add_error "Missing required command: $bin"
    return 1
  fi

  return 0
}

ensure_dir() {
  local dir="$1"

  if ! mkdir -p "$dir"; then
    add_error "Cannot create directory: $dir"
    return 1
  fi

  return 0
}

is_non_empty_file() {
  local path="$1"
  [ -f "$path" ] && [ -s "$path" ]
}

mark_existing_or_missing() {
  local path="$1"

  if is_non_empty_file "$path"; then
    add_skipped "$path"
    return 0
  fi

  return 1
}

download_with_wget() {
  local url="$1"
  local out="$2"
  local tmp="${out}.part"

  if is_non_empty_file "$out"; then
    echo "✓ Skipping $(basename "$out") - already exists"
    add_skipped "$out"
    return 0
  fi

  echo "→ Fetching $(basename "$out")"

  if ! wget \
    --continue \
    --tries="$WGET_RETRIES" \
    --timeout="$WGET_TIMEOUT_SECONDS" \
    --show-progress \
    --output-document="$tmp" \
    "$url"; then

    add_error "Failed to download: $(absolute_path "$out") from $url"
    return 1
  fi

  if ! is_non_empty_file "$tmp"; then
    add_error "Downloaded temporary file is missing or empty: $(absolute_path "$tmp")"
    return 1
  fi

  if ! mv "$tmp" "$out"; then
    add_error "Cannot move downloaded file from $(absolute_path "$tmp") to $(absolute_path "$out")"
    return 1
  fi

  echo "✓ Downloaded $(basename "$out")"
  add_downloaded "$out"
  return 0
}

download_hf_file() {
  local repo="$1"
  local file="$2"
  local target_dir="$3"
  local target_path="${target_dir}/${file}"

  if is_non_empty_file "$target_path"; then
    echo "✓ Skipping $file - already exists"
    add_skipped "$target_path"
    return 0
  fi

  echo "→ Fetching $repo:$file"

  if ! hf download "$repo" "$file" --local-dir "$target_dir"; then
    add_error "hf download failed: repo=$repo file=$file target=$(absolute_path "$target_dir")"
    return 1
  fi

  if ! is_non_empty_file "$target_path"; then
    add_error "hf download finished but file is missing or empty: $(absolute_path "$target_path")"
    return 1
  fi

  echo "✓ Downloaded $file"
  add_downloaded "$target_path"
  return 0
}

verify_required_file() {
  local path="$1"

  if is_non_empty_file "$path"; then
    return 0
  fi

  add_error "Missing or empty required file: $(absolute_path "$path")"
  return 1
}

print_report() {
  echo
  echo "================================================================"
  echo "DOWNLOAD REPORT"
  echo "================================================================"

  echo
  echo "Downloaded:"
  if [ "${#DOWNLOADED[@]}" -eq 0 ]; then
    echo " - none"
  else
    for item in "${DOWNLOADED[@]}"; do
      echo " - $item"
    done
  fi

  echo
  echo "Skipped:"
  if [ "${#SKIPPED[@]}" -eq 0 ]; then
    echo " - none"
  else
    for item in "${SKIPPED[@]}"; do
      echo " - $item"
    done
  fi

  echo
  echo "Errors:"
  if [ "${#ERRORS[@]}" -eq 0 ]; then
    echo " - none"
  else
    for item in "${ERRORS[@]}"; do
      echo " - $item"
    done
  fi

  echo
  echo "================================================================"

  if [ "${#ERRORS[@]}" -eq 0 ]; then
    echo "✅ Done without errors."
  else
    echo "❌ Done with errors."
  fi
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

need_bin wget
need_bin hf

if [ "${#ERRORS[@]}" -ne 0 ]; then
  print_report
  exit 1
fi

# ---------------------------------------------------------------------------
# 1) Code model: Codestral 22B GGUF Q6_K
# ---------------------------------------------------------------------------

echo "==> Code model"
if ensure_dir "$CODE_DIR"; then
  download_with_wget "$CODE_MODEL_URL" "${CODE_DIR}/${CODE_MODEL_FILE}"
fi

# ---------------------------------------------------------------------------
# 2) Embedding model: intfloat/e5-base-v2
# ---------------------------------------------------------------------------

echo "==> Embedding model (e5-base-v2)"
if ensure_dir "$EMBD_DIR"; then
  for file in "${HF_EMBEDDING_FILES[@]}"; do
    download_hf_file "$HF_EMBEDDING_REPO" "$file" "$EMBD_DIR"
  done
fi

# ---------------------------------------------------------------------------
# 3) EN -> PL translation model: gsarti/opus-mt-tc-en-pl
# ---------------------------------------------------------------------------

echo "==> Translation EN->PL (gsarti/opus-mt-tc-en-pl)"
if ensure_dir "$EN_PL_DIR"; then
  download_with_wget "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/config.json"             "${EN_PL_DIR}/config.json"
  download_with_wget "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/metadata.json"           "${EN_PL_DIR}/metadata.json"
  download_with_wget "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/pytorch_model.bin"       "${EN_PL_DIR}/pytorch_model.bin"
  download_with_wget "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/source.spm"              "${EN_PL_DIR}/source.spm"
  download_with_wget "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/special_tokens_map.json" "${EN_PL_DIR}/special_tokens_map.json"
  download_with_wget "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/target.spm"              "${EN_PL_DIR}/target.spm"
  download_with_wget "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/tokenizer_config.json"   "${EN_PL_DIR}/tokenizer_config.json"
  download_with_wget "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/vocab.json"              "${EN_PL_DIR}/vocab.json"
fi

# ---------------------------------------------------------------------------
# 4) PL -> EN translation model: Helsinki-NLP/opus-mt-pl-en
# ---------------------------------------------------------------------------

echo "==> Translation PL->EN (Helsinki-NLP/opus-mt-pl-en)"
if ensure_dir "$PL_EN_DIR"; then
  download_with_wget "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/pytorch_model.bin"     "${PL_EN_DIR}/pytorch_model.bin"
  download_with_wget "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/config.json"           "${PL_EN_DIR}/config.json"
  download_with_wget "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/tokenizer_config.json" "${PL_EN_DIR}/tokenizer_config.json"
  download_with_wget "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/source.spm"            "${PL_EN_DIR}/source.spm"
  download_with_wget "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/target.spm"            "${PL_EN_DIR}/target.spm"
  download_with_wget "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/vocab.json"            "${PL_EN_DIR}/vocab.json"
fi

# ---------------------------------------------------------------------------
# Final verification
# ---------------------------------------------------------------------------

verify_required_file "${CODE_DIR}/${CODE_MODEL_FILE}"

for file in "${HF_EMBEDDING_FILES[@]}"; do
  verify_required_file "${EMBD_DIR}/${file}"
done

verify_required_file "${EN_PL_DIR}/config.json"
verify_required_file "${EN_PL_DIR}/metadata.json"
verify_required_file "${EN_PL_DIR}/pytorch_model.bin"
verify_required_file "${EN_PL_DIR}/source.spm"
verify_required_file "${EN_PL_DIR}/special_tokens_map.json"
verify_required_file "${EN_PL_DIR}/target.spm"
verify_required_file "${EN_PL_DIR}/tokenizer_config.json"
verify_required_file "${EN_PL_DIR}/vocab.json"

verify_required_file "${PL_EN_DIR}/pytorch_model.bin"
verify_required_file "${PL_EN_DIR}/config.json"
verify_required_file "${PL_EN_DIR}/tokenizer_config.json"
verify_required_file "${PL_EN_DIR}/source.spm"
verify_required_file "${PL_EN_DIR}/target.spm"
verify_required_file "${PL_EN_DIR}/vocab.json"

# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

print_report

if [ "${#ERRORS[@]}" -eq 0 ]; then
  exit 0
fi

exit 1