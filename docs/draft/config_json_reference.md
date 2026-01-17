# LocalAI-RAG — config.json reference

This document explains the fields in `config.json` used by LocalAI-RAG.  
Goal: quickly understand **what each field means**, where logs go, and how logging (including AI logs) is configured.

---

## General rules

- `config.json` is the **source of truth** for runtime settings.
- Logging is conceptually split into:
  1) **normal application log** (INFO/WARN/ERROR, etc.),
  2) **AI interactions** (structured JSONL),
  3) **AI interaction log** (human-readable TXT).
- The `logging` section contains rotation, levels, filenames, and (optionally) AI logging toggles.
- If you later allow overrides via environment variables, treat ENV as **override only** (the base config still comes from `config.json`).

---

## Top-level fields

### `output_dir` (string)
Output directory for generated artifacts (e.g., branch snapshots).  
Example: `"branches"`.

### `model_path_embd` (string)
Path to the embeddings model used for vectorization (RAG).  
Example: `"models/embedding/e5-base-v2"`.

### `model_path_analysis` (string)
Path to the LLM used for analysis/answer generation.  
Example: `"models/code_analysis/codeLlama_13b_Instruct/codellama-13b-instruct.Q8_0.gguf"`.

### `model_translation_en_pl` (string)
Translation model EN → PL (used depending on `translate_chat` and pipeline).  
Example: `"models/translation/en_pl/Helsinki_NLPopus_mt_en_pl"`.

### `model_translation_pl_en` (string)
Translation model PL → EN (used depending on `translate_chat` and pipeline).  
Example: `"models/translation/pl_en/Helsinki_NLPopus_mt_pl_en"`.

### `use_gpu` (bool)
Whether to use GPU (if supported by the backend and environment).  
Example: `true`.

### `plantuml_server` (string)
PlantUML server URL used to generate diagrams.  
Example: `"http://localhost:8080"`.

### `branch` (string)
Default branch name (often used as default filtering in pipeline/retrieval).  
Example: `"develop"`.

### `vector_indexes_root` (string)
Root directory where vector indexes are stored.  
Example: `"repositories/nopCommerce/indexes"`.

### `active_index_id` (string)
Identifier of the currently active index (e.g., snapshot/version id).  
Example: `"2025-12-14__develop"`.

### `repo_name` (string)
Repository name (metadata / identification in logs).  
Example: `"nopCommerce"`.

---

## Logging

### `log_path` (string) — legacy / compatibility
Path to the AI interaction log file.  
Note: long-term, prefer `logging.ai_interaction.human_file` + `logging.dir`.  
Example: `"log/ai_interaction.log"`.

---

## `logging` section

The `logging` section defines **normal application logging** and AI log files.

### Common settings

- `logging.dir` (string)  
  Base directory for logs. Example: `"log"`.

- `logging.level` (string)  
  Normal application log level: `"INFO"`, `"WARNING"`, `"ERROR"`, `"DEBUG"`.  
  Example: `"INFO"`.

- `logging.when` (string)  
  Rotation schedule, e.g. `"midnight"`.

- `logging.interval` (int)  
  Rotation interval (units depend on `when`). Example: `1`.

- `logging.backup_count` (int)  
  How many rotated files to keep. Example: `14`.

- `logging.also_stdout` (bool)  
  Whether to also log to stdout (useful in CI). Example: `false`.

### Log files

- `logging.app_file` (string)  
  Normal application log filename. Example: `"app.log"`.

- `logging.interactions_file` (string)  
  Structured AI interactions log filename (JSONL). Example: `"ai_interactions.jsonl"`.

- `logging.interactions_level` (string)  
  Logger level for `ai_interactions.jsonl`.  
  **Note:** this is a logger level, not a “create file” toggle.  
  Example: `"TRACE"`.

---

## `logging.ai_interaction` (agreed extension)

This section controls **whether and how** AI interaction artifacts are produced.  
It is **independent from** INFO/DEBUG log levels to avoid confusion with the `TRACE` log level.

Proposed fields:

- `logging.ai_interaction.capture_jsonl` (bool)  
  Whether to write the structured JSONL interactions file (`logging.interactions_file`).  
  If `false` → no JSONL interaction records should be created/written, and **no pointer message** should be emitted into the normal app log.

- `logging.ai_interaction.human_log` (bool)  
  Whether to write the human-readable interaction log (TXT).

- `logging.ai_interaction.human_file` (string)  
  Human-readable log filename (within `logging.dir`).  
  Example: `"ai_interaction.log"`.

- `logging.ai_interaction.lang` (string)  
  Language for headings/labels in the human log. Default `"en"`.  
  Example: `"pl"`.

- `logging.ai_interaction.locale_dir` (string)  
  Directory for translation files (e.g., `locales/ai_interaction/pl.json`).  
  If a language file is missing → **warning in the normal app log** and fallback to English.

- `logging.ai_interaction.emit_app_log_pointers` (bool)  
  If `true` and `capture_jsonl` is enabled, the normal app log should contain messages like:  
  `AI interaction captured (details in <path-to-jsonl>)`  
  and similarly for the human log.

---

## Target log layout (recommended)

Inside `logging.dir` (e.g. `log/`) you will have:

- `app.log` — normal application log (INFO/WARN/ERROR)
- `ai_interactions.jsonl` — structured log (JSONL), 1 JSON record = 1 interaction/turn
- `ai_interaction.log` — human-readable log (TXT), many interactions appended (separated by section headers)

---

## Translation files for human log headings

Translation files are JSON dictionaries mapping English keys to localized labels.

Example:

`locales/ai_interaction/pl.json`:
```json
{
  "Timestamp": "Znacznik czasu",
  "Original question": "Pytanie oryginalne",
  "Final answer": "Odpowiedź końcowa"
}
```

Rule:
- if `lang != "en"` and the file does not exist → warning + fallback to English.

---

## Minimal example (logging fragment)

```json
"logging": {
  "dir": "log",
  "level": "INFO",
  "app_file": "app.log",
  "interactions_file": "ai_interactions.jsonl",
  "interactions_level": "TRACE",
  "when": "midnight",
  "interval": 1,
  "backup_count": 14,
  "also_stdout": false,
  "ai_interaction": {
    "capture_jsonl": true,
    "human_log": true,
    "human_file": "ai_interaction.log",
    "lang": "en",
    "locale_dir": "locales/ai_interaction",
    "emit_app_log_pointers": true
  }
}
```

---

## Security / privacy note

AI logs (JSONL/TXT) may contain:
- user questions,
- retrieved code/SQL context,
- model outputs.

In production you should:
- enable them only intentionally,
- consider masking/anonymization,
- keep rotation/retention under control.
