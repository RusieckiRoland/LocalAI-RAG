# Unified Vector Search – Design Assumptions (LocalAI-RAG)

This document describes how vector search will work in LocalAI-RAG once we switch (and have already started switching) to a single unified FAISS index for both application code and database code.

It is a conceptual design, not an implementation guide.

---

## 1. Goals

1. Use one shared embedding space and one FAISS index for:
   - regular application code (C#, Razor, configs, etc.),
   - database-related code (today: SQL files from `sql_bodies.jsonl`; later also EF migrations and inline SQL).
2. Keep strong filtering control at query time, so we can:
   - search only regular code,
   - search only DB code,
   - search only in specific subsets (e.g. only plain `.sql` files, later only EF migrations, only procedures, only tables, only one module).
3. Make the search layer simple to reason about:
   - always one vector search call,
   - all specialization is expressed via metadata filters applied to the results.

---

## 2. One unified index

All chunks (C# and SQL) are stored in a single FAISS index:

- one embedding model (e.g. SentenceTransformer),
- one global vector space,
- one FAISS index (e.g. `IndexFlatIP`),
- one metadata store (e.g. `unified_metadata.json`).

Each chunk is a “document” with:

- a text field used to build the embedding,
- a metadata record used to filter and display results.

The search layer never needs to know whether a given chunk came from a “C# pipeline” or “SQL pipeline” – it just sees metadata.

Today the unified index includes:

- C# code from `chunks.json` (`regular_code`),
- SQL objects from `sql_bodies.jsonl` (`db_code`, `file_type = "sql"`),

with both **develop** and **master** branches for nopCommerce merged into the same index.

EF migrations and inline SQL are planned for future iterations.

---

## 3. Core metadata

Each document in the unified index has a structured metadata object.  
Fields are grouped by purpose.

### 3.1. Common fields (all documents)

Required:

- `id` – global identifier of the logical object (with chunk suffix if needed), e.g.  
  - `cs:Nop.Web.Controllers.OrderController.PlaceOrder:part=0`  
  - `sql:NopDb::dbo.Order_Insert:part=1`
- `data_type` – top-level type of content:
  - `"regular_code"` – application / non-DB code (C#, Razor, etc.),
  - `"db_code"` – database-related code (SQL, later migrations, inline SQL).
- `file_type` – physical / logical file category:
  - for DB code: `"sql"` (today), later `"ef_migration"` / `"inline_sql"`,
  - for regular code: `"cs" | "razor" | "config" | "json" | ...`.
- `source_file` – path inside the branch/archive, e.g.
  - `src/Presentation/Nop.Web/Controllers/OrderController.cs`,
  - `src/Database/Tables/Order.sql`.
- `chunk_part` – index of the chunk within the object (0-based).
- `chunk_total` – total number of chunks for the object.

Recommended:

- `repo` – logical repository name, e.g. `"nopCommerce"`.
- `branch` – branch or snapshot name, e.g. `"develop"`, `"master"`.
- `project` / `assembly` / `module` – name of the project or assembly the file belongs to, e.g.  
  `Nop.Web`, `Nop.Core`, `Nop.Services`.
- `importance_score` – numeric multiplier used in ranking (default `1.0`).

These fields allow us to put multiple branches (and even multiple repositories) into one unified index and later filter by `branch` or `repo`.

### 3.2. SQL-specific fields (`data_type = "db_code"`)

- `kind` – type of SQL object, e.g.:  
  `"Table" | "Procedure" | "Function" | "View" | "Trigger" | "Index" | "ForeignKey" | "Constraint" | "Synonym"`.
- `schema` – e.g. `"dbo"`, `"audit"`.
- `name` – object name, e.g. `Order_Insert`, `Order`.
- `db_key` – canonical DB object key, e.g. `NopDb::dbo.Order_Insert`.

Graph-derived context (optional, but powerful):

- `reads_from` – list of table names / keys this object reads from.
- `writes_to` – list of table names / keys this object writes to.
- `calls` – list of other SQL objects it calls.
- `called_by` – list of objects that call this one.
- `fk_dependencies` – tables related by foreign keys.
- `used_by_csharp` – list of C# keys that depend on this SQL object.

### 3.3. C#-specific fields (`data_type = "regular_code"`)

- `class` – class / type name, e.g. `OrderController`.
- `member` – method / property / field name, e.g. `PlaceOrder`.
- `cs_key` – canonical C# object key, e.g. `Nop.Web.Controllers.OrderController.PlaceOrder`.

Other possible fields (optional):

- `member_kind` – `"Method" | "Property" | "Field" | "Class" | "Interface" | "Enum"`.
- `visibility` – `"public" | "internal" | "private" | "protected"`.

---

## 4. Query model

Vector search is driven by a simple query object:

```text
text_query        – user or system textual query (required)
top_k             – number of results to return (after filtering)
filters           – optional metadata filters
oversample_factor – how many raw FAISS hits to fetch before filtering
```

### 4.1. Filter structure

Filters are expressed in a neutral structure that can be passed from the RAG pipeline:

```json
{
  "data_type": ["regular_code", "db_code"],
  "file_type": ["sql"],
  "kind": ["Procedure"],
  "project": ["Nop.Web"],
  "schema": ["dbo"],
  "name_prefix": ["Order_"],
  "branch": ["develop"],
  "repo": ["nopCommerce"]
}
```

Semantics:

- For each field:
  - multiple values → logical **OR** within the field.
- Across different fields:
  - fields are combined with logical **AND**.
- Some fields (like `name_prefix`) use simple conventions (e.g. string starts with).

The initial design is equality + simple prefix matching. More complex operators can be added later if needed.

---

## 5. Search flow

The high-level search flow is always the same:

1. **Embed the query**
   - Encode `text_query` using the same embedding model as the index.
   - Get a single query vector.

2. **Raw FAISS search (unfiltered)**
   - Ask FAISS for `raw_top_k = top_k * oversample_factor` hits.
   - Typical `oversample_factor`: 3–10 (configurable).
   - Receive:
     - an array of indices,
     - an array of scores (similarities).

3. **Metadata lookup**
   - For each returned index `i`, load `metadata[i]`.
   - Optionally, also load a short text preview for display or logging.

4. **Filtering by metadata**
   - Apply filters from `filters`:
     - `data_type` (e.g. only `"db_code"`),
     - `file_type` (e.g. only `"sql"`),
     - `kind` (e.g. only `"Procedure"`),
     - `project`, `schema`, `name`, `branch`, `repo`, etc.
   - Keep only documents that satisfy all filter conditions.

5. **Re-ranking (optional)**
   - For each remaining document:
     - compute `final_score = faiss_score * importance_score`.
   - Sort results by `final_score` descending.

6. **Result truncation**
   - Return `top_k` results after filtering and re-ranking.
   - Each result includes:
     - `final_score`,
     - original FAISS score,
     - full metadata record,
     - document text (or a truncated preview).

7. **Fallback behavior**
   - If after filtering there are too few results:
     - Option 1: increase `oversample_factor` and re-run FAISS (same filters),
     - Option 2: relax filters (e.g. drop `file_type`, keep only `data_type`),
     - Option 3: return a “no results within current filters” status to the RAG pipeline.

---

## 6. Example search modes

All modes use the same FAISS index. The difference is only in the filters.

### 6.1. General search (both code and DB)

```json
{
  "data_type": ["regular_code", "db_code"]
}
```

No more filters → all chunks are allowed.  
Useful for broad questions where we want any relevant context.

---

### 6.2. Application code only

```json
{
  "data_type": ["regular_code"]
}
```

We only search C#/Razor/config chunks.  
Useful for questions like “Where is the order placement handled in the web app?”.

---

### 6.3. Database code only (all DB sources)

```json
{
  "data_type": ["db_code"]
}
```

We search all database-related code: today plain `.sql`, later also EF migrations and inline SQL.

---

### 6.4. Only plain SQL files

```json
{
  "data_type": ["db_code"],
  "file_type": ["sql"]
}
```

This excludes EF migrations and inline SQL (once they are added).  
Useful when we want to restrict answers to the “official” SQL project.

---

### 6.5. Only EF migrations (future)

```json
{
  "data_type": ["db_code"],
  "file_type": ["ef_migration"]
}
```

Useful when we want to see schema evolution over time or how a particular column/table was introduced.  
(Planned for later; not yet implemented.)

---

### 6.6. Only SQL procedures in a specific schema

```json
{
  "data_type": ["db_code"],
  "file_type": ["sql"],
  "kind": ["Procedure"],
  "schema": ["dbo"]
}
```

We can further restrict by `name` or `name_prefix` for families like `Order_*` if needed.

---

### 6.7. Only code in a specific project / branch

```json
{
  "project": ["Nop.Web"],
  "branch": ["develop"]
}
```

We keep both C# and SQL, but only for the selected project and branch.  
(If some SQL objects are not linked to a project, this filter will not apply to them.)

---

## 7. Integration with graph (future use)

The graph component can collaborate with vector search by providing additional constraints for the filters, for example:

- allowed set of `db_key` values (e.g. “only these 20 SQL objects”),
- allowed set of `cs_key` values (e.g. “only methods reachable from this entry point”).

The search flow stays the same. The only difference is that we add extra filter fields, for example:

```json
{
  "db_key_in": ["NopDb::dbo.Order_Insert", "NopDb::dbo.Order"]
}
```

The filter semantics remain AND across fields, so this behaves as a natural narrowing based on graph traversal.

---

## 8. Design principles

1. One index, many views  
   We always query the same FAISS index; different “views” are implemented by filters on metadata.

2. Metadata over separate indices  
   We prefer adding metadata fields to documents rather than splitting into multiple indices (code vs DB, SQL vs migrations, etc.).

3. Stable identifiers  
   `id`, `db_key`, and `cs_key` must be stable across runs so that:
   - we can cross-reference with the graph,
   - we can debug and reproduce results.

4. Backend keeps control of filters  
   - The RAG pipeline decides which filters are applied for a given step (e.g. first search DB only, then mix in C#).
   - The search layer remains simple and deterministic.

---

This document is the baseline for designing and implementing:

- the unified index builder,
- the unified search module (`search_unified_index`),
- and the RAG pipeline decisions on when and how to apply filters.
