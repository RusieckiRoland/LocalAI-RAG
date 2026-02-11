# Serwis Historii Konwersacji — Kontrakt (PL)

## Cel
Zapewnić profesjonalny i skalowalny mechanizm zapisu oraz odtwarzania historii rozmów w dwóch zakresach:

1) **Historia sesji (ulotna)** — zawsze dostępna poprzez `session_id` i zapisywana w Redis (lub mocku w pamięci).
2) **Historia użytkownika (trwała)** — dostępna dla użytkowników zalogowanych poprzez `identity_id` i zapisywana w bazie SQL.

System musi zachować parowanie języków i mapowanie tożsamości:
- `session_id` jest zawsze obecne.
- Język neutralny to **angielski**:
  - `question_en` (neutralne)
  - `answer_en` (neutralne)
- Jeżeli jest tłumaczenie i/lub użytkownik podał treść w języku narodowym (polski):
  - `question_pl` (opcjonalne)
  - `answer_pl` (opcjonalne)
- Dla użytkowników zalogowanych:
  - `identity_id` musi być powiązane z `session_id`.

## Poza zakresem (na teraz)
- API/UI do przeglądania historii z SQL.
- Wyszukiwanie semantyczne po historii (możliwe w przyszłości).
- Zapisywanie do historii: fragmentów retrieval, routingów, iteracji, promptów i diagnostyki.

## Model danych

### Turn (rekord kanoniczny)
Każde pytanie użytkownika tworzy dokładnie jeden **turn**:
- `turn_id` (UUID)
- `session_id` (string, wymagane)
- `identity_id` (string, opcjonalne; z Identity Provider)
- `request_id` (string, wymagane; klucz idempotencji per HTTP request)
- `created_at`, `finalized_at`
- `pipeline_name`, `consultant`, `repository` (opcjonalne metadane)
- `translate_chat` (bool)
- `question_en` (string, wymagane)
- `answer_en` (string, wymagane po finalizacji)
- `question_pl` (string, opcjonalne)
- `answer_pl` (string, opcjonalne)
- `answer_pl_is_fallback` (bool, opcjonalne; true jeśli `answer_pl` nie jest tłumaczeniem, tylko kopią EN)
- `metadata` (obiekt; rekomendowane jako JSONB w SQL)
- `record_version` (int, opcjonalne)
- `replaced_by_turn_id` (UUID, opcjonalne)
- `deleted_at` (timestamp, opcjonalne; soft-delete / redaction)

**Inwarianty**
- `session_id` jest wymagane zawsze.
- `request_id` musi być unikalne w obrębie sesji:
  - unikalność po `(session_id, request_id)` w magazynie sesyjnym
  - dla zapisu trwałego: unikalność po `(identity_id, session_id, request_id)`
- `question_en` musi być zawsze zapisane (neutralne EN).
- `answer_en` musi być zawsze zapisane dla zfinalizowanych turnów.
- Dla użytkowników zalogowanych: zapisujemy `identity_id` i wiążemy je z `session_id`.
- Jeśli tłumaczenie nie zachodzi, `question_pl` / `answer_pl` mogą być puste.
- Jeśli `translate_chat=true`, to `answer_pl` powinno być obecne; jeśli nie, system powinien ustawić `answer_pl_is_fallback=true` przy fallbacku.

**Reguły wytwarzania języka neutralnego (EN)**
- `question_en` musi powstać na starcie requestu.
- Jeśli tłumaczenie do EN nie jest dostępne lub się nie powiedzie:
  - zapisz oryginalny tekst pytania w `question_en` (fallback copy), oraz
  - odnotuj fallback w `metadata` (np. `question_en_is_fallback=true`).

**request_id vs turn_id (idempotentny start)**
- `request_id` to klucz idempotencji; `turn_id` to kanoniczny identyfikator rekordu.
- `start_turn` musi być idempotentne:
  - dla tego samego `(session_id, request_id)` MUSI zwrócić to samo `turn_id` (nie może rzucać błędem duplikatu).

## Architektura składowania

### A) Magazyn sesji (Redis / mock) — szybki + ulotny
Cel:
- dostarczanie „ostatnich Q/A” do wstrzykiwania historii do promptu
- działanie w oknie życia sesji

Cechy:
- kluczowanie przez `session_id`
- retencja TTL (konfigurowalna)
- zoptymalizowane na dopisywanie i pobranie ostatnich N turnów
- konieczny limit liczby turnów na sesję (anti-spam / ograniczenie pamięci)

**Rekomendacja TTL**
- TTL musi być konfigurowalny i **dłuższy niż najdłuższa sensowna sesja użytkownika**.
- Typowe wartości produkcyjne to **30 minut – 7 dni** (zależnie od UX).
- Rozsądny domyślny wybór to **24 godziny** + twardy limit liczby turnów.

**Anti-spam / kontrola rozmiaru (rekomendowane)**
- Przechowuj tylko ostatnie **N turnów** na sesję (np. `N=200..500`) i usuwaj najstarsze przy dopisywaniu.
- Twardy limit jest egzekwowany przy każdym dopisaniu; TTL wygasza cały klucz sesji dopiero później.
- Opcjonalnie rate-limit po `session_id` / `identity_id` po stronie serwera.

### B) Magazyn trwały (SQL) — źródło prawdy dla użytkowników zalogowanych
Cel:
- trwały zapis i możliwość pełnego odtworzenia
- audyt, zgodność, przyszłe raportowanie

Cechy:
- kluczowanie przez `identity_id` + indeksy po `session_id` i czasie
- zapis kanonicznych rekordów Turn (EN zawsze; PL opcjonalnie)
- przechowywanie `metadata` jako JSONB dla audytu (hash IP, user-agent, kanał, itd.)

**Bezpieczeństwo metadata (rekomendowane)**
- Nie zapisuj surowych danych PII w `metadata` (np. IP). Preferuj hashe (np. `ip_hash`) i allowlistę kluczy.
- Nie zapisuj pełnych promptów, chunksów retrieval ani payloadów trace w historii.

### C) ConversationHistoryService — orkiestrator
Jedna instancja po stronie serwera, odpowiedzialna za zapis do:
- Redis dla każdego requestu (zakres sesji)
- SQL dodatkowo, jeśli jest `identity_id`

Serwis odpowiada też za powiązanie:
- `session_id` ⇔ `identity_id`

## Kontrakty (porty / interfejsy)

### 1) Magazyn historii sesji (ulotny)
`ISessionConversationStore`
- `start_turn(*, session_id: str, request_id: str, identity_id: str | None, question_en: str, question_pl: str | None, meta: dict) -> str turn_id`
- `finalize_turn(*, session_id: str, turn_id: str, answer_en: str, answer_pl: str | None, answer_pl_is_fallback: bool | None, meta: dict) -> None`
- `get_recent_turns_en(*, session_id: str, limit: int, finalized_only: bool = True) -> list[dict{turn_id, question_en, answer_en}]`
- `get_session_meta(*, session_id: str) -> dict`
- `set_session_meta(*, session_id: str, identity_id: str | None, meta: dict) -> None`

Rekomendacja implementacyjna:
- Redis lista/stream per sesja (lepsze) zamiast przepisywania jednego dużego JSON-a przy każdej zmianie.
- `finalize_turn` musi być idempotentne: powtórne wywołania dla `(session_id, turn_id)` nie mogą psuć danych.

**Semantyka finalized_only**
- Gdy `finalized_only=True`, zwracaj tylko turny, w których `answer_en` jest obecne (zfinalizowane).

**Finalizacja bez startu**
- Jeśli finalizacja zostanie wywołana dla nieistniejącego `(session_id, turn_id)`, system MUSI fail-fast i zalogować błąd
  (to oznacza bug/race/restart; nie należy tworzyć „ghost turnów” po cichu).

### 2) Magazyn historii użytkownika (trwały)
`IUserConversationStore`
- `upsert_session_link(*, identity_id: str, session_id: str) -> None`
- `insert_turn(*, turn: Turn) -> None`
- `upsert_turn_final(*, identity_id: str, session_id: str, turn_id: str, answer_en: str, answer_pl: str | None, answer_pl_is_fallback: bool | None, finalized_at: str | None, meta: dict | None) -> None`

Uwagi:
- Zapisy powinny być idempotentne po kluczach naturalnych (np. `(identity_id, session_id, turn_id)`).
- Preferuj semantykę upsert przy finalizacji, żeby bezpiecznie obsłużyć retry/race-condition.
- `finalized_at` traktuj jako UTC i najlepiej ustawiaj po stronie storage (autorytatywne timestampy).
- Zfinalizowany turn powinien już istnieć (utworzony przez `insert_turn`); `upsert_turn_final` aktualizuje pola końcowe.

### 3) ConversationHistoryService (serwis serwerowy)
`IConversationHistoryService`
- `on_request_started(...) -> turn_id`
  - wywoływane raz na HTTP request przed uruchomieniem pipeline
  - zapisuje `question_en` (oraz `question_pl` jeśli jest)
  - zapewnia powiązanie `session_id ⇔ identity_id` dla zalogowanych
- `on_request_finalized(...) -> None`
  - wywoływane w `finalize`, gdy `final_answer` jest znane
  - zapisuje `answer_en` oraz opcjonalnie `answer_pl`

**Forwardowanie metadanych (rekomendowane)**
- `IConversationHistoryService` powinien forwardować do SQL `metadata` tylko allowlistowane klucze z `meta` (np. `channel`, `device_type`, `ip_hash`).
- Pozostałe klucze traktuj jako efemeryczne i domyślnie nie zapisuj ich w SQL.

## Strategia merge sesji (anonimowy → zalogowany)
System musi obsłużyć typowy scenariusz:
użytkownik anonimowy zaczyna rozmowę → loguje się → kontynuuje w tej samej sesji przeglądarki.

Rekomendowane zachowanie:
- Zachować ten sam `session_id` i zacząć dopinać `identity_id`, gdy jest dostępne.
- Przy pierwszym zalogowanym requeście dla `session_id`, które wcześniej nie miało tożsamości:
  - wykonać `upsert_session_link(identity_id, session_id)`
  - opcjonalnie (best-effort) przenieść ostatnie N turnów z Redis do SQL jako turny użytkownika
    (insert idempotentny po `(identity_id, session_id, turn_id)`).
  - Backfill powinien zachować chronologię (wg `created_at` lub kolejności przechowywanej w Redis).

Sesje porzucone:
- Sesje bez `identity_id` są normalne i powinny wygasać przez TTL w Redis.

**Reguła konfliktu (wymagana)**
- Jeśli `session_id` jest już powiązane z `identity_id`, to próba powiązania z *innym* `identity_id` musi zostać odrzucona i zalogowana
  (bezpieczeństwo/audyt).

## Punkty integracji z pipeline

### Gdzie zapisujemy historię
1) **Start requestu (warstwa serwera)**:
   - Utworzenie turnu i zapis `question_en` (oraz `question_pl` jeśli dostępne).
   - Umieszczenie `turn_id` w stanie pipeline, aby `finalize` zaktualizowało ten sam turn.

2) **Akcja finalize**:
   - Wywołanie serwisu historii z `answer_en` i `answer_pl` (jeżeli jest).

### Gdzie odczytujemy historię
`load_conversation_history` powinno ładować **pary Q/A po angielsku** (język neutralny) do stanu pipeline:
- `Dict(question_en, answer_en)` lub lista takich dictów.
- Warstwa budowania promptu decyduje o formacie renderowania.

## Aktualizacje rekordu / redakcja
- `record_version` / `replaced_by_turn_id` pozwalają na korekty bez utraty śladu audytowego.
- `deleted_at` oznacza rekord jako zredagowany/soft-deleted:
  - nie powinien trafiać do odczytu historii dla promptów,
  - przyszłe odczyty historii dla użytkownika powinny domyślnie pomijać rekordy z `deleted_at`.
  - magazyn sesji też powinien respektować redakcję (usunąć albo oznaczyć tombstonem, żeby prompt nie widział danych do TTL).

**Polityka redakcji (rekomendowane)**
- Preferuj redakcję w stylu tombstone:
  - zachowaj identyfikatory i timestampy,
  - wyczyść pola tekstowe (`question_*`, `answer_*`) lub zastąp je stałym placeholderem,
  - `deleted_at` jest autorytatywnym markerem redakcji.

## Rekomendacja dot. Weaviate (przechowywanie historii)

### Czy Weaviate może być główną bazą historii?
Nie rekomenduję jako źródła prawdy.
- Historia rozmów to dane transakcyjne/audytowe: spójność, kolejność, retencja, filtrowanie per user i zgodność są domeną SQL.
- „Najpierw zapis do Weaviate, potem eksport do SQL” robi z Weaviate źródło prawdy i komplikuje system (reconciliation, idempotencja, ryzyko utraty).

### Do czego Weaviate pasuje bardzo dobrze
Jako **wtórny indeks semantyczny** (opcjonalny):
- semantyczne wyszukiwanie po turnach
- podobieństwo pytań/odpowiedzi („czy już na to odpowiadaliśmy?”)

Preferowany przepływ danych:
- **SQL jako źródło prawdy**
- asynchroniczne indeksowanie do Weaviate dla szybkiego retrieval
- Weaviate traktujemy jako odbudowywalne z SQL

## Elastyczność na przyszłość
Ten kontrakt zakłada łatwą rozbudowę bez zmiany logiki zapisu:
- API do przeglądania historii (odczyt z SQL)
- replay sesji
- semantyczny retrieval historii (Weaviate)
- analityka i polityki retencji
- streszczenia konwersacji (np. `summary_en`, `summary_pl`) dla ograniczenia tokenów w długich sesjach
