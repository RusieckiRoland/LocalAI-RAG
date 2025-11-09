# tests/test_tsql_parsing_offsets_aliases.py
import pytest
from tsql_summarizer.parsing import find_select_blocks

pytestmark = pytest.mark.unit

def test_order_by_with_offset_and_aliases_no_as():
    sql = """
    WITH c AS (SELECT 1 AS a)
    SELECT t.Id, u.Name
    FROM dbo.Table1 t JOIN dbo.Users u ON u.Id = t.UserId
    ORDER BY t.Id OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY;
    """
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    # sprawdzamy, że aliasy zostały zebrane i paginacja wykryta w preview
    names = {x.get("alias") or x.get("table") for x in blocks[0]["tables"]}
    assert {"t", "u"} & names
    assert "OFFSET" in blocks[0]["preview"].upper()
