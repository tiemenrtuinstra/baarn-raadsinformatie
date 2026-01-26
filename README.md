# ![Gemeente Baarn logo](https://logos.notubiz.nl/gemeente_baarn.png) 
# Baarn Raadsinformatie MCP Server

[![CI/CD](https://github.com/tiemenrtuinstra/baarn-raadsinformatie/actions/workflows/ci.yml/badge.svg)](https://github.com/tiemenrtuinstra/baarn-raadsinformatie/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-1.0+-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Een **Model Context Protocol (MCP) server** die AI-assistenten toegang geeft tot politieke documenten en vergaderingen van de gemeente Baarn via de Notubiz API.

## Features

- **15 MCP Tools** - Vergaderingen, documenten, zoeken, annotaties
- **24 AI Agents** - Gespecialiseerde prompts voor verschillende taken
- **MCP Resources** - Directe toegang tot vergadering- en documentdata
- **Semantic Search** - AI-gebaseerd zoeken met embeddings
- **Automatische Sync** - Achtergrond synchronisatie met Notubiz API
- **Docker Support** - Containerized deployment

## Snel Starten

### One-Liner Installatie (Aanbevolen)

De snelste manier om te installeren - één commando en alles wordt automatisch geregeld:

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/tiemenrtuinstra/baarn-raadsinformatie/main/install.sh | bash
```

**Windows (PowerShell als Administrator):**

```powershell
irm https://raw.githubusercontent.com/tiemenrtuinstra/baarn-raadsinformatie/main/install.ps1 | iex
```

### Installatie via Git Clone

Als je de broncode wilt bewerken of meer controle wilt over de installatie:

**Windows:**

```powershell
git clone https://github.com/tiemenrtuinstra/baarn-raadsinformatie.git
cd baarn-raadsinformatie
.\scripts\install.ps1                    # Volledige installatie
.\scripts\install.ps1 -LightBuild        # Zonder embeddings (kleinere image)
.\scripts\install.ps1 -SkipDocker        # Skip Docker installatie
.\scripts\install.ps1 -SkipClaude        # Skip Claude Desktop/CLI installatie
```

**macOS/Linux:**

```bash
git clone https://github.com/tiemenrtuinstra/baarn-raadsinformatie.git
cd baarn-raadsinformatie
./scripts/install.sh
./scripts/install.sh --light         # Lichtgewicht build
./scripts/install.sh --skip-docker   # Skip Docker check
./scripts/install.sh --skip-claude   # Skip Claude Desktop/CLI installatie
```

### Wat doet de installer?

1. **Docker** - Installeert Docker Desktop indien nodig
2. **Environment** - Maakt `.env` bestand met unieke API key
3. **Build** - Bouwt Docker images (~3.5GB of ~1.5GB light)
4. **Claude** (optioneel, skip met `--skip-claude`) - Installeert Claude indien nodig:
   - Windows/macOS: Claude Desktop (via winget/brew of directe download)
   - Linux/Chromebook: Claude Code CLI (via npm)
   - Dependencies: Node.js wordt automatisch geïnstalleerd indien nodig voor CLI
5. **AI Tools** - Detecteert en configureert (14 tools):
   - Claude Desktop
   - Claude Code CLI
   - OpenAI Codex CLI
   - Cursor IDE
   - Continue.dev (VS Code/JetBrains)
   - Cline (Claude Dev) voor VS Code
   - Aider CLI
   - Zed Editor
   - Windsurf
   - Ollama
   - GitHub Copilot
   - Microsoft Copilot Studio
6. **Start** - Start API server en sync service

### Chromebook / ChromeOS Support

De installer werkt ook op Chromebooks met Linux (Crostini) ondersteuning:

```bash
# Open de Linux terminal op je Chromebook en voer uit:
curl -fsSL https://raw.githubusercontent.com/tiemenrtuinstra/baarn-raadsinformatie/main/install.sh | bash
```

**Opmerkingen:**

- Claude Desktop is niet beschikbaar voor Linux/ChromeOS
- De installer installeert automatisch Claude Code CLI via npm als alternatief
- Node.js wordt automatisch geïnstalleerd indien nodig
- Gebruik `--skip-claude` om Claude installatie over te slaan
- Docker moet beschikbaar zijn in je Linux container

### Services beheren

```bash
# Windows
.\scripts\start.ps1              # Start services
.\scripts\start.ps1 -Stop        # Stop services
.\scripts\start.ps1 -Logs        # Bekijk logs
.\scripts\start.ps1 -Restart     # Herstart

# macOS/Linux
./scripts/start.sh start         # Start services
./scripts/start.sh stop          # Stop services
./scripts/start.sh logs          # Bekijk logs
./scripts/start.sh status        # Toon status
```

### Handmatige Installatie

Als je liever handmatig installeert:

```bash
# Clone repository
git clone https://github.com/tiemenrtuinstra/baarn-raadsinformatie.git
cd baarn-raadsinformatie

# Kopieer environment file
cp .env.example .env

# Bouw en start met Docker
docker compose build
docker compose up -d api-server sync-service
```

### Claude Desktop Configuratie

Na installatie is Claude Desktop automatisch geconfigureerd. Handmatig toevoegen aan `%APPDATA%\Claude\claude_desktop_config.json` (Windows) of `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "baarn-raadsinformatie": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", "/pad/naar/project/.env",
               "-v", "/pad/naar/project/data:/app/data",
               "baarn-raadsinformatie:latest"]
    }
  }
}
```

Herstart Claude Desktop en de MCP server is beschikbaar.

## Architectuur

```
baarn-raadsinformatie/
├── mcp_server.py           # MCP server entry point
├── api_server.py           # REST API server (FastAPI)
├── sync_service.py         # Background sync service
├── agents/                 # AI agent definities (YAML)
├── analyzers/              # Analyse modules
├── configs/                # Configuratie bestanden
│   ├── openapi.json        # OpenAPI schema
│   └── copilot-studio-connector.json
├── core/                   # Core modules
│   ├── config.py           # Configuratie
│   ├── database.py         # SQLite database (WAL mode)
│   └── document_index.py   # Embeddings index
├── data/                   # Data directory (niet in git)
│   ├── baarn.db            # SQLite database
│   ├── cache/              # API cache
│   ├── documents/          # PDF downloads
│   └── images/             # Geëxtraheerde afbeeldingen
├── providers/              # Data providers
│   ├── notubiz_client.py   # Notubiz API client
│   ├── meeting_provider.py # Vergaderingen
│   ├── document_provider.py# Documenten + OCR
│   └── ...                 # Overige providers
├── scripts/                # Scripts
│   ├── install.sh/ps1      # Installatie scripts
│   ├── start.sh/ps1        # Start scripts
│   └── ...                 # Utility scripts
├── shared/                 # Gedeelde utilities
│   ├── logging_config.py   # Logging
│   └── cli_progress.py     # CLI progress bars
└── tools/                  # MCP tool definities
```

## MCP Tools

| Tool | Beschrijving |
|------|-------------|
| `get_meetings` | Vergaderingen ophalen met filters |
| `get_meeting_details` | Details van een vergadering |
| `get_agenda_items` | Agendapunten ophalen |
| `get_document` | Document met inhoud ophalen |
| `search_documents` | Keyword zoeken |
| `semantic_search` | AI zoeken op betekenis |
| `sync_data` | Data synchroniseren |
| `add_annotation` | Notities toevoegen |
| `get_annotations` | Notities ophalen |
| `get_gremia` | Commissies ophalen |
| `get_statistics` | Database statistieken |
| `get_coalitie_akkoord` | Coalitieakkoord info |
| `update_coalitie_afspraak` | Coalitie-afspraak updaten |
| `add_visit_report` | Werkbezoek-verslag toevoegen (upload) |
| `import_visit_reports` | Werkbezoek-verslagen aanmaken uit documenten |
| `list_visit_reports` | Werkbezoek-verslagen lijst |
| `get_visit_report` | Werkbezoek-verslag details |
| `search_visit_reports` | Zoeken in werkbezoek-verslagen |
| `update_visit_report` | Werkbezoek-verslag bijwerken |
| `delete_visit_report` | Werkbezoek-verslag archiveren |
| `link_visit_report_to_meeting` | Verslag koppelen aan vergadering |
| `index_visit_reports` | Verslagdocumenten indexeren |

## AI Agents

De server bevat 24 gespecialiseerde agents:

### Analyse & Onderzoek
- `vergadering-analist` - Analyseert vergaderingen
- `stemgedrag-analist` - Analyseert stempatronen
- `document-zoeker` - Doorzoekt documenten
- `beleids-onderzoeker` - Onderzoekt beleid

### Monitoring & Tracking
- `besluit-tracker` - Volgt besluiten
- `motie-tracker` - Volgt moties/amendementen
- `toezeggingen-tracker` - Volgt toezeggingen
- `coalitie-monitor` - Volgt coalitieakkoord

### Assistentie
- `raadslid-assistent` - Ondersteunt raadsleden
- `burger-informant` - Informeert burgers
- `journalist-assistent` - Ondersteunt journalisten
- `woo-assistent` - Helpt bij Woo-verzoeken

[Zie agents/README.md voor volledige lijst](agents/README.md)

## Docker Deployment

```bash
# Build en start
docker compose up -d

# Bekijk logs
docker compose logs -f

# Stop
docker compose down
```

De sync service synchroniseert automatisch elke 6 uur.

## Claude Code CLI Configuratie

De MCP server werkt met de Claude Code CLI (Anthropic's CLI tool). De installer registreert automatisch de MCP server als Claude Code CLI gedetecteerd wordt.

Handmatig registreren:

```bash
# Voeg MCP server toe aan Claude Code
claude mcp add baarn-raadsinformatie -- docker run -i --rm \
  --env-file "/pad/naar/baarn-raadsinformatie/.env" \
  -v "/pad/naar/baarn-raadsinformatie/data:/app/data" \
  -v "/pad/naar/baarn-raadsinformatie/logs:/app/logs" \
  baarn-raadsinformatie:latest

# Bekijk geconfigureerde MCP servers
claude mcp list

# Start Claude Code sessie met MCP tools
claude
> wat zijn de vergaderingen van deze week in Baarn?
```

## OpenAI Codex CLI Configuratie

De MCP server werkt ook met de OpenAI Codex CLI. De installer registreert automatisch de MCP server als Codex CLI gedetecteerd wordt.

Handmatig registreren:

```bash
# Voeg MCP server toe aan Codex
codex mcp add baarn-raadsinformatie -- docker run -i --rm \
  --env-file "/pad/naar/baarn-raadsinformatie/.env" \
  -v "/pad/naar/baarn-raadsinformatie/data:/app/data" \
  -v "/pad/naar/baarn-raadsinformatie/logs:/app/logs" \
  baarn-raadsinformatie:latest

# Bekijk geconfigureerde MCP servers
codex mcp list

# Test de server
codex
> wat zijn de vergaderingen van deze week in Baarn?
```

De server is dan beschikbaar als MCP tooling binnen CLI sessies.

## Cursor IDE Configuratie

Cursor IDE ondersteunt MCP native. De configuratie staat in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "baarn-raadsinformatie": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", ".env",
               "-v", "./data:/app/data", "baarn-raadsinformatie:latest"]
    }
  }
}
```

## Continue.dev Configuratie

Voor Continue.dev (VS Code/JetBrains), zie `.continue/config.json`:

```json
{
  "experimental": {
    "modelContextProtocolServers": [{
      "transport": {
        "type": "stdio",
        "command": "docker",
        "args": ["run", "-i", "--rm", "--env-file", ".env",
                 "-v", "./data:/app/data", "baarn-raadsinformatie:latest"]
      }
    }]
  }
}
```

## Cline (Claude Dev) Configuratie

Cline is een VS Code extensie voor AI-assisted coding. Configuratie in `.vscode/settings.json`:

```json
{
  "cline.mcpServers": {
    "baarn-raadsinformatie": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", "${workspaceFolder}/.env",
               "-v", "${workspaceFolder}/data:/app/data",
               "baarn-raadsinformatie:latest"]
    }
  }
}
```

Installeer de [Cline extensie](https://marketplace.visualstudio.com/items?itemName=saoudrizwan.claude-dev) in VS Code.

## Aider Configuratie

Aider is een CLI tool voor AI-assisted coding. Configuratie in `.aider.conf.yml`:

```yaml
model: claude-3-5-sonnet-20241022
edit-format: diff
auto-commits: true

# Context bestanden
read:
  - README.md
  - progress.md
```

Installeer en gebruik:

```bash
pip install aider-chat
cd baarn-raadsinformatie
aider

# Vraag om context via API
/run curl -s http://localhost:8000/api/meetings?limit=5
```

## Zed Editor Configuratie

Zed Editor heeft native MCP support. Configuratie in `.zed/settings.json`:

```json
{
  "context_servers": {
    "baarn-raadsinformatie": {
      "command": {
        "path": "docker",
        "args": ["run", "-i", "--rm", "--env-file", ".env",
                 "-v", "./data:/app/data", "baarn-raadsinformatie:latest"]
      }
    }
  },
  "assistant": {
    "default_model": {
      "provider": "anthropic",
      "model": "claude-3-5-sonnet-20241022"
    }
  }
}
```

Download Zed van [zed.dev](https://zed.dev).

## Windsurf Configuratie

Windsurf is een AI-first code editor. Configuratie in `.windsurf/mcp.json`:

```json
{
  "mcpServers": {
    "baarn-raadsinformatie": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", "${workspaceFolder}/.env",
               "-v", "${workspaceFolder}/data:/app/data",
               "baarn-raadsinformatie:latest"]
    }
  }
}
```

Cascade configuratie in `.windsurf/cascade.json` bevat custom commands voor vergaderingen en documenten zoeken.

## Microsoft Copilot Studio

Importeer `configs/copilot-studio-connector.json` als Custom Connector:
1. Ga naar Power Platform Admin Center
2. Maak een Custom Connector met de OpenAPI spec
3. Vervang `YOUR_API_HOST` met je publieke API URL

## Ollama (Lokale LLM)

Zie [docs/ollama-integration.md](docs/ollama-integration.md) voor integratie met lokale LLMs.

## REST API & ChatGPT Custom GPT

De server bevat ook een REST API die je kunt gebruiken voor ChatGPT Custom GPT Actions.

### API Server starten

```bash
# Direct
python api_server.py

# Of via Docker
docker compose up api-server -d
```

De API is beschikbaar op `http://localhost:8000`:
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

### API key roteren

De API gebruikt de `API_KEY` uit `.env`. Je kunt deze lokaal roteren met:

```bash
# Cross-platform (Python)
python scripts/rotate_api_key.py

# macOS/Linux
./scripts/rotate_api_key.sh

# Windows PowerShell
./scripts/rotate_api_key.ps1
```

Herstart daarna je services zodat de nieuwe key actief is.

### ChatGPT Custom GPT Setup

1. **Deploy de API** naar een publieke URL (bijv. via ngrok, Cloudflare Tunnel, of een server)

2. **Maak een Custom GPT** in ChatGPT:
   - Ga naar [ChatGPT](https://chat.openai.com) → Explore GPTs → Create
   - Geef het een naam: "Baarn Raadsinformatie Assistent"

3. **Configureer Actions**:
   - Klik op "Configure" → "Create new action"
   - Import de OpenAPI schema van `/openapi.json` of kopieer uit `openapi.json`
   - Vervang de server URL met jouw publieke URL

4. **Authenticatie**:
   - Kies "API Key" als authentication type
   - Auth Type: "Custom"
   - Custom Header Name: `X-API-Key`
   - Voer je API key in (zie `.env` file)

5. **Instructies** voor de GPT:
   ```
   Je bent een assistent voor politieke informatie over gemeente Baarn.
   Gebruik de beschikbare actions om vergaderingen, documenten en
   coalitieakkoord informatie op te halen. Geef altijd bronverwijzingen.
   ```

### API Endpoints

| Endpoint | Methode | Beschrijving |
|----------|---------|--------------|
| `/api/meetings` | GET | Vergaderingen ophalen |
| `/api/meetings/{id}` | GET | Vergadering details |
| `/api/meetings/{id}/agenda` | GET | Agendapunten |
| `/api/documents/{id}` | GET | Document ophalen |
| `/api/documents/search` | GET | Keyword zoeken |
| `/api/documents/semantic-search` | GET | Semantisch zoeken |
| `/api/gremia` | GET | Commissies ophalen |
| `/api/coalitie` | GET | Coalitieakkoord |
| `/api/statistics` | GET | Database statistieken |
| `/api/annotations` | GET/POST | Annotaties |

### Lokale Upload Portal

De REST API bevat een lokale uploader op `http://localhost:8000/upload`.
Deze pagina vereist de `X-API-Key` en gebruikt dezelfde opslag/extractie als de MCP tools.
Je kunt hier bestanden uploaden (PDF/DOCX/PPTX/XLSX) en optioneel direct een werkbezoek-verslag aanmaken.

Gebruik in Docker:
```bash
docker compose up api-server -d
# bezoek http://localhost:8000/upload en vul je API key in
```

## Environment Variables

| Variable | Beschrijving | Default |
|----------|-------------|---------|
| `NOTUBIZ_API_URL` | Notubiz API URL | `https://api.notubiz.nl` |
| `NOTUBIZ_API_TOKEN` | API token | - |
| `FORCE_ORCHESTRATOR` | Forceer routing via orchestrator prompt | `true` |
| `ORCHESTRATOR_AGENT_NAME` | Naam van de orchestrator agent | `orchestrator` |
| `STORE_FILES_IN_DB` | Sla bestanden op in de database | `true` |
| `MAX_FILE_SIZE_MB` | Max bestandsgrootte voor DB opslag | `25` |
| `LOG_LEVEL` | Log level | `INFO` |
| `AUTO_SYNC_ENABLED` | Auto sync aan/uit | `true` |
| `AUTO_SYNC_DAYS` | Dagen terug bij sync | `365` |
| `EMBEDDINGS_ENABLED` | Semantic search | `true` |

### GitHub Actions Variables (CI)

Stel de volgende repo variables in via **Settings → Secrets and variables → Actions → Variables**:

| Variable | Waarde |
|----------|--------|
| `FORCE_ORCHESTRATOR` | `true` |
| `ORCHESTRATOR_AGENT_NAME` | `orchestrator` |

## Semantic Search

Semantic search met embeddings is standaard ingeschakeld. De benodigde dependencies (`sentence-transformers` en `torch`) staan in `requirements.txt`.

Bij de eerste zoekopdracht wordt het embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) automatisch gedownload.

## API Bronnen

Deze server haalt data op via de [Notubiz API](https://api.notubiz.nl):

- Vergaderingen en agenda's
- Raadsstukken en documenten
- Commissies en gremia
- Besluiten en moties

## Licentie

MIT License - zie [LICENSE](LICENSE) voor details.

## Bijdragen

Bijdragen zijn welkom! Open een issue of pull request.

## Contact

- **Gemeente**: Baarn
- **Data bron**: [Notubiz Baarn](https://baarn.notubiz.nl)
