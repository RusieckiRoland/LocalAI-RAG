import re
from pathlib import Path


def _read_rag_html() -> str:
    path = Path("frontend/Rag.html")
    return path.read_text(encoding="utf-8")


def test_logout_clears_history_and_starts_new_chat() -> None:
    html = _read_rag_html()

    assert "if (!fakeAuthEnabled)" in html
    assert "historySearchQuery = \"\"" in html
    assert "historySearchInput.value = \"\"" in html
    assert "queryInput.value = \"\"" in html
    assert "resetQueryInputHeight();" in html
    assert "newChat();" in html


def test_query_form_is_centered_in_normal_and_mobile() -> None:
    html = _read_rag_html()

    assert re.search(r"#queryForm\s*\{[\s\S]*?max-width:\s*var\(--content-max-width\);", html)
    assert re.search(r"#queryForm\s*\{[\s\S]*?margin:\s*0\s+auto\s+1rem\s+auto;", html)

    assert re.search(
        r"@media\s*\(max-width:\s*1100px\)[\s\S]*#queryForm\.centered\s*\{[\s\S]*left:\s*50%;",
        html,
    )


def test_language_selector_obeys_multilingual_project_flag() -> None:
    html = _read_rag_html()

    assert "isMultilingualProject" in html
    assert "neutralLanguage" in html
    assert "translatedLanguage" in html
    assert "function renderLanguageSelector(selectedLang)" in html
    assert "langSelect.style.display = \"none\"" in html
    assert "translateChat: shouldTranslateChatForLang(lang)" in html
