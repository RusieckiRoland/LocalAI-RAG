// English comments only.

const http = require("http");
const fs = require("fs");
const path = require("path");
const url = require("url");
const crypto = require("crypto");
const zlib = require("zlib");

const PORT = parseInt(process.env.PORT || "8081", 10);

const ROOT = process.cwd();
const UI_FILE = path.join(ROOT, "strona.html");

// Default PlantUML server (official). You can override with env var if needed.
const PLANTUML_SERVER = String(process.env.PLANTUML_SERVER || "https://www.plantuml.com/plantuml").replace(/\/+$/, "");

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
  return crypto.randomUUID();
}

function safeStr(v) {
  return (v == null) ? "" : String(v);
}

function pickRandom(arr) {
  if (!arr || arr.length === 0) return null;
  const idx = crypto.randomInt(0, arr.length);
  return arr[idx];
}

function buildAppConfig() {
  return {
    defaultConsultantId: "rejewski",
    branches: [
      "2025-12-14__develop",
      "2025-12-14__release_4_60",
      "2025-12-14__release_4_90"
    ],
    consultants: [
      {
        id: "rejewski",
        pipelineName: "marian_rejewski_code_analysis_base",
        branchPickerMode: "single",
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
        pipelineName: "ada_uml_diagrams_base",
        branchPickerMode: "single",
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
        pipelineName: "branch_compare_base",
        branchPickerMode: "compare",
        icon: "🔀",
        displayName: "Claude Shannon",
        cardDescription: { pl: "Porównywanie branchy", en: "Branch comparison" },
        welcomeTemplate: {
          pl: "Zapytaj {link} o porównanie branchy i różnice.",
          en: "Ask {link} to compare branches and differences."
        },
        welcomeLinkText: { pl: "Claude’a Shannona", en: "Claude Shannon" },
        wikiUrl: {
          pl: "https://pl.wikipedia.org/wiki/Claude_Shannon",
          en: "https://en.wikipedia.org/wiki/Claude_Shannon"
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
        "**Branch A:** `" + safeStr(ctx.branchA) + "`  ",
        "**Branch B:** `" + safeStr(ctx.branchB) + "`",
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
        "**Branch A:** `" + safeStr(ctx.branchA) + "`  ",
        "**Branch B:** `" + safeStr(ctx.branchB) + "`",
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
        "## Porównanie branchy: potencjalny *breaking change* w kontrakcie API",
        "",
        "**Wniosek:** błąd na `" + safeStr(ctx.branchA) + "` może wynikać z tego, że zniknęło pole **`IsActive`** w DTO, a UI nadal go oczekuje.",
        "",
        "**Symptom (typowy):**",
        "- błąd deserializacji / brak pola w JSON",
        "- NullReference przy mapowaniu/wyświetlaniu",
        "",
        "Starszy branch (`" + safeStr(ctx.branchB) + "`):",
        "```csharp",
        "public sealed class CustomerContract",
        "{",
        "    public string Id { get; init; } = \"\";",
        "    public string DisplayName { get; init; } = \"\";",
        "    public bool IsActive { get; init; }  // <-- było",
        "}",
        "```",
        "",
        "Nowszy branch (`" + safeStr(ctx.branchA) + "`):",
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
        "## Porównanie branchy: różnica w walidacji → inne zachowanie",
        "",
        "**Wniosek:** na `" + safeStr(ctx.branchA) + "` mogła dojść ostrzejsza walidacja, przez co scenariusz działający na `" + safeStr(ctx.branchB) + "` zaczyna failować.",
        "",
        "Branch B:",
        "```csharp",
        "if (string.IsNullOrWhiteSpace(contract.DisplayName))",
        "    contract.DisplayName = \"Unknown\";",
        "```",
        "",
        "Branch A:",
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
        "## Porównanie branchy: migracja bazy / brak kolumny",
        "",
        "**Wniosek:** na `" + safeStr(ctx.branchA) + "` kod może oczekiwać nowej kolumny, ale schema DB jest jak na `" + safeStr(ctx.branchB) + "`.",
        "",
        "**Typowy symptom:** `SqlException: Invalid column name 'ExternalId'`",
        "",
        "Przykład migracji (powinna istnieć na branchu, który jej wymaga):",
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
        "## Porównanie branchy: zmiana sortowania/paginacji → UI widzi inne wyniki",
        "",
        "**Wniosek:** na `" + safeStr(ctx.branchA) + "` mogła wejść paginacja `OFFSET/FETCH` albo inne `ORDER BY`, co zmienia deterministykę wyników.",
        "",
        "Branch B:",
        "```sql",
        "SELECT TOP (@take) *",
        "FROM dbo.Customers",
        "WHERE IsActive = 1",
        "ORDER BY Name ASC;",
        "```",
        "",
        "Branch A:",
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
        "## Branch comparison: likely *breaking change* in API contract",
        "",
        "**Finding:** the bug on `" + safeStr(ctx.branchA) + "` may come from removing **`IsActive`** from the DTO while UI still expects it.",
        "",
        "Old branch (`" + safeStr(ctx.branchB) + "`):",
        "```csharp",
        "public sealed class CustomerContract",
        "{",
        "    public string Id { get; init; } = \"\";",
        "    public string DisplayName { get; init; } = \"\";",
        "    public bool IsActive { get; init; }  // existed",
        "}",
        "```",
        "",
        "New branch (`" + safeStr(ctx.branchA) + "`):",
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
        "## Branch comparison: validation change → different runtime behavior",
        "",
        "**Finding:** `" + safeStr(ctx.branchA) + "` may have stricter validation, so a scenario working on `" + safeStr(ctx.branchB) + "` fails on A.",
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
        "## Branch comparison: DB migration / missing column",
        "",
        "**Finding:** code on `" + safeStr(ctx.branchA) + "` may expect a new column while DB schema is still at `" + safeStr(ctx.branchB) + "` level.",
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
        "## Branch comparison: changed ordering/pagination semantics",
        "",
        "**Finding:** `" + safeStr(ctx.branchA) + "` may return data in different order (or with OFFSET/FETCH), making UI show unexpected results.",
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

  if (req.method === "OPTIONS") {
    setCors(res);
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "GET" && (pathname === "/" || pathname === "/strona.html")) {
    try {
      const html = fs.readFileSync(UI_FILE, "utf8");
      sendHtml(res, 200, html);
    } catch (e) {
      sendText(res, 404, "Missing file: " + UI_FILE + "\nPut strona.html next to server.js");
    }
    return;
  }

  if (req.method === "GET" && pathname === "/app-config") {
    return sendJson(res, 200, buildAppConfig());
  }

  // POST /query is the main endpoint used by the UI.
  // POST /search is kept as an alias for older HTML versions.
  if (req.method === "POST" && (pathname === "/query" || pathname === "/search")) {
    let payload = {};
    try {
      const raw = await readBody(req);
      payload = raw ? JSON.parse(raw) : {};
    } catch (e) {
      return sendJson(res, 400, { error: "Invalid JSON" });
    }

    const sessionId = getSessionId(req);
    const consultant = (payload.consultant || "unknown").toString();
    const query = (payload.query || "").toString();

    const branchA = payload.branchA ?? null;
    const branchB = payload.branchB ?? null;

    // UI sends translateChat: true for PL, false for EN.
    const translateChat = !!payload.translateChat;

    const md = buildMockMarkdownResponse({
      consultant,
      query,
      branchA,
      branchB,
      translateChat
    });

    return sendJson(res, 200, {
      session_id: sessionId,
      results: md
    });
  }

  if (req.method === "GET" && pathname === "/health") {
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
  console.log("Open UI:             http://localhost:" + PORT + "/strona.html");
  console.log("Endpoints:           GET /app-config, POST /query (alias /search)");
  console.log("PlantUML server:     " + PLANTUML_SERVER);
});
