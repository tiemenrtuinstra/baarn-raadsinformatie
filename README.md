# Baarn Raadsinformatie MCP Server

[![CI/CD](https://github.com/tiemenrtuinstra/baarn-raadsinformatie/actions/workflows/ci.yml/badge.svg)](https://github.com/tiemenrtuinstra/baarn-raadsinformatie/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-1.0+-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Een **Model Context Protocol (MCP) server** die AI-assistenten toegang geeft tot politieke documenten en vergaderingen van de gemeente Baarn via de Notubiz API.

## Features

- **13 MCP Tools** - Vergaderingen, documenten, zoeken, annotaties
- **24 AI Agents** - Gespecialiseerde prompts voor verschillende taken
- **MCP Resources** - Directe toegang tot vergadering- en documentdata
- **Semantic Search** - AI-gebaseerd zoeken met embeddings (optioneel)
- **Automatische Sync** - Achtergrond synchronisatie met Notubiz API
- **Docker Support** - Containerized deployment

## Snel Starten

### Vereisten

- Python 3.11+
- pip

### Installatie

```bash
# Clone repository
git clone https://github.com/tiemenrtuinstra/baarn-raadsinformatie.git
cd baarn-raadsinformatie

# Maak virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Installeer dependencies
pip install -r requirements.txt

# Kopieer environment file
copy .env.example .env
```

### Claude Desktop Configuratie

Voeg toe aan `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "baarn-raadsinformatie": {
      "command": "python",
      "args": ["C:\\pad\\naar\\baarn-raadsinformatie\\mcp_server.py"]
    }
  }
}
```

Herstart Claude Desktop en de MCP server is beschikbaar.

## Architectuur

```
baarn-raadsinformatie/
├── mcp_server.py           # MCP server entry point
├── sync_service.py         # Background sync daemon
├── agents/                 # 24 AI agent definities (YAML)
├── core/
│   ├── config.py           # Configuratie
│   ├── database.py         # SQLite database
│   ├── document_index.py   # Embeddings index
│   └── coalitie_tracker.py # Coalitieakkoord tracking
├── providers/
│   ├── notubiz_client.py   # Notubiz API client
│   ├── meeting_provider.py # Vergaderingen
│   └── document_provider.py# Documenten
├── analyzers/
│   └── search_analyzer.py  # Gecombineerd zoeken
└── shared/
    └── logging_config.py   # Logging
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

## Environment Variables

| Variable | Beschrijving | Default |
|----------|-------------|---------|
| `NOTUBIZ_API_URL` | Notubiz API URL | `https://api.notubiz.nl` |
| `NOTUBIZ_API_TOKEN` | API token | - |
| `LOG_LEVEL` | Log level | `INFO` |
| `AUTO_SYNC_ENABLED` | Auto sync aan/uit | `true` |
| `AUTO_SYNC_DAYS` | Dagen terug bij sync | `365` |
| `EMBEDDINGS_ENABLED` | Semantic search | `true` |

## Semantic Search (Optioneel)

Voor AI-gebaseerd zoeken:

```bash
pip install -r requirements-embeddings.txt
```

Dit installeert `sentence-transformers` en `torch` voor embedding-gebaseerd zoeken.

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
