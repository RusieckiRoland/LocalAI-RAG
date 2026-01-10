# code_query_engine/pipeline/query_parsers/base_query_parser.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class QueryParseResult:
    query: str
    filters: Dict[str, Any]
    warnings: List[str]


class BaseQueryParser:
    """
    Base class for parsing the text AFTER a routing prefix was stripped.

    Example payload:
        {"query":"ProductService class definition","filters":{"type":"CS"}}

    The parser must be resilient to typical LLM formatting mistakes.
    It must NOT throw for common issues; instead return warnings and a best-effort result.
    """

    @property
    def parser_id(self) -> str:
        raise NotImplementedError

    def parse(self, payload: str) -> QueryParseResult:
        raise NotImplementedError
