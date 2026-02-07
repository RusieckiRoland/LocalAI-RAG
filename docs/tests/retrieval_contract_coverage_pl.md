# Checklist zgodności: retrieval_contract vs. retrieval_integration_tests

Ten dokument porównuje wymagania z `docs/contracts/retrieval_contract.md` z oczekiwaniami i realnym zakresem testów integracyjnych opisanych w `docs/tests/retrieval_integration_tests.md`.
Celem jest szybka ocena pokrycia kontraktu oraz lista brakujących testów.

## Legenda
- ✅ pokryte (w dokumentacji testów i/lub w kodzie testów)
- ⚠️ częściowo pokryte (intencja opisana, brak realnej weryfikacji lub pokrycie fragmentaryczne)
- ❌ niepokryte (brak w dokumentacji testów i brak weryfikacji)

## 1) `search_nodes` — kontrakt i pokrycie

- ✅ Wspierane tryby wyszukiwania: `semantic`, `bm25`, `hybrid`  
  Status: ✅  
  Dowód: sekcje 1–3 w `retrieval_integration_tests.md`.

- ✅ Zwraca seed IDs (niepuste), deterministycznie dla case’ów  
  Status: ✅  
  Dowód: „search_nodes returns at least one seed node”.

- ⚠️ `search_nodes` nie materializuje tekstu i nie zapisuje `context_blocks`  
  Status: ⚠️  
  Uzasadnienie: brak jawnego testu, brak asercji na puste `node_texts` lub `context_blocks` po samym `search_nodes`.

- ❌ Fail-fast dla braków: `repository`, `snapshot_id` (lub brak resolvable snapshot_set)  
  Status: ❌  
  Uzasadnienie: brak negatywnych testów kontraktowych.

- ❌ Wymuszenie `top_k` (z kroku lub settings)  
  Status: ❌  
  Uzasadnienie: brak testu na błąd przy braku `top_k`.

- ❌ Rerank tylko dla `semantic`, fail-fast dla `bm25`/`hybrid`  
  Status: ❌  
  Uzasadnienie: brak testów rerank w integracji.

- ⚠️ Sacred `retrieval_filters` (nie da się ich nadpisać przez parser)  
  Status: ⚠️  
  Uzasadnienie: dokument testów opisuje filtry, ale nie weryfikuje merge-logic z parserem.

## 2) `expand_dependency_tree` — kontrakt i pokrycie

- ✅ Rozszerzanie grafu z seedów z allowlistą i limitami  
  Status: ✅  
  Dowód: sekcja 6 w `retrieval_integration_tests.md` + testy allowlist.

- ✅ Edge allowlist: brak disallowed relacji  
  Status: ✅  
  Dowód: testy dependency_tree w kodzie.

- ✅ `graph_max_depth` i `graph_max_nodes` respektowane  
  Status: ⚠️  
  Uzasadnienie: dokument testów opisuje, ale w kodzie integracyjnym brak jawnego limit-case poza allowlist (brak explicit testu limitów ilościowych).

- ❌ Fail-fast dla braków: `repository`, `snapshot_id`, brak settings map (`*_from_settings`)  
  Status: ❌  
  Uzasadnienie: brak negatywnych testów kontraktowych.

- ⚠️ Obowiązkowe `graph_debug` z pełnym schema  
  Status: ⚠️  
  Uzasadnienie: testy logują debug, ale nie weryfikują kompletności kluczy.

- ❌ Security trimming w `expand_dependency_tree` (ACL + classification)  
  Status: ❌  
  Uzasadnienie: dokument testów wymaga, ale kod integracyjny tego nie sprawdza.

## 3) `fetch_node_texts` — kontrakt i pokrycie

- ✅ Priorytetyzacja (`seed_first`, `graph_first`, `balanced`)  
  Status: ✅  
  Dowód: sekcja 7 + testy F2–F4.

- ✅ Limity: `budget_tokens`, `max_chars`, `budget_tokens_from_settings`  
  Status: ✅  
  Dowód: testy F5–F7.

- ✅ Atomic skip (brak częściowych fragmentów tekstu)  
  Status: ✅  
  Dowód: test F8.

- ⚠️ Minimalny schema `node_texts` (`id`, `text`, `is_seed`, `depth`, `parent_id`)  
  Status: ⚠️  
  Uzasadnienie: testy weryfikują `id` i `text`, brak sprawdzenia `is_seed`, `depth`, `parent_id`.

- ❌ Mutual exclusivity: `budget_tokens` vs `max_chars`  
  Status: ❌  
  Uzasadnienie: brak negatywnego testu fail-fast.

- ❌ Fail-fast dla braków: `repository`, `snapshot_id`, `max_context_tokens` <= 0  
  Status: ❌  
  Uzasadnienie: brak negatywnych testów kontraktowych.

## 4) Security (ACL + classification) — kontrakt i pokrycie

- ✅ Semantyka ACL (OR) i classification (AND) w `search_nodes`/`fetch_node_texts`  
  Status: ✅  
  Dowód: sekcja 5 w dokumentacji testów + integracyjne przypadki security.

- ❌ Security trimming w `expand_dependency_tree`  
  Status: ❌  
  Uzasadnienie: wymagane w kontrakcie i w dokumencie testów, brak testu w kodzie.

## 5) Hybrid/RRF — kontrakt i pokrycie

- ❌ RRF: `rrf_k`, deduplikacja, tie-breaki  
  Status: ❌  
  Uzasadnienie: testy integracyjne sprawdzają tylko markery w wynikach, nie algorytm RRF.

---

# Propozycje brakujących testów (min. zakres dla pełnej zgodności)

Poniższe testy domykają luki kontraktowe przy minimalnym nakładzie.
Każdy punkt zawiera sugerowane miejsce i typ testu.

## A) `search_nodes`

1. **Brak tekstu po `search_nodes`**  
   - Cel: upewnić się, że `search_nodes` nie materializuje tekstów ani `context_blocks`.  
   - Sugerowane miejsce: `tests/integration/retrival/test_search_and_fetch_expectations.py` (nowy test).  
   - Asercje: po `SearchNodesAction().execute(...)`: `state.node_texts == []` i `state.context_blocks == []`.

2. **Fail-fast na brak `top_k`**  
   - Cel: kontrakt wymaga `top_k` z kroku lub settings.  
   - Miejsce: `tests/pipeline/test_search_nodes_*.py` (test kontraktowy/unit).  
   - Oczekiwane: `RuntimeError`.

3. **Fail-fast na brak `repository` lub `snapshot_id`**  
   - Miejsce: testy kontraktowe w `tests/pipeline`.  
   - Oczekiwane: `RuntimeError` z czytelnym komunikatem.

4. **Rerank tylko dla `semantic`**  
   - Miejsce: `tests/pipeline/test_search_nodes_*.py`.  
   - Scenariusze: `search_type=bm25` + `rerank=keyword_rerank` => błąd; `semantic` + `rerank=keyword_rerank` => ok.

## B) `expand_dependency_tree`

5. **Security trimming w grafie**  
   - Cel: sprawdzenie, że ACL/classification filtrują węzły i krawędzie.  
   - Miejsce: `tests/integration/retrival/test_dependency_tree_expectations.py` (nowy case).  
   - Asercje: po ekspansji brak węzłów i krawędzi naruszających ACL/classification.

6. **Fail-fast na brak settings map** (`*_from_settings`)  
   - Miejsce: `tests/pipeline/test_expand_dependency_tree_*.py`.  
   - Oczekiwane: `RuntimeError`.

7. **`graph_debug` minimalny schema**  
   - Miejsce: `tests/integration/retrival/test_dependency_tree_expectations.py`.  
   - Asercje: obecność `seed_count`, `expanded_count`, `edges_count`, `truncated`, `reason`.

## C) `fetch_node_texts`

8. **Mutual exclusivity: `budget_tokens` + `max_chars`**  
   - Miejsce: `tests/pipeline/test_fetch_node_texts_action.py`.  
   - Oczekiwane: `RuntimeError`.

9. **Fail-fast na brak `max_context_tokens`**  
   - Miejsce: `tests/pipeline/test_fetch_node_texts_action.py`.  
   - Oczekiwane: `RuntimeError`.

10. **Minimalny schema `node_texts`**  
   - Miejsce: `tests/integration/retrival/test_fetch_node_texts_expectations.py`.  
   - Asercje: każde `node_texts[i]` ma `id`, `text`, `is_seed`, `depth`, `parent_id`.

## D) Hybrid RRF

11. **RRF algorytm (deduplikacja i tie-breaki)**  
   - Miejsce: `tests/pipeline/test_search_nodes_hybrid_rrf.py` (nowy test kontraktowy).  
   - Metoda: stub backend zwracający znane listy, asercja końcowej kolejności.

## E) Dodatkowe luki wskazane po review

12. **SnapshotSet / `snapshot_set_id` (rozwiązywanie i konflikty)**  
   - Cel: potwierdzić deterministyczne rozwiązywanie snapshotów i obsługę konfliktu `snapshot_id` vs `snapshot_set_id`.  
   - Miejsce: `tests/pipeline/test_search_nodes_snapshot_set.py` (nowy test kontraktowy).  
   - Scenariusze:  
     - tylko `snapshot_set_id` → resolve do konkretnego `snapshot_id`  
     - `snapshot_id` + `snapshot_set_id` niezgodne → fail-fast  
     - brak resolvable SnapshotSet → fail-fast

13. **Reranking (mechanizm) + `widen_factor`**  
   - Cel: upewnić się, że `semantic + rerank` pobiera `top_k * widen_factor` i zwraca tylko `top_k`.  
   - Miejsce: `tests/pipeline/test_search_nodes_rerank.py` (nowy test kontraktowy).  
   - Scenariusze:  
     - `semantic + keyword_rerank` → szerokie pobranie i przycięcie  
     - `bm25/hybrid + rerank` → fail-fast

14. **Deterministyczna kolejność tie-breaków w hybrid**  
   - Cel: potwierdzić dokładną kolejność: `score → semantic_rank → bm25_rank → ID`.  
   - Miejsce: `tests/pipeline/test_search_nodes_hybrid_rrf.py` (rozszerzenie testu z pkt 11).  
   - Scenariusze: kontrolowane listy z remisami na score.

15. **Edge-case’y `fetch_node_texts`**  
   - Cel: zachowanie w skrajnych warunkach budżetowych i danych.  
   - Miejsce: `tests/pipeline/test_fetch_node_texts_action.py` lub `tests/integration/retrival/test_fetch_node_texts_expectations.py`.  
   - Scenariusze:  
     - brak tekstu dla poprawnego ID → node pomijany / puste `text`? (zgodnie z kontraktem)  
     - wszystkie node’y za duże → `node_texts == []`  
     - bardzo dużo seedów + mały budżet → deterministyczne pomijanie

16. **Puste wejścia `expand_dependency_tree`**  
   - Cel: kontraktowy „reason” w `graph_debug` przy braku seedów.  
   - Miejsce: `tests/pipeline/test_expand_dependency_tree_empty.py` (nowy test kontraktowy).  
   - Oczekiwane: puste listy + `graph_debug.reason == "no_seeds"` (lub odpowiednik).

17. **Backend abstraction (brak bezpośredniego FAISS)**  
   - Cel: upewnić się, że akcje używają `runtime.retrieval_backend`.  
   - Miejsce: `tests/pipeline/test_backend_injection.py` (nowy test kontraktowy).  
   - Scenariusze: brak backendu → fail-fast; backend stub → poprawne wywołanie.

---

# Rekomendowana kolejność wdrożenia

1. Testy kontraktowe fail-fast (łatwe, stabilne).  
2. Security trimming w `expand_dependency_tree` (największa luka kontraktowa).  
3. Minimalne schema `node_texts` + `graph_debug`.  
4. Testy RRF (wymagają kontrolowanego backendu/stuba).

---

# Notatka o spójności dokumentów

`docs/tests/retrieval_integration_tests.md` jest spójny z kontraktem na poziomie **zachowania funkcjonalnego**, ale nie domyka wymagań **kontraktowych** (fail-fast, brak tekstów w `search_nodes`, security trimming w grafie, schematy outputu, RRF).
Ten dokument służy jako mapa braków, aby podnieść poziom zgodności do 100%.
