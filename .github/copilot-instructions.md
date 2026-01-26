# Baarn Raadsinformatie - GitHub Copilot Instructions

Dit is een MCP (Model Context Protocol) server voor toegang tot politieke documenten van de gemeente Baarn via de Notubiz API.

## Project Structuur

- `mcp_server.py` - Hoofd MCP server met tools, prompts en resources
- `api_server.py` - REST API server voor ChatGPT Custom GPT integratie
- `sync_service.py` - Achtergrond synchronisatie service
- `core/` - Database, configuratie, embeddings index
- `providers/` - Notubiz API client, meeting/document providers
- `agents/` - YAML gedefinieerde AI agents (24 stuks)
- `analyzers/` - Zoek functionaliteit

## Belangrijke Patterns

### MCP Tools
Tools worden gedefinieerd in `mcp_server.py` met `@server.list_tools()` en `@server.call_tool()` decorators. Elke tool heeft:
- Een `Tool` definitie met naam, beschrijving en inputSchema
- Een handler in `handle_tool()` functie

### Database
SQLite database met tabellen: gremia, meetings, agenda_items, documents, annotations, embeddings.
Gebruik `get_database()` singleton voor toegang.

### Providers
Singleton pattern met `get_*_provider()` functies:
- `get_meeting_provider()` - Vergaderingen en agenda's
- `get_document_provider()` - Documenten en tekst extractie
- `get_search_sync_provider()` - Gerichte sync op zoekterm

### Agents
Agents worden geladen uit `agents/*.yaml` bestanden. Elk bestand bevat:
- `name`: Agent identificatie
- `prompt.description`: Korte beschrijving
- `prompt.arguments`: Verwachte parameters
- `system_prompt`: Instructies voor de AI

## Code Conventies

- Nederlands voor gebruikersgerichte tekst (tool descriptions, prompts)
- Engels voor code comments en variabelen
- Type hints gebruiken waar mogelijk
- Logging via `shared.logging_config.get_logger()`

## Notubiz API

Publieke API op `https://api.notubiz.nl`. Document URLs volgen het patroon:
```
https://api.notubiz.nl/document/{notubiz_id}/1
```

## Docker

Services gedefinieerd in `docker-compose.yml`:
- `api-server` - REST API op poort 8000
- `mcp-server` - MCP server (stdio)
- `sync-service` - Achtergrond synchronisatie

## AI Platform Integraties

### Claude Desktop (MCP)
Configuratie in `claude_desktop_config.json`:
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

### OpenAI Codex CLI
Configuratie via `codex mcp add`:
```bash
codex mcp add baarn-raadsinformatie -- docker run -i --rm \
  --env-file ".env" -v "./data:/app/data" baarn-raadsinformatie:latest
```

### ChatGPT Custom GPT
Gebruik de REST API endpoints:
- OpenAPI spec: `http://localhost:8000/openapi.json`
- Authenticatie: `X-API-Key` header

## Test Commando's

```bash
# MCP server direct draaien
python mcp_server.py

# REST API draaien
python api_server.py

# Docker build en run
docker compose up -d api-server
docker compose logs -f

# Tests (indien aanwezig)
pytest
```
