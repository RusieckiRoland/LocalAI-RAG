# RAG-for-Code Pipeline Design (FAISS + Graph)

This document describes the **conceptual pipeline** for answering developer questions like:

> “How are invoices implemented in the system?”

The goal is to **combine FAISS-based retrieval with a code/database graph (RoslynIndexer)** in a controlled way:

- FAISS is used to **find entry points** and to fetch **concrete text** for known nodes.
- The **graph** is used to **walk dependencies** and reconstruct how a feature is actually implemented.

Implementation details (YAML, Python, prompt wiring) are intentionally omitted here.  
This is a **behavior / logic spec** for the pipeline.

---

## 0. Inputs and Assumptions

For each user request we assume:

- `UserQuestion` – the raw question from the user.
- `IsEnglish` – a boolean flag:
  - `True`  → `UserQuestion` is in English,
  - `False` → `UserQuestion` is in another language (in our case: Polish).

Additional internal state (not user-facing):

- `UserQuestionEN` – normalized English version of the question.
- `type` – the **intent** of the question, e.g. `"how_implemented"`, `"where_is"`, `"impact"`, `"bug"`, etc.
- `domain` – the **technical domain** of the question:
  - `"code"` – mainly about application code,
  - `"db"` – mainly about database,
  - `"mixed"` – both code and database.
- `concepts` – main concepts/entities (e.g. `["invoice"]`).
- `synonyms` – optional synonyms/related terms (`["invoice", "invoices", "faktura", "faktury", "billing document"]`).
- A **code+DB graph** from RoslynIndexer (nodes and edges).
- A **FAISS/hybrid index** over code/SQL artifacts.

---

## 1. Phase A – Question Normalization

**Goal:** Have a single English question to drive the rest of the pipeline.

**Step A.1 – Normalize to English**

- If `IsEnglish == True`  
  → `UserQuestionEN = UserQuestion`.
- If `IsEnglish == False`  
  → translate `UserQuestion` to English and store as `UserQuestionEN`.  
    (Keep the original for final answer translation.)

No language detection is performed – the caller decides via `IsEnglish`.

---

## 2. Phase B – Understanding the Question

**Goal:** Understand what the user is asking, before touching FAISS or the graph.

### Step B.1 – Intent classification (`type`)

From `UserQuestionEN` the model determines the **type of question**. Examples:

- `"how_implemented"` – “How is feature X implemented?”
- `"where_is"` – “Where is function X defined?”
- `"impact"` – “What breaks if we change X?”
- `"bug"` – “Why does X fail?”  
  etc.

For example:

> “How are invoices implemented in the system?”

→ `type = "how_implemented"`.

---

### Step B.2 – Domain classification (`domain`)

From `UserQuestionEN` the model determines the **technical domain**:

- `domain = "code"` – question mainly about source code,
- `domain = "db"` – question mainly about database schema / SQL,
- `domain = "mixed"` – both code and database are relevant.

Example:

> “How are invoices implemented in the system?”

→ `domain = "mixed"`  
(because we expect invoice implementation across tables, entities, services, controllers, etc.).

---

### Step B.3 – Concept and synonyms (`concepts`, `synonyms`)

The model extracts the **core business/technical concept(s)**:

- `concepts = ["invoice"]`
- `synonyms` may include localized and related terms, e.g.:
  - `["invoice", "invoices", "faktura", "faktury", "billing document"]`

At the end of Phase B we know:

- What the user is asking about (`type`),
- Which part of the system is involved (`domain`),
- Which concept(s) to look for (`concepts` and `synonyms`).

Still no FAISS and no graph traversal at this point.

---

## 3. Phase C – Decide if We Need Repository Context

**Goal:** Decide whether we can answer from general knowledge, or we must inspect the actual code/DB.

### Step C.1 – Can we answer without repository context?

The model uses:

- `UserQuestionEN`,
- `type`, `domain`, `concepts`,
- and the conversation history

to decide:

- If the question is **generic** (e.g. “What is an invoice in accounting?”),  
  then an answer can be produced from general knowledge.
- If the question is clearly about this **specific system**  
  (e.g. “How are invoices implemented in the system?”),  
  then we **cannot** answer reliably without repository context.

For system-specific implementation questions (our main case):

- We **must** consult the code/DB,
- So we move to planning retrieval.

---

## 4. Phase D – Retrieval Plan (Before Any FAISS Call)

**Goal:** Plan the retrieval strategy in terms of **what to search** and **how to use the graph**, before searching.

Given `type = "how_implemented"` and `domain`:

- If `domain = "code"`:
  - Plan:
    1. Find **entry points in code** for the given concept.
    2. From these entry points, walk the **code graph** (services, controllers, DbContexts, methods, etc.).
- If `domain = "db"`:
  - Plan:
    1. Find **entry points in DB** (tables, FKs, procedures).
    2. From these entry points, walk the **DB graph** (tables, FKs, migrations, procedures, etc.).
- If `domain = "mixed"` (our main scenario):
  - Plan:
    1. Find **code entry points** (entities, DbSets, services, controllers related to the concept).
    2. Find **DB entry points** (tables, FKs, procedures related to the concept).
    3. From these entry points, walk the combined **code+DB graph** to build a **local subgraph** (“the world of invoices”).
    4. Answer using that subgraph.

This is still planning – **no FAISS and no graph calls yet**.

---

## 5. Phase E – FAISS as Entry-Point Finder

**Goal:** Use FAISS **only** to find good entry points in code and DB, not to endlessly search.

### Step E.1 – Build internal FAISS queries

Based on `UserQuestionEN`, `domain`, `concepts`, and `synonyms`, we construct internal (non-user-facing) queries.

If the plan includes code:

- `CodeEntryQuery` (example):

  > "Where in the C# code is the *invoice* feature implemented?  
  > Look for controllers, services, DbContexts and entities related to invoices  
  > (invoice, invoices, faktura, faktury, billing document)."

If the plan includes DB:

- `DbEntryQuery` (example):

  > "In the database schema, where is the concept *invoice* implemented?  
  > Look for tables, foreign keys and stored procedures related to invoices  
  > (invoice, invoices, faktura, faktury, billing document)."

We may compute one or both, depending on `domain`.

---

### Step E.2 – First FAISS search (code / db)

We now perform **FAISS searches only for entry points**:

- If the plan includes code:
  - Send `CodeEntryQuery` to the **code index**.
  - Collect candidate chunks (classes, methods, DbSets, controllers).
- If the plan includes DB:
  - Send `DbEntryQuery` to the **SQL/DB index**.
  - Collect candidate chunks (tables, FK definitions, procedures, migrations, etc.).

From the retrieved chunks we extract **candidate graph nodes**, for example:

- Code:
  - `csharp:MyApp.Invoice|ENTITY`
  - `csharp:MyApp.Data.AppDbContext|DBCONTEXT (DbSet<Invoice>)`
  - `csharp:MyApp.InvoiceService|SERVICE`
  - `csharp:MyApp.InvoiceController|CONTROLLER`
- DB:
  - `dbo.Invoice|TABLE`
  - `dbo.InvoiceLine|TABLE`
  - `dbo.Invoice_Create|PROC`
  - `dbo.Invoice.CustomerId FK` → `FK_Invoice_Customer|FOREIGN_KEY`

These candidates are potential **entry points** in the graph.

---

### Step E.3 – Evaluate the quality of entry points

**This is the decision point:**

> “Do we have good entry points?  
> If yes → move to graph.  
> If no → reformulate and query FAISS again.  
> If still no → tell the user we can’t find the feature.”

Criteria for **good** entry points (examples):

- Names and types are clearly related to the concept:
  - `Invoice`, `InvoiceLine`, `Billing`, `Faktura`, etc.
- We have appropriate **node kinds**:
  - For DB: TABLE, FOREIGN_KEY, PROC, MIGRATION.
  - For code: ENTITY, DBSET, SERVICE, CONTROLLER, METHOD.
- Entries are not dominated by:
  - logs,
  - test-only code,
  - synthetic samples.

If the candidates are weak, we allow **one or two iterations** of:

- Ask the model to reformulate a more precise internal query, then
- Re-run FAISS for entry points, then
- Re-evaluate.

If, after this limited number of attempts, we **still** do not find acceptable entry points:

- We do **not** go to the graph.
- We inform the user honestly that we cannot find a clear implementation trace for the concept in this repository (instead of hallucinating).

If the candidates are acceptable:

- We **stop using FAISS as global “finder”**,
- We fix the list of entry-point nodes,
- We move on to graph traversal.

---

## 6. Phase F – Graph Traversal as the Main Navigation

**Goal:** Once we have entry points, we use the graph to understand the implementation, not more FAISS loops.

From now on, **the graph (RoslynIndexer output) is the main source of structure**.

### Step F.1 – Initialize entry nodes in the graph

We map the accepted candidates from Phase E to actual graph nodes, e.g.:

- `dbo.Invoice|TABLE`
- `dbo.InvoiceLine|TABLE`
- `csharp:MyApp.Invoice|ENTITY`
- `csharp:MyApp.Data.AppDbContext|DBCONTEXT`
- `csharp:MyApp.InvoiceService|SERVICE`
- `csharp:MyApp.InvoiceController|CONTROLLER`

These form the **starting set** for graph traversal.

---

### Step F.2 – Graph walk: build a local subgraph for the concept

We perform a **controlled graph walk** from each entry node, with depth and node-type limits.

Examples:

- Database side:
  - `TABLE` → outgoing and incoming `FOREIGN_KEY` edges → related `TABLE`s.
  - `TABLE` → `MIGRATION` nodes that created or altered it.
  - `TABLE` → `PROC` nodes that read/write this table.
- Code side:
  - `ENTITY`/`DBSET` → `DBCONTEXT`.
  - `SERVICE`/`REPOSITORY` → `METHOD` nodes operating on `ENTITY/TABLE`.
  - `CONTROLLER` → `ACTION` → `SERVICE`/`REPOSITORY`.
- Inline SQL:
  - `METHOD` → inline SQL usage → `TABLE`/`FOREIGN_KEY`.

The traversal is bounded (e.g. a few hops, restricted node types) to avoid exploding the graph.

The result is a **subgraph** that represents the “world” of the concept (e.g. invoices): which tables, relations, entities, contexts, services, controllers, and procedures are connected.

---

### Step F.3 – Using FAISS again, but locally (optional)

After we know **which nodes** are relevant, we may still need **text**:

- procedure bodies,
- method implementations,
- migration details, etc.

At this stage we use FAISS (or other storage) **only in a targeted way**:

- “give me the text body of node X”,
- “give me the snippet of file F, lines L–R, where node X is defined”.

This is **not** another global search for “invoice”; it is a **lookup by identity** of known nodes from the graph.

The subgraph + selected texts are combined into a **compact context** for the final answer.

---

## 7. Phase G – Answer Generation

**Goal:** Use the subgraph and supporting text to answer the original question.

The model receives:

- `UserQuestionEN`,
- A structured representation of the subgraph (nodes and relationships),
- A small set of text snippets (bodies of relevant methods/procedures/migrations, etc.).

The answer should:

1. Explain how the concept is implemented **in the database**:
   - key tables,
   - foreign keys,
   - important procedures/migrations.
2. Explain how the concept is implemented **in the code**:
   - entities,
   - DbContexts,
   - services/repositories,
   - controllers/actions.
3. Describe the **flow**:
   - from incoming request (controller),
   - through services and DbContexts,
   - to tables and back (including important FKs and dependent tables).

If `IsEnglish == False`:

- The final answer is translated back to the original language before returning to the user.

---

## 8. Phase H – Looping and Stopping Conditions

**Key rules for looping:**

1. **FAISS global search is limited to the entry-point phase (Phase E).**
   - We allow at most a small number of attempts:
     - initial entry queries,
     - maybe 1–2 reformulation attempts.
   - If we still don’t find good entry points:
     - we stop and inform the user that the concept is not clearly present in the code/DB.

2. **Once we accept entry points and move to graph traversal (Phase F), the graph is the main navigation tool.**
   - We do not start new global FAISS searches from scratch.
   - We walk the graph around known nodes to understand the implementation.

3. **FAISS is allowed again only for targeted text retrieval (Phase F.3).**
   - This is not concept-search; it is “bring me the body for known node X”.

4. **Final answer is generated once we have:**
   - a stable subgraph for the concept, and
   - enough text snippets to illustrate the implementation.

If, at any point during graph traversal or answer generation, the model detects that **critical pieces are missing** (e.g. no DB side found, or the concept appears only in partial test code), it should:

- explicitly mention these gaps in the answer,
- rather than invent missing parts.

---

## 9. Summary

- **FAISS** is used:
  - to find **entry points** (code/DB nodes related to the concept),
  - and later to fetch **text for known nodes**.
- The **graph** is used:
  - to follow **relationships and data flow** between these nodes,
  - to build a **local subgraph** that reflects how the feature is actually implemented.

The pipeline is structured in clear phases:

1. Normalize the question to English (using the `IsEnglish` flag).
2. Understand intent (`type`), domain (`domain`), and concepts (`concepts`, `synonyms`).
3. Decide whether repository context is required.
4. Plan retrieval strategy (code, DB, mixed).
5. Use FAISS **once or twice** to find good entry points; if that fails, stop.
6. Use the graph to walk dependencies and build a subgraph for the concept.
7. Use FAISS only for targeted node-text retrieval.
8. Generate a structured answer for the user, with optional translation back to the original language.

This design ensures that:

- The model does **not** endlessly loop on FAISS,
- The **graph** is the primary tool for understanding implementation,
- Repository-specific answers are grounded in actual code and database structure,
- And limitations (missing entry points, incomplete coverage) are visible and communicated.
