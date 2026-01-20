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
            "documents": [{"id": d['id'], "title": d['title'], "has_content": bool(d.get('text_content'))} for d in meeting.get('documents', [])]
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
        return {
            "id": doc['id'],
            "title": doc['title'],
            "has_text": bool(text),
            "text_content": text[:10000] if text else None,
            "truncated": len(text) > 10000 if text else False
        }

    elif name == "search_documents":
        provider = get_document_provider()
        results = provider.search_documents(args['query'], args.get('limit', 20))
        return {"query": args['query'], "count": len(results), "results": [
            {"id": d['id'], "title": d['title'], "match_type": d.get('match_type', [])}
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
