# Budget Contract (Pipeline + Model Limits)

Ten dokument opisuje **kontrakt budżetów tokenów** pomiędzy:
- konfiguracją modelu (`config.json`),
- ustawieniami pipeline (`pipelines/*.yaml` → `settings`),
- krokami `call_model` (limity generacji per-step),
- mechanizmem kontekstu/retrieval (`max_context_tokens`, `manage_context_budget`),
- historią rozmowy (`max_history_tokens`).

Cel: **nie dopuszczać** do sytuacji, gdzie model dostaje prompt, dla którego `prompt_tokens + max_output_tokens > model_context_window`, co skutkuje błędem typu:
`Requested tokens (...) exceed context window (...)`.

---

## Słownik pojęć

- `model_context_window` (okno kontekstu, `n_ctx`)  
  Maksymalna liczba tokenów, którą model jest w stanie obsłużyć łącznie: **prompt + generacja**.
  Źródło: `config.json["model_context_window"]`.

- `max_output_tokens` (limit generacji dla kroku `call_model`)  
  Maksymalna długość odpowiedzi modelu dla danego kroku.
  Źródła (pierwszeństwo):
  1) YAML step: `max_output_tokens`
  2) YAML step: `max_tokens`
  3) fallback: `config.json["model_max_tokens"]` (domyślny output, jeśli step nie ustawia limitu)

- `max_context_tokens` (limit kontekstu w pipeline)  
  Globalny limit tokenów dla kontekstu (`state.context_blocks`) używany przez retrieval/budget.
  Źródło: pipeline `settings.max_context_tokens`.

- `max_history_tokens` (limit historii)  
  Maksymalna liczba tokenów przeznaczona na historię (`state.history_dialog`) w krokach `call_model` z `use_history: true`.
  Źródło: pipeline `settings.max_history_tokens`.

- `budget_safety_margin_tokens`  
  Zapas bezpieczeństwa w tokenach, odejmowany od budżetu (na narzuty formatowania i niepewności).
  Źródło: pipeline `settings.budget_safety_margin_tokens` (domyślnie 128).

---

## Kontrakt budżetowy (nierówność)

Dla każdego kroku `call_model` ma zachodzić (w przybliżeniu):

`fixed_prompt_tokens(step) + max_history_tokens + max_context_tokens + max_output_tokens(step) + safety_margin <= model_context_window`

Gdzie:
- `fixed_prompt_tokens(step)` to koszt:
  - system prompt (`prompt_key`),
  - *same wrappery* z `user_parts.template` (liczone jako template z pustą `{}`),
  - plus konserwatywny narzut na format (`[INST]`, separatory, role).

Uwaga: retrieval (`state.node_texts`) **nie jest osobnym składnikiem** — po `manage_context_budget` trafia do `state.context_blocks`, więc realnie w prompt idzie `context_blocks` (do limitu `max_context_tokens`).

---

## Polityka środowiskowa (dev/prod)

Serwer rozróżnia tryb dev/prod tą samą flagą co endpointy deweloperskie:
- `config.json["developement"]` / `["development"]` oraz/lub `APP_DEVELOPMENT`.

Na tej podstawie ustawiana jest polityka:
- **dev**: `fail_fast`
- **prod**: `auto_clamp`

Możesz wymusić zachowanie przez ENV:
- `PIPELINE_LIMITS_POLICY=fail_fast|auto_clamp`

---

## Co jest walidowane / korygowane

### 1) Walidacja (zawsze)
- wymagane: `settings.max_context_tokens` (int > 0)
- wymagane: `model_context_window` (int > 0)
- `settings.max_history_tokens` (int >= 0) — jeśli pipeline używa historii

Jeśli jakikolwiek krok `call_model` ma `use_history: true` i `max_history_tokens` jest brak/0:
- `fail_fast`: błąd (pipeline misconfigured)
- `auto_clamp`: warning + historia jest w praktyce obcinana do 0 (brak historii)

### 2) Auto-clamp (tylko w `auto_clamp`)
Korekty są **in-memory** (na czas jednego requestu), bez zapisu do YAML.

Możliwe clampy:
- `settings.max_context_tokens` (globalnie, w dół), jeśli nie mieści się w oknie kontekstu w najgorszym kroku `call_model`.
- per-step `call_model.max_output_tokens` (w dół), jeśli dla konkretnego kroku nadal jest konflikt budżetów.

Każdy clamp generuje **warning** w `app.log` z powodem i wartościami przed/po.

---

## Cache (wydajność)

Budżety są liczone “ciężej” tylko wtedy, gdy zmieni się którykolwiek plik wejściowy.

Fingerprint (mtime) uwzględnia:
- plik YAML pipeline + wszystkie pliki z `extends` (łańcuch),
- pliki promptów używane przez `call_model` w tym pipeline (`prompts_dir/<prompt_key>.txt`).

Jeśli mtime się nie zmienia, serwer używa cache i nie liczy ponownie rezerw promptów.

---

## Historia — trimming runtime

Jeżeli krok `call_model` ma `use_history: true` i pipeline ma `settings.max_history_tokens`,
to `call_model` obcina `state.history_dialog` (od najstarszych) do tego budżetu tokenów.

Trim jest widoczny w trace (`history_trim`) przy `call_model.log_out`.

---

## Rekomendacje konfiguracji (praktyczne)

1) Ustal realne `model_context_window` (np. 9600, 16384) w `config.json`.
2) Dla pipeline ustaw:
   - `max_context_tokens` na poziomie ~60–70% `model_context_window`,
   - `max_history_tokens` na poziomie ~10–15%,
   - `max_output_tokens` per-step (router małe, answer/summarizer większe),
   - `budget_safety_margin_tokens` np. 128–256.
3) W dev trzymaj `fail_fast`, w prod `auto_clamp` + monitoring warningów.

