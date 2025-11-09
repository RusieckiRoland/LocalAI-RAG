huggingface-cli download intfloat/e5-base-v2 \
  --include "model.safetensors" "config.json" "modules.json" "1_Pooling/*" \
           "sentence_bert_config.json" "tokenizer.json" "tokenizer_config.json" \
           "special_tokens_map.json" "vocab.txt" \
  --local-dir . \
  --local-dir-use-symlinks False