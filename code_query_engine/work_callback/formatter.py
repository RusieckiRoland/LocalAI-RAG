from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .policy import (
    CallbackPolicy,
    DEFAULT_CALLBACK_POLICY,
    STAGES_VISIBILITY_ALLOWED,
    STAGES_VISIBILITY_EXPLICIT,
    STAGES_VISIBILITY_FORBIDDEN,
)


_DOC_PREVIEW_CHARS = 280
_DOC_MARKDOWN_CHARS = 12000


def summarize_trace_event_for_ui(
    event: Dict[str, Any],
    *,
    policy: Optional[CallbackPolicy],
) -> Optional[Dict[str, Any]]:
    if not isinstance(event, dict):
        return None

    effective_policy = policy or DEFAULT_CALLBACK_POLICY
    if not effective_policy.enabled:
        return None
    if not _is_stage_visible(event, effective_policy):
        return None

    callback_meta = event.get("callback") if isinstance(event.get("callback"), dict) else {}
    caption = _clean_str(callback_meta.get("caption"))
    caption_translated = _clean_str(callback_meta.get("caption_translated"))

    run_id = event.get("run_id")
    ts = event.get("ts_utc")

    event_type = _clean_str(event.get("event_type")).upper()
    if event_type in {"ENQUEUE", "CONSUME"}:
        return _summarize_queue_event(
            event=event,
            event_type=event_type,
            run_id=run_id,
            ts=ts,
            caption=caption,
            caption_translated=caption_translated,
        )

    step = event.get("step") if isinstance(event.get("step"), dict) else {}
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    in_data = event.get("in") if isinstance(event.get("in"), dict) else {}
    out_data = event.get("out") if isinstance(event.get("out"), dict) else {}

    step_id = step.get("id")
    action_id = action.get("action_id") or step.get("action")
    if not (step_id or action_id):
        return None

    summary, summary_pl, details, docs = _summarize_step_event(action_id, in_data, out_data)
    if caption:
        summary = caption
    if caption_translated:
        summary_pl = caption_translated

    payload: Dict[str, Any] = {
        "type": "step",
        "ts": ts,
        "run_id": run_id,
        "step_id": step_id,
        "action_id": action_id,
        "summary": summary,
        "summary_translated": summary_pl,
        "details": details,
    }
    if caption:
        payload["caption"] = caption
    if caption_translated:
        payload["caption_translated"] = caption_translated

    if docs and effective_policy.include_documents:
        payload["docs"] = docs
    return payload


def _summarize_queue_event(
    *,
    event: Dict[str, Any],
    event_type: str,
    run_id: Any,
    ts: Any,
    caption: str,
    caption_translated: str,
) -> Dict[str, Any]:
    if event_type == "ENQUEUE":
        summary = caption or "Inbox"
        summary_pl = caption_translated or "Skrzynka"
        details = {
            "topic": event.get("topic"),
            "target_step_id": event.get("target_step_id"),
            "sender_step_id": event.get("sender_step_id"),
        }
    else:
        summary = caption or "Consume"
        summary_pl = caption_translated or "Konsumpcja"
        details = {
            "consumer_step_id": event.get("consumer_step_id"),
            "count": event.get("count"),
        }

    out: Dict[str, Any] = {
        "type": event_type.lower(),
        "ts": ts,
        "run_id": run_id,
        "summary": summary,
        "summary_translated": summary_pl,
        "details": _compact(details),
    }
    if caption:
        out["caption"] = caption
    if caption_translated:
        out["caption_translated"] = caption_translated
    return out


def _summarize_step_event(
    action_id: Optional[str],
    in_data: Dict[str, Any],
    out_data: Dict[str, Any],
) -> Tuple[str, str, Dict[str, Any], List[Dict[str, Any]]]:
    action = _clean_str(action_id)

    if action == "search_nodes":
        summary = "Retrieval"
        summary_pl = "Pobieranie"
        details = {
            "search_type": in_data.get("search_type"),
            "top_k": in_data.get("top_k"),
            "query": _truncate(_clean_str(in_data.get("query_effective")), 180),
            "hits": out_data.get("retrieval_hits_count"),
        }
        return summary, summary_pl, _compact(details), []

    if action == "fetch_node_texts":
        summary = "Context materialization"
        summary_pl = "Budowanie kontekstu"
        details = {"node_texts_count": out_data.get("node_texts_count")}
        docs = _extract_docs(out_data.get("node_texts"))
        return summary, summary_pl, _compact(details), docs

    if action == "manage_context_budget":
        summary = "Context budget"
        summary_pl = "Budzet kontekstu"
        details = {
            "context_blocks": out_data.get("context_blocks_count"),
            "context_tokens": out_data.get("context_tokens"),
        }
        return summary, summary_pl, _compact(details), []

    if action == "call_model":
        summary = "Model call"
        summary_pl = "Wywolanie modelu"
        details = {
            "prompt": in_data.get("prompt_name"),
            "max_output_tokens": in_data.get("max_output_tokens"),
        }
        return summary, summary_pl, _compact(details), []

    summary = action or "step"
    return summary, summary, {}, []


def _is_stage_visible(event: Dict[str, Any], policy: CallbackPolicy) -> bool:
    mode = str(policy.stage_visibility_mode or STAGES_VISIBILITY_ALLOWED)
    if mode == STAGES_VISIBILITY_FORBIDDEN:
        return False
    if mode == STAGES_VISIBILITY_ALLOWED:
        return True
    if mode != STAGES_VISIBILITY_EXPLICIT:
        return True

    flag = None
    step = event.get("step") if isinstance(event.get("step"), dict) else {}
    if "stages_visible" in step:
        flag = step.get("stages_visible")
    elif "stages_visible" in event:
        flag = event.get("stages_visible")
    return bool(flag is True)


def _extract_docs(node_texts: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(node_texts, list):
        return out

    for item in node_texts:
        if not isinstance(item, dict):
            continue
        doc_id = _clean_str(item.get("id") or item.get("node_id") or item.get("key")) or "doc"
        text = _clean_str(
            item.get("text")
            or item.get("chunk")
            or item.get("content")
            or item.get("md")
            or item.get("markdown")
        )
        if not text:
            continue
        out.append(
            {
                "id": doc_id,
                "depth": item.get("depth"),
                "text_len": len(text),
                "preview": _truncate(text, _DOC_PREVIEW_CHARS),
                "markdown": _truncate(text, _DOC_MARKDOWN_CHARS),
            }
        )
    return out


def _compact(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (data or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        out[k] = v
    return out


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."
