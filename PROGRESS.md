# Baarn Raadsinformatie MCP Server - Voortgangslog

## Project Informatie
- **Naam:** baarn-raadsinformatie
- **Versie:** 2.0.0
- **Doel:** MCP server met agents voor politieke documenten gemeente Baarn via Notubiz
- **Gestart:** 2025-01-19
- **Status:** READY FOR TESTING

## Features v2.0
- **Automatische sync** - Data wordt automatisch opgehaald bij eerste start
- **MCP Tools** - 13 tools voor data access
- **MCP Prompts (Agents)** - 24 gerichte agents geladen uit YAML bestanden
- **MCP Resources** - Directe toegang tot vergaderingen en documenten
- **Semantic Search** - AI-gebaseerd zoeken met embeddings
- **Docker support** - Background sync service met container

## MCP Agents (Prompts)

Agents worden dynamisch geladen uit `agents/*.yaml` bestanden.

| Agent | Categorie | Beschrijving |
|-------|-----------|-------------|
| `vergadering-analist` | analyse | Analyseert vergaderingen en geeft inzichten |
| `document-zoeker` | zoeken | Doorzoekt politieke documenten op inhoud |
| `besluit-tracker` | monitoring | Volgt besluiten en hun voortgang |
| `raadslid-assistent` | assistent | Ondersteunt raadsleden bij hun werk |
| `vergadering-voorbereiding` | voorbereiding | Bereidt vergaderingen voor met samenvattingen |
| `burger-informant` | publiek | Informeert burgers over lokale politiek |
| `motie-tracker` | monitoring | Volgt moties en amendementen |
| `commissie-monitor` | monitoring | Monitort commissievergaderingen |
| `beleids-onderzoeker` | onderzoek | Onderzoekt beleidsontwikkelingen en historie |
| `journalist-assistent` | media | Ondersteunt journalisten bij onderzoek |
| `rekenkamer-analist` | controle | Analyseert beleid op effectiviteit en rechtmatigheid |
| `externe-onderzoeker` | onderzoek | Zoekt externe bronnen en vergelijkt met andere gemeenten |
| `orchestrator` | meta | Coördineert andere agents voor complexe vragen |
| `multi-gemeente-zoeker` | onderzoek | Doorzoekt Notubiz van andere gemeenten |
| `coalitie-monitor` | monitoring | Volgt uitvoering coalitieakkoord |
| `begrotings-analist` | financieel | Analyseert begrotingen en financiële besluiten |
| `raadsvragen-assistent` | assistent | Helpt bij schriftelijke vragen aan college |
| `actiepunten-tracker` | monitoring | Volgt actiepunten en toezeggingen uit vergaderingen |
| `ingekomen-stukken-tracker` | monitoring | Volgt ingekomen stukken en brieven aan de raad |
| `toezeggingen-tracker` | monitoring | Volgt toezeggingen van college aan raad |
| `stemgedrag-analist` | analyse | Analyseert stempatronen per partij/raadslid |
| `subsidie-tracker` | monitoring | Volgt subsidieaanvragen en -besluiten |
| `woo-assistent` | assistent | Helpt bij Woo-verzoeken (openbaarheid) |
| `personeel-informant` | informatie | Informeert over bestuurders, raadsleden en organisatie |

Zie `agents/README.md` voor details over het toevoegen van nieuwe agents.

## MCP Resources

| Resource | URI Pattern |
|----------|-------------|
| Vergadering details | `baarn://meeting/{id}` |
| Document inhoud | `baarn://document/{id}` |
| Vergaderingen per commissie | `baarn://gremium/{id}/meetings` |

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
| `get_coalitie_akkoord` | Coalitieakkoord informatie en voortgang |
| `update_coalitie_afspraak` | Status coalitie-afspraak updaten |

## Automatische Sync

Bij eerste start (als database leeg is):
1. Gremia (commissies) worden opgehaald
2. Vergaderingen van het laatste jaar worden gesynchroniseerd
3. Documenten worden automatisch gedownload (configureerbaar)
4. Optioneel: embeddings worden geindexeerd

Configuratie via `.env`:
```
AUTO_SYNC_ENABLED=true
AUTO_SYNC_DAYS=365
AUTO_DOWNLOAD_DOCS=true
AUTO_INDEX_DOCS=false
```

## Projectstructuur

```
baarn-raadsinformatie/
├── mcp_server.py              # MCP server met tools, prompts, resources
├── sync_service.py            # Background sync daemon
├── Dockerfile                 # Docker container
├── docker-compose.yml         # Docker orchestration
├── pyproject.toml
├── requirements.txt
├── .env.example
├── PROGRESS.md
│
├── agents/                    # Agent definities (YAML)
│   ├── __init__.py            # Agent loader module
│   ├── README.md              # Agent documentatie
│   ├── vergadering-analist.yaml
│   ├── document-zoeker.yaml
│   ├── besluit-tracker.yaml
│   ├── raadslid-assistent.yaml
│   ├── vergadering-voorbereiding.yaml
│   ├── burger-informant.yaml
│   ├── motie-tracker.yaml
│   ├── commissie-monitor.yaml
│   ├── beleids-onderzoeker.yaml
│   ├── journalist-assistent.yaml
│   ├── rekenkamer-analist.yaml
│   ├── externe-onderzoeker.yaml
│   ├── orchestrator.yaml
│   ├── multi-gemeente-zoeker.yaml
│   ├── coalitie-monitor.yaml
│   ├── begrotings-analist.yaml
│   ├── raadsvragen-assistent.yaml
│   ├── actiepunten-tracker.yaml
│   └── ingekomen-stukken-tracker.yaml
│
├── core/
│   ├── config.py              # Configuratie
│   ├── database.py            # SQLite database
│   ├── document_index.py      # Embeddings index
│   └── coalitie_tracker.py    # Coalitieakkoord tracking
│
├── providers/
│   ├── notubiz_client.py      # Notubiz API client
│   ├── meeting_provider.py    # Vergaderingen
│   └── document_provider.py   # Documenten
│
├── analyzers/
│   └── search_analyzer.py     # Gecombineerd zoeken
│
├── shared/
│   └── logging_config.py      # Logging
│
├── scripts/
│   ├── start_sync_service.bat # Windows start script
│   ├── install_scheduled_task.ps1
│   └── uninstall_scheduled_task.ps1
│
├── data/
│   ├── documents/             # PDFs (optioneel)
│   ├── cache/                 # API cache
│   ├── baarn.db               # Database
│   └── coalitieakkoord.yaml   # Coalitieakkoord data
│
└── logs/
    └── mcp-server.log
```

## Installatie

```bash
cd C:\xampp\htdocs\baarn-politiek-mcp
pip install -r requirements.txt

# Optioneel voor semantic search:
pip install -r requirements-embeddings.txt
```

## Claude Desktop Configuratie

Voeg toe aan `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "baarn-raadsinformatie": {
      "command": "python",
      "args": ["C:\\xampp\\htdocs\\baarn-politiek-mcp\\mcp_server.py"]
    }
  }
}
```

## Gebruik

### Via Tools
```
get_meetings(limit=10, date_from="2024-01-01")
get_document(document_id=123)
search_documents(query="woningbouw")
semantic_search(query="besluiten over duurzaamheid")
```

### Via Agents (Prompts)
Selecteer een agent in Claude Desktop:
- **vergadering-analist** - "Analyseer de vergadering van vorige week"
- **document-zoeker** - "Zoek documenten over woningbouw"
- **besluit-tracker** - "Welke besluiten zijn er genomen over duurzaamheid?"
- **raadslid-assistent** - "Wat zijn de belangrijkste onderwerpen van dit jaar?"

### Via Resources
Directe toegang tot data:
- `baarn://meeting/123` - Vergadering details
- `baarn://document/456` - Document inhoud
- `baarn://gremium/1/meetings` - Alle vergaderingen van een commissie

## Logboek

### 2025-01-19
- Project gestart
- Basis structuur opgezet
- Core modules geimplementeerd

### 2025-01-20
- Providers module afgerond
- MCP Server v1.0 met tools
- **Upgrade naar v2.0:**
  - Automatische sync toegevoegd
  - MCP Prompts (5 Agents) toegevoegd
  - MCP Resources toegevoegd
  - Project hernoemd naar baarn-raadsinformatie
  - Docker support toegevoegd (docker-compose.yml, Dockerfile)
  - Background sync service (sync_service.py)
  - Windows Scheduled Task scripts
  - Storage optimalisatie: PDF → tekst → verwijder PDF (KEEP_PDF_FILES=false)

- **Agent System v2.1:**
  - Agents verplaatst naar YAML bestanden in agents/ directory
  - Agent loader module voor dynamisch laden
  - 5 extra agents toegevoegd (10 totaal):
    - burger-informant, motie-tracker, commissie-monitor
    - beleids-onderzoeker, journalist-assistent
  - Agents documentatie in agents/README.md

- **Agent System v2.2:**
  - 9 extra agents toegevoegd (19 totaal):
    - rekenkamer-analist, externe-onderzoeker
    - orchestrator (meta-agent), multi-gemeente-zoeker
    - coalitie-monitor, begrotings-analist, raadsvragen-assistent
    - actiepunten-tracker, ingekomen-stukken-tracker
  - Coalitieakkoord tracking systeem:
    - data/coalitieakkoord.yaml voor gestructureerde afspraken
    - core/coalitie_tracker.py voor status management
    - 2 nieuwe tools: get_coalitie_akkoord, update_coalitie_afspraak
    - Automatische koppeling van besluiten aan afspraken
  - Totaal 13 MCP tools
