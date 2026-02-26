# Flagi i tryby uruchomieniowe (`prod` / `dev` / `test`)

Dokument opisuje, które **flagi/parametry** sterują zachowaniem aplikacji LocalAI‑RAG, skąd są wczytywane (ENV vs `config*.json`) i jak różnią się w profilach `prod|dev|test`.

Stan na: **2026-02-26**.

---

## 1) Wybór profilu i pliku konfiguracyjnego

### `APP_PROFILE` (ENV)
- Dozwolone: `prod`, `dev`, `test` (dodatkowo aliasy: `production`→`prod`, `development`→`dev`).
- Domyślnie: `prod` (gdy zmienna nie jest ustawiona).
- Wpływ:
  - wybór domyślnego pliku `config.<profile>.json` (jeżeli istnieje),
  - blokada niebezpiecznych ustawień (np. `DEV_ALLOW_NO_AUTH=true` jest zabronione w `prod`).

### `APP_CONFIG_PATH` (ENV)
- Nadpisuje ścieżkę do pliku konfiguracyjnego runtime (zamiast `config.json` / `config.<profile>.json`).
- Może być ścieżką absolutną albo relatywną do katalogu projektu.

### `--env` (flaga CLI w `start_AI_server.py`)
- Jeżeli podasz `--env`, skrypt próbuje załadować `.env` z katalogu projektu do `os.environ`.
- To tylko “helper” do ENV; nie zastępuje `config*.json`.

---

## 2) “Development mode” niezależnie od profilu

### `development` (w `config*.json`) + `APP_DEVELOPMENT` (ENV override)
- Cel: przełączać zachowania “dev/debug” niezależnie od tego czy `APP_PROFILE=dev|prod|test`.
- Efekty (w backendzie):
  - Flask `debug` jest włączony tylko gdy `APP_PROFILE != prod` **i** `development == true`.
  - domyślna polityka limitów pipeline:
    - gdy `development=true` → `fail_fast`
    - gdy `development=false` → `auto_clamp`
  - walidacje security/Weaviate są bardziej “strict” poza development (częściej `raise` zamiast `warning`).

Uwaga: `APP_DEVELOPMENT` ma pierwszeństwo nad `development` z configu.

---

## 3) Auth / bezpieczeństwo (API + UI)

### `API_TOKEN` (ENV)
- Wymusza prostą autoryzację API: nagłówek `Authorization: Bearer <API_TOKEN>`.
- Używane, gdy nie jest aktywne OIDC “resource server” (patrz niżej).

### `auth.oidc.resource_server.*` (w `config*.json`) + `IDP_AUTH_ENABLED` (ENV override)
- Cel: walidacja JWT dla API (po stronie backendu) po JWKS.
- Klucze:
  - `auth.oidc.issuer`
  - `auth.oidc.resource_server.enabled`
  - `auth.oidc.resource_server.jwks_url`
  - `auth.oidc.resource_server.audience`
  - `auth.oidc.resource_server.algorithms`
  - `auth.oidc.resource_server.required_claims`
- `IDP_AUTH_ENABLED` może wymusić `enabled=true/false` niezależnie od configu.
- Zachowanie:
  - gdy “resource server” jest aktywny i kompletny → backend waliduje JWT,
  - gdy nieaktywny → backend używa `API_TOKEN`.

### `auth.oidc.client.*` (w `config*.json`)
- Cel: konfiguracja logowania w UI (Authorization Code + PKCE).
- To jest publikowane do frontendu jako publiczny bootstrap config (nie są tu trzymane sekrety).

### `DEV_ALLOW_NO_AUTH` (ENV; tylko `dev/test`)
- Cel: tryb developerski ułatwiający testowanie UI.
- Ograniczenia:
  - **zabronione** w `APP_PROFILE=prod` (aplikacja przerwie start).
  - nie oznacza “no auth”; backend nadal wymaga nagłówka:
    - `Authorization: Bearer dev-user:<id>`
    - gdzie `<id>` musi istnieć w `fake_users` w configu (`config.dev.json` / `config.test.json`).

---

## 4) Weaviate

### `weaviate.host/http_port/grpc_port` (w `config*.json`) + override’y w ENV
- Cel: adres/porty połączenia do Weaviate.
- ENV override’y:
  - `WEAVIATE_HOST`, `WEAVIATE_HTTP_PORT`, `WEAVIATE_GRPC_PORT`
  - `WEAVIATE_API_KEY` (sekret)
  - `WEAVIATE_CONFIG_PATH` (alternatywny plik config tylko dla klienta Weaviate)

### `WEAVIATE_SKIP_INIT` (ENV)
- Gdy `true`, backend nie inicjalizuje klienta Weaviate (tryb zdegradowany, użyteczne w testach).
- Automatycznie jest też pomijane w trakcie uruchamiania testów (gdy ustawione `PYTEST_CURRENT_TEST`).

---

## 5) Pipeline / debugowanie

### Tracing (ENV)
- `RAG_PIPELINE_TRACE=1` → włącza trace eventów pipeline.
- `RAG_PIPELINE_TRACE_FILE=1` → zapisuje pliki trace per zapytanie.
- `RAG_PIPELINE_TRACE_DIR=<path>` → katalog docelowy trace.

### Limity pipeline (ENV)
- `PIPELINE_LIMITS_POLICY`:
  - typowo `fail_fast` (dev) lub `auto_clamp` (prod),
  - wartość z ENV ma pierwszeństwo.

### Callback / widoczność etapów (w `config*.json`, oraz per‑pipeline w `pipelines/*.yaml`)
- `callback`: `allowed` / `forbidden` / `pipeline_decision`
- `callback_content`: np. `["all"]` lub tryby ograniczające dokumenty
- `stages_visibility`: `allowed` / `forbidden` / `pipeline_driven` / `explicit`

### `snapshot_policy` (w `config*.json`)
- Cel: polityka wyboru snapshotu w UI.
- Przykładowe wartości spotykane w UI: `single`, `multi_confirm`.

---

## 6) Modele / routing LLM

### Lokalny model (w `config*.json`)
- `enable_model_path_analysis`:
  - `true` → backend inicjalizuje model lokalny z `model_path_analysis`
  - `false` → model lokalny wyłączony
- `model_path_analysis`, `model_max_tokens`, `model_context_window`, `use_gpu`
- `model_n_gpu_layers` / `n_gpu_layers` (opcjonalne): liczba warstw offloadowanych na GPU

### Serwer LLM (w `config*.json` + `ServersLLM.json`)
- `serverLLM=true` → backend używa/ładuje `ServersLLM.json`.
- Serwery mogą mieć klucze bezpieczeństwa (np. `allowed_doc_level`, `allowed_*_labels`) i throttling.
- Wpis `api_key` w `ServersLLM.json` wspiera podstawianie z ENV (format `${ENV_NAME}`).

---

## 7) Języki / UI

### Przełączanie języka (w `config*.json`)
- `is_multilingual_project` – czy UI i chat są “dwujęzyczne”
- `neutral_language`, `translated_language` – kody języków (np. `en`, `pl`)

### Grupy historii (w `config*.json`)
- `history_groups` – definicje filtrów czasu (np. today, last 7 days)
- `history_important` – konfiguracja sekcji “ważne” (UI)

---

## 8) Matryca: profil → domyślne zachowanie

| Obszar | `dev` | `test` | `prod` |
|---|---|---|---|
| Domyślny config | `config.dev.json` (jeśli istnieje) | `config.test.json` (jeśli istnieje) | `config.prod.json` (jeśli istnieje) |
| `DEV_ALLOW_NO_AUTH` | dozwolone | dozwolone | **zabronione** |
| Flask `debug` | zależy od `development` | zależy od `development` | wyłączone (profil) |
| Walidacje security | mniej “strict” gdy `development=true` | mniej “strict” gdy `development=true` | bardziej “strict” (gdy `development=false`) |
| Polityka limitów pipeline (domyślna) | `fail_fast` gdy `development=true` | `fail_fast` gdy `development=true` | `auto_clamp` gdy `development=false` |

---

## 9) Zmienne z `.env.example`, które obecnie nie zmieniają zachowania (stan na 2026-02-26)

- `APP_SECRET_KEY` – nieużywane przez backend (brak konfiguracji `app.secret_key`).
- `APP_HOST` / `APP_PORT` – `start_AI_server.py` uruchamia serwer na `0.0.0.0:5000` (stałe wartości).

## 10) Domyślna metoda wyszukiwania (pipeline)

Jeżeli krok `search_nodes` ma `search_type: auto`, to backend musi wybrać konkretny tryb (`semantic|bm25|hybrid`).
Gdy router/prefix nie poda jawnego `search_type`, można ustawić default na poziomie pipeline:

- `pipeline.settings.default_search_method: semantic|bm25|hybrid`
- legacy alias (literówka wspierana w kodzie): `pipeline.settings.default_serach_method`

Opcjonalnie można też ustawić default per‑step:
- `step.default_search_type` albo `step.default_search_method`
