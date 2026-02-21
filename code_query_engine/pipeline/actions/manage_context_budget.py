# code_query_engine/pipeline/actions/manage_context_budget.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from classifiers.code_classifier import CodeKind, classify_text

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase

LOG = logging.getLogger(__name__)


_ALLOWED_POLICIES = {"always", "threshold", "demand"}
_ALLOWED_LANGUAGES = {"sql", "dotnet"}


def _token_count(token_counter: Any, text: str) -> int:
    if token_counter is None:
        raise ValueError("manage_context_budget: runtime.token_counter is required")
    fn = getattr(token_counter, "count_tokens", None)
    if callable(fn):
        return int(fn(text))
    fn = getattr(token_counter, "count", None)
    if callable(fn):
        return int(fn(text))
    raise ValueError("manage_context_budget: token_counter must provide count_tokens(...) or count(...).")


def _normalize_language(kind: CodeKind) -> str:
    if kind == CodeKind.SQL:
        return "sql"
    if kind in (CodeKind.DOTNET, CodeKind.DOTNET_WITH_SQL):
        return "dotnet"
    return "unknown"


def _context_text_from_blocks(blocks: List[str]) -> str:
    return "\n\n".join([str(x) for x in (blocks or []) if str(x or "").strip()]).strip()


def _resolve_divide_new_content(step_raw: Dict[str, Any]) -> str:
    if "divide_new_content" not in (step_raw or {}):
        return ""
    raw = (step_raw or {}).get("divide_new_content")
    if raw is None:
        return ""
    val = str(raw).strip()
    return val


def _strip_divider_prefix(block: str, divider: str) -> str:
    txt = str(block or "")
    if not divider:
        return txt
    if not txt.startswith(divider):
        return txt
    rest = txt[len(divider) :]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    return rest


def _with_divider(block: str, divider: str) -> str:
    txt = str(block or "")
    if not divider:
        return txt
    if txt.startswith(divider):
        return txt
    return f"{divider}\n{txt}"


def _payload_summary(payload: Optional[Dict[str, Any]], *, max_len: int = 240) -> str:
    if payload is None:
        return ""
    try:
        s = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        s = repr(payload)
    return s if len(s) <= max_len else (s[: max_len - 3] + "...")


@dataclass(frozen=True)
class _Rule:
    language: str
    policy: str
    threshold: Optional[float] = None
    inbox_key: str = ""


def _parse_rules(step_raw: Dict[str, Any]) -> List[_Rule]:
    cfg = step_raw.get("compact_code") or {}
    if cfg is None:
        return []
    if not isinstance(cfg, dict):
        raise ValueError("manage_context_budget: compact_code must be a dict if present")
    rules = cfg.get("rules") or []
    if rules is None:
        return []
    if not isinstance(rules, list):
        raise ValueError("manage_context_budget: compact_code.rules must be a list")

    out: List[_Rule] = []
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            raise ValueError(f"manage_context_budget: compact_code.rules[{i}] must be a dict")
        lang = str(r.get("language") or "").strip().lower()
        policy = str(r.get("policy") or "").strip().lower()
        if lang not in _ALLOWED_LANGUAGES:
            raise ValueError(
                f"manage_context_budget: compact_code.rules[{i}].language must be one of {sorted(_ALLOWED_LANGUAGES)}"
            )
        if policy not in _ALLOWED_POLICIES:
            raise ValueError(
                f"manage_context_budget: compact_code.rules[{i}].policy must be one of {sorted(_ALLOWED_POLICIES)}"
            )

        threshold_val: Optional[float] = None
        inbox_key = str(r.get("inbox_key") or "").strip()

        if policy == "threshold":
            if "threshold" not in r:
                raise ValueError(f"manage_context_budget: compact_code.rules[{i}].threshold is required for policy=threshold")
            try:
                threshold_val = float(r.get("threshold"))
            except Exception as ex:
                raise ValueError(
                    f"manage_context_budget: compact_code.rules[{i}].threshold must be a number in (0,1]"
                ) from ex
            if not (0.0 < float(threshold_val) <= 1.0):
                raise ValueError(
                    f"manage_context_budget: compact_code.rules[{i}].threshold must be in (0,1], got {threshold_val!r}"
                )
        if policy == "demand":
            if not inbox_key:
                raise ValueError(f"manage_context_budget: compact_code.rules[{i}].inbox_key is required for policy=demand")

        out.append(_Rule(language=lang, policy=policy, threshold=threshold_val, inbox_key=inbox_key))

    return out


def _first_matching_rule(rules: List[_Rule], language: str) -> Optional[_Rule]:
    lang = str(language or "").strip().lower()
    for r in rules or []:
        if r.language == lang:
            return r
    return None


class ManageContextBudgetAction(PipelineActionBase):
    action_id = "manage_context_budget"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = getattr(step, "raw", {}) or {}
        return {
            "max_context_tokens": (runtime.pipeline_settings or {}).get("max_context_tokens"),
            "incoming_node_texts": len(getattr(state, "node_texts", []) or []),
            "context_blocks": len(getattr(state, "context_blocks", []) or []),
            "divide_new_content": raw.get("divide_new_content"),
            "on_ok": raw.get("on_ok"),
            "on_over": raw.get("on_over"),
        }

    def log_out(
        self,
        step: StepDef,
        state: PipelineState,
        runtime: PipelineRuntime,
        *,
        next_step_id: Optional[str],
        error: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        raw = getattr(step, "raw", {}) or {}
        return {
            "next_step_id": next_step_id,
            "error": error,
            "incoming_node_texts_after": len(getattr(state, "node_texts", []) or []),
            "context_blocks_after": len(getattr(state, "context_blocks", []) or []),
            "divide_new_content": raw.get("divide_new_content"),
            "on_ok": raw.get("on_ok"),
            "on_over": raw.get("on_over"),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = getattr(step, "raw", {}) or {}
        on_ok = str(raw.get("on_ok") or "").strip()
        on_over = str(raw.get("on_over") or "").strip()
        if not on_ok:
            raise ValueError("manage_context_budget: on_ok is required")
        if not on_over:
            raise ValueError("manage_context_budget: on_over is required")

        max_context_tokens = (runtime.pipeline_settings or {}).get("max_context_tokens")
        if max_context_tokens is None:
            raise ValueError("manage_context_budget: settings.max_context_tokens is required")
        try:
            max_context_tokens_i = int(max_context_tokens)
        except Exception as ex:
            raise ValueError("manage_context_budget: settings.max_context_tokens must be int") from ex
        if max_context_tokens_i <= 0:
            raise ValueError("manage_context_budget: settings.max_context_tokens must be > 0")

        divide_new_content = _resolve_divide_new_content(raw)
        rules = _parse_rules(raw)
        incoming = list(getattr(state, "node_texts", []) or [])
        context_blocks = list(getattr(state, "context_blocks", []) or [])
        if divide_new_content:
            # Marker is only for freshly appended blocks; strip it from already existing context.
            context_blocks = [
                _strip_divider_prefix(str(x), divide_new_content)
                for x in context_blocks
                if str(x or "").strip()
            ]
            state.context_blocks = list(context_blocks)
        current_context_text = _context_text_from_blocks(context_blocks)

        demand_topics = self._demand_topics_for_step(state, step_id=step.id)

        # Process nodes in order; build a candidate append list first (transactional semantics).
        to_append: List[str] = []
        debug_nodes: List[Dict[str, Any]] = []

        # Precompute current context tokens once (used in logs and misconfig detection).
        cur_tokens = _token_count(getattr(runtime, "token_counter", None), current_context_text)

        for idx, node in enumerate(incoming):
            if not isinstance(node, dict):
                raise ValueError("manage_context_budget: state.node_texts items must be dicts (contract)")

            node_id = str(node.get("node_id") or node.get("id") or "").strip()
            path = str(
                node.get("path")
                or node.get("repo_relative_path")
                or node.get("source_file")
                or node.get("source")
                or ""
            ).strip()
            text = str(node.get("text") or "")
            metadata_lines = None
            if isinstance(node.get("metadata_context"), list):
                metadata_lines = [str(x) for x in node.get("metadata_context") if str(x or "").strip()]

            kind = classify_text(text).kind
            language = _normalize_language(kind)

            rule = _first_matching_rule(rules, language)

            raw_formatted = self.format_text(
                node_id=node_id,
                path=path,
                language=language,
                compact=False,
                text=text,
                metadata_lines=metadata_lines,
            )

            # Evaluate budget with raw candidate (before compaction).
            raw_with_divider = _with_divider(raw_formatted, divide_new_content)
            candidate_ctx_raw = self._join_context(current_context_text, to_append, raw_with_divider)
            tokens_raw = _token_count(getattr(runtime, "token_counter", None), candidate_ctx_raw)

            compacted = False
            policy = rule.policy if rule else ""
            reason = ""

            candidate_text = raw_formatted

            if rule:
                if rule.policy == "always":
                    compacted = True
                    reason = "policy=always"
                elif rule.policy == "threshold":
                    thr_tokens = int(max_context_tokens_i * float(rule.threshold or 0.0))
                    if tokens_raw > thr_tokens:
                        compacted = True
                        reason = f"policy=threshold tokens_raw>{thr_tokens}"
                    else:
                        reason = f"policy=threshold tokens_raw<={thr_tokens}"
                elif rule.policy == "demand":
                    if rule.inbox_key in demand_topics:
                        compacted = True
                        reason = f"policy=demand inbox_topic={rule.inbox_key}"
                    else:
                        reason = f"policy=demand no_inbox_topic={rule.inbox_key}"
                else:
                    raise ValueError(f"manage_context_budget: invalid policy '{rule.policy}' (internal)")

            if compacted:
                compact_text = self._compact_text(language=language, text=text)
                candidate_text = self.format_text(
                    node_id=node_id,
                    path=path,
                    language=language,
                    compact=True,
                    text=compact_text,
                    metadata_lines=metadata_lines,
                )

            candidate_with_divider = _with_divider(candidate_text, divide_new_content)
            candidate_ctx_final = self._join_context(current_context_text, to_append, candidate_with_divider)
            tokens_final = _token_count(getattr(runtime, "token_counter", None), candidate_ctx_final)

            debug_nodes.append(
                {
                    "idx": idx,
                    "node_id": node_id,
                    "path": path,
                    "language": language,
                    "policy": policy,
                    "compacted": bool(compacted),
                    "reason": reason,
                    "tokens_raw": int(tokens_raw),
                    "tokens_final": int(tokens_final),
                }
            )

            if tokens_final > max_context_tokens_i:
                # Misconfiguration guard: if incoming retrieval context alone cannot fit, this will never succeed.
                incoming_only_text = "\n\n".join(
                    [
                        _with_divider(
                            self.format_text(
                                node_id=str((n or {}).get("node_id") or (n or {}).get("id") or "").strip(),
                                path=str((n or {}).get("path") or (n or {}).get("repo_relative_path") or (n or {}).get("source_file") or "").strip(),
                                language=_normalize_language(classify_text(str((n or {}).get("text") or "")).kind),
                                compact=False,
                                text=str((n or {}).get("text") or ""),
                                metadata_lines=(
                                    [str(x) for x in (n or {}).get("metadata_context") if str(x or "").strip()]
                                    if isinstance((n or {}).get("metadata_context"), list)
                                    else None
                                ),
                            ),
                            divide_new_content,
                        )
                        for n in (incoming or [])
                        if isinstance(n, dict)
                    ]
                )
                incoming_only_tokens = _token_count(getattr(runtime, "token_counter", None), incoming_only_text)
                if incoming_only_tokens > max_context_tokens_i:
                    raise RuntimeError(
                        "PIPELINE_BUDGET_MISCONFIG: fetch_node_texts produced retrieval texts that cannot fit into "
                        f"settings.max_context_tokens (incoming_tokens={incoming_only_tokens} max={max_context_tokens_i})"
                    )

                # Retry demand: if we consumed a demand request and we're going on_over, re-enqueue so it persists.
                self._reenqueue_demand_if_needed(step=step, state=state, used_topics=demand_topics, rules=rules)
                self._emit_trace_budget_event(
                    state=state,
                    step_id=step.id,
                    max_context_tokens=max_context_tokens_i,
                    current_context_tokens=cur_tokens,
                    decision="on_over",
                    nodes=debug_nodes,
                )
                return on_over

            to_append.append(candidate_with_divider)

        # Success: append all prepared blocks and consume incoming retrieval buffer.
        if to_append:
            state.context_blocks = list(getattr(state, "context_blocks", []) or []) + to_append
        state.node_texts = []

        self._emit_trace_budget_event(
            state=state,
            step_id=step.id,
            max_context_tokens=max_context_tokens_i,
            current_context_tokens=cur_tokens,
            decision="on_ok",
            nodes=debug_nodes,
        )
        return on_ok

    # ------------------------------
    # Deterministic formatting
    # ------------------------------

    def format_text(
        self,
        *,
        node_id: str,
        path: str,
        language: str,
        compact: bool,
        text: str,
        metadata_lines: Optional[List[str]] = None,
    ) -> str:
        nid = node_id or ""
        p = path or ""
        lang = language or "unknown"
        c = "true" if compact else "false"
        meta_lines = [str(x) for x in (metadata_lines or []) if str(x or "").strip()]
        return (
            "--- NODE ---\n"
            f"id: {nid}\n"
            f"path: {p}\n"
            f"language: {lang}\n"
            f"compact: {c}\n"
            + ("metadata:\n" + "\n".join(meta_lines) + "\n" if meta_lines else "")
            "text:\n"
            f"{text}\n"
        )

    # ------------------------------
    # Helpers
    # ------------------------------

    def _join_context(self, current_context_text: str, appended: List[str], candidate: str) -> str:
        parts: List[str] = []
        if current_context_text.strip():
            parts.append(current_context_text.strip())
        parts.extend([x.strip() for x in appended if str(x or "").strip()])
        parts.append(candidate.strip())
        return "\n\n".join(parts).strip()

    def _demand_topics_for_step(self, state: PipelineState, *, step_id: str) -> List[str]:
        # base_action consumes inbox on entry and stores for action usage.
        msgs = list(getattr(state, "inbox_last_consumed", []) or [])
        topics: List[str] = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            if str(m.get("target_step_id") or "").strip() != str(step_id or "").strip():
                continue
            t = str(m.get("topic") or "").strip()
            if t:
                topics.append(t)
        return topics

    def _reenqueue_demand_if_needed(self, *, step: StepDef, state: PipelineState, used_topics: List[str], rules: List[_Rule]) -> None:
        # On on_over we want demand requests to persist to the retry run.
        # If the user requested demand compaction for a language, and we consumed that message on entry,
        # we re-enqueue the same topic back to this step so it's available next time.
        if not used_topics:
            return
        rule_keys = {r.inbox_key for r in (rules or []) if r.policy == "demand" and r.inbox_key}
        for topic in used_topics:
            if topic not in rule_keys:
                continue
            try:
                state.enqueue_message(target_step_id=step.id, topic=topic, payload={"retry": True})
            except Exception:
                LOG.exception("soft-failure: failed to re-enqueue demand inbox topic=%r", topic)

    def _compact_text(self, *, language: str, text: str) -> str:
        lang = str(language or "").strip().lower()
        if lang == "sql":
            from tsql_summarizer.api import summarize_tsql, make_compact

            payload = summarize_tsql(text)
            compact = make_compact(payload)
            return json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        if lang == "dotnet":
            from dotnet_summarizer.code_compressor import compress_chunks

            # Represent the incoming node as a single chunk.
            chunk = {"path": "<retrieved>", "content": text, "rank": 0, "distance": 0.0}
            return compress_chunks([chunk], mode="snippets", token_budget=1200, language="dotnet")

        return text

    def _emit_trace_budget_event(
        self,
        *,
        state: PipelineState,
        step_id: str,
        max_context_tokens: int,
        current_context_tokens: int,
        decision: str,
        nodes: List[Dict[str, Any]],
    ) -> None:
        try:
            evt = {
                "event_type": "MANAGE_CONTEXT_BUDGET",
                "step_id": step_id,
                "max_context_tokens": int(max_context_tokens),
                "current_context_tokens": int(current_context_tokens),
                "decision": decision,
                "nodes": nodes,
            }
            # Use state helper (exists in PipelineState) if present; otherwise append directly.
            fn = getattr(state, "_append_pipeline_trace_event", None)
            if callable(fn):
                fn(evt)
            else:
                events = getattr(state, "pipeline_trace_events", None)
                if events is None:
                    events = []
                    setattr(state, "pipeline_trace_events", events)
                events.append(evt)
        except Exception:
            LOG.exception("soft-failure: failed to append MANAGE_CONTEXT_BUDGET trace event")
