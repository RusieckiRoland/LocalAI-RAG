// English comments only.

const http = require("http");
const fs = require("fs");
const path = require("path");
const url = require("url");
const crypto = require("crypto");
const zlib = require("zlib");

const PORT = parseInt(process.env.PORT || "8081", 10);

const UI_FILE = path.join(__dirname, "page.html");

// Default PlantUML server (official). You can override with env var if needed.
const PLANTUML_SERVER = String(process.env.PLANTUML_SERVER || "https://www.plantuml.com/plantuml").replace(/\/+$/, "");

// In-memory chat history store (lifetime of this process).
const chatHistory = {
  sessions: new Map(), // sessionId -> session
  messages: new Map(), // sessionId -> [messages]
};

function setCors(res) {
  // Allow file:// origin ("null") and normal http origins.
  // Using "*" is enough for this mock (no credentials).
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type,X-Session-ID");
}

function sendJson(res, status, obj) {
  setCors(res);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(obj, null, 2));
}

function sendText(res, status, text) {
  setCors(res);
  res.writeHead(status, { "Content-Type": "text/plain; charset=utf-8" });
  res.end(text);
}

function sendHtml(res, status, html) {
  setCors(res);
  res.writeHead(status, { "Content-Type": "text/html; charset=utf-8" });
  res.end(html);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => {
      data += chunk;
      if (data.length > 2_000_000) {
        reject(new Error("Payload too large"));
        req.destroy();
      }
    });
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

function getSessionId(req) {
  const sid = (req.headers["x-session-id"] || "").toString().trim();
  if (sid) return sid;
  return randomId();
}

function runIdFromPayload(payload) {
  const enabled = !!(payload && (payload.enableTrace || payload.enable_trace));
  if (!enabled) return null;
  const provided = safeStr(payload && (payload.pipeline_run_id || payload.run_id)).trim();
  if (provided) return provided;
  const ts = Date.now();
  const rand = randomId().slice(0, 8);
  return `${ts}_mock_${rand}`;
}

function safeStr(v) {
  return (v == null) ? "" : String(v);
}

function pickRandom(arr) {
  if (!arr || arr.length === 0) return null;
  const idx = Math.floor(Math.random() * arr.length);
  return arr[idx];
}

function randomId() {
  // crypto.randomUUID is not available in older Node versions (e.g. 12).
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  try {
    return crypto.randomBytes(16).toString("hex");
  } catch (e) {
    // Last-resort fallback.
    return String(Date.now()) + "_" + String(Math.floor(Math.random() * 1e9));
  }
}

function nowTs() {
  return Date.now();
}

function getAuthUser(req) {
  const auth = String(req.headers["authorization"] || "");
  const match = auth.match(/^Bearer\\s+dev-user:([^\\s]+)$/i);
  return match ? match[1] : "anon";
}

function getTenantId(req) {
  // Simple mock: single-tenant unless header provided.
  return String(req.headers["x-tenant-id"] || "tenant-default");
}

function listSessions({ tenantId, userId, limit, cursor, q }) {
  const all = Array.from(chatHistory.sessions.values())
    .filter(s => s.tenantId === tenantId && s.userId === userId && !s.deletedAt && !s.softDeletedAt)
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));

  const filtered = q
    ? all.filter(s => (s.title || "").toLowerCase().includes(q.toLowerCase()))
    : all;

  let startIdx = 0;
  if (cursor) {
    const idx = filtered.findIndex(s => String(s.updatedAt) === String(cursor));
    startIdx = idx >= 0 ? idx + 1 : 0;
  }

  const items = filtered.slice(startIdx, startIdx + limit);
  const next = items.length === limit ? String(items[items.length - 1].updatedAt) : null;
  return { items, next_cursor: next };
}

function buildAppConfig() {
  return {
    contractVersion: "1.0",
    defaultConsultantId: "rejewski",
    isMultilingualProject: true,
    neutralLanguage: "en",
    translatedLanguage: "pl",
    snapshotPolicy: "single",
    historyGroups: [
      {
        neutral_description: "today",
        translated_description: "dzisiaj",
        formula: { type: "today" }
      },
      {
        neutral_description: "last week",
        translated_description: "ostatni tydzień",
        formula: { type: "last_n_days", days: 7 }
      }
    ],
    historyImportant: {
      neutral_description: "important",
      translated_description: "ważne",
      show_important_on_the_top: true
    },
    consultants: [
      {
        id: "rejewski",
        pipelineName: "rejewski",
        snapshotPickerMode: "single",
        snapshotSetId: "nopCommerce_4-60_4-90",
        snapshots: [
          { id: "48440Ahh", label: "release-4.60.0" },
          { id: "585959595", label: "release-4.90.0" }
        ],
        icon: "🧠",
        displayName: "Marian Rejewski",
        cardDescription: { pl: "Analiza kodu", en: "Code analysis" },
        welcomeTemplate: {
          pl: "Zapytaj {link}, mistrza w analizie kodu.",
          en: "Ask {link}, the master of code analysis."
        },
        welcomeLinkText: { pl: "Mariana Rejewskiego", en: "Marian Rejewski" },
        wikiUrl: {
          pl: "https://pl.wikipedia.org/wiki/Marian_Rejewski",
          en: "https://en.wikipedia.org/wiki/Marian_Rejewski"
        }
      },
      {
        id: "ada",
        pipelineName: "ada",
        snapshotPickerMode: "none",
        snapshotSetId: "",
        snapshots: [],
        icon: "📐",
        displayName: "Ada Lovelace",
        cardDescription: { pl: "Diagramy UML", en: "UML diagrams" },
        welcomeTemplate: {
          pl: "Zapytaj {link}, mistrzynię diagramów i wizualizacji.",
          en: "Ask {link}, the master of diagrams and visualization."
        },
        welcomeLinkText: { pl: "Adę Lovelace", en: "Ada Lovelace" },
        wikiUrl: {
          pl: "https://pl.wikipedia.org/wiki/Ada_Lovelace",
          en: "https://en.wikipedia.org/wiki/Ada_Lovelace"
        }
      },
      {
        id: "shannon",
        pipelineName: "shannon",
        snapshotPickerMode: "compare",
        snapshotSetId: "fakeSnapSet",
        snapshots: [
          { id: "aaa111", label: "fake-4.60.0" },
          { id: "bbb222", label: "fake-4.90.0" }
        ],
        icon: "🔀",
        displayName: "Claude Shannon",
        cardDescription: { pl: "Porównywanie wersji", en: "Version comparison" },
        welcomeTemplate: {
          pl: "Zapytaj {link} o porównanie wersji i różnice.",
          en: "Ask {link} to compare versions and differences."
        },
        welcomeLinkText: { pl: "Claude’a Shannona", en: "Claude Shannon" },
        wikiUrl: {
          pl: "https://pl.wikipedia.org/wiki/Claude_Shannon",
          en: "https://en.wikipedia.org/wiki/Claude_Shannon"
        }
      },
      {
        id: "chuck",
        pipelineName: "chuck",
        snapshotPickerMode: "none",
        snapshotSetId: "",
        snapshots: [],
        icon: "🥋",
        displayName: "Chuck Norris",
        cardDescription: { pl: "Wsparcie IT i kodowania", en: "IT and coding support" },
        welcomeTemplate: {
          pl: "Zapytaj {link} o analizę IT, kod i architekturę.",
          en: "Ask {link} about IT analysis, code, and architecture."
        },
        welcomeLinkText: { pl: "Chucka Norrisa", en: "Chuck Norris" },
        wikiUrl: {
          pl: "https://pl.wikipedia.org/wiki/Chuck_Norris",
          en: "https://en.wikipedia.org/wiki/Chuck_Norris"
        }
      }
    ]
  };
}

// PlantUML encoding helpers (deflate raw + PlantUML alphabet).
function encodePlantUml(text) {
  const utf8 = Buffer.from(String(text), "utf8");
  const deflatedRaw = zlib.deflateRawSync(utf8, { level: 9 });
  return encodePlantUmlBase64(deflatedRaw);
}

function encodePlantUmlBase64(buf) {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_";
  let res = "";
  let current = 0;
  let bits = 0;

  for (const b of buf) {
    current = (current << 8) | b;
    bits += 8;
    while (bits >= 6) {
      bits -= 6;
      res += alphabet[(current >> bits) & 0x3f];
    }
  }

  if (bits > 0) {
    res += alphabet[(current << (6 - bits)) & 0x3f];
  }

  return res;
}

function findFirstPlantUmlDiagram(markdown) {
  const s = String(markdown || "");
  const re = /@startuml[\s\S]*?@enduml/i;
  const m = s.match(re);
  return m ? m[0] : null;
}

function appendDiagramLink(markdown, translateChat) {
  const diagram = findFirstPlantUmlDiagram(markdown);
  if (!diagram) return markdown;

  const encoded = encodePlantUml(diagram);
  const renderUrl = PLANTUML_SERVER + "/uml/" + encoded;

  const isPl = !!translateChat;
  const linkText = isPl ? "Otwórz diagram UML" : "Open UML diagram";
  const linkTitle = isPl ? "Otwiera się w nowej karcie" : "Opens in a new tab";

  const a =
    '<a href="' + renderUrl + '" target="_blank" rel="noopener noreferrer" ' +
    'title="' + linkTitle + '" ' +
    'style="color:#2563eb;text-decoration:underline;text-underline-offset:3px;">' +
    "📎 " + linkText + "</a>";

  return markdown + "\n\n" + a;
}

function buildMockMarkdownResponse(ctx) {
  const isPl = !!ctx.translateChat;
  const consultantId = String(ctx.consultant || "").toLowerCase();

  const baseHeader = isPl
    ? [
        "# Mock analiza (Node)",
        "",
        "**Konsultant:** `" + safeStr(ctx.consultant) + "`  ",
        "**Version A:** `" + safeStr(ctx.snapshotA) + "`  ",
        "**Version B:** `" + safeStr(ctx.snapshotB) + "`",
        "",
        "**Pytanie użytkownika (wejście):**",
        "```",
        safeStr(ctx.query),
        "```",
        "",
        "---"
      ].join("\n")
    : [
        "# Mock analysis (Node)",
        "",
        "**Consultant:** `" + safeStr(ctx.consultant) + "`  ",
        "**Version A:** `" + safeStr(ctx.snapshotA) + "`  ",
        "**Version B:** `" + safeStr(ctx.snapshotB) + "`",
        "",
        "**User question (input):**",
        "```",
        safeStr(ctx.query),
        "```",
        "",
        "---"
      ].join("\n");

  // "Marketing-grade" PlantUML styling.
  const umlStyle = [
    "skinparam backgroundColor #FFFFFF",
    "skinparam shadowing true",
    "skinparam RoundCorner 10",
    "skinparam dpi 140",
    'skinparam defaultFontName "Inter"',
    "skinparam defaultFontSize 14",
    "skinparam ArrowColor #334155",
    "skinparam ArrowThickness 1.2",
    "skinparam NoteBackgroundColor #F8FAFC",
    "skinparam NoteBorderColor #CBD5E1",
    "skinparam TitleFontColor #0F172A",
    "",
    "skinparam class {",
    "  BackgroundColor #F8FAFC",
    "  BorderColor #CBD5E1",
    "  FontColor #0F172A",
    "  AttributeFontColor #0F172A",
    "}",
    "skinparam component {",
    "  BackgroundColor #F8FAFC",
    "  BorderColor #CBD5E1",
    "  FontColor #0F172A",
    "}",
    "skinparam sequence {",
    "  LifeLineBorderColor #CBD5E1",
    "  LifeLineBackgroundColor #FFFFFF",
    "  ParticipantBorderColor #CBD5E1",
    "  ParticipantBackgroundColor #F8FAFC",
    "  ParticipantFontColor #0F172A",
    "}"
  ].join("\n");

  // ADA (3 diagrams, random) + PlantUML render link.
  const adaPl = [
    function () {
      return [
        baseHeader,
        "",
        "## Diagram klas: API contract + domain + data",
        "",
        "```plantuml",
        "@startuml",
        "title Customer query flow — class view",
        umlStyle,
        "",
        "hide circle",
        "skinparam classAttributeIconSize 0",
        "",
        'class "CustomerController" as Controller <<UI>>',
        'class "CustomerService" as Service <<Domain>>',
        'interface "ICustomerRepository" as Repo <<Data>>',
        'class "Customer" as Entity <<Entity>>',
        'class "CustomerContract" as Contract <<Contract>>',
        "",
        "Controller : +GetCustomer(id)",
        "Service : +GetCustomerAsync(id, ct)",
        "Repo : +FindByIdAsync(id, ct)",
        "",
        "Entity : +Id : string",
        "Entity : +Name : string",
        "Entity : +IsActive : bool",
        "",
        "Contract : +Id : string",
        "Contract : +DisplayName : string",
        "Contract : +IsActive : bool",
        "",
        "Controller --> Service : calls",
        "Service --> Repo : uses",
        "Repo ..> Entity : returns",
        "Service ..> Contract : maps to",
        "",
        "note right of Service",
        "Mapping & validation",
        "should live here",
        "end note",
        "@enduml",
        "```"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Diagram sekwencji: request → validate → repository → map",
        "",
        "```plantuml",
        "@startuml",
        "title Customer query flow — sequence view",
        umlStyle,
        "",
        "actor User as U",
        'participant "CustomerController" as C',
        'participant "CustomerService" as S',
        'participant "ICustomerRepository" as R',
        "",
        "U -> C : GET /customers/{id}",
        "activate C",
        "C -> S : GetCustomerAsync(id, ct)",
        "activate S",
        "",
        "S -> S : Validate(id)",
        "alt invalid id",
        "  S --> C : null / validation error",
        "else ok",
        "  S -> R : FindByIdAsync(id, ct)",
        "  activate R",
        "  R --> S : Customer | null",
        "  deactivate R",
        "",
        "  alt not found",
        "    S --> C : null",
        "  else found",
        "    S -> S : Map(Customer → CustomerContract)",
        "    S --> C : CustomerContract",
        "  end",
        "end",
        "",
        "deactivate S",
        "C --> U : 200 / 404",
        "deactivate C",
        "@enduml",
        "```"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Diagram komponentów: warstwy i zależności",
        "",
        "```plantuml",
        "@startuml",
        "title Application layers — component view",
        umlStyle,
        "",
        "left to right direction",
        "",
        'package "UI" #EEF2FF {',
        "  [CustomerController] as UIController",
        "}",
        "",
        'package "Domain" #E0F2FE {',
        "  [CustomerService] as DomainService",
        "  [CustomerValidator] as DomainValidator",
        "}",
        "",
        'package "Data" #ECFDF5 {',
        "  [CustomerRepository] as DataRepo",
        '  database "AppDb" as DB',
        "}",
        "",
        "UIController --> DomainService : command/query",
        "DomainService --> DomainValidator : validate",
        "DomainService --> DataRepo : load entity",
        "DataRepo --> DB : SQL/EF",
        "",
        "note bottom of DomainService",
        "Single place for:",
        "- validation",
        "- mapping",
        "- orchestration",
        "end note",
        "@enduml",
        "```"
      ].join("\n");
    }
  ];

  const adaEn = [
    function () {
      return [
        baseHeader,
        "",
        "## Class diagram: API contract + domain + data",
        "",
        "```plantuml",
        "@startuml",
        "title Customer query flow — class view",
        umlStyle,
        "",
        "hide circle",
        "skinparam classAttributeIconSize 0",
        "",
        'class "CustomerController" as Controller <<UI>>',
        'class "CustomerService" as Service <<Domain>>',
        'interface "ICustomerRepository" as Repo <<Data>>',
        'class "Customer" as Entity <<Entity>>',
        'class "CustomerContract" as Contract <<Contract>>',
        "",
        "Controller : +GetCustomer(id)",
        "Service : +GetCustomerAsync(id, ct)",
        "Repo : +FindByIdAsync(id, ct)",
        "",
        "Entity : +Id : string",
        "Entity : +Name : string",
        "Entity : +IsActive : bool",
        "",
        "Contract : +Id : string",
        "Contract : +DisplayName : string",
        "Contract : +IsActive : bool",
        "",
        "Controller --> Service : calls",
        "Service --> Repo : uses",
        "Repo ..> Entity : returns",
        "Service ..> Contract : maps to",
        "",
        "note right of Service",
        "Mapping & validation",
        "should live here",
        "end note",
        "@enduml",
        "```"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Sequence diagram: request → validate → repository → map",
        "",
        "```plantuml",
        "@startuml",
        "title Customer query flow — sequence view",
        umlStyle,
        "",
        "actor User as U",
        'participant "CustomerController" as C',
        'participant "CustomerService" as S',
        'participant "ICustomerRepository" as R',
        "",
        "U -> C : GET /customers/{id}",
        "activate C",
        "C -> S : GetCustomerAsync(id, ct)",
        "activate S",
        "",
        "S -> S : Validate(id)",
        "alt invalid id",
        "  S --> C : null / validation error",
        "else ok",
        "  S -> R : FindByIdAsync(id, ct)",
        "  activate R",
        "  R --> S : Customer | null",
        "  deactivate R",
        "",
        "  alt not found",
        "    S --> C : null",
        "  else found",
        "    S -> S : Map(Customer → CustomerContract)",
        "    S --> C : CustomerContract",
        "  end",
        "end",
        "",
        "deactivate S",
        "C --> U : 200 / 404",
        "deactivate C",
        "@enduml",
        "```"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Component diagram: layers and dependencies",
        "",
        "```plantuml",
        "@startuml",
        "title Application layers — component view",
        umlStyle,
        "",
        "left to right direction",
        "",
        'package "UI" #EEF2FF {',
        "  [CustomerController] as UIController",
        "}",
        "",
        'package "Domain" #E0F2FE {',
        "  [CustomerService] as DomainService",
        "  [CustomerValidator] as DomainValidator",
        "}",
        "",
        'package "Data" #ECFDF5 {',
        "  [CustomerRepository] as DataRepo",
        '  database "AppDb" as DB',
        "}",
        "",
        "UIController --> DomainService : command/query",
        "DomainService --> DomainValidator : validate",
        "DomainService --> DataRepo : load entity",
        "DataRepo --> DB : SQL/EF",
        "",
        "note bottom of DomainService",
        "Single place for:",
        "- validation",
        "- mapping",
        "- orchestration",
        "end note",
        "@enduml",
        "```"
      ].join("\n");
    }
  ];

  // SHANNON: 4 compare answers, random.
  const shannonPl = [
    function () {
      return [
        baseHeader,
        "",
        "## Porównanie wersji: potencjalny *breaking change* w kontrakcie API",
        "",
        "**Wniosek:** błąd na `" + safeStr(ctx.snapshotA) + "` może wynikać z tego, że zniknęło pole **`IsActive`** w DTO, a UI nadal go oczekuje.",
        "",
        "**Symptom (typowy):**",
        "- błąd deserializacji / brak pola w JSON",
        "- NullReference przy mapowaniu/wyświetlaniu",
        "",
        "Starsza wersja (`" + safeStr(ctx.snapshotB) + "`):",
        "```csharp",
        "public sealed class CustomerContract",
        "{",
        "    public string Id { get; init; } = \"\";",
        "    public string DisplayName { get; init; } = \"\";",
        "    public bool IsActive { get; init; }  // <-- było",
        "}",
        "```",
        "",
        "Nowsza wersja (`" + safeStr(ctx.snapshotA) + "`):",
        "```csharp",
        "public sealed class CustomerContract",
        "{",
        "    public string Id { get; init; } = \"\";",
        "    public string DisplayName { get; init; } = \"\";",
        "    // IsActive removed or renamed",
        "}",
        "```",
        "",
        "**Co sprawdzić:**",
        "- mapping w serwisie (czy nadal ustawia `IsActive`)",
        "- klient UI/DTO (czy nie oczekuje starego kontraktu)",
        "- testy integracyjne kontraktu (snapshot/contract tests)"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Porównanie wersji: różnica w walidacji → inne zachowanie",
        "",
        "**Wniosek:** na `" + safeStr(ctx.snapshotA) + "` mogła dojść ostrzejsza walidacja, przez co scenariusz działający na `" + safeStr(ctx.snapshotB) + "` zaczyna failować.",
        "",
        "Wersja B:",
        "```csharp",
        "if (string.IsNullOrWhiteSpace(contract.DisplayName))",
        "    contract.DisplayName = \"Unknown\";",
        "```",
        "",
        "Wersja A:",
        "```csharp",
        "if (string.IsNullOrWhiteSpace(contract.DisplayName))",
        "    throw new ValidationException(\"DisplayName is required\");",
        "```",
        "",
        "**Jak diagnozować:**",
        "- logi: `validation failed` / `bad request`",
        "- różnice w testach (które przypadki teraz failują)",
        "- czy UI przesyła komplet danych"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Porównanie wersji: migracja bazy / brak kolumny",
        "",
        "**Wniosek:** na `" + safeStr(ctx.snapshotA) + "` kod może oczekiwać nowej kolumny, ale schema DB jest jak na `" + safeStr(ctx.snapshotB) + "`.",
        "",
        "**Typowy symptom:** `SqlException: Invalid column name 'ExternalId'`",
        "",
        "Przykład migracji (powinna istnieć na wersji, która jej wymaga):",
        "```sql",
        "ALTER TABLE dbo.Customers ADD ExternalId nvarchar(64) NULL;",
        "```",
        "",
        "**Checklist:**",
        "- czy migracje są obecne i uruchomione",
        "- czy EF model/SQL query są spójne",
        "- czy środowisko ma zaktualizowany schema"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Porównanie wersji: zmiana sortowania/paginacji → UI widzi inne wyniki",
        "",
        "**Wniosek:** na `" + safeStr(ctx.snapshotA) + "` mogła wejść paginacja `OFFSET/FETCH` albo inne `ORDER BY`, co zmienia deterministykę wyników.",
        "",
        "Wersja B:",
        "```sql",
        "SELECT TOP (@take) *",
        "FROM dbo.Customers",
        "WHERE IsActive = 1",
        "ORDER BY Name ASC;",
        "```",
        "",
        "Wersja A:",
        "```sql",
        "SELECT *",
        "FROM dbo.Customers",
        "WHERE IsActive = 1",
        "ORDER BY CreatedAt DESC",
        "OFFSET @skip ROWS FETCH NEXT @take ROWS ONLY;",
        "```",
        "",
        "**Co sprawdzić:**",
        "- czy `ORDER BY` jest deterministyczny",
        "- czy UI nie zakłada stabilnej kolejności",
        "- czy paginacja nie “gubi” elementów przy zmianach danych"
      ].join("\n");
    }
  ];

  const shannonEn = [
    function () {
      return [
        baseHeader,
        "",
        "## Version comparison: likely *breaking change* in API contract",
        "",
        "**Finding:** the bug on `" + safeStr(ctx.snapshotA) + "` may come from removing **`IsActive`** from the DTO while UI still expects it.",
        "",
        "Older version (`" + safeStr(ctx.snapshotB) + "`):",
        "```csharp",
        "public sealed class CustomerContract",
        "{",
        "    public string Id { get; init; } = \"\";",
        "    public string DisplayName { get; init; } = \"\";",
        "    public bool IsActive { get; init; }  // existed",
        "}",
        "```",
        "",
        "Newer version (`" + safeStr(ctx.snapshotA) + "`):",
        "```csharp",
        "public sealed class CustomerContract",
        "{",
        "    public string Id { get; init; } = \"\";",
        "    public string DisplayName { get; init; } = \"\";",
        "    // IsActive removed or renamed",
        "}",
        "```",
        "",
        "**What to check:**",
        "- mapping still sets `IsActive`",
        "- UI/client DTO expects old contract",
        "- integration/contract tests"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Version comparison: validation change → different runtime behavior",
        "",
        "**Finding:** `" + safeStr(ctx.snapshotA) + "` may have stricter validation, so a scenario working on `" + safeStr(ctx.snapshotB) + "` fails on A.",
        "",
        "Old:",
        "```csharp",
        "if (string.IsNullOrWhiteSpace(contract.DisplayName))",
        "    contract.DisplayName = \"Unknown\";",
        "```",
        "",
        "New:",
        "```csharp",
        "if (string.IsNullOrWhiteSpace(contract.DisplayName))",
        "    throw new ValidationException(\"DisplayName is required\");",
        "```"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Version comparison: DB migration / missing column",
        "",
        "**Finding:** code on `" + safeStr(ctx.snapshotA) + "` may expect a new column while DB schema is still at `" + safeStr(ctx.snapshotB) + "` level.",
        "",
        "Typical symptom: `Invalid column name 'ExternalId'`",
        "",
        "Example migration:",
        "```sql",
        "ALTER TABLE dbo.Customers ADD ExternalId nvarchar(64) NULL;",
        "```",
        "",
        "**Checklist:**",
        "- migrations present vs applied",
        "- EF model / SQL queries updated consistently",
        "- environment schema in sync"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Version comparison: changed ordering/pagination semantics",
        "",
        "**Finding:** `" + safeStr(ctx.snapshotA) + "` may return data in different order (or with OFFSET/FETCH), making UI show unexpected results.",
        "",
        "Old:",
        "```sql",
        "SELECT TOP (@take) *",
        "FROM dbo.Customers",
        "WHERE IsActive = 1",
        "ORDER BY Name ASC;",
        "```",
        "",
        "New:",
        "```sql",
        "SELECT *",
        "FROM dbo.Customers",
        "WHERE IsActive = 1",
        "ORDER BY CreatedAt DESC",
        "OFFSET @skip ROWS FETCH NEXT @take ROWS ONLY;",
        "```",
        "",
        "**What to check:**",
        "- deterministic `ORDER BY`",
        "- UI assumptions about stable ordering",
        "- query builder diffs"
      ].join("\n");
    }
  ];

  // Other (simple C# mock).
  const otherPl = [
    function () {
      return [
        baseHeader,
        "",
        "## Szybka analiza C#: kontrakt i mapowanie",
        "",
        "```csharp",
        "public sealed class CustomerContract",
        "{",
        "    public string Id { get; init; } = \"\";",
        "    public string DisplayName { get; init; } = \"\";",
        "    public bool IsActive { get; init; }",
        "}",
        "```",
        "",
        "- kontrakt stabilny",
        "- mapowanie w serwisie"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Uwaga: `async void` (poza event handlerami)",
        "",
        "```csharp",
        "public async Task RefreshAsync(CancellationToken ct)",
        "{",
        "    await LoadAsync(ct).ConfigureAwait(false);",
        "}",
        "```"
      ].join("\n");
    }
  ];

  const otherEn = [
    function () {
      return [
        baseHeader,
        "",
        "## Quick C# analysis: contract and mapping",
        "",
        "```csharp",
        "public sealed class CustomerContract",
        "{",
        "    public string Id { get; init; } = \"\";",
        "    public string DisplayName { get; init; } = \"\";",
        "    public bool IsActive { get; init; }",
        "}",
        "```"
      ].join("\n");
    },
    function () {
      return [
        baseHeader,
        "",
        "## Note: avoid `async void` (except event handlers)",
        "",
        "```csharp",
        "public async Task RefreshAsync(CancellationToken ct)",
        "{",
        "    await LoadAsync(ct).ConfigureAwait(false);",
        "}",
        "```"
      ].join("\n");
    }
  ];

  if (consultantId === "ada") {
    const chosen = isPl ? pickRandom(adaPl) : pickRandom(adaEn);
    const md = chosen ? chosen() : (baseHeader + "\n\n" + (isPl ? "Brak szablonów." : "No templates.") + "\n");
    return appendDiagramLink(md, ctx.translateChat);
  }

  if (consultantId === "shannon") {
    const chosen = isPl ? pickRandom(shannonPl) : pickRandom(shannonEn);
    return chosen ? chosen() : (baseHeader + "\n\n" + (isPl ? "Brak szablonów." : "No templates.") + "\n");
  }

  const chosen = isPl ? pickRandom(otherPl) : pickRandom(otherEn);
  return chosen ? chosen() : (baseHeader + "\n\n" + (isPl ? "Brak szablonów." : "No templates.") + "\n");
}

const server = http.createServer(async (req, res) => {
  const parsed = url.parse(req.url, true);
  const pathname = parsed.pathname || "/";
  const basePath = pathname;

  if (req.method === "OPTIONS") {
    setCors(res);
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "GET" && (pathname === "/" || pathname === "/page.html")) {
    try {
      const html = fs.readFileSync(UI_FILE, "utf8");
      sendHtml(res, 200, html);
    } catch (e) {
      sendText(res, 404, "Missing file: " + UI_FILE + "\nPut page.html next to server.js");
    }
    return;
  }

  if (req.method === "GET" && basePath === "/app-config") {
    return sendJson(res, 200, buildAppConfig());
  }

  if (req.method === "GET" && basePath === "/pipeline/stream") {
    const runId = (parsed.query && parsed.query.run_id) ? String(parsed.query.run_id) : "";
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "Access-Control-Allow-Origin": "*"
    });

    const events = [
      { type: "step", summary: "Retrieval", action_id: "search_nodes", details: { search_type: "semantic", top_k: 8, hits: 8 } },
      { type: "step", summary: "Context materialization", action_id: "fetch_node_texts", details: { node_texts_count: 8 },
        docs: [
          { id: "doc:alpha", depth: 0, text_len: 420, preview: "Przykladowy fragment dokumentu alpha..." },
          { id: "doc:beta", depth: 1, text_len: 300, preview: "Przykladowy fragment dokumentu beta..." }
        ]
      },
      { type: "step", summary: "Model call", action_id: "call_model", details: { prompt: "answer_v1", max_output_tokens: 1200 } }
    ];

    let idx = 0;
    const timer = setInterval(() => {
      if (idx < events.length) {
        res.write("data: " + JSON.stringify(events[idx]) + "\n\n");
        idx += 1;
        return;
      }
      res.write("data: " + JSON.stringify({ type: "done", reason: "mock" }) + "\n\n");
      clearInterval(timer);
      res.end();
    }, 700);

    req.on("close", () => {
      clearInterval(timer);
    });
    return;
  }

  if (req.method === "GET" && basePath === "/chat-history/sessions") {
    const tenantId = getTenantId(req);
    const userId = getAuthUser(req);
    const limit = Math.max(1, Math.min(200, parseInt(parsed.query.limit || "50", 10)));
    const cursor = parsed.query.cursor ? String(parsed.query.cursor) : null;
    const q = parsed.query.q ? String(parsed.query.q) : "";
    return sendJson(res, 200, listSessions({ tenantId, userId, limit, cursor, q }));
  }

  if (req.method === "GET" && basePath.startsWith("/chat-history/sessions/") && !basePath.endsWith("/messages")) {
    const tenantId = getTenantId(req);
    const userId = getAuthUser(req);
    const sessionId = basePath.split("/").pop();
    const session = chatHistory.sessions.get(sessionId);
    if (!session || session.tenantId !== tenantId || session.userId !== userId || session.deletedAt || session.softDeletedAt) {
      return sendJson(res, 404, { error: "not_found" });
    }
    return sendJson(res, 200, session);
  }

  if (req.method === "GET" && basePath.endsWith("/messages")) {
    const tenantId = getTenantId(req);
    const userId = getAuthUser(req);
    const sessionId = basePath.split("/").slice(-2)[0];
    const session = chatHistory.sessions.get(sessionId);
    if (!session || session.tenantId !== tenantId || session.userId !== userId || session.deletedAt) {
      return sendJson(res, 404, { error: "not_found" });
    }
    const limit = Math.max(1, Math.min(200, parseInt(parsed.query.limit || "100", 10)));
    const before = parsed.query.before ? parseInt(parsed.query.before, 10) : null;
    const all = (chatHistory.messages.get(sessionId) || []).filter(m => !m.deletedAt);
    const filtered = before ? all.filter(m => m.ts < before) : all;
    const items = filtered.slice(-limit);
    const next = items.length === limit ? String(items[0].ts) : null;
    return sendJson(res, 200, { items, next_cursor: next });
  }

  if (req.method === "POST" && basePath === "/chat-history/sessions") {
    let payload = {};
    try {
      const raw = await readBody(req);
      payload = raw ? JSON.parse(raw) : {};
    } catch (e) {
      return sendJson(res, 400, { error: "Invalid JSON" });
    }
    const tenantId = getTenantId(req);
    const userId = getAuthUser(req);
    const now = nowTs();
    const sessionId = String(payload.sessionId || randomId());
    const session = {
      sessionId,
      tenantId,
      userId,
      title: safeStr(payload.title || payload.firstQuestion || "New chat"),
      consultantId: safeStr(payload.consultantId || payload.consultant || ""),
      createdAt: now,
      updatedAt: now,
      messageCount: 0,
      deletedAt: null,
      softDeletedAt: null,
      status: "active",
    };
    chatHistory.sessions.set(sessionId, session);
    chatHistory.messages.set(sessionId, []);
    return sendJson(res, 200, session);
  }

  if (req.method === "POST" && basePath.endsWith("/messages")) {
    let payload = {};
    try {
      const raw = await readBody(req);
      payload = raw ? JSON.parse(raw) : {};
    } catch (e) {
      return sendJson(res, 400, { error: "Invalid JSON" });
    }
    const tenantId = getTenantId(req);
    const userId = getAuthUser(req);
    const sessionId = basePath.split("/").slice(-2)[0];
    const session = chatHistory.sessions.get(sessionId);
    if (!session || session.tenantId !== tenantId || session.userId !== userId || session.deletedAt) {
      return sendJson(res, 404, { error: "not_found" });
    }
    const now = nowTs();
    const msg = {
      messageId: String(payload.messageId || randomId()),
      sessionId,
      ts: now,
      q: payload.q == null ? "" : String(payload.q),
      a: payload.a == null ? "" : String(payload.a),
      meta: payload.meta || null,
      deletedAt: null,
    };
    const list = chatHistory.messages.get(sessionId) || [];
    list.push(msg);
    chatHistory.messages.set(sessionId, list);
    session.updatedAt = now;
    session.messageCount = list.length;
    chatHistory.sessions.set(sessionId, session);
    return sendJson(res, 200, msg);
  }

  if (req.method === "PATCH" && basePath.startsWith("/chat-history/sessions/")) {
    let payload = {};
    try {
      const raw = await readBody(req);
      payload = raw ? JSON.parse(raw) : {};
    } catch (e) {
      return sendJson(res, 400, { error: "Invalid JSON" });
    }
    const tenantId = getTenantId(req);
    const userId = getAuthUser(req);
    const sessionId = basePath.split("/").pop();
    const session = chatHistory.sessions.get(sessionId);
    if (!session || session.tenantId !== tenantId || session.userId !== userId || session.deletedAt) {
      return sendJson(res, 404, { error: "not_found" });
    }
    if (payload.title != null) session.title = String(payload.title);
    if (payload.consultantId != null) session.consultantId = String(payload.consultantId);
    if (payload.important != null) session.important = !!payload.important;
    if (payload.softDeleted != null) {
      if (payload.softDeleted) {
        session.softDeletedAt = nowTs();
        session.status = "soft_deleted";
      } else {
        session.softDeletedAt = null;
        session.status = "active";
      }
    }
    session.updatedAt = nowTs();
    chatHistory.sessions.set(sessionId, session);
    return sendJson(res, 200, session);
  }

  if (req.method === "DELETE" && basePath.startsWith("/chat-history/sessions/")) {
    const tenantId = getTenantId(req);
    const userId = getAuthUser(req);
    const sessionId = basePath.split("/").pop();
    const session = chatHistory.sessions.get(sessionId);
    if (!session || session.tenantId !== tenantId || session.userId !== userId || session.deletedAt) {
      return sendJson(res, 404, { error: "not_found" });
    }
    session.softDeletedAt = nowTs();
    session.status = "soft_deleted";
    session.updatedAt = nowTs();
    chatHistory.sessions.set(sessionId, session);
    return sendJson(res, 200, { ok: true, sessionId });
  }

  if (req.method === "POST" && basePath === "/pipeline/cancel") {
    let payload = {};
    try {
      const raw = await readBody(req);
      payload = raw ? JSON.parse(raw) : {};
    } catch (e) {
      payload = {};
    }
    const runId = String(payload.pipeline_run_id || payload.run_id || "").trim();
    return sendJson(res, 200, { ok: true, cancelled: true, run_id: runId });
  }

  // POST /query is the main endpoint used by the UI.
  // POST /search is kept as an alias for older HTML versions.
  if (req.method === "POST" && (basePath === "/query" || basePath === "/search")) {
    let payload = {};
    try {
      const raw = await readBody(req);
      payload = raw ? JSON.parse(raw) : {};
    } catch (e) {
      return sendJson(res, 400, { error: "Invalid JSON" });
    }

    const sessionId = getSessionId(req);
    const consultant = (payload.pipelineName || payload.consultant || "unknown").toString();
    const query = (payload.query || "").toString();

    let snapshotA = null;
    let snapshotB = null;
    if (Array.isArray(payload.snapshots)) {
      snapshotA = payload.snapshots[0] == null ? null : payload.snapshots[0];
      snapshotB = payload.snapshots[1] == null ? null : payload.snapshots[1];
    } else {
      // Legacy fallback
      snapshotA = payload.branchA == null ? null : payload.branchA;
      snapshotB = payload.branchB == null ? null : payload.branchB;
    }

    // UI sends translateChat: true for PL, false for EN.
    const translateChat = !!payload.translateChat;

    const md = buildMockMarkdownResponse({
      consultant,
      query,
      snapshotA,
      snapshotB,
      translateChat
    });

    return sendJson(res, 200, {
      session_id: sessionId,
      results: md,
      pipeline_run_id: runIdFromPayload(payload)
    });
  }

  if (req.method === "GET" && basePath === "/health") {
    return sendJson(res, 200, { ok: true });
  }

  sendText(res, 404, "Not Found");
});

server.on("error", (err) => {
  if (err && err.code === "EADDRINUSE") {
    console.error("Port " + PORT + " is already in use. Try: set PORT=8082 and run again.");
    process.exit(1);
  }
  console.error(err);
  process.exit(1);
});

  server.listen(PORT, "0.0.0.0", () => {
  console.log("Mock server running: http://localhost:" + PORT);
  console.log("Open UI:             http://localhost:" + PORT + "/page.html");
  console.log("Endpoints:           GET /app-config, POST /query, POST /search, GET /pipeline/stream, POST /pipeline/cancel");
  console.log("Chat history:        GET /chat-history/sessions, GET /chat-history/sessions/{id}, GET /chat-history/sessions/{id}/messages");
  console.log("                     POST /chat-history/sessions, POST /chat-history/sessions/{id}/messages, PATCH/DELETE /chat-history/sessions/{id}");
  console.log("PlantUML server:     " + PLANTUML_SERVER);
});
