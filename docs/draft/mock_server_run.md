# Mock server (Node.js) — running it

This mock pretends to be a backend for `strona.html`:
- returns `/app-config` (consultants + branch picker mode),
- handles `POST /query` and the alias `POST /search`,
- generates random Markdown responses (including PlantUML for Ada),
- respects the UI language toggle (`translateChat`: PL/EN).

## Requirements
- Node.js **18+** (also works on 22.x)
- Files in the **same directory**:
  - `server.js`
  - `strona.html`

## Run (Windows — PowerShell)
Go to the folder with the files and run:

```powershell
cd C:\Users\<your_user>\Desktop\Rag_frontend
node server.js
```

After startup you should see something like:
- `Mock server running: http://localhost:8081`
- `Open UI: http://localhost:8081/strona.html`

Open in your browser:
- `http://localhost:8081/strona.html`

## Run (Linux/macOS)
```bash
cd /path/to/Rag_frontend
node server.js
```

## Change the port
Default port is **8081**. Change it via the `PORT` environment variable.

**Windows (PowerShell):**
```powershell
$env:PORT=8082
node server.js
```

**Linux/macOS (bash/zsh):**
```bash
PORT=8082 node server.js
```

## (Optional) Change the PlantUML server
By default the public PlantUML server is used:
- `https://www.plantuml.com/plantuml`

You can override it:

**Windows (PowerShell):**
```powershell
$env:PLANTUML_SERVER="https://www.plantuml.com/plantuml"
node server.js
```

**Linux/macOS:**
```bash
PLANTUML_SERVER="https://www.plantuml.com/plantuml" node server.js
```

## Endpoints
- `GET /app-config` — UI configuration (consultants, branches)
- `POST /query` — main UI endpoint
- `POST /search` — alias (for older UI versions)
- `GET /health` — simple `{"ok": true}`
- `GET /strona.html` — serves the UI

## Quick test (curl)
```bash
curl -X POST http://localhost:8081/query ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"test\",\"consultant\":\"rejewski\",\"translateChat\":true,\"branchA\":\"A\",\"branchB\":\"B\"}"
```

## Common issues
### Port already in use
If you see a “port in use” message, set a different `PORT` (e.g. 8082) and run again.

### Missing `strona.html`
The server will return 404 with a message that the file is missing. Make sure `strona.html` is next to `server.js`.
