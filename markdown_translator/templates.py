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


def _parse_terms_file(text: str) -> List[str]:
    """
    Parse a terms file into a list[str].

    Supported formats:
    - one term per line
    - Markdown bullets: "- TERM"
    - ignores empty lines and comment lines starting with "#"
    """
    out: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if line:
            out.append(line)
    return out


def _load_terms_from_files(base_dir: str, files: List[str]) -> List[str]:
    terms: List[str] = []
    for fpath in files:
        p = (fpath or "").strip()
        if not p:
            continue
        if not os.path.isabs(p):
            p = os.path.join(base_dir, p)
        try:
            with open(p, "r", encoding="utf-8") as f:
                terms.extend(_parse_terms_file(f.read()))
        except FileNotFoundError as e:
            raise ValueError(f"templates.json: missing never-translate terms file: {fpath}") from e
    return terms


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for it in items:
        v = (it or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


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

    nt_files = data.get("never_translate_terms_files") or []
    if isinstance(nt_files, str):
        nt_files = [s.strip() for s in nt_files.split(",") if s.strip()]
    if not isinstance(nt_files, list) or not all(isinstance(x, str) for x in nt_files):
        raise ValueError("templates.json: never_translate_terms_files must be a list[str]")

    base_dir = os.path.dirname(path)
    nt_from_files = _load_terms_from_files(base_dir, [x for x in nt_files if x.strip()])

    merged_nt = _dedupe_keep_order([x for x in nt if x.strip()] + nt_from_files)
    return TemplatesConfig(templates=templates, never_translate_terms=merged_nt)


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
