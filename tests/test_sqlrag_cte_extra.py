# tests/test_sqlrag_cte_extra.py
import pytest
from tsql_summarizer.parsing import find_select_blocks

@pytest.mark.unit
def test_recursive_cte_is_classified_as_cte():
    sql = """
    WITH cte AS (
      SELECT 1 AS id
      UNION ALL
      SELECT id+1 FROM cte WHERE id < 10
    )
    SELECT * FROM cte
    """
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    assert blocks[0]["tables"] == [{"table": "cte", "alias": None, "kind": "cte"}]
