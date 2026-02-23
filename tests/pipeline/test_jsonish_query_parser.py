from __future__ import annotations

from code_query_engine.pipeline.query_parsers.jsonish_query_parser import JsonishQueryParser


def test_jsonish_parser_extracts_meta_and_repairs_payload() -> None:
    payload = """```json
{query:\"find Foo\",filters:{data_type:\"regular_code\",},search_type:\"bm25\",match_operator:\"and\",top_k:5,rrf_k:17,}
```"""

    result = JsonishQueryParser().parse(payload)

    assert result.query == "find Foo"
    assert result.filters.get("data_type") == "regular_code"
    assert result.filters.get("__search_type") == "bm25"
    assert result.filters.get("__match_operator") == "and"
    assert result.filters.get("__top_k") == 5
    assert result.filters.get("__rrf_k") == 17


def test_jsonish_parser_extracts_search_type_from_query() -> None:
    payload = "{\"query\":\"find Foo search_type:bm25\",\"filters\":{}}"

    result = JsonishQueryParser().parse(payload)

    assert result.query == "find Foo"
    assert result.filters.get("__search_type") == "bm25"
    assert any("extracted search_type/mode" in w for w in result.warnings)


def test_jsonish_parser_invalid_match_operator_is_ignored() -> None:
    payload = "{\"query\":\"find Foo\",\"match_operator\":\"xor\"}"

    result = JsonishQueryParser().parse(payload)

    assert result.filters.get("__match_operator") is None
    assert any("unknown match_operator" in w for w in result.warnings)


def test_jsonish_parser_non_object_payload_returns_query() -> None:
    payload = "just a query"

    result = JsonishQueryParser().parse(payload)

    assert result.query == "just a query"
    assert result.filters == {}
    assert any("could not parse payload as object" in w for w in result.warnings)
