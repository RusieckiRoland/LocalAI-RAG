# tests/test_sqlrag_edge.py
import pytest

from tsql_summarizer.parsing import (
    find_select_blocks,
    parse_writes,
    parse_ctes,
    parse_dml_ops,
)

@pytest.mark.unit
def test_nested_select_in_exists_is_not_counted_as_top_level():
    """
    Top-level SELECT should be parsed; inner SELECT in EXISTS must be ignored.
    """
    sql = "SELECT a FROM dbo.T WHERE EXISTS (SELECT 1 FROM dbo.U WHERE U.x = T.x)"
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    # Should capture base table from FROM
    assert blocks[0]["tables"][:1] == [{"table": "dbo.T", "alias": None, "kind": "table"}]
    # Inner SELECT is ignored as separate block
    assert "EXISTS" in blocks[0]["where"].upper()

@pytest.mark.unit
def test_select_with_nolock_hint_keeps_table_detection():
    """
    WITH (NOLOCK) hint must not break table extraction nor previews.
    """
    sql = "SELECT * FROM dbo.Users WITH (NOLOCK) WHERE Id = 1"
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    assert {"table": "dbo.Users", "alias": None, "kind": "table"} in blocks[0]["tables"]
    assert "NOLOCK" not in blocks[0]["preview"].upper()  # hints are stripped in preview

@pytest.mark.unit
def test_delete_simple_from_detected_and_where_preview_present():
    """
    DELETE ... FROM <table> should be classified; do not assert alias-specific behavior.
    """
    sql = "DELETE FROM dbo.Orders WHERE OrderId = 42;"
    writes = parse_writes(sql)
    assert any(w["op"] == "DELETE" for w in writes)
    del_ops = [w for w in writes if w["op"] == "DELETE"]
    assert del_ops[0]["where_preview"] and "OrderId" in del_ops[0]["where_preview"]

@pytest.mark.unit
def test_insert_select_with_union_and_comments_counts_union_parts():
    """
    INSERT ... SELECT ... UNION ALL SELECT ... with comments should count union parts correctly.
    """
    sql = """
    INSERT INTO dbo.Target (x)
    SELECT a FROM dbo.A  /* part 1 */
    UNION ALL
    SELECT b FROM dbo.B  -- part 2
    ;
    """
    writes = parse_writes(sql)
    ins = [w for w in writes if w["op"] == "INSERT"]
    assert len(ins) == 1
    # Two SELECT branches => 2 union parts
    assert ins[0]["union_parts"] == 2

@pytest.mark.unit
def test_merge_statement_is_classified_in_dml_ops():
    """
    MERGE should be visible in high-level DML ops even without deep parsing.
    """
    sql = """
    MERGE dbo.Dst AS d
    USING dbo.Src AS s
      ON d.Id = s.Id
    WHEN MATCHED THEN
      UPDATE SET d.Val = s.Val;
    """
    ops = parse_dml_ops(sql)
    assert "MERGE" in ops

@pytest.mark.unit
def test_select_with_in_subquery_ignores_inner_select_as_top_level():
    """
    SELECT ... WHERE col IN (SELECT ...) should not add a second top-level block.
    """
    sql = "SELECT * FROM dbo.A WHERE Id IN (SELECT Id FROM dbo.B)"
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    # Only base table from outer FROM is expected
    assert blocks[0]["tables"][:1] == [{"table": "dbo.A", "alias": None, "kind": "table"}]
