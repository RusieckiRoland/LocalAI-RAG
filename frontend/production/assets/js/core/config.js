(function () {
  const App = window.App = window.App || {};

  const API_BASE = (window.location.protocol === "file:")
    ? "http://localhost:8081"
    : window.location.origin;
  const URL_MODE = (new URLSearchParams(window.location.search).get("mode") || "dev").toLowerCase();
  const IS_FILE_MODE = window.location.protocol === "file:";
  const APP_MODE = (URL_MODE === "prod") ? "prod" : "dev";
  const APP_CONFIG_PATH = IS_FILE_MODE ? "/app-config" : `/app-config/${APP_MODE}`;
  const SEARCH_PATH = IS_FILE_MODE ? "/search" : `/search/${APP_MODE}`;
  const CANCEL_PATH = IS_FILE_MODE ? "/pipeline/cancel" : `/pipeline/cancel/${APP_MODE}`;
  const DEFAULT_APP_CONFIG = {
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
      },
      {
        id: "chuck",
        pipelineName: "chuck",
        snapshotPickerMode: "none",
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
  const HISTORY_STORAGE_KEY = "chatHistoryByUser_v1";
  const HISTORY_SEARCH_PAGE_SIZE = 50;
  const MAX_BRANCH_LABEL_LEN = 28;
  const TRACE_STREAM_PATH = IS_FILE_MODE ? "/pipeline/stream" : `/pipeline/stream/${APP_MODE}`;

  App.config = {
    API_BASE,
    URL_MODE,
    IS_FILE_MODE,
    APP_MODE,
    APP_CONFIG_PATH,
    SEARCH_PATH,
    CANCEL_PATH,
    TRACE_STREAM_PATH,
    DEFAULT_APP_CONFIG,
    HISTORY_STORAGE_KEY,
    HISTORY_SEARCH_PAGE_SIZE,
    MAX_BRANCH_LABEL_LEN,
  };
})();
