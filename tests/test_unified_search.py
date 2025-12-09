# tests/test_unified_search.py
import numpy as np
import pytest

from vector_search.models import VectorSearchFilters, VectorSearchRequest
from vector_search.unified_search import search_unified, metadata_matches_filters


pytestmark = pytest.mark.unit


class DummyIndex:
    """Simple FAISS-like stub returning fixed distances/indices."""
    def __init__(self):
        # We simulate 3 docs: idx 0, 1, 2
        self._dist = np.array([[0.9, 0.8, 0.7]], dtype=np.float32)
        self._idx = np.array([[0, 1, 2]], dtype=np.int64)
        self.ntotal = 3

    def search(self, vectors, k):
        # Ignore vectors; always return first k items
        return self._dist[:, :k], self._idx[:, :k]


class DummyEmbed:
    """Minimal encoder that returns the right shape for FAISS."""
    def encode(self, texts, convert_to_numpy=True):
        v = np.zeros((1, 8), dtype=np.float32)
        return v if convert_to_numpy else v.tolist()


def _metadata_fixture():
    return [
        {
            "id": 0,
            "data_type": "regular_code",
            "file_type": "cs",
            "source_file": "src/App/Program.cs",
            "project": "WebApp",
            "branch": "develop",
            "text": "public class Program { static void Main() {} }",
        },
        {
            "id": 1,
            "data_type": "db_code",
            "file_type": "sql",
            "source_file": "db/Orders.sql",
            "schema": "dbo",
            "name": "Orders_Get",
            "db_key": "MainDb::dbo.Orders_Get",
            "branch": "develop",
            "text": "SELECT * FROM Orders",
        },
        {
            "id": 2,
            "data_type": "db_code",
            "file_type": "sql",
            "source_file": "db/Customers.sql",
            "schema": "dbo",
            "name": "Customers_Get",
            "db_key": "MainDb::dbo.Customers_Get",
            "branch": "feature/customers",
            "text": "SELECT * FROM Customers",
        },
    ]


def test_metadata_matches_filters_basic_fields():
    meta = {
        "data_type": "db_code",
        "file_type": "sql",
        "schema": "dbo",
        "name": "Orders_Get",
        "branch": "develop",
    }

    f = VectorSearchFilters(
        data_type=["db_code"],
        file_type=["sql"],
        schema=["dbo"],
        name_prefix=["Orders_"],
        branch=["develop"],
    )

    assert metadata_matches_filters(meta, f) is True

    f_bad = VectorSearchFilters(
        data_type=["regular_code"]
    )
    assert metadata_matches_filters(meta, f_bad) is False


def test_search_unified_filters_by_data_type_and_file_type():
    index = DummyIndex()
    embed_model = DummyEmbed()
    metadata = _metadata_fixture()

    req = VectorSearchRequest(
        text_query="orders",
        top_k=2,
        oversample_factor=2,
        filters=VectorSearchFilters(
            data_type=["db_code"],
            file_type=["sql"],
        ),
        include_text_preview=True,
    )

    results = search_unified(
        index=index,
        metadata=metadata,
        embed_model=embed_model,
        request=req,
    )

    # We expect only DB code (sql) results
    assert results
    assert all(
        r["Metadata"]["data_type"] == "db_code"
        for r in results
    )
    assert all(
        r["Metadata"]["file_type"] == "sql"
        for r in results
    )


def test_search_unified_can_filter_by_branch_and_name_prefix():
    index = DummyIndex()
    embed_model = DummyEmbed()
    metadata = _metadata_fixture()

    req = VectorSearchRequest(
        text_query="customers",
        top_k=5,
        oversample_factor=2,
        filters=VectorSearchFilters(
            data_type=["db_code"],
            file_type=["sql"],
            branch=["feature/customers"],
            name_prefix=["Customers_"],
        ),
        include_text_preview=False,
    )

    results = search_unified(
        index=index,
        metadata=metadata,
        embed_model=embed_model,
        request=req,
    )

    # Should narrow down to the Customers_Get object
    assert len(results) == 1
    r = results[0]
    meta = r["Metadata"]
    assert meta["name"] == "Customers_Get"
    assert meta["branch"] == "feature/customers"
