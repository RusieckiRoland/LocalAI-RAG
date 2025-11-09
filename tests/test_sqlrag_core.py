import pytest
from tsql_summarizer.parsing import find_select_blocks


@pytest.mark.unit
def test_simple_select_with_where():
    """Parses basic SELECT with WHERE clause."""
    sql = "SELECT col1, col2 FROM table1 WHERE id = 1"
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    b = blocks[0]
    assert b["preview"] == sql
    assert b["tables"] == [{"table": "table1", "alias": None, "kind": "table"}]
    assert b["where"] == "id = 1"


@pytest.mark.unit
def test_join_with_table_aliases():
    """Handles JOIN with table aliases."""
    sql = """
    SELECT t1.a, t2.b
    FROM users t1
    JOIN orders t2 ON t1.id = t2.user_id
    """
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    b = blocks[0]
    assert b["tables"] == [
        {"table": "users", "alias": "t1", "kind": "table"},
        {"table": "orders", "alias": "t2", "kind": "table"}
    ]


@pytest.mark.unit
def test_select_in_cte_is_ignored():
    """Ignores SELECT inside CTE, captures only top-level."""
    sql = """
    WITH cte AS (SELECT id FROM source)
    SELECT * FROM cte
    """
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    assert blocks[0]["tables"] == [{"table": "cte", "alias": None, "kind": "cte"}]


@pytest.mark.unit
def test_comments_are_removed_from_output():
    """Strips -- and /* */ comments from preview."""
    sql = """
    -- Get active users
    SELECT name FROM users /* active only */ WHERE active = 1
    """
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    preview = blocks[0]["preview"]
    assert "comment" not in preview.lower()
    assert "SELECT name FROM users WHERE active = 1" in preview


@pytest.mark.unit
def test_detects_aggregates_and_window_functions():
    """Sets flags for SUM, COUNT, OVER()."""
    sql = """
    SELECT dept, COUNT(*) AS cnt, AVG(salary) OVER (PARTITION BY dept) AS avg_sal
    FROM emp
    GROUP BY dept
    """
    blocks = find_select_blocks(sql)
    b = blocks[0]
    assert b["has_aggregates"] is True
    assert b["has_windows"] is True
    assert b["group_by"] == "dept"


@pytest.mark.unit
def test_multiple_top_level_selects():
    """Returns one block per top-level SELECT."""
    sql = "SELECT 1 FROM a; SELECT name FROM b WHERE x > 0;"
    blocks = find_select_blocks(sql)
    assert len(blocks) == 2
    assert blocks[0]["tables"] == [{"table": "a", "alias": None, "kind": "table"}]
    assert blocks[1]["tables"] == [{"table": "b", "alias": None, "kind": "table"}]


@pytest.mark.unit
def test_recognizes_table_variables():
    """Classifies @var and #temp correctly."""
    sql = "SELECT col INTO #temp; SELECT * FROM @var;"
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1
    assert blocks[0]["tables"] == [{"table": "@var", "alias": None, "kind": "var"}]


@pytest.mark.unit
def test_empty_or_whitespace_input():
    """Returns empty list on blank input."""
    assert find_select_blocks("") == []
    assert find_select_blocks("   \n   ") == []


@pytest.mark.unit
def test_malformed_sql_does_not_crash():
    """Recovers from syntax errors."""
    sql = "SELECT a FROM t WHERE; SELECT b FROM u;"
    blocks = find_select_blocks(sql)
    assert len(blocks) == 1