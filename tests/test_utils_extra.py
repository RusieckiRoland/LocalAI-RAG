# tests/test_utils_extra.py
import pytest
from tsql_summarizer.utils import one_line, normalize_ident

@pytest.mark.unit
def test_one_line_handles_unicode_and_crlf():
    text = "Zażółć\r\ngęślą\r\njaźń"
    assert one_line(text, maxlen=50) == "Zażółć gęślą jaźń"

@pytest.mark.unit
def test_normalize_ident_various_quotes():
    assert normalize_ident('"User Table"') == "[User Table]"
    assert normalize_ident("`user`") == "[user]"
    assert normalize_ident("[dbo].[Users]") == "dbo.Users"
