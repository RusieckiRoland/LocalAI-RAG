# new.py
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple, Dict, Optional


class CodeKind(str, Enum):
    DOTNET = "dotnet"
    SQL = "sql"
    DOTNET_WITH_SQL = "dotnet_with_sql"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassificationResult:
    kind: CodeKind
    confidence: float  # 0..1
    dotnet_score: float
    sql_score: float
    embedded_sql_score: float
    dotnet_migration_hint: bool
    reasons: List[str]
    embedded_sql_samples: List[str]


@dataclass
class _StrLit:
    quote: str              # '"', "'", '"""'
    content: str
    multiline: bool
    prefix: str             # e.g. '$@', '@', '$', ''


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WS_RE = re.compile(r"\s+")


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _strip_comments_collect_strings(text: str) -> Tuple[str, List[_StrLit], Dict[str, int]]:
    """
    Remove line/block comments while preserving strings, and collect string literals.

    Supported (best-effort):
      - C# normal strings: "..." with optional prefixes ($, @, $@, @$)
      - C# raw strings: triple-double-quote raw strings (and $-prefixed variants)
      - SQL strings: '...' with '' escape
    """
    n = len(text)
    i = 0
    out_chars: List[str] = []
    strings: List[_StrLit] = []

    stats = {
        "len": n,
        "lines": text.count("\n") + 1,
        "strings": 0,
        "removed_comment_chars": 0,
    }

    def peek(k: int = 0) -> str:
        j = i + k
        return text[j] if 0 <= j < n else ""

    def startswith_at(s: str) -> bool:
        return text.startswith(s, i)

    # Lexer states
    IN_NONE = 0
    IN_LINE_COMMENT = 1
    IN_BLOCK_COMMENT = 2
    IN_DQ_STRING = 3
    IN_SQ_STRING = 4
    IN_RAW_DQ3_STRING = 5

    state = IN_NONE

    # Current string buffers/flags
    str_buf: List[str] = []
    str_prefix = ""
    str_multiline = False
    dq_verbatim = False  # @"..."

    def _read_csharp_string_prefix() -> Optional[str]:
        # Prefix ends right before the first quote.
        if startswith_at('$@"'):
            return '$@"'
        if startswith_at('@$"'):
            return '@$"'
        if startswith_at('@"'):
            return '@"'
        if startswith_at('$"'):
            return '$"'
        if startswith_at('"'):
            return '"'
        return None

    def _read_csharp_raw_prefix() -> Optional[str]:
        # Raw string literal start: """ or $"""
        if startswith_at('$"""'):
            return '$"""'
        if startswith_at('"""'):
            return '"""'
        return None

    while i < n:
        c = peek(0)

        if state == IN_NONE:
            # Detect C# raw string first
            rawp = _read_csharp_raw_prefix()
            if rawp is not None:
                if rawp == '$"""':
                    str_prefix = '$'
                    i += 1  # consume $
                else:
                    str_prefix = ''
                i += 3  # consume opening """
                state = IN_RAW_DQ3_STRING
                str_buf = []
                str_multiline = True
                continue

            # Detect C# normal string: "..." with optional prefixes
            p = _read_csharp_string_prefix()
            if p is not None:
                if p == '$@"':
                    str_prefix = '$@'
                    dq_verbatim = True
                    i += 3
                elif p == '@$"':
                    str_prefix = '@$'
                    dq_verbatim = True
                    i += 3
                elif p == '@"':
                    str_prefix = '@'
                    dq_verbatim = True
                    i += 2
                elif p == '$"':
                    str_prefix = '$'
                    dq_verbatim = False
                    i += 2
                else:
                    str_prefix = ''
                    dq_verbatim = False
                    i += 1

                state = IN_DQ_STRING
                str_buf = []
                str_multiline = False
                continue

            # Detect SQL single-quoted string
            if c == "'":
                str_prefix = ""
                str_buf = []
                str_multiline = False
                i += 1
                state = IN_SQ_STRING
                continue

            # Detect comments (outside strings)
            if startswith_at("/*"):
                state = IN_BLOCK_COMMENT
                i += 2
                continue
            if startswith_at("//") or startswith_at("--"):
                state = IN_LINE_COMMENT
                i += 2
                continue

            out_chars.append(c)
            i += 1
            continue

        if state == IN_LINE_COMMENT:
            # Consume until newline, keep newline
            if c == "\n":
                out_chars.append("\n")
                i += 1
                state = IN_NONE
            else:
                stats["removed_comment_chars"] += 1
                i += 1
            continue

        if state == IN_BLOCK_COMMENT:
            # Consume until */
            if startswith_at("*/"):
                i += 2
                state = IN_NONE
            else:
                stats["removed_comment_chars"] += 1
                i += 1
            continue

        if state == IN_DQ_STRING:
            c = peek(0)

            if dq_verbatim:
                # Verbatim string: "" escapes
                if c == '"':
                    if peek(1) == '"':
                        str_buf.append('"')
                        i += 2
                        continue
                    # end
                    strings.append(_StrLit('"', "".join(str_buf), True, str_prefix))
                    stats["strings"] += 1
                    out_chars.append("__STR__")
                    i += 1
                    state = IN_NONE
                    dq_verbatim = False
                    continue
                if c == "\n":
                    str_multiline = True
                str_buf.append(c)
                i += 1
                continue

            # Normal C# string: backslash escapes
            if c == "\\":
                if i + 1 < n:
                    str_buf.append(c)
                    str_buf.append(peek(1))
                    i += 2
                else:
                    str_buf.append(c)
                    i += 1
                continue
            if c == '"':
                strings.append(_StrLit('"', "".join(str_buf), str_multiline, str_prefix))
                stats["strings"] += 1
                out_chars.append("__STR__")
                i += 1
                state = IN_NONE
                continue
            if c == "\n":
                str_multiline = True
            str_buf.append(c)
            i += 1
            continue

        if state == IN_SQ_STRING:
            # SQL string: '' escapes
            c = peek(0)
            if c == "'":
                if peek(1) == "'":
                    str_buf.append("'")
                    i += 2
                    continue
                strings.append(_StrLit("'", "".join(str_buf), str_multiline, ""))
                stats["strings"] += 1
                out_chars.append("__STR__")
                i += 1
                state = IN_NONE
                continue
            if c == "\n":
                str_multiline = True
            str_buf.append(c)
            i += 1
            continue

        if state == IN_RAW_DQ3_STRING:
            # Close only on exact """ and NOT on """"
            if startswith_at('"""') and not startswith_at('""""'):
                strings.append(_StrLit('"""', "".join(str_buf), True, str_prefix))
                stats["strings"] += 1
                out_chars.append("__STR__")
                i += 3
                state = IN_NONE
                continue
            if c == "\n":
                str_multiline = True
            str_buf.append(c)
            i += 1
            continue

    clean = "".join(out_chars)
    return clean, strings, stats


def _score_dotnet(clean: str) -> Tuple[float, List[str], bool, bool, bool]:
    """
    Returns:
      - dotnet_score
      - reasons
      - mig_hint: EF migration-like structure detected
      - sql_callsite_hint: SQL execution patterns in .NET detected
      - mig_sql_callsite: migrationBuilder.Sql(...) specifically detected
    """
    reasons: List[str] = []
    score = 0.0

    # Line-anchored C# signals reduce false positives
    using_lines = len(re.findall(r"(?m)^\s*using\s+[A-Za-z0-9_.]+\s*;\s*$", clean))
    namespace_lines = len(re.findall(r"(?m)^\s*namespace\s+[A-Za-z0-9_.]+\s*[{;]", clean))
    if using_lines:
        score += 8.0 + 1.5 * using_lines
        reasons.append(f"found {using_lines} using directive(s)")
    if namespace_lines:
        score += 10.0 + 2.0 * namespace_lines
        reasons.append(f"found {namespace_lines} namespace declaration(s)")

    kw_hits = {
        "class": len(re.findall(r"\bclass\b", clean)),
        "struct": len(re.findall(r"\bstruct\b", clean)),
        "record": len(re.findall(r"\brecord\b", clean)),
        "interface": len(re.findall(r"\binterface\b", clean)),
        "public": len(re.findall(r"\bpublic\b", clean)),
        "private": len(re.findall(r"\bprivate\b", clean)),
        "internal": len(re.findall(r"\binternal\b", clean)),
        "protected": len(re.findall(r"\bprotected\b", clean)),
        "static": len(re.findall(r"\bstatic\b", clean)),
        "async": len(re.findall(r"\basync\b", clean)),
        "await": len(re.findall(r"\bawait\b", clean)),
        "var": len(re.findall(r"\bvar\b", clean)),
        "new": len(re.findall(r"\bnew\b", clean)),
        "get_set": len(re.findall(r"\bget\s*;\s*set\s*;\b", clean)),
    }
    for k, v in kw_hits.items():
        if not v:
            continue
        if k in ("class", "struct", "record", "interface"):
            score += 8.0 + 1.0 * v
        elif k in ("async", "await"):
            score += 3.0 + 0.7 * v
        else:
            score += 1.5 + 0.3 * v

    if any(kw_hits[k] for k in ("class", "struct", "record", "interface")):
        reasons.append("type declaration keyword(s) present (class/struct/record/interface)")

    op_hits = {
        "lambda": clean.count("=>"),
        "attributes": len(re.findall(r"(?m)^\s*\[[A-Za-z_][A-Za-z0-9_\.]*.*?\]\s*$", clean)),
        "generics": len(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\s*<\s*[A-Za-z0-9_,\s\.\?]+\s*>", clean)),
        "linq": len(re.findall(r"\.\s*(Select|Where|ToList|FirstOrDefault|Any|All|Join|GroupBy|OrderBy)\s*\(", clean)),
        "try_catch": len(re.findall(r"\btry\s*{|\bcatch\s*\(|\bfinally\s*{", clean)),
    }
    if op_hits["lambda"]:
        score += 6.0 + 0.4 * op_hits["lambda"]
        reasons.append("'=>': expression-bodied / lambda syntax present")
    if op_hits["attributes"]:
        score += 6.0 + 0.8 * op_hits["attributes"]
        reasons.append("C# attributes [..] detected")
    if op_hits["generics"]:
        score += 4.0 + 0.5 * op_hits["generics"]
    if op_hits["linq"]:
        score += 3.0 + 0.4 * op_hits["linq"]
    if op_hits["try_catch"]:
        score += 2.0 + 0.4 * op_hits["try_catch"]

    # Punctuation balance typical for C#
    semis = clean.count(";")
    braces = clean.count("{") + clean.count("}")
    if semis >= 3 and braces >= 2:
        score += 2.5
    if semis >= 15:
        score += 3.0

    # EF / migrations hint
    mig_hint = False
    mig_patterns = [
        r"\bMigration\b",
        r"\bMigrationBuilder\b",
        r"\bmigrationBuilder\b",
        r"\bprotected\s+override\s+void\s+Up\s*\(",
        r"\bprotected\s+override\s+void\s+Down\s*\(",
        r"\bCreateTable\s*\(",
        r"\bAlterColumn\s*\(",
        r"\bAddColumn\s*\(",
        r"\bDropTable\s*\(",
        r"\bRenameColumn\s*\(",
        r"\bRenameTable\s*\(",
        r"\bSql\s*\(",
        r"\bModelSnapshot\b",
    ]
    mig_hits = sum(1 for p in mig_patterns if re.search(p, clean))
    if mig_hits >= 2:
        mig_hint = True
        score += 6.0 + 1.0 * mig_hits
        reasons.append("EF Core migration patterns detected (Up/Down/migrationBuilder/...)")

    # SQL callsite hints inside .NET code
    sql_callsite_hint = False
    mig_sql_callsite = False

    # migrationBuilder.Sql(...) should be treated specially
    if re.search(r"\bmigrationBuilder\s*\.\s*Sql\s*\(", clean):
        mig_sql_callsite = True
        sql_callsite_hint = True
        score += 4.0
        reasons.append("migrationBuilder.Sql(...) callsite detected")

    # Other common SQL execution sites
    callsite_patterns = [
        r"\bFromSqlRaw\s*\(",
        r"\bFromSqlInterpolated\s*\(",
        r"\bExecuteSqlRaw\s*\(",
        r"\bExecuteSqlRawAsync\s*\(",
        r"\bExecuteSqlInterpolated\s*\(",
        r"\bDbCommand\b",
        r"\bSqlCommand\b",
        r"\bCommandText\b",
        r"\bDapper\b",
        r"\bExecuteAsync\s*\(",
        r"\bQueryAsync\s*\(",
        r"\bExecuteScalarAsync\s*\(",
    ]
    if any(re.search(p, clean) for p in callsite_patterns):
        sql_callsite_hint = True
        score += 3.5
        reasons.append("SQL callsite pattern detected (EF/Dapper/SqlCommand/...)")

    return score, reasons, mig_hint, sql_callsite_hint, mig_sql_callsite


def _score_sql(clean: str) -> Tuple[float, List[str]]:
    reasons: List[str] = []
    score = 0.0
    upper = clean.upper()

    sql_kw = [
        "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
        "GROUP", "BY", "ORDER", "HAVING", "UNION", "INSERT", "INTO", "UPDATE",
        "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "PROCEDURE", "PROC",
        "DECLARE", "SET", "BEGIN", "END", "EXEC", "EXECUTE", "WITH", "TOP",
        "DISTINCT", "CASE", "WHEN", "THEN", "ELSE", "AS", "RETURNS", "TRY", "CATCH", "THROW",
        "TRAN", "COMMIT", "ROLLBACK",
    ]

    distinct_hits = 0
    total_hits = 0
    for kw in sql_kw:
        cnt = len(re.findall(rf"\b{re.escape(kw)}\b", upper))
        if cnt:
            distinct_hits += 1
            total_hits += cnt
    if distinct_hits:
        score += 2.2 * distinct_hits + 0.18 * total_hits

    # Strong DDL / programmable objects
    if re.search(r"\bCREATE\s+TABLE\b", upper):
        score += 12.0
        reasons.append("CREATE TABLE detected")
    if re.search(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b", upper):
        score += 7.0
        reasons.append("CREATE INDEX detected")
    if re.search(r"\bCREATE\s+(OR\s+ALTER\s+)?FUNCTION\b", upper):
        score += 12.0
        reasons.append("CREATE FUNCTION detected")
    if re.search(r"\bCREATE\s+(OR\s+ALTER\s+)?VIEW\b", upper):
        score += 10.0
        reasons.append("CREATE VIEW detected")
    if re.search(r"\bCREATE\s+(OR\s+ALTER\s+)?TRIGGER\b", upper):
        score += 10.0
        reasons.append("CREATE TRIGGER detected")

    # T-SQL flavored patterns
    if re.search(r"\bCREATE\s+(OR\s+ALTER\s+)?PROCEDURE\b|\bCREATE\s+PROC\b", upper):
        score += 12.0
        reasons.append("CREATE PROC/PROCEDURE detected")
    if re.search(r"\bDECLARE\s+@\w+|\bSET\s+@\w+", upper):
        score += 9.0
        reasons.append("T-SQL variable syntax (@var) detected")
    if re.search(r"(?m)^\s*GO\s*$", upper):
        score += 6.0
        reasons.append("batch separator GO detected")
    if re.search(r"\bWITH\s*\(\s*NOLOCK\s*\)", upper):
        score += 4.0

    # Clause structure
    if re.search(r"\bSELECT\b[\s\S]{0,2000}\bFROM\b", upper):
        score += 10.0
        reasons.append("SELECT ... FROM clause structure detected")
    if re.search(r"\bUPDATE\b[\s\S]{0,2000}\bSET\b", upper):
        score += 9.0
        reasons.append("UPDATE ... SET structure detected")
    if re.search(r"\bINSERT\b[\s\S]{0,120}\bINTO\b", upper):
        score += 9.0
        reasons.append("INSERT ... INTO structure detected")
    if re.search(r"\bDELETE\b[\s\S]{0,120}\bFROM\b", upper):
        score += 9.0
        reasons.append("DELETE ... FROM structure detected")

    # Transactional TRY/TRAN pattern boost
    if re.search(r"\bBEGIN\s+TRY\b", upper) and re.search(r"\bBEGIN\s+TRAN\b|\bBEGIN\s+TRANSACTION\b", upper):
        score += 8.0
        reasons.append("TRY/TRAN pattern detected")

    return score, reasons


# --- Embedded SQL detection helpers ---

_SQL_KEYWORDS_AFTER_FROM = re.compile(
    r"^(where|join|inner|left|right|full|group|order|having|union|select|on|cross|outer)\b",
    re.IGNORECASE,
)

def _has_select_from_with_object(low: str) -> bool:
    # Require something object-like after FROM (identifier, bracketed name, #temp, dbo.Users, etc.)
    m = re.search(r"\bselect\b[\s\S]{0,2000}\bfrom\b\s+(.{1,80})", low, re.IGNORECASE)
    if not m:
        return False
    tail = m.group(1).lstrip()
    if not tail:
        return False
    # Reject keyword immediately after FROM (e.g. "SELECT FROM WHERE")
    if _SQL_KEYWORDS_AFTER_FROM.match(tail):
        return False
    # Accept typical object starts
    return bool(re.match(r"^(\[|#|[a-z_])", tail, re.IGNORECASE))


def _has_update_set_with_object(low: str) -> bool:
    m = re.search(r"\bupdate\b\s+(.{1,80})\bset\b", low, re.IGNORECASE | re.DOTALL)
    if not m:
        return False
    head = m.group(1).strip()
    if not head:
        return False
    if _SQL_KEYWORDS_AFTER_FROM.match(head):
        return False
    return bool(re.match(r"^(\[|#|[a-z_])", head, re.IGNORECASE))


def _has_insert_into_with_object(low: str) -> bool:
    m = re.search(r"\binsert\b[\s\S]{0,120}\binto\b\s+(.{1,80})", low, re.IGNORECASE)
    if not m:
        return False
    head = m.group(1).strip()
    if not head:
        return False
    if _SQL_KEYWORDS_AFTER_FROM.match(head):
        return False
    return bool(re.match(r"^(\[|#|[a-z_])", head, re.IGNORECASE))


def _has_delete_from_with_object(low: str) -> bool:
    m = re.search(r"\bdelete\b[\s\S]{0,120}\bfrom\b\s+(.{1,80})", low, re.IGNORECASE)
    if not m:
        return False
    head = m.group(1).strip()
    if not head:
        return False
    if _SQL_KEYWORDS_AFTER_FROM.match(head):
        return False
    return bool(re.match(r"^(\[|#|[a-z_])", head, re.IGNORECASE))


def _has_exec_with_object(low: str) -> bool:
    # Require a proc/function name after EXEC/EXECUTE
    m = re.match(r"^\s*(exec|execute)\s+(.{1,80})", low, re.IGNORECASE)
    if not m:
        return False
    head = m.group(2).strip()
    if not head:
        return False
    if _SQL_KEYWORDS_AFTER_FROM.match(head):
        return False
    return bool(re.match(r"^(\[|[a-z_])", head, re.IGNORECASE))


_SQL_IN_STRING_KWS = {
    "select", "from", "where", "join", "group by", "order by", "having",
    "insert into", "update", "delete from", "merge",
    "create table", "create procedure", "create proc", "alter table", "drop table",
    "create index", "drop index", "create view", "create trigger",
    "declare", "set", "exec", "execute", "with (nolock)", "union all",
}
_SQL_IN_STRING_FUNCS = {"isnull", "coalesce", "datediff", "dateadd", "getdate", "cast", "convert", "sysutcdatetime"}


def _score_embedded_sql(strings: List[_StrLit]) -> Tuple[float, List[str]]:
    """
    Score SQL-likeness inside string literals with guardrails:
      - Short strings are ignored unless they contain a major clause with an object.
      - Weak keyword-only strings are filtered out to avoid log/config false positives.
    """
    score = 0.0
    samples: List[str] = []

    for s in strings:
        content_raw = s.content.strip()
        if not content_raw:
            continue

        content = _WS_RE.sub(" ", content_raw)
        low = content.lower()

        hit_phrases = [p for p in _SQL_IN_STRING_KWS if p in low]
        hit_funcs = [f for f in _SQL_IN_STRING_FUNCS if re.search(rf"\b{re.escape(f)}\b", low)]
        at_params = len(re.findall(r"@\w+", content))

        distinct = len(set(hit_phrases)) + len(set(hit_funcs))

        # Major clause detection (stricter than before)
        has_select_from = _has_select_from_with_object(low)
        has_update_set = _has_update_set_with_object(low)
        has_insert_into = _has_insert_into_with_object(low)
        has_delete_from = _has_delete_from_with_object(low)
        has_exec = _has_exec_with_object(low)

        has_major_clause = has_select_from or has_update_set or has_insert_into or has_delete_from or has_exec

        # Allow short strings only if there is a major clause
        if len(content) < 60 and not has_major_clause:
            continue

        # If no major clause -> require stronger evidence (avoid logs/docs/config strings)
        if not has_major_clause:
            if distinct < 4 and at_params < 2:
                continue

        local = 0.0
        local += 2.1 * distinct
        local += 1.1 * min(at_params, 6)

        if has_select_from:
            local += 9.0
        if has_update_set:
            local += 8.0
        if has_insert_into:
            local += 8.0
        if has_delete_from:
            local += 8.0
        if has_exec:
            local += 7.0

        if s.multiline:
            local += 2.0

        # C# strings (", """) are slightly preferred for embedded SQL
        if s.quote in ('"', '"""'):
            local *= 1.07

        # Final gate
        if local < 7.0:
            continue

        score += local
        if len(samples) < 3 and local >= 10.0:
            snippet = content[:220] + ("..." if len(content) > 220 else "")
            samples.append(snippet)

    return score, samples


def _score_embedded_sql_combined(strings: List[_StrLit]) -> Tuple[float, Optional[str]]:
    """
    Detect SQL that is split across multiple literals (concatenation / StringBuilder.AppendLine).
    We only use this as a boost when a SQL callsite is detected in the host code.

    Returns:
      - boost_score (float)
      - sample snippet (optional)
    """
    # Only combine C#-style strings; SQL single quotes in code often indicate SQL script itself.
    parts: List[str] = []
    total_len = 0
    for s in strings:
        if s.quote not in ('"', '"""'):
            continue
        frag = s.content.strip()
        if not frag:
            continue
        parts.append(frag)
        total_len += len(frag)
        if total_len >= 4000:
            break

    if len(parts) < 2:
        return 0.0, None

    combined = _WS_RE.sub(" ", " ".join(parts))
    low = combined.lower()

    has_major_clause = (
        _has_select_from_with_object(low)
        or _has_update_set_with_object(low)
        or _has_insert_into_with_object(low)
        or _has_delete_from_with_object(low)
        or _has_exec_with_object(low)
    )

    if not has_major_clause:
        return 0.0, None

    # Basic keyword variety
    hit_phrases = [p for p in _SQL_IN_STRING_KWS if p in low]
    hit_funcs = [f for f in _SQL_IN_STRING_FUNCS if re.search(rf"\b{re.escape(f)}\b", low)]
    distinct = len(set(hit_phrases)) + len(set(hit_funcs))
    at_params = len(re.findall(r"@\w+", combined))

    boost = 0.0
    boost += 1.6 * distinct
    boost += 1.0 * min(at_params, 6)
    boost += 10.0  # major-clause strong evidence

    # Cap boost so it doesn't dominate everything
    boost = min(boost, 22.0)

    sample = combined[:220] + ("..." if len(combined) > 220 else "")
    return boost, sample


def _is_config_like(text: str) -> bool:
    """
    Detect INI/CFG-like text that often contains words like 'namespace' or 'class'
    but is not source code.
    """
    ini_sections = bool(re.search(r"(?m)^\s*\[[^\]]+\]\s*$", text))
    kv_lines = len(re.findall(r"(?m)^\s*[A-Za-z0-9_.-]+\s*=\s*.+$", text))
    if ini_sections and kv_lines >= 1:
        return True
    if kv_lines >= 3 and len(text) < 800:
        return True
    return False


def classify_text(text: str) -> ClassificationResult:
    clean, strings, stats = _strip_comments_collect_strings(text)
    token_count = len(_WORD_RE.findall(clean))

    dotnet_score, dotnet_reasons, mig_hint, sql_callsite_hint, mig_sql_callsite = _score_dotnet(clean)
    sql_score, sql_reasons = _score_sql(clean)
    embedded_score, embedded_samples = _score_embedded_sql(strings)

    reasons: List[str] = []

    # Anti-config guard: prevent INI/CFG from becoming "dotnet" on weak signals.
    # Only applies when both language scores are weak.
    if _is_config_like(text) and dotnet_score < 16.0 and sql_score < 16.0:
        kind = CodeKind.UNKNOWN
        reasons = ["config-like text detected (INI/CFG style), avoiding code classification"]
        confidence = 0.65
        return ClassificationResult(
            kind=kind,
            confidence=float(confidence),
            dotnet_score=float(dotnet_score),
            sql_score=float(sql_score),
            embedded_sql_score=float(embedded_score),
            dotnet_migration_hint=bool(mig_hint),
            reasons=reasons[:6],
            embedded_sql_samples=embedded_samples,
        )

    # Hard rule: EF migration + migrationBuilder.Sql(...) => DOTNET_WITH_SQL
    # This is intentionally strong to handle truncated/short SQL strings.
    if mig_hint and mig_sql_callsite:
        kind = CodeKind.DOTNET_WITH_SQL
        reasons.extend(dotnet_reasons[:3] or ["EF migration detected"])
        reasons.append("migrationBuilder.Sql(...) implies embedded SQL (forced classification)")
        confidence = 0.92
        return ClassificationResult(
            kind=kind,
            confidence=float(confidence),
            dotnet_score=float(dotnet_score),
            sql_score=float(sql_score),
            embedded_sql_score=float(embedded_score),
            dotnet_migration_hint=bool(mig_hint),
            reasons=reasons[:6],
            embedded_sql_samples=embedded_samples,
        )

    # If we see a SQL callsite in .NET, try a combined-string boost (concat/StringBuilder cases)
    combined_boost = 0.0
    combined_sample: Optional[str] = None
    if sql_callsite_hint:
        combined_boost, combined_sample = _score_embedded_sql_combined(strings)
        if combined_boost > 0.0:
            embedded_score += combined_boost
            if combined_sample and len(embedded_samples) < 3:
                embedded_samples.append(combined_sample)

    # Thresholds depend on snippet size (helps short snippets)
    if token_count < 60:
        dotnet_strong_th = 14.0
        sql_strong_th = 14.0
        embedded_strong_th = 12.0
    else:
        dotnet_strong_th = 18.0
        sql_strong_th = 18.0
        embedded_strong_th = 14.0

    dotnet_strong = dotnet_score >= dotnet_strong_th
    sql_strong = sql_score >= sql_strong_th
    embedded_strong = embedded_score >= embedded_strong_th

    # DOTNET_WITH_SQL: strong dotnet + (strong embedded OR callsite hint + moderate embedded)
    if dotnet_strong and (embedded_strong or (sql_callsite_hint and embedded_score >= 8.5)):
        kind = CodeKind.DOTNET_WITH_SQL
        reasons.extend(dotnet_reasons[:3])
        reasons.append(f"embedded SQL in strings detected (score={embedded_score:.1f})")
        if sql_callsite_hint:
            reasons.append("SQL callsite hint present (EF/Dapper/migration/SqlCommand)")
        if mig_hint:
            reasons.append("migration hint: EF Core migration-like structure")
    else:
        # Pure SQL if SQL dominates and dotnet is not strong
        if sql_strong and not dotnet_strong:
            kind = CodeKind.SQL
            reasons.extend(sql_reasons[:4])

        # Pure DOTNET if dotnet dominates and sql not strong and embedded weak
        elif dotnet_strong and (sql_score < (sql_strong_th - 2.0)) and embedded_score < 8.0:
            kind = CodeKind.DOTNET
            reasons.extend(dotnet_reasons[:4])
            if mig_hint:
                reasons.append("migration hint: EF Core migration-like structure")
        else:
            # Borderline resolution
            if dotnet_score >= (dotnet_strong_th - 2.0) and embedded_score >= 9.0:
                kind = CodeKind.DOTNET_WITH_SQL
                reasons.extend(dotnet_reasons[:3] or ["dotnet-like syntax detected"])
                reasons.append(f"leaning to dotnet_with_sql due to embedded signals (score={embedded_score:.1f})")
                if sql_callsite_hint:
                    reasons.append("SQL callsite hint present (EF/Dapper/migration/SqlCommand)")
                if mig_hint:
                    reasons.append("migration hint: EF Core migration-like structure")
            elif sql_score >= (sql_strong_th - 2.0) and dotnet_score < (dotnet_strong_th - 2.0):
                kind = CodeKind.SQL
                reasons.extend(sql_reasons[:4])
            elif dotnet_score >= (dotnet_strong_th - 2.0) and sql_score < (sql_strong_th - 2.0):
                kind = CodeKind.DOTNET
                reasons.extend(dotnet_reasons[:4])
            else:
                kind = CodeKind.UNKNOWN
                if dotnet_reasons:
                    reasons.append("some .NET/C# signals present: " + "; ".join(dotnet_reasons[:2]))
                if sql_reasons:
                    reasons.append("some SQL signals present: " + "; ".join(sql_reasons[:2]))
                if embedded_score >= 8.0:
                    reasons.append(f"possible embedded SQL in strings (score={embedded_score:.1f})")

    # Confidence estimation
    sep = abs(dotnet_score - sql_score)
    strength = max(dotnet_score, sql_score, embedded_score if kind == CodeKind.DOTNET_WITH_SQL else 0.0)

    base = _sigmoid((sep - 6.0) / 6.0) * _sigmoid((strength - 10.0) / 8.0)

    # Short snippets => lower confidence
    short_penalty = 1.0
    if token_count < 30 or stats["len"] < 200:
        short_penalty = 0.75
    if token_count < 15 or stats["len"] < 120:
        short_penalty = 0.6

    if kind == CodeKind.DOTNET_WITH_SQL:
        base = max(base, _sigmoid((embedded_score - 10.0) / 6.0))

    confidence = max(0.05, min(0.99, base * short_penalty))

    if not reasons:
        reasons = ["no strong language-specific signals found"]

    return ClassificationResult(
        kind=kind,
        confidence=float(confidence),
        dotnet_score=float(dotnet_score),
        sql_score=float(sql_score),
        embedded_sql_score=float(embedded_score),
        dotnet_migration_hint=bool(mig_hint),
        reasons=reasons[:6],
        embedded_sql_samples=embedded_samples,
    )


def classify_text_compact(text: str) -> Tuple[str, float]:
    r = classify_text(text)
    return r.kind.value, r.confidence


if __name__ == "__main__":
    import sys

    data = sys.stdin.read()
    r = classify_text(data)
    print(f"kind={r.kind.value} confidence={r.confidence:.3f}")
    print(f"dotnet_score={r.dotnet_score:.1f} sql_score={r.sql_score:.1f} embedded_sql_score={r.embedded_sql_score:.1f}")
    print(f"dotnet_migration_hint={r.dotnet_migration_hint}")
    print("reasons:")
    for x in r.reasons:
        print(f"- {x}")
    if r.embedded_sql_samples:
        print("embedded_sql_samples:")
        for s in r.embedded_sql_samples:
            print(f"- {s}")
