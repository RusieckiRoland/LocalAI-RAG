# Retrieval Results Report (Top-5 per query)

This report evaluates each query against **both corpora** and lists the **Top-5 hits** for each retrieval method:

- **BM25** (classic lexical ranking)
- **Semantic** (TF‑IDF cosine proxy)
- **Hybrid** (0.5 * norm(BM25) + 0.5 * norm(Semantic))

> Note: semantic/hybrid here are offline proxies (no embeddings). Useful for repeatable test scaffolding.


---

## Corpus 1 — C# (100 items)

### Q01 (BM25)

**Query:** `archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" nlog Rolling vs Date`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 2 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 3 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 4 | 082 | Item 082: Data / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 5 | 045 | Item 045: Billing / dto_mapping | nlog archiveNumbering Date archiveDateFormat |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 2 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 3 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 4 | 015 | Item 015: Logging / async_pipeline | nlog archiveNumbering Date archiveDateFormat |
| 5 | 045 | Item 045: Billing / dto_mapping | nlog archiveNumbering Date archiveDateFormat |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 2 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 3 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 4 | 045 | Item 045: Billing / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 5 | 082 | Item 082: Data / dto_mapping | nlog archiveNumbering Date archiveDateFormat |


### Q02 (BM25)

**Query:** `reciprocal rank fusion RRF tie-break k=60 score 1/(k+rank) hybrid retrieval`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |


### Q03 (BM25)

**Query:** `weaviate BYOV import snapshot head_sha branch zip create collection RagNode RagEdge`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 003 | Item 003: Testing / extension_method | yaml pipeline step id next loop guard context budget |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 003 | Item 003: Testing / extension_method | yaml pipeline step id next loop guard context budget |


### Q04 (BM25)

**Query:** `Dapper MERGE Upsert CommandDefinition cancellationtoken QuerySingleOrDefaultAsync`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 069 | Item 069: Concurrency / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 058 | Item 058: Search / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 4 | 054 | Item 054: Concurrency / linq_transform | dapper merge upsert commanddefinition cancellationtoken |
| 5 | 042 | Item 042: Parsing / linq_transform | dapper merge upsert commanddefinition cancellationtoken |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 058 | Item 058: Search / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 069 | Item 069: Concurrency / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 4 | 042 | Item 042: Parsing / linq_transform | dapper merge upsert commanddefinition cancellationtoken |
| 5 | 041 | Item 041: Shipping / linq_transform | dapper merge upsert commanddefinition cancellationtoken |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 058 | Item 058: Search / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 069 | Item 069: Concurrency / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 4 | 042 | Item 042: Parsing / linq_transform | dapper merge upsert commanddefinition cancellationtoken |
| 5 | 041 | Item 041: Shipping / linq_transform | dapper merge upsert commanddefinition cancellationtoken |


### Q05 (BM25)

**Query:** `acl filter applied before ranking allowed_group_ids TenantId deny traversal graph expansion`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 2 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |
| 5 | 080 | Item 080: Networking / linq_transform | acl filter applied before ranking |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 2 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |
| 5 | 067 | Item 067: UI / async_pipeline | acl filter applied before ranking |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 2 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |
| 5 | 067 | Item 067: UI / async_pipeline | acl filter applied before ranking |


### Q06 (Semantic)

**Query:** `How do we ensure access control filters are applied before scoring or truncation in retrieval (ACL prefilter) and what happens during graph expansion when an intermediate node is denied?`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 2 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 067 | Item 067: UI / async_pipeline | acl filter applied before ranking |
| 5 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 2 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 067 | Item 067: UI / async_pipeline | acl filter applied before ranking |
| 5 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 2 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 067 | Item 067: UI / async_pipeline | acl filter applied before ranking |
| 5 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |


### Q07 (Semantic)

**Query:** `Show examples of configuring NLog file archiving by date (archiveNumbering=Date) and explain how it differs from rolling numbering, including date format settings.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 2 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 3 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 4 | 045 | Item 045: Billing / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 5 | 082 | Item 082: Data / dto_mapping | nlog archiveNumbering Date archiveDateFormat |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 2 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 3 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 4 | 015 | Item 015: Logging / async_pipeline | nlog archiveNumbering Date archiveDateFormat |
| 5 | 045 | Item 045: Billing / dto_mapping | nlog archiveNumbering Date archiveDateFormat |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 2 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 3 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 4 | 045 | Item 045: Billing / dto_mapping | nlog archiveNumbering Date archiveDateFormat |
| 5 | 082 | Item 082: Data / dto_mapping | nlog archiveNumbering Date archiveDateFormat |


### Q08 (Semantic)

**Query:** `Find code that implements Reciprocal Rank Fusion (RRF) scoring and discusses tie-breaking when dense and sparse ranks produce equal scores.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |


### Q09 (Semantic)

**Query:** `Locate import-related code/comments for Weaviate bring-your-own-vectors (BYOV), including snapshot identifiers like head_sha and branch zip ingestion.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 003 | Item 003: Testing / extension_method | yaml pipeline step id next loop guard context budget |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 003 | Item 003: Testing / extension_method | yaml pipeline step id next loop guard context budget |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 003 | Item 003: Testing / extension_method | yaml pipeline step id next loop guard context budget |


### Q10 (Semantic)

**Query:** `Find C# repository patterns that use Dapper to upsert records via MERGE and use CommandDefinition with CancellationToken.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 078 | Item 078: Concurrency / controller | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 069 | Item 069: Concurrency / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 4 | 058 | Item 058: Search / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 5 | 054 | Item 054: Concurrency / linq_transform | dapper merge upsert commanddefinition cancellationtoken |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 078 | Item 078: Concurrency / controller | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 058 | Item 058: Search / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 4 | 069 | Item 069: Concurrency / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 5 | 042 | Item 042: Parsing / linq_transform | dapper merge upsert commanddefinition cancellationtoken |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 078 | Item 078: Concurrency / controller | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 058 | Item 058: Search / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 4 | 069 | Item 069: Concurrency / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 5 | 042 | Item 042: Parsing / linq_transform | dapper merge upsert commanddefinition cancellationtoken |


### Q11 (Hybrid)

**Query:** `("reciprocal rank fusion" OR RRF) AND (tie-break OR "k = 60") AND (hybrid OR bm25)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 056 | Item 056: Files / record_and_validation | bm25 reciprocal rank fusion rrf tie-break |
| 2 | 012 | Item 012: Files / dto_mapping | bm25 reciprocal rank fusion rrf tie-break |
| 3 | 060 | Item 060: Identity / async_pipeline | bm25 reciprocal rank fusion rrf tie-break |
| 4 | 061 | Item 061: Crypto / linq_transform | bm25 reciprocal rank fusion rrf tie-break |
| 5 | 071 | Item 071: Parsing / exceptions_and_result | bm25 reciprocal rank fusion rrf tie-break |


### Q12 (Hybrid)

**Query:** `(weaviate OR BYOV) AND (head_sha OR snapshot) AND (import OR zip OR branch)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 051 | Item 051: Testing / record_and_validation |  |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 051 | Item 051: Testing / record_and_validation |  |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 046 | Item 046: Search / extension_method | weaviate byov vector import snapshot head_sha |
| 2 | 097 | Item 097: Logging / unit_test | weaviate byov vector import snapshot head_sha |
| 3 | 013 | Item 013: Parsing / async_pipeline | weaviate byov vector import snapshot head_sha |
| 4 | 081 | Item 081: Concurrency / repository | weaviate byov vector import snapshot head_sha |
| 5 | 051 | Item 051: Testing / record_and_validation |  |


### Q13 (Hybrid)

**Query:** `(archiveNumbering OR archiveDateFormat) AND (NLog OR nlog.config) AND (Rolling OR Date)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 029 | Item 029: Logging / record_and_validation | nlog archiveNumbering Date archiveDateFormat |
| 2 | 043 | Item 043: Search / record_and_validation | nlog archiveNumbering Date archiveDateFormat |
| 3 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 4 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 5 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 2 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 3 | 029 | Item 029: Logging / record_and_validation | nlog archiveNumbering Date archiveDateFormat |
| 4 | 043 | Item 043: Search / record_and_validation | nlog archiveNumbering Date archiveDateFormat |
| 5 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 029 | Item 029: Logging / record_and_validation | nlog archiveNumbering Date archiveDateFormat |
| 2 | 043 | Item 043: Search / record_and_validation | nlog archiveNumbering Date archiveDateFormat |
| 3 | 034 | Item 034: Cache / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 4 | 091 | Item 091: UI / extension_method | nlog archiveNumbering Date archiveDateFormat |
| 5 | 050 | Item 050: UI / dto_mapping | nlog archiveNumbering Date archiveDateFormat |


### Q14 (Hybrid)

**Query:** `(acl OR allowed_group_ids OR TenantId) AND ("filter before ranking" OR prefilter) AND (graph expansion OR dependencies)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 2 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |
| 5 | 080 | Item 080: Networking / linq_transform | acl filter applied before ranking |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 2 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |
| 5 | 067 | Item 067: UI / async_pipeline | acl filter applied before ranking |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 011 | Item 011: Search / extension_method | acl filter applied before ranking |
| 2 | 017 | Item 017: Concurrency / extension_method | acl filter applied before ranking |
| 3 | 048 | Item 048: Search / extension_method | acl filter applied before ranking |
| 4 | 018 | Item 018: Testing / unit_test | acl filter applied before ranking |
| 5 | 067 | Item 067: UI / async_pipeline | acl filter applied before ranking |


### Q15 (Hybrid)

**Query:** `(Dapper OR CommandDefinition) AND (MERGE OR Upsert) AND (QuerySingleOrDefaultAsync OR ExecuteAsync)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Logging / record_and_validation | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 075 | Item 075: Identity / repository |  |
| 4 | 006 | Item 006: Search / repository |  |
| 5 | 040 | Item 040: Concurrency / repository |  |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Logging / record_and_validation | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 058 | Item 058: Search / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 069 | Item 069: Concurrency / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 4 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 5 | 042 | Item 042: Parsing / linq_transform | dapper merge upsert commanddefinition cancellationtoken |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Logging / record_and_validation | dapper merge upsert commanddefinition cancellationtoken |
| 2 | 088 | Item 088: Data / controller | dapper merge upsert commanddefinition cancellationtoken |
| 3 | 058 | Item 058: Search / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 4 | 069 | Item 069: Concurrency / async_pipeline | dapper merge upsert commanddefinition cancellationtoken |
| 5 | 042 | Item 042: Parsing / linq_transform | dapper merge upsert commanddefinition cancellationtoken |



---

## Corpus 2 — SQL/T-SQL (100 items)

### Q01 (BM25)

**Query:** `OPENJSON with schema TenantId CorrelationId "openjson(@payload) with" sql server`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 038 | Item 038: Logging / json_parse |  |
| 2 | 073 | Item 073: Logging / json_parse |  |
| 3 | 065 | Item 065: Files / json_parse |  |
| 4 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 5 | 009 | Item 009: Jobs / json_parse | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 038 | Item 038: Logging / json_parse |  |
| 2 | 073 | Item 073: Logging / json_parse |  |
| 3 | 065 | Item 065: Files / json_parse |  |
| 4 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 5 | 009 | Item 009: Jobs / json_parse | snapshot head_sha branch import |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 038 | Item 038: Logging / json_parse |  |
| 2 | 073 | Item 073: Logging / json_parse |  |
| 3 | 065 | Item 065: Files / json_parse |  |
| 4 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 5 | 009 | Item 009: Jobs / json_parse | snapshot head_sha branch import |


### Q02 (BM25)

**Query:** `apply filter before ranking tenant_id allowed_group_ids_json exists openjson UserGroups ACL`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 088 | Item 088: Shipping / acl_prefilter_query | openjson with schema |
| 3 | 063 | Item 063: Identity / acl_prefilter_query |  |
| 4 | 074 | Item 074: Files / acl_prefilter_query | deduplicate by checksum sha256 |
| 5 | 096 | Item 096: Analytics / acl_prefilter_query | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 088 | Item 088: Shipping / acl_prefilter_query | openjson with schema |
| 3 | 063 | Item 063: Identity / acl_prefilter_query |  |
| 4 | 074 | Item 074: Files / acl_prefilter_query | deduplicate by checksum sha256 |
| 5 | 014 | Item 014: Data / acl_prefilter_query | rsa decrypt base64 private key |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 088 | Item 088: Shipping / acl_prefilter_query | openjson with schema |
| 3 | 063 | Item 063: Identity / acl_prefilter_query |  |
| 4 | 074 | Item 074: Files / acl_prefilter_query | deduplicate by checksum sha256 |
| 5 | 014 | Item 014: Data / acl_prefilter_query | rsa decrypt base64 private key |


### Q03 (BM25)

**Query:** `merge upsert pattern "when matched then update" sysutcdatetime sql server`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 030 | Item 030: Identity / merge_upsert |  |
| 2 | 085 | Item 085: Search / merge_upsert |  |
| 3 | 076 | Item 076: Data / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 030 | Item 030: Identity / merge_upsert |  |
| 2 | 085 | Item 085: Search / merge_upsert |  |
| 3 | 076 | Item 076: Data / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 030 | Item 030: Identity / merge_upsert |  |
| 2 | 085 | Item 085: Search / merge_upsert |  |
| 3 | 076 | Item 076: Data / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |


### Q04 (BM25)

**Query:** `order by offset fetch next pagination @offset @limit stored procedure`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |
| 5 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |
| 5 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |
| 5 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |


### Q05 (BM25)

**Query:** `head_sha snapshot branch import RagEdge EdgeType Calls ReadsFrom WritesTo`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 023 | Item 023: Data / graph_expansion_edges |  |
| 3 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 4 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 5 | 062 | Item 062: Shipping / graph_expansion_edges | lease 15 minutes with heartbeat |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 023 | Item 023: Data / graph_expansion_edges |  |
| 3 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 4 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 5 | 031 | Item 031: Search / graph_expansion_edges | rsa decrypt base64 private key |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 023 | Item 023: Data / graph_expansion_edges |  |
| 3 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 4 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 5 | 031 | Item 031: Search / graph_expansion_edges | rsa decrypt base64 private key |


### Q06 (Semantic)

**Query:** `Find SQL code that enforces ACL by prefiltering rows using tenant and group membership, explicitly applying filters before any ranking or limiting.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 074 | Item 074: Files / acl_prefilter_query | deduplicate by checksum sha256 |
| 3 | 063 | Item 063: Identity / acl_prefilter_query |  |
| 4 | 088 | Item 088: Shipping / acl_prefilter_query | openjson with schema |
| 5 | 096 | Item 096: Analytics / acl_prefilter_query | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 3 | 053 | Item 053: Files / stored_procedure_report |  |
| 4 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |
| 5 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 074 | Item 074: Files / acl_prefilter_query | deduplicate by checksum sha256 |
| 3 | 063 | Item 063: Identity / acl_prefilter_query |  |
| 4 | 015 | Item 015: Identity / acl_prefilter_query | deduplicate by checksum sha256 |
| 5 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |


### Q07 (Semantic)

**Query:** `Show examples of SQL Server JSON parsing with OPENJSON and an explicit WITH schema that extracts tenantId and correlationId fields.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 038 | Item 038: Logging / json_parse |  |
| 2 | 073 | Item 073: Logging / json_parse |  |
| 3 | 065 | Item 065: Files / json_parse |  |
| 4 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 5 | 009 | Item 009: Jobs / json_parse | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 038 | Item 038: Logging / json_parse |  |
| 2 | 073 | Item 073: Logging / json_parse |  |
| 3 | 065 | Item 065: Files / json_parse |  |
| 4 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 5 | 009 | Item 009: Jobs / json_parse | snapshot head_sha branch import |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 073 | Item 073: Logging / json_parse |  |
| 2 | 038 | Item 038: Logging / json_parse |  |
| 3 | 065 | Item 065: Files / json_parse |  |
| 4 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 5 | 009 | Item 009: Jobs / json_parse | snapshot head_sha branch import |


### Q08 (Semantic)

**Query:** `Locate T-SQL MERGE-based upsert statements that update timestamps with sysutcdatetime() and insert when not matched.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 030 | Item 030: Identity / merge_upsert |  |
| 2 | 085 | Item 085: Search / merge_upsert |  |
| 3 | 076 | Item 076: Data / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 030 | Item 030: Identity / merge_upsert |  |
| 2 | 085 | Item 085: Search / merge_upsert |  |
| 3 | 076 | Item 076: Data / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 030 | Item 030: Identity / merge_upsert |  |
| 2 | 085 | Item 085: Search / merge_upsert |  |
| 3 | 076 | Item 076: Data / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |


### Q09 (Semantic)

**Query:** `Find stored procedures that implement pagination using ORDER BY ... OFFSET ... FETCH NEXT ... and accept @offset/@limit parameters.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |
| 5 | 029 | Item 029: Identity / stored_procedure_report | openjson with schema |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |
| 5 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |
| 5 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |


### Q10 (Semantic)

**Query:** `Find schema or DDL for a dependency/graph edge table that includes snapshot identifiers like head_sha and an EdgeType such as Calls/ReadsFrom/WritesTo.`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 3 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 4 | 023 | Item 023: Data / graph_expansion_edges |  |
| 5 | 062 | Item 062: Shipping / graph_expansion_edges | lease 15 minutes with heartbeat |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 3 | 023 | Item 023: Data / graph_expansion_edges |  |
| 4 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 5 | 031 | Item 031: Search / graph_expansion_edges | rsa decrypt base64 private key |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 3 | 023 | Item 023: Data / graph_expansion_edges |  |
| 4 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 5 | 031 | Item 031: Search / graph_expansion_edges | rsa decrypt base64 private key |


### Q11 (Hybrid)

**Query:** `("apply filter before ranking" OR prefilter) AND (tenant_id OR TenantId) AND (allowed_group_ids OR UserGroups)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 063 | Item 063: Identity / acl_prefilter_query |  |
| 3 | 088 | Item 088: Shipping / acl_prefilter_query | openjson with schema |
| 4 | 074 | Item 074: Files / acl_prefilter_query | deduplicate by checksum sha256 |
| 5 | 096 | Item 096: Analytics / acl_prefilter_query | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 063 | Item 063: Identity / acl_prefilter_query |  |
| 3 | 088 | Item 088: Shipping / acl_prefilter_query | openjson with schema |
| 4 | 074 | Item 074: Files / acl_prefilter_query | deduplicate by checksum sha256 |
| 5 | 014 | Item 014: Data / acl_prefilter_query | rsa decrypt base64 private key |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 078 | Item 078: Jobs / acl_prefilter_query | apply filter before ranking |
| 2 | 063 | Item 063: Identity / acl_prefilter_query |  |
| 3 | 088 | Item 088: Shipping / acl_prefilter_query | openjson with schema |
| 4 | 074 | Item 074: Files / acl_prefilter_query | deduplicate by checksum sha256 |
| 5 | 014 | Item 014: Data / acl_prefilter_query | rsa decrypt base64 private key |


### Q12 (Hybrid)

**Query:** `(OPENJSON OR json) AND ("with (" OR "with(") AND (TenantId OR CorrelationId)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 073 | Item 073: Logging / json_parse |  |
| 2 | 038 | Item 038: Logging / json_parse |  |
| 3 | 065 | Item 065: Files / json_parse |  |
| 4 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 5 | 009 | Item 009: Jobs / json_parse | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 2 | 073 | Item 073: Logging / json_parse |  |
| 3 | 038 | Item 038: Logging / json_parse |  |
| 4 | 065 | Item 065: Files / json_parse |  |
| 5 | 010 | Item 010: Identity / json_parse | lease 15 minutes with heartbeat |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 073 | Item 073: Logging / json_parse |  |
| 2 | 038 | Item 038: Logging / json_parse |  |
| 3 | 018 | Item 018: Shipping / json_parse | lease 15 minutes with heartbeat |
| 4 | 065 | Item 065: Files / json_parse |  |
| 5 | 009 | Item 009: Jobs / json_parse | snapshot head_sha branch import |


### Q13 (Hybrid)

**Query:** `(MERGE OR upsert) AND ("when matched" OR "when not matched") AND sysutcdatetime`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 085 | Item 085: Search / merge_upsert |  |
| 2 | 076 | Item 076: Data / merge_upsert |  |
| 3 | 030 | Item 030: Identity / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 030 | Item 030: Identity / merge_upsert |  |
| 2 | 085 | Item 085: Search / merge_upsert |  |
| 3 | 076 | Item 076: Data / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 030 | Item 030: Identity / merge_upsert |  |
| 2 | 085 | Item 085: Search / merge_upsert |  |
| 3 | 076 | Item 076: Data / merge_upsert |  |
| 4 | 047 | Item 047: Data / merge_upsert |  |
| 5 | 097 | Item 097: Analytics / merge_upsert | snapshot head_sha branch import |


### Q14 (Hybrid)

**Query:** `(OFFSET AND FETCH) AND (pagination OR @offset OR @limit) AND (order by)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |
| 5 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |
| 5 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 066 | Item 066: Analytics / stored_procedure_report | order by offset fetch |
| 2 | 053 | Item 053: Files / stored_procedure_report |  |
| 3 | 040 | Item 040: Identity / stored_procedure_report | deduplicate by checksum sha256 |
| 4 | 061 | Item 061: Logging / stored_procedure_report | openjson with schema |
| 5 | 054 | Item 054: Billing / stored_procedure_report | snapshot head_sha branch import |


### Q15 (Hybrid)

**Query:** `(head_sha OR snapshot) AND (RagEdge OR EdgeType OR dependencies) AND (Calls OR ReadsFrom OR WritesTo)`

#### BM25 — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 3 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 4 | 023 | Item 023: Data / graph_expansion_edges |  |
| 5 | 062 | Item 062: Shipping / graph_expansion_edges | lease 15 minutes with heartbeat |

#### Semantic — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 3 | 023 | Item 023: Data / graph_expansion_edges |  |
| 4 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 5 | 031 | Item 031: Search / graph_expansion_edges | rsa decrypt base64 private key |

#### Hybrid — Top 5

| Rank | Item | Title | Anchor phrase |
|---:|:---:|---|---|
| 1 | 064 | Item 064: Identity / graph_expansion_edges | snapshot head_sha branch import |
| 2 | 091 | Item 091: Jobs / graph_expansion_edges |  |
| 3 | 023 | Item 023: Data / graph_expansion_edges |  |
| 4 | 028 | Item 028: Logging / graph_expansion_edges |  |
| 5 | 031 | Item 031: Search / graph_expansion_edges | rsa decrypt base64 private key |

