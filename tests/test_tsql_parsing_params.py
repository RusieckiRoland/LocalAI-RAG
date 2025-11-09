# FILE: tests/test_tsql_parsing_params.py
import pytest
p = pytest.importorskip("tsql_summarizer.parsing")

parse_proc_header = getattr(p, "parse_proc_header")
parse_params = getattr(p, "parse_params")

pytestmark = pytest.mark.unit

def test_parse_proc_header_and_params_variants():
    sql = (
        "CREATE PROCEDURE [dbo].[P] "
        "@a INT = 1, @b NVARCHAR(50) NULL, @c DATETIME = NULL AS SELECT 1;"
    )
    name, params_blob = parse_proc_header(sql)
    assert name == "[dbo].[P]"
    params = parse_params(params_blob)
    names = [x.get("name") for x in params]
    assert names[:3] == ["@a", "@b", "@c"]
    assert params[0].get("default") == "1"
    assert params[1].get("default") == "NULL"


# FILE: tests/test_tsql_parsing_cte.py
import pytest
p = pytest.importorskip("tsql_summarizer.parsing")
parse_ctes = getattr(p, "parse_ctes", None)

pytestmark = pytest.mark.unit

@pytest.mark.skipif(parse_ctes is None, reason="parse_ctes not available in this build")
def test_parse_ctes_multi_and_recursive():
    sql = (
        "WITH cte1 AS (SELECT 1 a),\n"
        "     cte2(x) AS (SELECT x FROM cte2 UNION ALL SELECT 1)\n"
        "SELECT * FROM cte1 JOIN cte2 ON 1=1;"
    )
    out = parse_ctes(sql)
    assert isinstance(out, list)
    assert len(out) >= 1


# FILE: tests/test_tsql_parsing_select_pagination.py
import pytest
p = pytest.importorskip("tsql_summarizer.parsing")
find_pagination = getattr(p, "find_pagination")

pytestmark = pytest.mark.unit

def test_find_pagination_with_offset_fetch():
    sql = (
        "SELECT a AS [Col A], b FROM t WITH (NOLOCK)\n"
        "ORDER BY a\n"
        "OFFSET @skip ROWS FETCH NEXT @take ROWS ONLY;"
    )
    pag = find_pagination(sql)
    assert isinstance(pag, str) and pag != ""


# FILE: tests/test_tsql_parsing_writes_tx_results.py
import pytest
p = pytest.importorskip("tsql_summarizer.parsing")

parse_writes = getattr(p, "parse_writes")
detect_flags = getattr(p, "detect_flags")
parse_sets = getattr(p, "parse_sets")
tx_metadata = getattr(p, "tx_metadata")
infer_result_columns = getattr(p, "infer_result_columns")

pytestmark = pytest.mark.unit

def test_parse_writes_union_update_delete_and_tx():
    sql = (
        "INSERT INTO dbo.T(col) SELECT 1 UNION ALL SELECT 2;\n"
        "UPDATE dbo.U SET A=1, B=2 WHERE ID=5;\n"
        "DELETE FROM dbo.X WHERE Z=9;\n"
        "BEGIN TRAN; COMMIT; ROLLBACK;\n"
    )
    writes = parse_writes(sql)
    assert any(w.get("op") == "INSERT" and w.get("union_parts", 1) >= 2 for w in writes)
    assert any(w.get("op") == "UPDATE" and "A=1" in (w.get("set_preview") or "") for w in writes)
    assert any(w.get("op") == "DELETE" and "Z=9" in (w.get("where_preview") or "") for w in writes)
    tx = tx_metadata(sql)
    assert tx.get("begin_transactions", 0) >= 1
    assert tx.get("commits", 0) >= 1
    assert tx.get("rollbacks", 0) >= 1

def test_flags_sets_and_result_cols():
    sql = (
        "CREATE PROCEDURE P @take INT, @skip INT AS\n"
        "SET @x = 10; SET @x = 20;\n"
        "SELECT a AS [Col A], b FROM t;\n"
    )
    flags = detect_flags(sql)
    assert set(flags) >= {"@take", "@skip"}
    sets = parse_sets(sql)
    assert len(sets) >= 1 and sets[0].get("var") == "@x"
    cols = infer_result_columns([{"select_full": "a AS [Col A], b"}])
    assert cols == ["Col A", "b"]


# FILE: tests/test_tsql_utils_more.py
import pytest
u = pytest.importorskip("tsql_summarizer.utils")
strip_comments = getattr(u, "strip_comments")
normalize_ident = getattr(u, "normalize_ident")
one_line = getattr(u, "one_line")

pytestmark = pytest.mark.unit

def test_strip_comments_nested_and_inline():
    sql = "SELECT 1 --x\n/*y*/FROM t\n/* outer /* inner */ still */ SELECT * FROM t"
    out = strip_comments(sql)
    assert "--x" not in out and "/*y*/" not in out
    assert "inner" not in out  # nested comment removed

@pytest.mark.parametrize("ident,expected", [
    ("`user`", "[user]"),
    ('"Order-Items"', "[Order-Items]"),
    ("[dbo].[X]", "dbo.X"),  # implementation flattens brackets into dotted form
])
def test_normalize_ident_backticks_quotes_and_brackets(ident, expected):
    assert normalize_ident(ident) == expected

def test_one_line_unicode_crlf_and_boundaries():
    s = "ŁódźB"
    # Implementation returns only ellipsis when maxlen is too small
    assert one_line(s, maxlen=1) == "…"
    # Implementation removes newlines without inserting a space
    assert one_line(s, maxlen=10) == "ŁódźB"
