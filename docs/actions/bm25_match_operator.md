# BM25 `match_operator` (AND/OR) in this pipeline

## What it is
For `search_type: "bm25"` the pipeline supports an optional request parameter:
- `match_operator: "and" | "or"`

It controls **how BM25 query tokens are matched**:
- `"and"`: all (non-stopword) tokens must match for an object to be considered a hit
- `"or"`: at least one token must match (today: minimum match = 1)

This is conceptually the same knob exposed by Lucene/Elasticsearch/OpenSearch as:
- `operator: "and" | "or"` (e.g. in `match` queries)
- `default_operator: AND|OR` (in `query_string`)
- `bool.must` vs `bool.should` (Lucene BooleanQuery)

## Where it is parsed
When using `JsonishQueryParser`, the model can include:
```json
{"query":"class Category","filters":{"data_type":"regular_code"},"search_type":"bm25","match_operator":"and"}
```

`match_operator` is extracted as retrieval metadata and is **not** passed as a filter.

## Where it is applied
The value is passed through:
1) `search_nodes` → `SearchRequest.bm25_operator`
2) retrieval backend (Weaviate) → BM25 query `operator`

## Defaults
- If `match_operator` is omitted, BM25 uses backend defaults.
- If `search_type` is not `bm25`, `match_operator` is ignored.

