import pytest
c = pytest.importorskip("constants")


def test_constants_module_imports_and_has_some_symbols():
    names = [n for n in dir(c) if not n.startswith("_")]
    assert len(names) >= 1