# Baarn Raadsinformatie MCP Server - Voortgangslog

## Project Informatie
- **Naam:** baarn-raadsinformatie
- **Versie:** 3.0.0
- **Doel:** MCP server met agents voor politieke documenten gemeente Baarn via Notubiz
- **Gestart:** 2025-01-19
- **Status:** PRODUCTION READY - DebatRijk-achtige Functionaliteit

## Features v3.0 (DebatRijk Upgrade)
- **Automatische sync** - Data wordt automatisch opgehaald bij eerste start
- **MCP Tools** - 59 tools voor data access, dossiers, transcriptie, samenvattingen
- **MCP Prompts (Agents)** - 29 gerichte agents geladen uit YAML bestanden
- **MCP Resources** - Directe toegang tot vergaderingen en documenten
- **Semantic Search** - VERPLICHT - AI-gebaseerd zoeken met embeddings
- **Docker support** - Background sync service met container
- **Werkbezoek-verslagen** - Import/handmatig toevoegen met tools en metadata
- **Video/Audio Transcriptie** - Whisper lokaal (small model) voor vergaderingen
- **Automatische Dossiers** - Tijdlijn generatie per onderwerp
- **Document Generatie** - Moties en amendementen in Word formaat
- **Standpunten Tracking** - Partij en raadslid standpunten met bronverwijzingen
- **Verkiezingsprogramma's** - Zoeken en vergelijken van partijstandpunten

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

## MCP Tools (59 totaal)

### Basis Tools

| Tool | Beschrijving |
|------|-------------|
| `get_meetings` | Vergaderingen ophalen met filters |
| `get_meeting_details` | Details van een vergadering |
| `get_agenda_items` | Agendapunten ophalen |
| `get_document` | Document met inhoud en URL ophalen |
| `search_documents` | Keyword zoeken met document URLs |
| `semantic_search` | AI zoeken op betekenis (VERPLICHT) |
| `sync_data` | Data synchroniseren |
| `add_annotation` | Notities toevoegen |
| `get_annotations` | Notities ophalen |
| `get_gremia` | Commissies ophalen |
| `get_statistics` | Database statistieken |
| `get_notubiz_status` | Notubiz API configuratie en auth status |

### Historische Data & Dossiers

| Tool | Beschrijving |
|------|-------------|
| `search_and_sync` | Zoek historische data en sync relevante vergaderingen |
| `get_upcoming_meetings` | Aankomende vergaderingen (vandaag, morgen, week, maand) |
| `create_dossier` | Maak automatisch dossier/tijdlijn voor een onderwerp |
| `get_dossier` | Haal dossier op met alle tijdlijn items |
| `list_dossiers` | Lijst bestaande dossiers |
| `get_dossier_timeline` | Genereer markdown tijdlijn |

### Coalitie & Beleid

| Tool | Beschrijving |
|------|-------------|
| `get_coalitie_akkoord` | Coalitieakkoord informatie en voortgang |
| `update_coalitie_afspraak` | Status coalitie-afspraak updaten |

### Media & Broadcasts

| Tool | Beschrijving |
|------|-------------|
| `get_upcoming_broadcasts` | Aankomende live uitzendingen |
| `get_meeting_video` | Video/stream URL voor vergadering |
| `get_media_info` | Media informatie voor meerdere vergaderingen |
| `get_organization_info` | Organisatie info inclusief logo en settings |

### Verkiezingsprogramma's

| Tool | Beschrijving |
|------|-------------|
| `list_parties` | Lijst politieke partijen (actief en historisch) |
| `sync_parties` | Synchroniseer partijen van gemeente website |
| `get_party_sync_status` | Status partij-synchronisatie |
| `search_election_programs` | Zoek in verkiezingsprogramma's |
| `compare_party_positions` | Vergelijk partijstandpunten |
| `get_party_history` | Historische ontwikkeling partijstandpunt |

### Document Generatie

| Tool | Beschrijving |
|------|-------------|
| `generate_motie` | Genereer motie in Word formaat |
| `generate_amendement` | Genereer amendement in Word formaat |

### Standpunten Tracking

| Tool | Beschrijving |
|------|-------------|
| `add_standpunt` | Voeg politiek standpunt toe |
| `search_standpunten` | Zoek standpunten met filters |
| `compare_standpunten` | Vergelijk standpunten over onderwerp |
| `get_standpunt_history` | Historische ontwikkeling standpunten |
| `get_party_context` | Context voor party-aligned antwoorden |
| `list_raadsleden` | Lijst raadsleden, wethouders, steunfractieleden |
| `add_raadslid` | Voeg raadslid toe |
| `verify_standpunt` | Markeer standpunt als geverifieerd |
| `get_standpunt_topics` | Lijst standpunt-topics |

### Werkbezoek Verslagen

| Tool | Beschrijving |
|------|-------------|
| `add_visit_report` | Voeg werkbezoek-verslag toe |
| `import_visit_reports` | Maak verslagen van bestaande documenten |
| `list_visit_reports` | Lijst werkbezoek-verslagen |
| `get_visit_report` | Haal werkbezoek-verslag op |
| `search_visit_reports` | Zoek in werkbezoek-verslagen |
| `update_visit_report` | Werk metadata bij |

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

Orchestrator routing via `.env`:
```
FORCE_ORCHESTRATOR=true
ORCHESTRATOR_AGENT_NAME=orchestrator
```

Bestandsopslag via `.env`:
```
STORE_FILES_IN_DB=true
MAX_FILE_SIZE_MB=25
```

## Projectstructuur

```
baarn-raadsinformatie/
├── mcp_server.py              # MCP server met tools, prompts, resources
├── api_server.py              # REST API voor ChatGPT/Copilot Studio
├── sync_service.py            # Background sync daemon
├── install.ps1                # Windows PowerShell installer
├── install.sh                 # macOS/Linux bash installer
├── install.bat                # Windows batch wrapper
├── start.ps1                  # Windows service management
├── start.sh                   # macOS/Linux service management
├── copilot-studio-connector.json  # MS Copilot Studio OpenAPI spec
├── Dockerfile                 # Multi-stage Docker build
├── docker-compose.yml         # Docker orchestration
├── .dockerignore              # Docker build exclusions
├── pyproject.toml
├── requirements.txt
├── requirements-embeddings.txt
├── .env.example
├── progress.md
│
├── .cursor/                   # Cursor IDE configuratie
│   └── mcp.json               # MCP server config
│
├── .continue/                 # Continue.dev configuratie
│   └── config.json            # MCP + models config
│
├── .github/
│   └── copilot-instructions.md  # GitHub Copilot context
│
├── docs/
│   └── ollama-integration.md  # Ollama lokale LLM integratie
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

### 2026-01-21
- **AI Platform Support v2.3:**
  - Analyse van Codex CLI chat historie voor verbeterpunten
  - Document URLs toegevoegd aan API responses:
    - `get_document` retourneert nu `url` en `notubiz_url` velden
    - `search_documents` retourneert nu `url` per resultaat
    - `get_meeting_details` retourneert nu `url` per document
  - Nieuwe tool: `get_upcoming_meetings` voor periode-gebaseerde queries
    - Ondersteunt: today, tomorrow, this_week, next_week, this_month
    - Handig voor vragen als "wat staat er morgen op de agenda?"
  - REST API uitgebreid met `/api/meetings/upcoming` endpoint
  - GitHub Copilot ondersteuning: `.github/copilot-instructions.md`
  - OpenAI Codex CLI documentatie in README.md
  - Totaal 15 MCP tools

- **AI Platform Ondersteuning Status:**
  | Platform | Status | Integratie |
  |----------|--------|------------|
  | Claude Desktop | ✅ Volledig | MCP native |
  | Claude Code CLI | ✅ Volledig | `claude mcp add` (auto) |
  | OpenAI Codex CLI | ✅ Volledig | `codex mcp add` (auto) |
  | ChatGPT Custom GPT | ✅ Volledig | REST API |
  | GitHub Copilot | ✅ Basis | copilot-instructions.md |
  | Cursor IDE | ✅ Volledig | `.cursor/mcp.json` |
  | Continue.dev | ✅ Volledig | `.continue/config.json` |
  | MS Copilot Studio | ✅ Volledig | OpenAPI connector |
  | Ollama (lokaal) | ✅ Volledig | `docs/ollama-integration.md` |
  | Cline (Claude Dev) | ✅ Volledig | `.vscode/settings.json` |
  | Aider | ✅ Volledig | `.aider.conf.yml` |
  | Zed Editor | ✅ Volledig | `.zed/settings.json` |
  | Windsurf | ✅ Volledig | `.windsurf/mcp.json` |
  | Google Gemini | ❌ Niet ondersteund | - |

- **Verbeteringen n.a.v. chat historie analyse:**
  - Document URLs worden nu correct geretourneerd (notubiz_id → URL)
  - Datumgebaseerde queries vereenvoudigd met get_upcoming_meetings
  - Betere documentatie voor multi-AI platform support

- **Nieuwe AI Platform Configuraties (v2.3.1):**
  - Cursor IDE: `.cursor/mcp.json` met MCP server config
  - Continue.dev: `.continue/config.json` met MCP + custom commands
  - Microsoft Copilot Studio: `copilot-studio-connector.json` OpenAPI spec
  - Ollama: `docs/ollama-integration.md` met lokale LLM integratie

- **Installatiescripts (v2.3.2):**
  - `install.ps1` - Windows PowerShell installer
  - `install.sh` - macOS/Linux bash installer
  - `install.bat` - Windows batch wrapper (start als Administrator)
  - `start.ps1` / `start.sh` - Service management scripts
  - `.dockerignore` - Optimaliseer Docker builds
  - Features:
    - Automatische Docker Desktop installatie
    - Multi-stage Docker builds met caching
    - Detectie en configuratie van 12 AI tools
    - Lichtgewicht build optie (`--light`) zonder embeddings
    - Unieke API key generatie per installatie
    - Volledige env_file support in docker-compose.yml

- **Extra AI Clients (v2.3.3):**
  - Cline (Claude Dev): `.vscode/settings.json` met MCP config
  - Aider: `.aider.conf.yml` met project-specifieke settings
  - Zed Editor: `.zed/settings.json` met context_servers
  - Windsurf: `.windsurf/mcp.json` en `cascade.json`
  - Install scripts detecteren nu 12 AI tools automatisch

- **CLI MCP Registratie (v2.3.4):**
  - Automatische MCP registratie bij CLI tools:
    - Claude Code CLI: `claude mcp add` registratie
    - OpenAI Codex CLI: `codex mcp add` registratie
  - Install scripts detecteren nu 14 AI tools:
    - Nieuw: Claude Code CLI, OpenAI Codex CLI
  - Automatische registratie bij installatie als CLI tools aanwezig zijn
  - README.md uitgebreid met CLI configuratie instructies

- **Claude Auto-Installatie & Chromebook Support (v2.3.5):**
  - Automatische Claude installatie indien niet aanwezig:
    - Windows: Claude Desktop via winget of directe download
    - macOS: Claude Desktop via Homebrew cask of DMG download
    - Linux/Chromebook: Claude Code CLI via npm
  - Nieuwe optie `--skip-claude` / `-SkipClaude` om installatie over te slaan
  - Chromebook/ChromeOS (Crostini) ondersteuning:
    - Automatische detectie van ChromeOS omgeving
    - Node.js auto-installatie indien nodig
    - Claude Code CLI als alternatief voor Desktop
  - Node.js auto-installatie (alleen indien Claude CLI nodig is):
    - Windows: via winget of directe MSI download
    - Linux: via NodeSource LTS repository
  - README.md uitgebreid met Chromebook installatie instructies

- **DebatRijk Upgrade v3.0.0:**
  - **Semantic Search VERPLICHT** - sentence-transformers en torch nu verplichte dependencies
  - **59 MCP Tools** (was 15) - uitgebreide functionaliteit
  - **29 Agents** (was 24) - nieuwe gespecialiseerde agents toegevoegd
  - **Nieuwe Providers:**
    - `dossier_provider.py` - Automatische dossier/tijdlijn generatie
    - `transcription_provider.py` - Video/audio transcriptie met Whisper
    - `summary_provider.py` - AI samenvattingen van documenten/vergaderingen
    - `document_generator.py` - Motie/amendement generatie in Word formaat
    - `election_program_provider.py` - Verkiezingsprogramma zoeken
    - `standpunt_provider.py` - Standpunten tracking per partij/raadslid
    - `visit_report_provider.py` - Werkbezoek-verslagen beheer
  - **Notubiz Client Verbeteringen:**
    - 9 nieuwe API methoden gebaseerd op HAR-analyse
    - `get_media()` - Video/audio informatie voor transcriptie
    - `get_encoder_plannings()` - Broadcast planning
    - `get_upcoming_broadcasts()` - Aankomende livestreams
    - `get_video_url_for_meeting()` - Video URL extractie
    - `get_organization_details()` - Organisatie informatie
    - Verbeterde `get_events()` met meer filters (sort, broadcast, canceled)
  - **Historische Data Tools:**
    - `search_and_sync` - Zoek vanaf 2010, sync alleen relevante data
    - `create_dossier` - Automatisch dossier/tijdlijn per onderwerp
    - `get_party_history` - Historische partijstandpunten
    - `get_standpunt_history` - Ontwikkeling standpunten over tijd
  - **Document Ondersteuning:**
    - Word (DOCX), PowerPoint (PPTX), Excel (XLSX) extractie
    - PDF extractie met tekst en afbeeldingen
  - **FFmpeg Installatie:**
    - Toegevoegd aan install.ps1 en install.sh
    - Vereist voor video/audio transcriptie met Whisper
  - **Database Schema Uitbreidingen:**
    - `transcriptions` tabel voor video transcripties
    - `transcription_embeddings` voor semantic search in transcripties
    - `summaries` tabel voor AI samenvattingen
    - `dossiers` en `dossier_items` voor tijdlijnen
    - `standpunten` en `standpunt_topics` voor standpunten tracking
    - `political_parties` en `raadsleden` tabellen
    - `visit_reports` en `visit_report_documents` tabellen

## Agents voor Historisch Onderzoek

De volgende agents zijn specifiek ontworpen voor historisch onderzoek:

| Agent | Functie | Primaire Tools |
|-------|---------|----------------|
| `beleids-onderzoeker` | Reconstrueert besluitvormingstrajecten en chronologieën | `search_documents`, `semantic_search`, `get_meetings`, `create_dossier` |
| `document-zoeker` | Zoekt documenten met periode-filter | `search_documents`, `semantic_search`, `get_document` |
| `besluit-tracker` | Volgt besluiten over de tijd, maakt tijdlijnen | `get_meetings`, `get_agenda_items`, `search_documents` |
| `journalist-assistent` | Achtergrondonderzoek en factchecking | `search_documents`, `semantic_search`, `create_dossier` |
| `vergadering-analist` | Analyseert vergaderingen over een periode | `get_meetings`, `get_meeting_details`, `search_documents` |
| `externe-onderzoeker` | Vergelijkt met andere gemeenten | `search_documents`, `semantic_search`, web search |

### Typische Workflow Historisch Onderzoek

```
1. search_and_sync(query="Paleis Soestdijk", start_date="2010-01-01")
2. create_dossier(topic="Paleis Soestdijk")
3. Gebruik beleids-onderzoeker agent voor analyse
```
