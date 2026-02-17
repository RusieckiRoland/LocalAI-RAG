from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, FrozenSet, Optional, Set


GLOBAL_CALLBACK_ALLOWED = "allowed"
GLOBAL_CALLBACK_PIPELINE_DECISION = "pipeline_decision"
GLOBAL_CALLBACK_FORBIDDEN = "forbidden"

PIPELINE_CALLBACK_ALLOWED = "allowed"
PIPELINE_CALLBACK_FORBIDDEN = "forbidden"

CONTENT_ALL = "all"
CONTENT_CAPTIONED = "captioned"
CONTENT_DOCUMENTS_FORBIDDEN = "documents_forbidden"


_GLOBAL_CALLBACK_VALUES = {
    GLOBAL_CALLBACK_ALLOWED,
    GLOBAL_CALLBACK_PIPELINE_DECISION,
    GLOBAL_CALLBACK_FORBIDDEN,
}

_PIPELINE_CALLBACK_VALUES = {
    PIPELINE_CALLBACK_ALLOWED,
    PIPELINE_CALLBACK_FORBIDDEN,
}

_CONTENT_VALUES = {
    CONTENT_ALL,
    CONTENT_CAPTIONED,
    CONTENT_DOCUMENTS_FORBIDDEN,
}

_ALIASES = {
    "allawed": GLOBAL_CALLBACK_ALLOWED,
    "allow": GLOBAL_CALLBACK_ALLOWED,
    "pipeline_decison": GLOBAL_CALLBACK_PIPELINE_DECISION,
    "pipeline_decision": GLOBAL_CALLBACK_PIPELINE_DECISION,
    "forbidden": GLOBAL_CALLBACK_FORBIDDEN,
    "documents_fordbiden": CONTENT_DOCUMENTS_FORBIDDEN,
    "documents_forbiden": CONTENT_DOCUMENTS_FORBIDDEN,
    "documents_forbidden": CONTENT_DOCUMENTS_FORBIDDEN,
    "document_forbidden": CONTENT_DOCUMENTS_FORBIDDEN,
}


@dataclass(frozen=True)
class CallbackPolicy:
    enabled: bool
    require_caption: bool
    include_documents: bool
    global_mode: str
    pipeline_mode: str
    content_modes: FrozenSet[str]


DEFAULT_CALLBACK_POLICY = CallbackPolicy(
    enabled=True,
    require_caption=False,
    include_documents=True,
    global_mode=GLOBAL_CALLBACK_ALLOWED,
    pipeline_mode=PIPELINE_CALLBACK_ALLOWED,
    content_modes=frozenset({CONTENT_ALL}),
)


def resolve_callback_policy(
    *,
    runtime_cfg: Optional[Dict[str, Any]],
    pipeline_settings: Optional[Dict[str, Any]],
) -> CallbackPolicy:
    cfg = runtime_cfg or {}
    pset = pipeline_settings or {}

    global_mode = _normalize_global_mode(cfg.get("callback"))
    pipeline_mode = _normalize_pipeline_mode(pset.get("callback"))

    # Precedence matrix:
    # - global=forbidden          -> always disabled
    # - global=allowed            -> always enabled (pipeline callback cannot override)
    # - global=pipeline_decision  -> enabled only when pipeline callback=allowed
    if global_mode == GLOBAL_CALLBACK_FORBIDDEN:
        enabled = False
    elif global_mode == GLOBAL_CALLBACK_ALLOWED:
        enabled = True
    else:
        enabled = pipeline_mode == PIPELINE_CALLBACK_ALLOWED

    global_content = _normalize_content_set(cfg.get("callback_content"), default={CONTENT_ALL})
    has_pipeline_content = isinstance(pset, dict) and ("callback_content" in pset)
    pipeline_content = _normalize_content_set(
        pset.get("callback_content"),
        default={CONTENT_ALL} if has_pipeline_content else set(),
    )

    require_caption = _require_caption(global_content) or _require_caption(pipeline_content)
    include_documents = _include_documents(global_content) and _include_documents(pipeline_content)

    modes: Set[str] = {CONTENT_CAPTIONED if require_caption else CONTENT_ALL}
    if not include_documents:
        modes.add(CONTENT_DOCUMENTS_FORBIDDEN)

    return CallbackPolicy(
        enabled=enabled,
        require_caption=require_caption,
        include_documents=include_documents,
        global_mode=global_mode,
        pipeline_mode=pipeline_mode,
        content_modes=frozenset(modes),
    )


def callback_policy_from_dict(raw: Optional[Dict[str, Any]]) -> CallbackPolicy:
    if not isinstance(raw, dict):
        return DEFAULT_CALLBACK_POLICY

    enabled = bool(raw.get("enabled", True))
    require_caption = bool(raw.get("require_caption", False))
    include_documents = bool(raw.get("include_documents", True))

    global_mode = _normalize_global_mode(raw.get("global_mode"))
    pipeline_mode = _normalize_pipeline_mode(raw.get("pipeline_mode"))
    modes = _normalize_content_set(raw.get("content_modes"), default={CONTENT_ALL})

    if require_caption:
        modes.discard(CONTENT_ALL)
        modes.add(CONTENT_CAPTIONED)
    if not include_documents:
        modes.add(CONTENT_DOCUMENTS_FORBIDDEN)

    return CallbackPolicy(
        enabled=enabled,
        require_caption=require_caption,
        include_documents=include_documents,
        global_mode=global_mode,
        pipeline_mode=pipeline_mode,
        content_modes=frozenset(modes),
    )


def callback_policy_to_dict(policy: CallbackPolicy) -> Dict[str, Any]:
    return {
        "enabled": bool(policy.enabled),
        "require_caption": bool(policy.require_caption),
        "include_documents": bool(policy.include_documents),
        "global_mode": str(policy.global_mode or GLOBAL_CALLBACK_ALLOWED),
        "pipeline_mode": str(policy.pipeline_mode or PIPELINE_CALLBACK_ALLOWED),
        "content_modes": sorted(set(policy.content_modes or set())),
    }


def _normalize_global_mode(value: Any) -> str:
    token = _normalize_token(value)
    if token in _GLOBAL_CALLBACK_VALUES:
        return token
    return GLOBAL_CALLBACK_ALLOWED


def _normalize_pipeline_mode(value: Any) -> str:
    token = _normalize_token(value)
    if token in _PIPELINE_CALLBACK_VALUES:
        return token
    return PIPELINE_CALLBACK_ALLOWED


def _normalize_content_set(value: Any, *, default: Set[str]) -> Set[str]:
    items = _iter_tokens(value)
    out: Set[str] = set()
    for item in items:
        token = _normalize_token(item)
        if token in _CONTENT_VALUES:
            out.add(token)
    if not out:
        return set(default)
    # "all" is a superset over "captioned" in this policy model.
    if CONTENT_ALL in out and CONTENT_CAPTIONED in out:
        out.discard(CONTENT_CAPTIONED)
    return out


def _require_caption(modes: Set[str]) -> bool:
    if not modes:
        return False
    if CONTENT_ALL in modes:
        return False
    return CONTENT_CAPTIONED in modes


def _include_documents(modes: Set[str]) -> bool:
    if not modes:
        return True
    return CONTENT_DOCUMENTS_FORBIDDEN not in modes


def _iter_tokens(value: Any) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.replace(";", ",").split(",") if x.strip()]
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            token = str(item or "").strip()
            if token:
                out.append(token)
        return out
    return [str(value).strip()]


def _normalize_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    return _ALIASES.get(token, token)
