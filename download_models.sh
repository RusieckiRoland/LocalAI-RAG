#!/usr/bin/env bash
# Download all required models into the EXISTING folders in ./models/*
# Run this script from the repo root.

set -euo pipefail

# --- Helpers ---------------------------------------------------------------
here="$(pwd)"

need_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: Missing '$1'. Install it first." >&2
    if [ "$1" = "huggingface-cli" ]; then
      echo "Hint: pip install --upgrade huggingface_hub" >&2
    fi
    exit 1
  fi
}

ensure_dir() {
  local d="$1"
  mkdir -p "$d"
}

download_file() {
  # wget with resume support (-c)
  local url="$1"
  local out="$2"
  echo "→ Fetching $(basename "$out")"
  wget -c -q --show-progress -O "$out" "$url"
}

# --- Sanity checks ---------------------------------------------------------
need_bin wget
need_bin huggingface-cli

# --- Paths (must match your repo tree) -------------------------------------
CODE_DIR="models/code_analysis/codeLlama_13b_Instruct"
EMBD_DIR="models/embedding/e5-base-v2"
EN_PL_DIR="models/translation/en_pl/Helsinki_NLPopus_mt_en_pl"   # EN→PL (files from gsarti/opus-mt-tc-en-pl)
PL_EN_DIR="models/translation/pl_en/Helsinki_NLPopus_mt_pl_en"   # PL→EN (Helsinki-NLP/opus-mt-pl-en)

# --- 1) Code model: TheBloke/CodeLlama-13B-Instruct-GGUF (Q8_0) -----------
echo "==> Code model"
ensure_dir "$CODE_DIR"
pushd "$CODE_DIR" >/dev/null
download_file \
  "https://huggingface.co/TheBloke/CodeLlama-13B-Instruct-GGUF/resolve/main/codellama-13b-instruct.Q8_0.gguf" \
  "codellama-13b-instruct.Q8_0.gguf"
popd >/dev/null

# --- 2) Embedding: intfloat/e5-base-v2 ------------------------------------
echo "==> Embedding model (e5-base-v2)"
ensure_dir "$EMBD_DIR"
pushd "$EMBD_DIR" >/dev/null
huggingface-cli download intfloat/e5-base-v2 \
  --include "model.safetensors" "config.json" "modules.json" "1_Pooling/*" \
           "sentence_bert_config.json" "tokenizer.json" "tokenizer_config.json" \
           "special_tokens_map.json" "vocab.txt" \
  --local-dir . \
  --local-dir-use-symlinks False
popd >/dev/null

# --- 3) EN→PL translation: gsarti/opus-mt-tc-en-pl ------------------------
echo "==> Translation EN→PL (gsarti/opus-mt-tc-en-pl)"
ensure_dir "$EN_PL_DIR"
pushd "$EN_PL_DIR" >/dev/null
download_file "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/config.json"             "config.json"
download_file "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/metadata.json"           "metadata.json"
download_file "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/pytorch_model.bin"       "pytorch_model.bin"
download_file "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/source.spm"              "source.spm"
download_file "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/special_tokens_map.json" "special_tokens_map.json"
download_file "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/target.spm"              "target.spm"
download_file "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/tokenizer_config.json"   "tokenizer_config.json"
download_file "https://huggingface.co/gsarti/opus-mt-tc-en-pl/resolve/main/vocab.json"              "vocab.json"
popd >/dev/null

# --- 4) PL→EN translation: Helsinki-NLP/opus-mt-pl-en ---------------------
echo "==> Translation PL→EN (Helsinki-NLP/opus-mt-pl-en)"
ensure_dir "$PL_EN_DIR"
pushd "$PL_EN_DIR" >/dev/null
download_file "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/pytorch_model.bin"     "pytorch_model.bin"
download_file "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/config.json"           "config.json"
download_file "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/tokenizer_config.json" "tokenizer_config.json"
download_file "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/source.spm"            "source.spm"
download_file "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/target.spm"            "target.spm"
download_file "https://huggingface.co/Helsinki-NLP/opus-mt-pl-en/resolve/main/vocab.json"            "vocab.json"
popd >/dev/null

echo "✅ Done. Models downloaded into:"
echo " - $CODE_DIR"
echo " - $EMBD_DIR"
echo " - $EN_PL_DIR"
echo " - $PL_EN_DIR"
