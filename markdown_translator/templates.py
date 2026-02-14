from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple


@dataclass(frozen=True)
class TemplateRule:
    id: str
    match: str  # "exact" | "prefix"
    en: str
    pl: str


@dataclass(frozen=True)
class TemplatesConfig:
    templates: List[TemplateRule]
    never_translate_terms: List[str]


def load_templates_config(path: str) -> TemplatesConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("templates.json: expected JSON object")

    raw_templates = data.get("templates") or []
    if not isinstance(raw_templates, list):
        raise ValueError("templates.json: templates must be a list")

    templates: List[TemplateRule] = []
    for i, t in enumerate(raw_templates):
        if not isinstance(t, dict):
            raise ValueError(f"templates.json: templates[{i}] must be an object")
        tid = str(t.get("id") or "").strip() or f"tpl_{i}"
        match = str(t.get("match") or "exact").strip().lower()
        if match not in ("exact", "prefix"):
            raise ValueError(f"templates.json: templates[{i}].match must be exact|prefix")
        en = str(t.get("en") or "")
        pl = str(t.get("pl") or "")
        if not en or not pl:
            raise ValueError(f"templates.json: templates[{i}] requires en and pl")
        templates.append(TemplateRule(id=tid, match=match, en=en, pl=pl))

    nt = data.get("never_translate_terms") or []
    if isinstance(nt, str):
        nt = [s.strip() for s in nt.split(",") if s.strip()]
    if not isinstance(nt, list) or not all(isinstance(x, str) for x in nt):
        raise ValueError("templates.json: never_translate_terms must be a list[str]")

    return TemplatesConfig(templates=templates, never_translate_terms=[x for x in nt if x.strip()])


def default_templates_path() -> str:
    return os.path.join(os.path.dirname(__file__), "templates.json")


def apply_templates_to_line(line: str, cfg: TemplatesConfig) -> Tuple[str, Optional[TemplateRule]]:
    """
    Apply template rules to a single line.
    Returns (possibly modified line, matched_rule or None).

    Rules are applied in order; first match wins (deterministic).
    """
    for rule in cfg.templates:
        if rule.match == "exact":
            if line == rule.en:
                return rule.pl, rule
        else:  # prefix
            if line.startswith(rule.en):
                return rule.pl + line[len(rule.en) :], rule
    return line, None
