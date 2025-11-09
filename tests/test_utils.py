import pytest
from tsql_summarizer.utils import strip_comments, normalize_ident, one_line


@pytest.mark.unit
def test_strip_comments_removes_line_and_inline_comments():
    """Removes -- and /* */ comments, preserves SQL."""
    sql = """
    -- Full line comment
    SELECT id, name FROM users /* temp column */ WHERE active = 1
    """
    result = strip_comments(sql)
    assert result == "SELECT id, name FROM users WHERE active = 1"


@pytest.mark.unit
def test_normalize_ident_removes_brackets_and_whitespace():
    """Cleans identifiers from brackets and extra spaces."""
    assert normalize_ident("[dbo].[My Table]") == "dbo.My Table"
    assert normalize_ident("  temp_table  ") == "temp_table"
    assert normalize_ident("") == ""


@pytest.mark.unit
def test_one_line_truncates_with_ellipsis():
    """Collapses multiline text and cuts at maxlen with …"""
    text = "First line\nSecond line\nThird line"
    assert one_line(text, maxlen=12) == "First line …"
    assert one_line(text, maxlen=30) == "First line Second line Third …"
    assert one_line("", maxlen=10) == ""