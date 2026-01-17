# Logging in LocalAI-RAG

This document describes the **target, consistent** logging model in LocalAI-RAG:
- **regular application logging** (levels, `app.log`),
- **AI interaction logging** in two formats:
  - **JSONL** (structured events per turn) → `ai_interactions.jsonl`
  - **human-readable** (readable text per turn) → `ai_interaction.log`

## 1. Source of truth: `config.json`

All logging configuration comes from `config.json`.
**ENV is not used as the source of truth** for enabling/disabling interaction logs (ENV may still be used for non-logging concerns such as tokens, Redis, etc.).

### 1.1. `logging` section – fields

Example:

```json
{
  "logging": {
    "dir": "log",
    "level": "INFO",
    "interactions_level": "TRACE",
    "when": "midnight",
    "interval": 1,
    "backup_count": 14,
    "also_stdout": false,
    "app_file": "app.log",
    "interactions_file": "ai_interactions.jsonl",
    "ai_interaction": {
      "capture_jsonl": true,
      "human_log": true,
      "human_file": "ai_interaction.log",
      "lang": "en",
      "locale_dir": "locales/ai_interaction",
      "emit_app_log_pointers": true
    }
  }
}
```

#### Field meanings
- `logging.dir`
  Target directory for logs (e.g. `log/`). Created if missing.
- `logging.level`
  Application/root log level. Typical: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- `logging.app_file`
  Application log file name, e.g. `app.log`.

- `logging.interactions_level`
  Level for the `localai.interactions` logger. Typically `TRACE` (most detailed).
- `logging.interactions_file`
  JSONL interaction log file name, e.g. `ai_interactions.jsonl`.

- Rotation:
  - `logging.when` – usually `midnight` (daily rotation).
  - `logging.interval` – how often (e.g. every 1 day).
  - `logging.backup_count` – how many rotated files to keep (e.g. 14).
- `logging.also_stdout`
  If `true`, application logs are also written to stdout (useful for dev/CI).

#### `logging.ai_interaction.*` (interaction logs)
- `capture_jsonl`
  Enables JSONL interaction logging (`ai_interactions.jsonl`).
- `human_log`
  Enables human-readable interaction logging (`ai_interaction.log`).
- `human_file`
  Human-readable log file name.
- `lang` and `locale_dir`
  Localization for labels in human log (e.g. `Timestamp`, `Final answer`).
  If the locale file is missing or broken → fallback to EN and a warning in `app.log`.
- `emit_app_log_pointers`
  If `true`, `app.log` contains short pointers such as:
  - “AI interaction captured (details in …/ai_interactions.jsonl)”
  - “AI interaction human log written (details in …/ai_interaction.log)”

## 2. Regular application logging (`app.log`)

### 2.1. Levels
The system uses standard Python levels:
- `DEBUG` – very detailed (developer-focused).
- `INFO` – normal operational events (startup, config, requests, modes).
- `WARNING` – non-fatal but potentially problematic situations (language fallback, missing locale file).
- `ERROR` – runtime errors.
- (optional) `CRITICAL` – major failures.

### 2.2. Format and rotation
- Application logs are written to:
  `logging.dir / logging.app_file` → e.g. `log/app.log`
- Rotation via `TimedRotatingFileHandler`:
  - `when`, `interval`, `backup_count`
  - UTF-8 encoding
  - UTC time recommended for consistency

### 2.3. What `app.log` is for
- Application startup/bootstrap.
- Index loading / searcher errors.
- Exceptions in endpoints (`/search`, `/query`).
- Fallback warnings (e.g. missing locale).
- Pointers to interaction log files (if enabled).

## 3. AI interaction logging – two streams

Interaction logs are “per turn” (one request/conversation turn = one record).

### 3.1. JSONL: `ai_interactions.jsonl` (structured)

#### What it is
- A **JSON Lines** file: each line is one JSON object.
- It is the **source for analytics, pipeline debugging, evaluation, and replays**.

#### When a record is written
- A record is emitted **when the pipeline finalizes a turn** (e.g. a `persist_turn` step).
- A record is written only if:
  - `logging.ai_interaction.capture_jsonl == true`

#### File location
- `logging.dir / logging.interactions_file`
  e.g. `log/ai_interactions.jsonl`

#### Minimal recommended record contract
Example record:

```json
{
  "timestamp": "2025-12-30T19:39:20Z",
  "session_id": "569a2b21-458a-4b85-924a-2fb66ef2e0e9",
  "pipeline_name": "marian_rejewski_code_analysis_base",
  "step_id": "persist_turn",
  "action": "persist_turn",
  "original_question": "…",
  "model_input_en": "…",
  "codellama_response": "…",
  "followup_query": "…",
  "query_type": "direct answer (heuristic)",
  "final_answer": "…",
  "context_blocks": ["…", "…"],
  "next_codellama_prompt": "rejewski/answer_v1",
  "metadata": {
    "step_trace": ["…optional…"],
    "timings_ms": { "…": 12 }
  }
}
```

#### Practical notes
- `metadata` is flexible for diagnostic data (trace, debug, timings).
- `context_blocks` is a snapshot of evidence/sources used for the answer.
- `timestamp` should be UTC (`Z`).

### 3.2. Human-readable: `ai_interaction.log` (readable)

#### What it is
- A text file meant to be read like a report.
- Fixed structure, sections, separators.
- Convenient for manual review of the conversation flow.

#### When an entry is written
- An entry is written only if:
  - `logging.ai_interaction.human_log == true`

#### File location
- `logging.dir / logging.ai_interaction.human_file`
  e.g. `log/ai_interaction.log`

#### Recommended entry structure
- Separator
- `Timestamp`
- `Prompt`
- `Original question`
- `Translated (EN)`
- `CodeLlama replied`
- `Follow-up query` (optional)
- `Query type`
- `Final answer`
- `Context blocks`
- `Metadata` (optional)
- `JSON` (one-line mini snapshot)

## 4. Logger names and dependencies

Recommended loggers:
- Root logger → `app.log`
- `localai` → application info (pointers, warnings)
- `localai.interactions` → JSONL (typically `TRACE`)
- `localai.ai_interaction.human` → human log

Important: enabling/disabling JSONL and human logs is controlled by `capture_jsonl` / `human_log`, not by the log `level` alone.

## 5. Typical scenarios and troubleshooting

### 5.1. “Nothing is being logged”
Check:
1) Does `logging.dir` exist / does the process have write permission?
2) Is `logging.ai_interaction.human_log == true` (for `ai_interaction.log`)?
3) Is `logging.ai_interaction.capture_jsonl == true` (for `ai_interactions.jsonl`)?
4) Does the pipeline reach the turn-finalization step (if it crashes earlier, the interaction may not be written)?
5) Does `app.log` include pointers (if `emit_app_log_pointers == true`)?

### 5.2. “Interaction log fields are empty”
Most common cause:
- The frontend sends the question under a different field name (`query` vs `question`), and the backend maps it incorrectly → resulting in `original_question == ""`.

Rule: the backend should clearly map request fields to `original_question` and reject empty queries with `400`.

### 5.3. “Label localization in ai_interaction.log does not work”
- Ensure the file exists:
  - `logging.ai_interaction.locale_dir/<lang>.json`
- If missing → fallback to EN and a warning in `app.log`.

## 6. Minimal quality requirements (logging contract)

To keep logging useful and stable:
- Deterministic paths (from `logging.dir`).
- Rotation and retention (`backup_count`) set in `config.json`.
- Stable, versionable JSONL format (1 record = 1 line).
- Human log has a fixed section layout.
- `metadata` is optional, but if present it must be JSON-serializable.

## 7. FAQ

### Is `ai_interactions.jsonl` the same as `ai_interaction.log`?
No.
- `ai_interactions.jsonl` → structured data for tools, analytics, evaluation.
- `ai_interaction.log` → human-readable report.

### Is `app.log` enough?
No. `app.log` is good for general diagnostics, but it does not replace the interaction/pipeline trace.

### Can I disable the human log but keep JSONL?
Yes:
- `capture_jsonl: true`
- `human_log: false`

## 8. Checklist “is logging configured correctly?”
- [ ] `config.json` contains `logging` and `logging.ai_interaction`
- [ ] `logging.dir` is writable
- [ ] `app.log` is created and rotated
- [ ] `ai_interactions.jsonl` is created when `capture_jsonl=true`
- [ ] `ai_interaction.log` is created when `human_log=true`
- [ ] If `emit_app_log_pointers=true`, `app.log` includes pointers to the interaction logs
