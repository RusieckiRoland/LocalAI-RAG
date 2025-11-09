# tests/test_sqlrag_dml_extra.py
import pytest
from tsql_summarizer.parsing import parse_writes

@pytest.mark.unit
def test_insert_select_union_parts_counted():
    sql = """
    INSERT INTO dbo.Target(col)
    SELECT a FROM A
    UNION ALL SELECT b FROM B
    UNION ALL SELECT c FROM C;
    """
    w = parse_writes(sql)
    ins = [x for x in w if x["op"] == "INSERT"][0]
    assert ins["union_parts"] == 3
