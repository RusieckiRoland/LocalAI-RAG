import pytest
import numpy as np
from unittest.mock import MagicMock

from common.semantic_keyword_rerank_search import SemanticKeywordRerankSearch


@pytest.fixture
def mock_faiss_index():
    """Mock FAISS index returning fixed results."""
    index = MagicMock()
    index.search.return_value = (
        np.array([[0.73]], dtype=np.float32),
        np.array([[0]], dtype=np.int64),
    )
    return index


@pytest.fixture
def mock_embed_model():
    """Mock embedding model with fixed vector."""
    model = MagicMock()
    model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
    return model


@pytest.fixture
def sample_chunks():
    """Sample code chunks for C# and SQL."""
    return [
        {
            "Id": "1",
            "File": "src/Calculator.cs",
            "Text": "public int Add(int a, int b) => a + b;",
            "Member": "Add",
            "Type": "Method",
        },
        {
            "Id": "2",
            "File": "dbo/usp_GetReport.sql",
            "Text": "SELECT OrderId, Total FROM Sales WHERE Year = @year;",
            "Member": "usp_GetReport",
            "Type": "Procedure",
        },
    ]


@pytest.fixture
def sample_metadata(sample_chunks):
    """Metadata matching FAISS vector order."""
    return [{"Id": c["Id"], "File": c["File"]} for c in sample_chunks]


@pytest.fixture
def sample_dependencies():
    """Dependency: C# method calls SQL proc."""
    return {"1": ["2"]}


@pytest.fixture
def search_engine(mock_faiss_index, mock_embed_model, sample_metadata, sample_chunks, sample_dependencies):
    """Fully mocked HybridSearch – no disk, no GPU."""
    return SemanticKeywordRerankSearch(
        index=mock_faiss_index,
        metadata=sample_metadata,
        chunks=sample_chunks,
        dependencies=sample_dependencies,
        embed_model=mock_embed_model,
    )


# --------------------------------------------------------------------------- #
# Embedding search tests
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_embedding_search_returns_top_k_results(search_engine):
    """Top-k results from vector similarity."""
    results = search_engine._embedding_search(query="add numbers", k=1)
    assert len(results) == 1
    assert results[0]["Rank"] == 1
    assert results[0]["File"] == "src/Calculator.cs"
    assert isinstance(results[0]["Distance"], float)


@pytest.mark.unit
def test_embedding_search_includes_dependency_chunks(search_engine):
    """Related chunks from dependency graph are attached."""
    results = search_engine._embedding_search(query="calc", k=1)
    related = results[0]["Related"]
    assert len(related) == 1
    assert related[0]["File"] == "dbo/usp_GetReport.sql"
    assert "SELECT OrderId" in related[0]["Content"]


# --------------------------------------------------------------------------- #
# Keyword search tests
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_keyword_search_empty_query_returns_nothing(search_engine):
    """Empty query yields no results."""
    assert search_engine._keyword_search("", top_k=5) == []


@pytest.mark.unit
def test_keyword_search_requires_all_tokens(search_engine):
    """All tokens must appear in chunk."""
    results = search_engine._keyword_search("SELECT Year", top_k=5)
    assert len(results) == 1
    assert results[0]["File"] == "dbo/usp_GetReport.sql"


@pytest.mark.unit
def test_keyword_search_ranks_by_frequency(search_engine):
    """Higher token count = higher rank."""
    search_engine.chunks[0]["Text"] = "SELECT SELECT SELECT"
    results = search_engine._keyword_search("SELECT", top_k=2)
    assert results[0]["File"] == search_engine.chunks[0]["File"]


# --------------------------------------------------------------------------- #
# Rerank search fusion
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_search_combines_embedding_and_keyword_scores(search_engine, mocker):
    """Reranked score merges semantic and keyword signals."""
    search_engine.index.search.return_value = (
        np.array([[0.1, 0.9]], dtype=np.float32),
        np.array([[0, 1]], dtype=np.int64),
    )
    results = search_engine.search("Add SELECT", top_k=2, widen=10)
    assert len(results) == 2
    assert results[0]["File"] == "src/Calculator.cs"
    assert results[1]["File"] == "dbo/usp_GetReport.sql"


@pytest.mark.unit
def test_search_respects_alpha_beta_weighting(search_engine, mocker):
    """Alpha/beta control embedding vs keyword influence."""
    search_engine.index.search.return_value = (
        np.array([[0.0, 0.99]], dtype=np.float32),
        np.array([[0, 1]], dtype=np.int64),
    )
    # Pure embedding
    assert search_engine.search("irrelevant", top_k=1, alpha=1.0, beta=0.0)[0]["File"] == "src/Calculator.cs"
    # Pure keyword
    assert search_engine.search("SELECT", top_k=1, alpha=0.0, beta=1.0)[0]["File"] == "dbo/usp_GetReport.sql"