#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baarn Raadsinformatie MCP Server

MCP server met agents voor toegang tot politieke documenten van gemeente Baarn.
Features:
- Automatische data synchronisatie bij opstarten
- MCP Tools voor data access
- MCP Prompts (Agents) voor gerichte taken - geladen uit YAML bestanden
- MCP Resources voor directe data access

Agents worden dynamisch geladen uit de agents/ directory.
Zie agents/*.yaml voor beschikbare agents.
"""

import asyncio
import json
from datetime import date, timedelta
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    Prompt,
    PromptMessage,
    PromptArgument,
    Resource,
    ResourceTemplate,
)

from core.config import Config
from core.database import get_database
from core.document_index import get_document_index
from core.coalitie_tracker import get_coalitie_tracker
from providers.meeting_provider import get_meeting_provider
from providers.document_provider import get_document_provider
from providers.notubiz_client import get_notubiz_client
from providers.search_sync_provider import get_search_sync_provider
from providers.document_generator import get_document_generator
from providers.election_program_provider import get_election_program_provider
from providers.standpunt_provider import get_standpunt_provider
from providers.visit_report_provider import get_visit_report_provider
from agents import get_agent_loader, get_agent
from shared.logging_config import get_mcp_logger

logger = get_mcp_logger()

# Initialize MCP server
server = Server(Config.SERVER_NAME)

# Track if initial sync is done
_initial_sync_done = False


def format_response(data: Any, success: bool = True) -> str:
    """Format response data as JSON string."""
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return str(data)


# ==================== Auto Sync ====================

async def perform_initial_sync():
    """Perform initial data sync if database is empty."""
    global _initial_sync_done

    if _initial_sync_done or not Config.AUTO_SYNC_ENABLED:
        return

    db = get_database()
    stats = db.get_statistics()

    # Check if we need to sync
    if stats.get('meetings', 0) == 0:
        logger.info('Database empty - performing initial sync...')

        meeting_provider = get_meeting_provider()
        doc_provider = get_document_provider()

        # Sync gremia first
        meeting_provider.sync_gremia()

        # Sync meetings
        date_from = (date.today() - timedelta(days=Config.AUTO_SYNC_DAYS)).isoformat()
        meetings, docs = meeting_provider.sync_meetings(
            date_from=date_from,
            full_details=True
        )
        logger.info(f'Initial sync: {meetings} meetings, {docs} documents')

        # Download documents if enabled
        if Config.AUTO_DOWNLOAD_DOCS:
            logger.info('Downloading documents...')
            success, failed = doc_provider.download_pending_documents()
            logger.info(f'Downloaded {success} documents, {failed} failed')

            # Extract text
            doc_provider.extract_all_text()

        # Index documents if enabled
        if Config.AUTO_INDEX_DOCS:
            logger.info('Indexing documents for semantic search...')
            index = get_document_index()
            indexed, chunks = index.index_all_documents()
            logger.info(f'Indexed {indexed} documents, {chunks} chunks')

    _initial_sync_done = True


# ==================== MCP Resources ====================

@server.list_resources()
async def list_resources() -> list[Resource]:
    """List available resources."""
    await perform_initial_sync()

    db = get_database()
    resources = []

    # Add recent meetings as resources
    meetings = db.get_meetings(limit=20)
    for m in meetings:
        resources.append(Resource(
            uri=f"baarn://meeting/{m['id']}",
            name=f"Vergadering: {m['title']}",
            description=f"Vergadering van {m['date']}",
            mimeType="application/json"
        ))

    # Add gremia as resources
    gremia = db.get_gremia()
    for g in gremia:
        resources.append(Resource(
            uri=f"baarn://gremium/{g['id']}",
            name=f"Commissie: {g['name']}",
            description=g.get('description', ''),
            mimeType="application/json"
        ))

    return resources


@server.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    """List resource templates."""
    return [
        ResourceTemplate(
            uriTemplate="baarn://meeting/{meeting_id}",
            name="Vergadering details",
            description="Haal details op van een specifieke vergadering",
            mimeType="application/json"
        ),
        ResourceTemplate(
            uriTemplate="baarn://document/{document_id}",
            name="Document inhoud",
            description="Haal inhoud op van een specifiek document",
            mimeType="application/json"
        ),
        ResourceTemplate(
            uriTemplate="baarn://gremium/{gremium_id}/meetings",
            name="Vergaderingen per commissie",
            description="Alle vergaderingen van een specifieke commissie",
            mimeType="application/json"
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read a specific resource."""
    await perform_initial_sync()

    parts = uri.replace("baarn://", "").split("/")

    if parts[0] == "meeting" and len(parts) >= 2:
        meeting_id = int(parts[1])
        provider = get_meeting_provider()
        meeting = provider.get_meeting(meeting_id=meeting_id)
        return format_response(meeting) if meeting else '{"error": "Meeting not found"}'

    elif parts[0] == "document" and len(parts) >= 2:
        doc_id = int(parts[1])
        provider = get_document_provider()
        doc = provider.get_document(doc_id)
        return format_response(doc) if doc else '{"error": "Document not found"}'

    elif parts[0] == "gremium" and len(parts) >= 2:
        gremium_id = int(parts[1])
        db = get_database()

        if len(parts) >= 3 and parts[2] == "meetings":
            meetings = db.get_meetings(gremium_id=gremium_id, limit=100)
            return format_response({"gremium_id": gremium_id, "meetings": meetings})
        else:
            gremia = db.get_gremia()
            gremium = next((g for g in gremia if g['id'] == gremium_id), None)
            return format_response(gremium) if gremium else '{"error": "Gremium not found"}'

    return '{"error": "Unknown resource"}'


# ==================== MCP Prompts (Agents) ====================

@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available prompts/agents - dynamically loaded from YAML files."""
    loader = get_agent_loader()
    agents = loader.load_agents()

    if Config.FORCE_ORCHESTRATOR:
        orchestrator = agents.get(Config.ORCHESTRATOR_AGENT_NAME)
        if not orchestrator:
            logger.warning(f"Orchestrator agent not found: {Config.ORCHESTRATOR_AGENT_NAME}")
            return []
        agents = {orchestrator.name: orchestrator}

    prompts = []
    for agent in agents.values():
        prompts.append(Prompt(
            name=agent.name,
            description=agent.prompt.description.strip(),
            arguments=[
                PromptArgument(
                    name=arg.name,
                    description=arg.description,
                    required=arg.required
                )
                for arg in agent.prompt.arguments
            ]
        ))

    logger.info(f'Loaded {len(prompts)} agents from YAML files')
    return prompts


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None) -> list[PromptMessage]:
    """Get a specific prompt/agent - loads system prompt from YAML."""
    await perform_initial_sync()

    if Config.FORCE_ORCHESTRATOR and name != Config.ORCHESTRATOR_AGENT_NAME:
        logger.info(f"Routing prompt '{name}' to orchestrator")
        name = Config.ORCHESTRATOR_AGENT_NAME

    args = arguments or {}

    # Try to get agent from YAML files
    agent = get_agent(name)

    if agent:
        # Build context based on arguments
        context = await _build_agent_context(name, args)

        # Combine system prompt with context
        full_prompt = f"""{agent.system_prompt}

{context}

Begin nu met je taak. Gebruik de beschikbare MCP tools om informatie op te halen."""

        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=full_prompt
                )
            )
        ]

    # Fallback to hardcoded prompts for backwards compatibility
    if name == "vergadering-analist":
        return await _prompt_vergadering_analist(args)
    elif name == "document-zoeker":
        return await _prompt_document_zoeker(args)
    elif name == "besluit-tracker":
        return await _prompt_besluit_tracker(args)
    elif name == "raadslid-assistent":
        return await _prompt_raadslid_assistent(args)
    elif name == "vergadering-voorbereiding":
        return await _prompt_vergadering_voorbereiding(args)
    else:
        raise ValueError(f"Unknown prompt: {name}")


async def _build_agent_context(name: str, args: dict) -> str:
    """Build context string based on agent name and arguments."""
    context_parts = []

    # Add database stats
    db = get_database()
    stats = db.get_statistics()
    context_parts.append(f"""Database status:
- {stats.get('meetings', 0)} vergaderingen
- {stats.get('documents', 0)} documenten
- {stats.get('agenda_items', 0)} agendapunten""")

    # Add meeting context if meeting_id provided
    if args.get('meeting_id') or args.get('vergadering_id'):
        meeting_id = args.get('meeting_id') or args.get('vergadering_id')
        provider = get_meeting_provider()
        meeting = provider.get_meeting(meeting_id=int(meeting_id))
        if meeting:
            context_parts.append(f"""Geselecteerde vergadering:
- Titel: {meeting['title']}
- Datum: {meeting['date']}
- ID: {meeting['id']}""")

    # Add search context
    if args.get('onderwerp') or args.get('zoekterm'):
        query = args.get('onderwerp') or args.get('zoekterm')
        context_parts.append(f"Zoekonderwerp: {query}")

    if args.get('periode'):
        context_parts.append(f"Periode: {args['periode']}")

    if args.get('vraag'):
        context_parts.append(f"Gebruikersvraag: {args['vraag']}")

    if args.get('status'):
        context_parts.append(f"Status filter: {args['status']}")

    if args.get('partij'):
        context_parts.append(f"Partij filter: {args['partij']}")

    if args.get('commissie'):
        context_parts.append(f"Commissie: {args['commissie']}")

    return "\n\n".join(context_parts)


async def _prompt_vergadering_analist(args: dict) -> list[PromptMessage]:
    """Generate vergadering-analist prompt."""
    meeting_data = ""
    provider = get_meeting_provider()

    if args.get('meeting_id'):
        meeting = provider.get_meeting(meeting_id=int(args['meeting_id']))
        if meeting:
            meeting_data = f"\n\nVergadering data:\n{format_response(meeting)}"

    focus = args.get('focus', '')
    focus_instruction = f"\nFocus specifiek op: {focus}" if focus else ""

    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Je bent een vergadering-analist voor de gemeente Baarn.
Je taak is om vergaderingen te analyseren en heldere samenvattingen te maken.

Gebruik de beschikbare tools om:
1. Vergadering details op te halen (get_meeting_details)
2. Agendapunten te bekijken (get_agenda_items)
3. Relevante documenten te lezen (get_document)
4. Te zoeken naar gerelateerde informatie (search_documents, semantic_search)

Maak een analyse met:
- Korte samenvatting van de vergadering
- Belangrijkste agendapunten
- Genomen besluiten
- Actiepunten en vervolgstappen
- Relevante context uit eerdere vergaderingen
{focus_instruction}{meeting_data}

Begin met het ophalen van de benodigde informatie."""
            )
        )
    ]


async def _prompt_document_zoeker(args: dict) -> list[PromptMessage]:
    """Generate document-zoeker prompt."""
    onderwerp = args.get('onderwerp', 'algemeen')
    periode = args.get('periode', '')

    periode_instruction = f"\nZoek binnen periode: {periode}" if periode else ""

    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Je bent een document-zoeker voor de gemeente Baarn.
Je helpt bij het vinden van relevante documenten over specifieke onderwerpen.

Onderwerp: {onderwerp}
{periode_instruction}

Gebruik de beschikbare tools om:
1. Te zoeken op keywords (search_documents)
2. Semantisch te zoeken op betekenis (semantic_search)
3. Documenten te lezen (get_document)
4. Gerelateerde vergaderingen te vinden (get_meetings)

Geef voor elk gevonden document:
- Titel en datum
- Relevantie voor het onderwerp
- Korte samenvatting van de inhoud
- Link naar de vergadering

Begin met een brede zoektocht en verfijn dan de resultaten."""
            )
        )
    ]


async def _prompt_besluit_tracker(args: dict) -> list[PromptMessage]:
    """Generate besluit-tracker prompt."""
    onderwerp = args.get('onderwerp', 'algemeen')
    status = args.get('status', '')

    status_instruction = f"\nFilter op status: {status}" if status else ""

    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Je bent een besluit-tracker voor de gemeente Baarn.
Je volgt besluiten, moties en amendementen over specifieke onderwerpen.

Onderwerp: {onderwerp}
{status_instruction}

Gebruik de beschikbare tools om:
1. Vergaderingen te doorzoeken (get_meetings, search_documents)
2. Agendapunten te analyseren (get_agenda_items)
3. Documenten te lezen voor besluitvorming (get_document)

Maak een overzicht van:
- Relevante moties en amendementen
- Genomen besluiten (aangenomen/verworpen)
- Stemverhoudingen indien beschikbaar
- Vervolgacties en deadlines
- Tijdlijn van de besluitvorming

Sorteer chronologisch en geef context bij elk besluit."""
            )
        )
    ]


async def _prompt_raadslid_assistent(args: dict) -> list[PromptMessage]:
    """Generate raadslid-assistent prompt."""
    vraag = args.get('vraag', 'Hoe kan ik je helpen?')

    # Get some context
    db = get_database()
    stats = db.get_statistics()

    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Je bent een assistent voor raadsleden van de gemeente Baarn.
Je hebt toegang tot alle vergaderingen, documenten en besluiten.

Database status:
- {stats.get('meetings', 0)} vergaderingen
- {stats.get('documents', 0)} documenten
- {stats.get('agenda_items', 0)} agendapunten

Vraag van het raadslid: {vraag}

Gebruik de beschikbare tools om de vraag te beantwoorden:
- get_meetings: Vergaderingen ophalen
- get_meeting_details: Details van een vergadering
- get_document: Document inhoud
- search_documents: Zoeken op keywords
- semantic_search: Zoeken op betekenis
- get_statistics: Database statistieken

Geef een helder en volledig antwoord met bronverwijzingen."""
            )
        )
    ]


async def _prompt_vergadering_voorbereiding(args: dict) -> list[PromptMessage]:
    """Generate vergadering-voorbereiding prompt."""
    meeting_id = args.get('meeting_id')
    datum = args.get('datum')

    context = ""
    if meeting_id:
        provider = get_meeting_provider()
        meeting = provider.get_meeting(meeting_id=int(meeting_id))
        if meeting:
            context = f"\n\nVergadering:\n{meeting['title']} op {meeting['date']}"

    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Je bent een assistent voor vergadervoorbereiding voor de gemeente Baarn.
Je helpt raadsleden bij het voorbereiden op vergaderingen.
{context}

Gebruik de beschikbare tools om:
1. De agenda op te halen (get_meeting_details, get_agenda_items)
2. Bijbehorende documenten te lezen (get_document)
3. Historische context te vinden (search_documents, semantic_search)
4. Eerdere besluiten over dezelfde onderwerpen te vinden

Maak een voorbereidingsdocument met:
- Overzicht van agendapunten
- Samenvatting van elk stuk
- Historische context en eerdere besluiten
- Aandachtspunten en mogelijke discussiepunten
- Suggesties voor vragen

Begin met het ophalen van de vergaderdetails."""
            )
        )
    ]


# ==================== Tool Definitions ====================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    await perform_initial_sync()

    return [
        Tool(
            name="get_meetings",
            description="Haal een lijst van vergaderingen op met optionele filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum aantal resultaten", "default": 20},
                    "date_from": {"type": "string", "description": "Start datum (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "Eind datum (YYYY-MM-DD)"},
                    "search": {"type": "string", "description": "Zoekterm"}
                }
            }
        ),
        Tool(
            name="get_meeting_details",
            description="Haal gedetailleerde informatie op over een specifieke vergadering.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "integer", "description": "Database ID van de vergadering"}
                },
                "required": ["meeting_id"]
            }
        ),
        Tool(
            name="get_agenda_items",
            description="Haal agendapunten op voor een specifieke vergadering.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "integer", "description": "Database ID van de vergadering"}
                },
                "required": ["meeting_id"]
            }
        ),
        Tool(
            name="get_document",
            description="Haal een specifiek document op met metadata en geëxtraheerde tekst.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "integer", "description": "Database ID van het document"}
                },
                "required": ["document_id"]
            }
        ),
        Tool(
            name="search_documents",
            description="Zoek in documenten op titel en inhoud (keyword search).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zoekterm"},
                    "limit": {"type": "integer", "description": "Maximum resultaten", "default": 20}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="semantic_search",
            description="Semantisch zoeken met AI embeddings - vindt documenten op basis van betekenis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zoekvraag in natuurlijke taal"},
                    "limit": {"type": "integer", "description": "Maximum resultaten", "default": 10}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="sync_data",
            description="Synchroniseer data van Notubiz naar de lokale database.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Start datum (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "Eind datum (YYYY-MM-DD)"},
                    "download_documents": {"type": "boolean", "description": "Download documenten", "default": False},
                    "index_documents": {"type": "boolean", "description": "Indexeer voor semantic search", "default": False}
                }
            }
        ),
        Tool(
            name="add_annotation",
            description="Voeg een annotatie/notitie toe.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Inhoud van de annotatie"},
                    "document_id": {"type": "integer", "description": "Document ID (optioneel)"},
                    "meeting_id": {"type": "integer", "description": "Vergadering ID (optioneel)"},
                    "title": {"type": "string", "description": "Titel (optioneel)"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"}
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="get_annotations",
            description="Haal annotaties op.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "integer", "description": "Filter op document"},
                    "meeting_id": {"type": "integer", "description": "Filter op vergadering"},
                    "search": {"type": "string", "description": "Zoekterm"}
                }
            }
        ),
        Tool(
            name="get_gremia",
            description="Haal de lijst van gremia (commissies) op.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_statistics",
            description="Haal statistieken op over de database.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_notubiz_status",
            description="Bekijk de Notubiz API configuratie en auth status. "
            "Toont of historische data toegankelijk is.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_coalitie_akkoord",
            description="Haal coalitieakkoord informatie op met afspraken en voortgang.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thema": {"type": "string", "description": "Filter op thema (bijv: 'wonen', 'duurzaamheid')"},
                    "status": {"type": "string", "description": "Filter op status (niet_gestart, in_voorbereiding, in_uitvoering, gerealiseerd)"}
                }
            }
        ),
        Tool(
            name="update_coalitie_afspraak",
            description="Update de status van een coalitie-afspraak of koppel een besluit.",
            inputSchema={
                "type": "object",
                "properties": {
                    "afspraak_id": {"type": "string", "description": "ID van de afspraak (bijv: 'wonen-001')"},
                    "new_status": {"type": "string", "description": "Nieuwe status"},
                    "link_meeting_id": {"type": "integer", "description": "Meeting ID om te koppelen"}
                },
                "required": ["afspraak_id"]
            }
        ),
        Tool(
            name="search_and_sync",
            description="Zoek naar een specifiek onderwerp in historische data en synchroniseer alleen relevante vergaderingen en documenten. Efficiënter dan volledige sync voor dossiers zoals 'Paleis Soestdijk' of 'De Speeldoos'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zoekterm (bijv: 'Paleis Soestdijk', 'De Speeldoos')"},
                    "start_date": {"type": "string", "description": "Start datum (YYYY-MM-DD)", "default": "2010-01-01"},
                    "end_date": {"type": "string", "description": "Eind datum (YYYY-MM-DD), default vandaag"},
                    "download_documents": {"type": "boolean", "description": "Download documenten en extraheer tekst", "default": True},
                    "index_documents": {"type": "boolean", "description": "Indexeer voor semantic search", "default": True},
                    "limit": {"type": "integer", "description": "Maximum aantal vergaderingen", "default": 100}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_upcoming_meetings",
            description="Haal aankomende vergaderingen op (vandaag, morgen, deze week, volgende week). Handig voor vragen als 'wat staat er morgen op de agenda?'",
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Periode: 'today' (vandaag), 'tomorrow' (morgen), 'this_week' (deze week), 'next_week' (volgende week), 'this_month' (deze maand)",
                        "enum": ["today", "tomorrow", "this_week", "next_week", "this_month"],
                        "default": "this_week"
                    },
                    "include_agenda": {"type": "boolean", "description": "Inclusief agendapunten", "default": True},
                    "include_documents": {"type": "boolean", "description": "Inclusief documenten", "default": False}
                }
            }
        ),
        # ==================== Media/Broadcast Tools ====================
        Tool(
            name="get_upcoming_broadcasts",
            description="Haal aankomende live uitzendingen op. Toont vergaderingen met geplande livestreams.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum aantal resultaten", "default": 10}
                }
            }
        ),
        Tool(
            name="get_meeting_video",
            description="Haal video/stream URL op voor een vergadering. Nuttig voor transcriptie of bekijken van opnames.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "integer", "description": "Vergadering ID (database ID of Notubiz ID)"}
                },
                "required": ["meeting_id"]
            }
        ),
        Tool(
            name="get_media_info",
            description="Haal media informatie (video/audio) op voor meerdere vergaderingen tegelijk.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lijst van event/meeting IDs"
                    }
                },
                "required": ["event_ids"]
            }
        ),
        Tool(
            name="get_organization_info",
            description="Haal organisatie informatie op inclusief logo URL en dashboard instellingen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_settings": {"type": "boolean", "description": "Inclusief dashboard/entity settings", "default": False}
                }
            }
        ),
        # ==================== Verkiezingsprogramma Tools ====================
        Tool(
            name="list_parties",
            description="Lijst alle politieke partijen in Baarn (actief en historisch).",
            inputSchema={
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean", "description": "Alleen actieve partijen", "default": False}
                }
            }
        ),
        Tool(
            name="sync_parties",
            description="Synchroniseer politieke partijen door de gemeente Baarn website te checken voor actuele fracties. Detecteert nieuwe partijen en deactiveert verdwenen partijen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "initialize_known": {"type": "boolean", "description": "Initialiseer ook bekende historische partijen", "default": True}
                }
            }
        ),
        Tool(
            name="get_party_sync_status",
            description="Bekijk de huidige status van partij-synchronisatie: aantal actieve/historische partijen.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="search_election_programs",
            description="Zoek in verkiezingsprogramma's van Baarnse politieke partijen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zoekterm"},
                    "party": {"type": "string", "description": "Filter op partij (naam of afkorting)"},
                    "year_from": {"type": "integer", "description": "Vanaf verkiezingsjaar"},
                    "year_to": {"type": "integer", "description": "Tot verkiezingsjaar"},
                    "limit": {"type": "integer", "description": "Maximum resultaten", "default": 20}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="compare_party_positions",
            description="Vergelijk standpunten van partijen over een specifiek onderwerp.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Onderwerp (bijv: 'woningbouw', 'duurzaamheid', 'verkeer')"},
                    "parties": {"type": "array", "items": {"type": "string"}, "description": "Partijen om te vergelijken (optioneel, standaard alle)"},
                    "year": {"type": "integer", "description": "Specifiek verkiezingsjaar (optioneel)"}
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="get_party_history",
            description="Bekijk historische ontwikkeling van een partijstandpunt over de jaren.",
            inputSchema={
                "type": "object",
                "properties": {
                    "party": {"type": "string", "description": "Partij naam of afkorting"},
                    "topic": {"type": "string", "description": "Onderwerp"}
                },
                "required": ["party", "topic"]
            }
        ),
        # ==================== Document Generatie Tools ====================
        Tool(
            name="generate_motie",
            description="Genereer een motie document in Word formaat conform Notubiz standaard.",
            inputSchema={
                "type": "object",
                "properties": {
                    "titel": {"type": "string", "description": "Titel van de motie"},
                    "indieners": {"type": "array", "items": {"type": "string"}, "description": "Namen van de indieners"},
                    "partijen": {"type": "array", "items": {"type": "string"}, "description": "Partijen van de indieners"},
                    "constateringen": {"type": "array", "items": {"type": "string"}, "description": "Constaterende dat... punten"},
                    "overwegingen": {"type": "array", "items": {"type": "string"}, "description": "Overwegende dat... punten"},
                    "verzoeken": {"type": "array", "items": {"type": "string"}, "description": "Verzoekt het college... punten"},
                    "vergadering_datum": {"type": "string", "description": "Datum vergadering (YYYY-MM-DD)"},
                    "agendapunt": {"type": "string", "description": "Agendapunt nummer"},
                    "toelichting": {"type": "string", "description": "Optionele toelichting"}
                },
                "required": ["titel", "indieners", "partijen", "constateringen", "overwegingen", "verzoeken"]
            }
        ),
        Tool(
            name="generate_amendement",
            description="Genereer een amendement document in Word formaat conform Notubiz standaard.",
            inputSchema={
                "type": "object",
                "properties": {
                    "titel": {"type": "string", "description": "Titel van het amendement"},
                    "indieners": {"type": "array", "items": {"type": "string"}, "description": "Namen van de indieners"},
                    "partijen": {"type": "array", "items": {"type": "string"}, "description": "Partijen van de indieners"},
                    "raadsvoorstel_nummer": {"type": "string", "description": "Nummer van het raadsvoorstel"},
                    "raadsvoorstel_titel": {"type": "string", "description": "Titel van het raadsvoorstel"},
                    "wijzigingen": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "oorspronkelijk": {"type": "string", "description": "Oorspronkelijke tekst"},
                                "wordt": {"type": "string", "description": "Nieuwe tekst"}
                            },
                            "required": ["oorspronkelijk", "wordt"]
                        },
                        "description": "Lijst van tekstwijzigingen"
                    },
                    "toelichting": {"type": "string", "description": "Toelichting op de wijzigingen"},
                    "vergadering_datum": {"type": "string", "description": "Datum vergadering (YYYY-MM-DD)"},
                    "agendapunt": {"type": "string", "description": "Agendapunt nummer"}
                },
                "required": ["titel", "indieners", "partijen", "raadsvoorstel_nummer", "raadsvoorstel_titel", "wijzigingen"]
            }
        ),
        # ==================== Standpunten Tools ====================
        Tool(
            name="add_standpunt",
            description="Voeg een politiek standpunt toe voor een partij of raadslid.",
            inputSchema={
                "type": "object",
                "properties": {
                    "party_id": {"type": "integer", "description": "Partij ID (of raadslid_id)"},
                    "raadslid_id": {"type": "integer", "description": "Raadslid ID (of party_id)"},
                    "topic": {"type": "string", "description": "Onderwerp (bijv: 'Woningbouw', 'Duurzaamheid')"},
                    "position_summary": {"type": "string", "description": "Korte samenvatting van het standpunt"},
                    "position_text": {"type": "string", "description": "Volledige tekst/toelichting"},
                    "stance": {"type": "string", "enum": ["voor", "tegen", "neutraal", "genuanceerd", "onbekend"], "description": "Positie"},
                    "stance_strength": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Sterkte van het standpunt (1-5)"},
                    "source_type": {"type": "string", "enum": ["verkiezingsprogramma", "motie", "amendement", "debat", "stemming", "interview", "persbericht", "website", "anders"], "description": "Type bron"},
                    "source_document_id": {"type": "integer", "description": "Document ID van de bron"},
                    "source_meeting_id": {"type": "integer", "description": "Vergadering ID van de bron"},
                    "source_quote": {"type": "string", "description": "Exacte quote uit de bron"},
                    "position_date": {"type": "string", "description": "Datum van standpunt (YYYY-MM-DD)"},
                    "subtopic": {"type": "string", "description": "Subonderwerp"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"}
                },
                "required": ["topic", "position_summary", "source_type"]
            }
        ),
        Tool(
            name="search_standpunten",
            description="Zoek standpunten met filters op partij, raadslid, topic, stance, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zoekterm in standpunten"},
                    "party_id": {"type": "integer", "description": "Filter op partij"},
                    "party_name": {"type": "string", "description": "Filter op partijnaam"},
                    "raadslid_id": {"type": "integer", "description": "Filter op raadslid"},
                    "topic": {"type": "string", "description": "Filter op topic"},
                    "stance": {"type": "string", "enum": ["voor", "tegen", "neutraal", "genuanceerd", "onbekend"], "description": "Filter op stance"},
                    "verified_only": {"type": "boolean", "description": "Alleen geverifieerde standpunten", "default": False},
                    "limit": {"type": "integer", "description": "Maximum resultaten", "default": 50}
                }
            }
        ),
        Tool(
            name="compare_standpunten",
            description="Vergelijk standpunten van verschillende partijen over een specifiek onderwerp.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Onderwerp om te vergelijken"},
                    "party_ids": {"type": "array", "items": {"type": "integer"}, "description": "Specifieke partij IDs (optioneel)"},
                    "include_raadsleden": {"type": "boolean", "description": "Ook individuele raadsleden meenemen", "default": False}
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="get_standpunt_history",
            description="Bekijk de historische ontwikkeling van standpunten over een topic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Onderwerp"},
                    "party_id": {"type": "integer", "description": "Filter op partij"},
                    "raadslid_id": {"type": "integer", "description": "Filter op raadslid"}
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="get_party_context",
            description="Haal context op van een partij voor party-aligned antwoorden. Geeft overzicht van standpunten, stemgedrag, en prioriteiten.",
            inputSchema={
                "type": "object",
                "properties": {
                    "party_id": {"type": "integer", "description": "Partij ID"},
                    "party_name": {"type": "string", "description": "Partijnaam (alternatief voor ID)"},
                    "topics": {"type": "array", "items": {"type": "string"}, "description": "Specifieke topics (optioneel)"}
                }
            }
        ),
        Tool(
            name="list_raadsleden",
            description="Lijst alle raadsleden, wethouders en steunfractieleden met optionele filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "party_id": {"type": "integer", "description": "Filter op partij"},
                    "active_only": {"type": "boolean", "description": "Alleen actieve leden", "default": True},
                    "include_steunfractie": {"type": "boolean", "description": "Inclusief steunfractieleden", "default": True}
                }
            }
        ),
        Tool(
            name="add_raadslid",
            description="Voeg een raadslid, wethouder of steunfractielid toe aan de database.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Volledige naam"},
                    "party_id": {"type": "integer", "description": "Partij ID"},
                    "email": {"type": "string", "description": "E-mailadres"},
                    "start_date": {"type": "string", "description": "Start datum (YYYY-MM-DD)"},
                    "is_wethouder": {"type": "boolean", "description": "Is wethouder", "default": False},
                    "is_fractievoorzitter": {"type": "boolean", "description": "Is fractievoorzitter", "default": False},
                    "is_steunfractielid": {"type": "boolean", "description": "Is steunfractielid (geen stemrecht in raad)", "default": False}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="verify_standpunt",
            description="Markeer een standpunt als geverifieerd.",
            inputSchema={
                "type": "object",
                "properties": {
                    "standpunt_id": {"type": "integer", "description": "ID van het standpunt"},
                    "verified": {"type": "boolean", "description": "Verificatie status", "default": True}
                },
                "required": ["standpunt_id"]
            }
        ),
        Tool(
            name="get_standpunt_topics",
            description="Haal de lijst van standpunt-topics op.",
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_id": {"type": "integer", "description": "Filter op parent topic (voor subtopics)"}
                }
            }
        ),
        # ==================== Visit Report Tools ====================
        Tool(
            name="add_visit_report",
            description="Voeg een werkbezoek-verslag toe met handmatige upload (base64).",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titel van het verslag"},
                    "date": {"type": "string", "description": "Datum (YYYY-MM-DD)"},
                    "location": {"type": "string", "description": "Locatie"},
                    "participants": {"type": "array", "items": {"type": "string"}, "description": "Deelnemers"},
                    "organizations": {"type": "array", "items": {"type": "string"}, "description": "Organisaties"},
                    "topics": {"type": "array", "items": {"type": "string"}, "description": "Onderwerpen/tags"},
                    "visit_type": {"type": "string", "description": "Type werkbezoek"},
                    "summary": {"type": "string", "description": "Korte samenvatting"},
                    "status": {"type": "string", "description": "Status (draft/published/archived)"},
                    "source_url": {"type": "string", "description": "Bron URL (optioneel)"},
                    "attachments": {"type": "array", "items": {"type": "string"}, "description": "Bijlagen/IDs (optioneel)"},
                    "filename": {"type": "string", "description": "Bestandsnaam"},
                    "mime_type": {"type": "string", "description": "MIME type"},
                    "file_base64": {"type": "string", "description": "Bestand als base64"}
                },
                "required": ["title", "filename", "mime_type", "file_base64"]
            }
        ),
        Tool(
            name="import_visit_reports",
            description="Maak werkbezoek-verslagen aan op basis van bestaande documenten.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_ids": {"type": "array", "items": {"type": "integer"}, "description": "Document IDs"},
                    "date": {"type": "string", "description": "Datum (YYYY-MM-DD)"},
                    "location": {"type": "string", "description": "Locatie"},
                    "participants": {"type": "array", "items": {"type": "string"}, "description": "Deelnemers"},
                    "organizations": {"type": "array", "items": {"type": "string"}, "description": "Organisaties"},
                    "topics": {"type": "array", "items": {"type": "string"}, "description": "Onderwerpen/tags"},
                    "visit_type": {"type": "string", "description": "Type werkbezoek"},
                    "summary": {"type": "string", "description": "Korte samenvatting"},
                    "status": {"type": "string", "description": "Status (draft/published/archived)"}
                },
                "required": ["document_ids"]
            }
        ),
        Tool(
            name="list_visit_reports",
            description="Lijst werkbezoek-verslagen met filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Start datum (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "Eind datum (YYYY-MM-DD)"},
                    "status": {"type": "string", "description": "Status filter"},
                    "visit_type": {"type": "string", "description": "Type filter"},
                    "limit": {"type": "integer", "description": "Maximum resultaten", "default": 50},
                    "offset": {"type": "integer", "description": "Offset", "default": 0}
                }
            }
        ),
        Tool(
            name="get_visit_report",
            description="Haal een werkbezoek-verslag op.",
            inputSchema={
                "type": "object",
                "properties": {
                    "visit_report_id": {"type": "integer", "description": "Verslag ID"}
                },
                "required": ["visit_report_id"]
            }
        ),
        Tool(
            name="search_visit_reports",
            description="Zoek in werkbezoek-verslagen (incl. gekoppelde document tekst).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zoekterm"},
                    "limit": {"type": "integer", "description": "Maximum resultaten", "default": 50}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="update_visit_report",
            description="Werk metadata van een werkbezoek-verslag bij.",
            inputSchema={
                "type": "object",
                "properties": {
                    "visit_report_id": {"type": "integer", "description": "Verslag ID"},
                    "title": {"type": "string", "description": "Titel"},
                    "date": {"type": "string", "description": "Datum (YYYY-MM-DD)"},
                    "location": {"type": "string", "description": "Locatie"},
                    "participants": {"type": "array", "items": {"type": "string"}, "description": "Deelnemers"},
                    "organizations": {"type": "array", "items": {"type": "string"}, "description": "Organisaties"},
                    "topics": {"type": "array", "items": {"type": "string"}, "description": "Onderwerpen/tags"},
                    "visit_type": {"type": "string", "description": "Type werkbezoek"},
                    "summary": {"type": "string", "description": "Samenvatting"},
                    "status": {"type": "string", "description": "Status"},
                    "source_url": {"type": "string", "description": "Bron URL"},
                    "attachments": {"type": "array", "items": {"type": "string"}, "description": "Bijlagen"}
                },
                "required": ["visit_report_id"]
            }
        ),
        Tool(
            name="delete_visit_report",
            description="Archiveer (soft delete) een werkbezoek-verslag.",
            inputSchema={
                "type": "object",
                "properties": {
                    "visit_report_id": {"type": "integer", "description": "Verslag ID"}
                },
                "required": ["visit_report_id"]
            }
        ),
        Tool(
            name="link_visit_report_to_meeting",
            description="Koppel een werkbezoek-verslag aan een vergadering.",
            inputSchema={
                "type": "object",
                "properties": {
                    "visit_report_id": {"type": "integer", "description": "Verslag ID"},
                    "meeting_id": {"type": "integer", "description": "Vergadering ID"}
                },
                "required": ["visit_report_id", "meeting_id"]
            }
        ),
        Tool(
            name="index_visit_reports",
            description="Indexeer gekoppelde documenten van werkbezoek-verslagen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "visit_report_ids": {"type": "array", "items": {"type": "integer"}, "description": "Specifieke verslag IDs (optioneel)"}
                }
            }
        ),
        # ==================== Transcriptie Tools ====================
        Tool(
            name="transcribe_meeting",
            description="Transcribeer de video van een vergadering met AI (Whisper). "
            "Zet gesproken tekst om naar doorzoekbare tekst.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "integer", "description": "Database ID van de vergadering"}
                },
                "required": ["meeting_id"]
            }
        ),
        Tool(
            name="transcribe_url",
            description="Transcribeer video/audio van een URL (YouTube, direct link).",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Video/audio URL"},
                    "source_type": {
                        "type": "string",
                        "enum": ["youtube", "notubiz", "direct"],
                        "description": "Type bron",
                        "default": "direct"
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="search_transcriptions",
            description="Zoek in video/audio transcripties met timestamps. "
            "Vindt relevante fragmenten en geeft tijdstippen in de video.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zoekvraag"},
                    "limit": {"type": "integer", "description": "Maximum resultaten", "default": 10}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_transcription_status",
            description="Bekijk hoeveel vergaderingen nog getranscribeerd moeten worden.",
            inputSchema={"type": "object", "properties": {}}
        ),
        # ==================== Samenvatting Tools ====================
        Tool(
            name="get_document_for_summary",
            description="Haal document content op voor het maken van een samenvatting. "
            "Retourneert de tekst die samengevat kan worden.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "integer", "description": "Document ID"}
                },
                "required": ["document_id"]
            }
        ),
        Tool(
            name="save_document_summary",
            description="Sla een gegenereerde samenvatting op voor een document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "integer", "description": "Document ID"},
                    "summary_text": {"type": "string", "description": "De samenvatting"},
                    "summary_type": {
                        "type": "string",
                        "enum": ["kort", "normaal", "lang"],
                        "default": "normaal"
                    }
                },
                "required": ["document_id", "summary_text"]
            }
        ),
        Tool(
            name="get_meeting_for_summary",
            description="Haal vergadering content op voor het maken van een samenvatting. "
            "Combineert agenda, documenten en transcriptie.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "integer", "description": "Vergadering ID"}
                },
                "required": ["meeting_id"]
            }
        ),
        Tool(
            name="save_meeting_summary",
            description="Sla een gegenereerde samenvatting op voor een vergadering.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "integer", "description": "Vergadering ID"},
                    "summary_text": {"type": "string", "description": "De samenvatting"},
                    "summary_type": {
                        "type": "string",
                        "enum": ["kort", "normaal", "lang"],
                        "default": "normaal"
                    }
                },
                "required": ["meeting_id", "summary_text"]
            }
        ),
        # ==================== Dossier Tools ====================
        Tool(
            name="create_dossier",
            description="Maak een automatisch dossier/tijdlijn voor een onderwerp. "
            "Verzamelt alle relevante vergaderingen, documenten en transcripties.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Onderwerp (bijv: 'Paleis Soestdijk')"},
                    "date_from": {"type": "string", "description": "Start datum (YYYY-MM-DD)"},
                    "include_transcripts": {
                        "type": "boolean",
                        "description": "Ook transcripties doorzoeken",
                        "default": True
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="get_dossier",
            description="Haal een dossier op met alle tijdlijn items.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dossier_id": {"type": "integer", "description": "Dossier ID"}
                },
                "required": ["dossier_id"]
            }
        ),
        Tool(
            name="update_dossier",
            description="Update een bestaand dossier met nieuwe informatie.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dossier_id": {"type": "integer", "description": "Dossier ID"}
                },
                "required": ["dossier_id"]
            }
        ),
        Tool(
            name="list_dossiers",
            description="Lijst alle beschikbare dossiers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["active", "archived"],
                        "description": "Filter op status"
                    }
                }
            }
        ),
        Tool(
            name="get_dossier_timeline",
            description="Haal een dossier tijdlijn op als markdown tekst.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dossier_id": {"type": "integer", "description": "Dossier ID"}
                },
                "required": ["dossier_id"]
            }
        ),
    ]


# ==================== Tool Handlers ====================

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    await perform_initial_sync()

    logger.info(f'Tool call: {name}')

    try:
        result = await handle_tool(name, arguments)
        return [TextContent(type="text", text=format_response(result))]
    except Exception as e:
        logger.error(f'Tool error: {name} - {e}')
        return [TextContent(type="text", text=format_response({"error": str(e)}))]


async def handle_tool(name: str, args: dict) -> Any:
    """Route tool calls to handlers."""

    if name == "get_meetings":
        provider = get_meeting_provider()
        meetings = provider.get_meetings(
            limit=args.get('limit', 20),
            date_from=args.get('date_from'),
            date_to=args.get('date_to'),
            search=args.get('search')
        )
        return {"count": len(meetings), "meetings": [
            {"id": m['id'], "title": m['title'], "date": m['date'], "gremium": m.get('gremium_name')}
            for m in meetings
        ]}

    elif name == "get_meeting_details":
        provider = get_meeting_provider()
        meeting = provider.get_meeting(meeting_id=args['meeting_id'])
        if not meeting:
            return {"error": "Meeting not found"}
        return {
            "id": meeting['id'],
            "title": meeting['title'],
            "date": meeting['date'],
            "location": meeting.get('location'),
            "agenda_items": [{"id": i['id'], "title": i['title']} for i in meeting.get('agenda_items', [])],
            "documents": [
                {
                    "id": d['id'],
                    "title": d['title'],
                    "url": d.get('url') or (f"https://api.notubiz.nl/document/{d['notubiz_id']}/1" if d.get('notubiz_id') else None),
                    "has_content": bool(d.get('text_content'))
                }
                for d in meeting.get('documents', [])
            ]
        }

    elif name == "get_agenda_items":
        provider = get_meeting_provider()
        items = provider.get_agenda_items(args['meeting_id'])
        return {"meeting_id": args['meeting_id'], "count": len(items), "agenda_items": items}

    elif name == "get_document":
        provider = get_document_provider()
        doc = provider.get_document(args['document_id'])
        if not doc:
            return {"error": "Document not found"}
        text = doc.get('text_content', '')
        # Build Notubiz URL if we have a notubiz_id
        notubiz_url = None
        if doc.get('notubiz_id'):
            notubiz_url = f"https://api.notubiz.nl/document/{doc['notubiz_id']}/1"
        return {
            "id": doc['id'],
            "title": doc['title'],
            "url": doc.get('url') or notubiz_url,
            "notubiz_url": notubiz_url,
            "has_text": bool(text),
            "text_content": text[:10000] if text else None,
            "truncated": len(text) > 10000 if text else False
        }

    elif name == "search_documents":
        provider = get_document_provider()
        results = provider.search_documents(args['query'], args.get('limit', 20))
        return {"query": args['query'], "count": len(results), "results": [
            {
                "id": d['id'],
                "title": d['title'],
                "url": d.get('url') or (f"https://api.notubiz.nl/document/{d['notubiz_id']}/1" if d.get('notubiz_id') else None),
                "match_type": d.get('match_type', [])
            }
            for d in results
        ]}

    elif name == "semantic_search":
        index = get_document_index()
        results = index.search(args['query'], args.get('limit', 10))
        if not results:
            stats = index.get_index_stats()
            if not stats.get('embeddings_available'):
                return {"error": "Embeddings niet beschikbaar", "hint": "pip install sentence-transformers torch"}
            if stats.get('indexed_documents', 0) == 0:
                return {"error": "Geen documenten geïndexeerd", "hint": "sync_data met index_documents=true"}
        return {"query": args['query'], "count": len(results), "results": [
            {"document_id": r.document_id, "title": r.document_title, "similarity": round(r.similarity, 3), "excerpt": r.chunk_text[:300]}
            for r in results
        ]}

    elif name == "sync_data":
        meeting_provider = get_meeting_provider()
        doc_provider = get_document_provider()

        meeting_provider.sync_gremia()
        meetings, docs = meeting_provider.sync_meetings(
            date_from=args.get('date_from'),
            date_to=args.get('date_to')
        )

        result = {"meetings": meetings, "documents_found": docs}

        if args.get('download_documents'):
            success, failed = doc_provider.download_pending_documents()
            doc_provider.extract_all_text()
            result["documents_downloaded"] = success

        if args.get('index_documents'):
            index = get_document_index()
            indexed, chunks = index.index_all_documents()
            result["documents_indexed"] = indexed

        return result

    elif name == "add_annotation":
        db = get_database()
        aid = db.add_annotation(
            content=args['content'],
            document_id=args.get('document_id'),
            meeting_id=args.get('meeting_id'),
            title=args.get('title'),
            tags=args.get('tags')
        )
        return {"success": True, "annotation_id": aid}

    elif name == "get_annotations":
        db = get_database()
        return {"annotations": db.get_annotations(
            document_id=args.get('document_id'),
            meeting_id=args.get('meeting_id'),
            search=args.get('search')
        )}

    elif name == "get_gremia":
        provider = get_meeting_provider()
        gremia = provider.get_gremia()
        return {"count": len(gremia), "gremia": [{"id": g['id'], "name": g['name']} for g in gremia]}

    elif name == "get_statistics":
        db = get_database()
        index = get_document_index()
        return {
            "database": db.get_statistics(),
            "index": index.get_index_stats(),
            "municipality": Config.MUNICIPALITY_NAME
        }

    elif name == "get_notubiz_status":
        client = get_notubiz_client()
        return client.get_auth_status()

    elif name == "get_coalitie_akkoord":
        tracker = get_coalitie_tracker()
        summary = tracker.get_akkoord_summary()
        afspraken = tracker.get_afspraken(
            thema=args.get('thema'),
            status=args.get('status')
        )
        return {
            "summary": summary,
            "afspraken": [
                {
                    "id": a.get('id'),
                    "thema": a.get('thema'),
                    "tekst": a.get('tekst'),
                    "status": a.get('status'),
                    "prioriteit": a.get('prioriteit'),
                    "gerelateerde_besluiten": len(a.get('gerelateerde_besluiten', []))
                }
                for a in afspraken
            ],
            "count": len(afspraken)
        }

    elif name == "update_coalitie_afspraak":
        tracker = get_coalitie_tracker()
        result = {"afspraak_id": args['afspraak_id'], "success": False}

        if args.get('new_status'):
            if tracker.update_afspraak_status(args['afspraak_id'], args['new_status']):
                result["status_updated"] = args['new_status']
                result["success"] = True

        if args.get('link_meeting_id'):
            if tracker.link_besluit(args['afspraak_id'], args['link_meeting_id']):
                result["meeting_linked"] = args['link_meeting_id']
                result["success"] = True

        return result

    elif name == "search_and_sync":
        provider = get_search_sync_provider()
        result = provider.search_and_sync(
            query=args['query'],
            start_date=args.get('start_date', '2010-01-01'),
            end_date=args.get('end_date'),
            download_docs=args.get('download_documents', True),
            index_docs=args.get('index_documents', True),
            limit=args.get('limit', 100)
        )
        return result

    elif name == "get_upcoming_meetings":
        from datetime import datetime, timedelta

        period = args.get('period', 'this_week')
        include_agenda = args.get('include_agenda', True)
        include_documents = args.get('include_documents', False)

        today = date.today()

        # Calculate date range based on period
        if period == 'today':
            date_from = date_to = today.isoformat()
            period_label = f"vandaag ({today.strftime('%d-%m-%Y')})"
        elif period == 'tomorrow':
            tomorrow = today + timedelta(days=1)
            date_from = date_to = tomorrow.isoformat()
            period_label = f"morgen ({tomorrow.strftime('%d-%m-%Y')})"
        elif period == 'this_week':
            # Start of week (Monday)
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            date_from = start.isoformat()
            date_to = end.isoformat()
            period_label = f"deze week ({start.strftime('%d-%m')} t/m {end.strftime('%d-%m-%Y')})"
        elif period == 'next_week':
            start = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
            end = start + timedelta(days=6)
            date_from = start.isoformat()
            date_to = end.isoformat()
            period_label = f"volgende week ({start.strftime('%d-%m')} t/m {end.strftime('%d-%m-%Y')})"
        elif period == 'this_month':
            start = today.replace(day=1)
            # End of month
            if today.month == 12:
                end = today.replace(year=today.year+1, month=1, day=1) - timedelta(days=1)
            else:
                end = today.replace(month=today.month+1, day=1) - timedelta(days=1)
            date_from = start.isoformat()
            date_to = end.isoformat()
            period_label = f"deze maand ({today.strftime('%B %Y')})"
        else:
            date_from = date_to = today.isoformat()
            period_label = "vandaag"

        provider = get_meeting_provider()
        meetings = provider.get_meetings(
            limit=50,
            date_from=date_from,
            date_to=date_to
        )

        result_meetings = []
        for m in meetings:
            meeting_data = {
                "id": m['id'],
                "title": m['title'],
                "date": m['date'],
                "gremium": m.get('gremium_name'),
                "location": m.get('location')
            }

            if include_agenda:
                items = provider.get_agenda_items(m['id'])
                meeting_data['agenda_items'] = [
                    {"id": i['id'], "title": i['title']}
                    for i in items
                ]

            if include_documents:
                full_meeting = provider.get_meeting(meeting_id=m['id'])
                if full_meeting:
                    meeting_data['documents'] = [
                        {
                            "id": d['id'],
                            "title": d['title'],
                            "url": d.get('url') or (f"https://api.notubiz.nl/document/{d['notubiz_id']}/1" if d.get('notubiz_id') else None)
                        }
                        for d in full_meeting.get('documents', [])
                    ]

            result_meetings.append(meeting_data)

        return {
            "period": period_label,
            "date_range": {"from": date_from, "to": date_to},
            "count": len(result_meetings),
            "meetings": result_meetings
        }

    # ==================== Media/Broadcast Handlers ====================

    elif name == "get_upcoming_broadcasts":
        from providers.notubiz_client import get_notubiz_client
        client = get_notubiz_client()
        limit = args.get('limit', 10)

        broadcasts = client.get_upcoming_broadcasts(limit=limit)

        result = []
        for event in broadcasts:
            result.append({
                'id': event.get('id'),
                'title': event.get('title') or event.get('name'),
                'date': event.get('start_date') or event.get('date'),
                'gremium': event.get('gremium', {}).get('name') if isinstance(event.get('gremium'), dict) else None,
                'has_broadcast': True
            })

        return {
            "count": len(result),
            "upcoming_broadcasts": result,
            "note": "Vergaderingen met geplande live uitzendingen"
        }

    elif name == "get_meeting_video":
        from providers.notubiz_client import get_notubiz_client
        client = get_notubiz_client()
        provider = get_meeting_provider()

        meeting_id = args.get('meeting_id')

        # Get meeting from database to find Notubiz ID
        meeting = provider.get_meeting(meeting_id)
        if not meeting:
            return {"error": f"Vergadering {meeting_id} niet gevonden"}

        notubiz_id = meeting.get('notubiz_id') or str(meeting_id)

        # Try to get video URL from database first
        video_url = meeting.get('video_url')
        if not video_url:
            # Try to fetch from Notubiz API
            video_url = client.get_video_url_for_meeting(notubiz_id)

        return {
            "meeting_id": meeting_id,
            "title": meeting.get('title'),
            "date": meeting.get('date'),
            "video_url": video_url,
            "has_video": video_url is not None,
            "note": "Video URL kan direct afgespeeld worden of gebruikt voor transcriptie"
        }

    elif name == "get_media_info":
        from providers.notubiz_client import get_notubiz_client
        client = get_notubiz_client()

        event_ids = args.get('event_ids', [])
        if not event_ids:
            return {"error": "Geen event_ids opgegeven"}

        media_list = client.get_media(event_ids)

        return {
            "count": len(media_list),
            "media": media_list,
            "requested_events": len(event_ids)
        }

    elif name == "get_organization_info":
        from providers.notubiz_client import get_notubiz_client
        client = get_notubiz_client()

        include_settings = args.get('include_settings', False)

        org_details = client.get_organization_details()
        org_id = client.get_organization_id()

        result = {
            "organization": org_details,
            "organization_id": org_id,
            "logo_url": client.get_organization_image_url('organisationLogo', size='200x200'),
            "header_url": client.get_organization_image_url('dashboardheader', size='2000x320')
        }

        if include_settings:
            result["dashboard_settings"] = client.get_dashboard_settings()
            result["entity_settings"] = client.get_entity_type_settings(entity_types=['events'])

        return result

    # ==================== Verkiezingsprogramma Handlers ====================

    elif name == "list_parties":
        provider = get_election_program_provider()
        # Initialize parties if not done yet
        provider.initialize_parties()
        parties = provider.get_parties(active_only=args.get('active_only', False))
        return {
            "count": len(parties),
            "parties": [
                {
                    "id": p['id'],
                    "name": p['name'],
                    "abbreviation": p.get('abbreviation'),
                    "active": bool(p.get('active')),
                    "website": p.get('website_url'),
                    "color": p.get('color')
                }
                for p in parties
            ]
        }

    elif name == "sync_parties":
        provider = get_election_program_provider()
        # Initialize known parties first if requested
        if args.get('initialize_known', True):
            provider.initialize_parties()
        # Check for updates from web
        result = provider.check_and_update_parties_from_web()
        return result

    elif name == "get_party_sync_status":
        provider = get_election_program_provider()
        return provider.get_party_sync_status()

    elif name == "search_election_programs":
        provider = get_election_program_provider()
        results = provider.search_programs(
            query=args['query'],
            party=args.get('party'),
            year_from=args.get('year_from'),
            year_to=args.get('year_to'),
            limit=args.get('limit', 20)
        )
        return {
            "query": args['query'],
            "count": len(results),
            "results": [
                {
                    "program_id": r.get('id'),
                    "party": r.get('party_name'),
                    "abbreviation": r.get('abbreviation'),
                    "year": r.get('election_year'),
                    "snippet": r.get('snippet', '')[:500]
                }
                for r in results
            ]
        }

    elif name == "compare_party_positions":
        provider = get_election_program_provider()
        result = provider.compare_positions(
            topic=args['topic'],
            parties=args.get('parties'),
            year=args.get('year')
        )
        return result

    elif name == "get_party_history":
        provider = get_election_program_provider()
        history = provider.get_party_position_history(
            party=args['party'],
            topic=args['topic']
        )
        return {
            "party": args['party'],
            "topic": args['topic'],
            "positions": history
        }

    # ==================== Document Generatie Handlers ====================

    elif name == "generate_motie":
        generator = get_document_generator()
        result = generator.generate_motie(
            titel=args['titel'],
            indieners=args['indieners'],
            partijen=args['partijen'],
            constateringen=args['constateringen'],
            overwegingen=args['overwegingen'],
            verzoeken=args['verzoeken'],
            vergadering_datum=args.get('vergadering_datum'),
            agendapunt=args.get('agendapunt'),
            toelichting=args.get('toelichting')
        )
        return result

    elif name == "generate_amendement":
        generator = get_document_generator()
        result = generator.generate_amendement(
            titel=args['titel'],
            indieners=args['indieners'],
            partijen=args['partijen'],
            raadsvoorstel_nummer=args['raadsvoorstel_nummer'],
            raadsvoorstel_titel=args['raadsvoorstel_titel'],
            wijzigingen=args['wijzigingen'],
            toelichting=args.get('toelichting'),
            vergadering_datum=args.get('vergadering_datum'),
            agendapunt=args.get('agendapunt')
        )
        return result

    # ==================== Standpunten Handlers ====================

    elif name == "add_standpunt":
        provider = get_standpunt_provider()
        result = provider.add_standpunt(
            party_id=args.get('party_id'),
            raadslid_id=args.get('raadslid_id'),
            topic=args['topic'],
            position_summary=args['position_summary'],
            position_text=args.get('position_text'),
            stance=args.get('stance', 'onbekend'),
            stance_strength=args.get('stance_strength'),
            source_type=args['source_type'],
            source_document_id=args.get('source_document_id'),
            source_meeting_id=args.get('source_meeting_id'),
            source_quote=args.get('source_quote'),
            position_date=args.get('position_date'),
            subtopic=args.get('subtopic'),
            tags=args.get('tags')
        )
        return result

    elif name == "search_standpunten":
        provider = get_standpunt_provider()
        results = provider.search_standpunten(
            query=args.get('query'),
            party_id=args.get('party_id'),
            party_name=args.get('party_name'),
            raadslid_id=args.get('raadslid_id'),
            topic=args.get('topic'),
            stance=args.get('stance'),
            verified_only=args.get('verified_only', False),
            limit=args.get('limit', 50)
        )
        return {
            "count": len(results),
            "standpunten": results
        }

    elif name == "compare_standpunten":
        provider = get_standpunt_provider()
        result = provider.compare_standpunten(
            topic=args['topic'],
            party_ids=args.get('party_ids'),
            include_raadsleden=args.get('include_raadsleden', False)
        )
        return result

    elif name == "get_standpunt_history":
        provider = get_standpunt_provider()
        history = provider.get_standpunt_history(
            topic=args['topic'],
            party_id=args.get('party_id'),
            raadslid_id=args.get('raadslid_id')
        )
        return {
            "topic": args['topic'],
            "history": history
        }

    elif name == "get_party_context":
        provider = get_standpunt_provider()
        context = provider.get_party_context(
            party_id=args.get('party_id'),
            party_name=args.get('party_name'),
            topics=args.get('topics')
        )
        return context

    elif name == "list_raadsleden":
        provider = get_standpunt_provider()
        raadsleden = provider.get_raadsleden(
            party_id=args.get('party_id'),
            active_only=args.get('active_only', True)
        )
        return {
            "count": len(raadsleden),
            "raadsleden": raadsleden
        }

    elif name == "add_raadslid":
        provider = get_standpunt_provider()
        result = provider.add_raadslid(
            name=args['name'],
            party_id=args.get('party_id'),
            email=args.get('email'),
            start_date=args.get('start_date'),
            is_wethouder=args.get('is_wethouder', False),
            is_fractievoorzitter=args.get('is_fractievoorzitter', False),
            is_steunfractielid=args.get('is_steunfractielid', False)
        )
        return result

    elif name == "verify_standpunt":
        provider = get_standpunt_provider()
        result = provider.verify_standpunt(
            standpunt_id=args['standpunt_id'],
            verified=args.get('verified', True)
        )
        return result

    elif name == "get_standpunt_topics":
        provider = get_standpunt_provider()
        topics = provider.get_topics(parent_id=args.get('parent_id'))
        return {
            "count": len(topics),
            "topics": topics
        }

    elif name == "add_visit_report":
        provider = get_visit_report_provider()
        report_id = provider.add_manual_visit_report(
            title=args['title'],
            file_base64=args['file_base64'],
            filename=args['filename'],
            mime_type=args['mime_type'],
            date=args.get('date'),
            location=args.get('location'),
            participants=args.get('participants'),
            organizations=args.get('organizations'),
            topics=args.get('topics'),
            visit_type=args.get('visit_type'),
            summary=args.get('summary'),
            status=args.get('status'),
            source_url=args.get('source_url'),
            attachments=args.get('attachments')
        )
        return {"success": True, "visit_report_id": report_id}

    elif name == "import_visit_reports":
        provider = get_visit_report_provider()
        created, skipped = provider.import_visit_reports_from_documents(
            document_ids=args['document_ids'],
            date=args.get('date'),
            location=args.get('location'),
            participants=args.get('participants'),
            organizations=args.get('organizations'),
            topics=args.get('topics'),
            visit_type=args.get('visit_type'),
            summary=args.get('summary'),
            status=args.get('status')
        )
        return {"created": created, "skipped": skipped}

    elif name == "list_visit_reports":
        provider = get_visit_report_provider()
        reports = provider.list_visit_reports(
            date_from=args.get('date_from'),
            date_to=args.get('date_to'),
            status=args.get('status'),
            visit_type=args.get('visit_type'),
            limit=args.get('limit', 50),
            offset=args.get('offset', 0)
        )
        return {"count": len(reports), "visit_reports": reports}

    elif name == "get_visit_report":
        provider = get_visit_report_provider()
        report = provider.get_visit_report(args['visit_report_id'])
        return report or {"error": "Visit report not found"}

    elif name == "search_visit_reports":
        provider = get_visit_report_provider()
        results = provider.search_visit_reports(args['query'], limit=args.get('limit', 50))
        return {"query": args['query'], "count": len(results), "results": results}

    elif name == "update_visit_report":
        provider = get_visit_report_provider()
        success = provider.update_visit_report(
            args['visit_report_id'],
            title=args.get('title'),
            date=args.get('date'),
            location=args.get('location'),
            participants=args.get('participants'),
            organizations=args.get('organizations'),
            topics=args.get('topics'),
            visit_type=args.get('visit_type'),
            summary=args.get('summary'),
            status=args.get('status'),
            source_url=args.get('source_url'),
            attachments=args.get('attachments')
        )
        return {"success": success}

    elif name == "delete_visit_report":
        provider = get_visit_report_provider()
        success = provider.delete_visit_report(args['visit_report_id'])
        return {"success": success}

    elif name == "link_visit_report_to_meeting":
        provider = get_visit_report_provider()
        success = provider.link_to_meeting(args['visit_report_id'], args['meeting_id'])
        return {"success": success}

    elif name == "index_visit_reports":
        provider = get_visit_report_provider()
        count = provider.index_visit_reports(args.get('visit_report_ids'))
        return {"indexed_chunks": count}

    # ==================== Transcriptie Handlers ====================

    elif name == "transcribe_meeting":
        from providers.transcription_provider import get_transcription_provider
        provider = get_transcription_provider()
        return provider.transcribe_meeting(args['meeting_id'])

    elif name == "transcribe_url":
        from providers.transcription_provider import get_transcription_provider
        provider = get_transcription_provider()
        return provider.transcribe_url(
            args['url'],
            source_type=args.get('source_type', 'direct')
        )

    elif name == "search_transcriptions":
        from providers.transcription_provider import get_transcription_provider
        provider = get_transcription_provider()
        results = provider.search_transcriptions(
            args['query'],
            limit=args.get('limit', 10)
        )
        return {
            "count": len(results),
            "results": results
        }

    elif name == "get_transcription_status":
        from providers.transcription_provider import get_transcription_provider
        provider = get_transcription_provider()
        pending = provider.get_pending_transcriptions_count()
        return {
            "pending_transcriptions": pending,
            "whisper_model": provider.model_size
        }

    # ==================== Samenvatting Handlers ====================

    elif name == "get_document_for_summary":
        from providers.summary_provider import get_summary_provider
        provider = get_summary_provider()
        return provider.get_document_for_summary(args['document_id'])

    elif name == "save_document_summary":
        from providers.summary_provider import get_summary_provider
        provider = get_summary_provider()
        return provider.save_document_summary(
            args['document_id'],
            args['summary_text'],
            summary_type=args.get('summary_type', 'normaal')
        )

    elif name == "get_meeting_for_summary":
        from providers.summary_provider import get_summary_provider
        provider = get_summary_provider()
        return provider.get_meeting_for_summary(args['meeting_id'])

    elif name == "save_meeting_summary":
        from providers.summary_provider import get_summary_provider
        provider = get_summary_provider()
        return provider.save_meeting_summary(
            args['meeting_id'],
            args['summary_text'],
            summary_type=args.get('summary_type', 'normaal')
        )

    # ==================== Dossier Handlers ====================

    elif name == "create_dossier":
        from providers.dossier_provider import get_dossier_provider
        provider = get_dossier_provider()
        return provider.create_dossier(
            args['topic'],
            date_from=args.get('date_from'),
            include_transcripts=args.get('include_transcripts', True)
        )

    elif name == "get_dossier":
        from providers.dossier_provider import get_dossier_provider
        provider = get_dossier_provider()
        return provider.get_dossier(args['dossier_id'])

    elif name == "update_dossier":
        from providers.dossier_provider import get_dossier_provider
        provider = get_dossier_provider()
        return provider.update_dossier(args['dossier_id'])

    elif name == "list_dossiers":
        from providers.dossier_provider import get_dossier_provider
        provider = get_dossier_provider()
        dossiers = provider.list_dossiers(status=args.get('status'))
        return {
            "count": len(dossiers),
            "dossiers": dossiers
        }

    elif name == "get_dossier_timeline":
        from providers.dossier_provider import get_dossier_provider
        provider = get_dossier_provider()
        return {
            "markdown": provider.get_dossier_timeline_markdown(args['dossier_id'])
        }

    else:
        raise ValueError(f"Unknown tool: {name}")


# ==================== Main ====================

async def main():
    """Run the MCP server."""
    logger.info(f'Starting {Config.SERVER_NAME} v{Config.SERVER_VERSION}')

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
