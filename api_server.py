#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baarn Raadsinformatie REST API Server

FastAPI server die dezelfde functionaliteit biedt als de MCP server,
maar via REST endpoints. Geschikt voor ChatGPT Actions en andere integraties.

Authenticatie via X-API-Key header.
"""

import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.config import Config
from core.database import get_database
from core.document_index import get_document_index
from core.coalitie_tracker import get_coalitie_tracker
from providers.meeting_provider import get_meeting_provider
from providers.document_provider import get_document_provider
from shared.logging_config import get_logger

logger = get_logger(__name__)

# API Key authentication
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def get_api_key() -> str:
    """Get API key from environment."""
    return os.getenv("API_KEY", "baarn-api-key-change-me")


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Verify API key from header."""
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header."
        )
    if api_key != get_api_key():
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

# Track if initial sync is done
_initial_sync_done = False


async def perform_initial_sync():
    """Perform initial data sync if database is empty."""
    global _initial_sync_done

    if _initial_sync_done or not Config.AUTO_SYNC_ENABLED:
        return

    db = get_database()
    stats = db.get_statistics()

    if stats.get('meetings', 0) == 0:
        logger.info('Database empty - performing initial sync...')

        meeting_provider = get_meeting_provider()
        doc_provider = get_document_provider()

        meeting_provider.sync_gremia()

        date_from = (date.today() - timedelta(days=Config.AUTO_SYNC_DAYS)).isoformat()
        meetings, docs = meeting_provider.sync_meetings(
            date_from=date_from,
            full_details=True
        )
        logger.info(f'Initial sync: {meetings} meetings, {docs} documents')

        if Config.AUTO_DOWNLOAD_DOCS:
            logger.info('Downloading documents...')
            success, failed = doc_provider.download_pending_documents()
            logger.info(f'Downloaded {success} documents, {failed} failed')
            doc_provider.extract_all_text()

        if Config.AUTO_INDEX_DOCS:
            logger.info('Indexing documents for semantic search...')
            index = get_document_index()
            indexed, chunks = index.index_all_documents()
            logger.info(f'Indexed {indexed} documents, {chunks} chunks')

    _initial_sync_done = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info(f'Starting {Config.SERVER_NAME} REST API v{Config.SERVER_VERSION}')
    await perform_initial_sync()
    yield
    logger.info('Shutting down REST API')


# Initialize FastAPI with OpenAPI config for ChatGPT Custom GPT
app = FastAPI(
    title="Baarn Raadsinformatie API",
    description="""
REST API voor toegang tot politieke documenten en vergaderingen van gemeente Baarn.

## Features
- **Vergaderingen**: Ophalen van gemeenteraads- en commissievergaderingen
- **Documenten**: Doorzoeken van raadsstukken (keyword en semantisch)
- **Gremia**: Lijst van commissies en de gemeenteraad
- **Annotaties**: Notities toevoegen en ophalen
- **Coalitieakkoord**: Tracking van coalitieafspraken en voortgang

## Authenticatie
Alle endpoints vereisen een API key via de `X-API-Key` header.

## Gebruik met ChatGPT
Deze API is ontworpen voor ChatGPT Custom GPT Actions.
Importeer de OpenAPI spec via `/openapi.json`.
    """,
    version=Config.SERVER_VERSION,
    lifespan=lifespan,
    contact={
        "name": "Baarn Raadsinformatie",
        "url": "https://github.com/tiemenrtuinstra/baarn-raadsinformatie"
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT"
    },
    servers=[
        {"url": "http://localhost:8000", "description": "Local development"},
    ]
)

# CORS middleware voor browser toegang
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Pydantic Models ====================

class MeetingBase(BaseModel):
    id: int
    title: str
    date: str
    gremium: Optional[str] = None


class MeetingsResponse(BaseModel):
    count: int
    meetings: list[MeetingBase]


class AgendaItem(BaseModel):
    id: int
    title: str
    description: Optional[str] = None


class MeetingDetail(BaseModel):
    id: int
    title: str
    date: str
    location: Optional[str] = None
    agenda_items: list[dict]
    documents: list[dict]


class DocumentResponse(BaseModel):
    id: int
    title: str
    has_text: bool
    text_content: Optional[str] = None
    truncated: bool = False


class SearchResult(BaseModel):
    id: int
    title: str
    match_type: list[str] = []


class SearchResponse(BaseModel):
    query: str
    count: int
    results: list[SearchResult]


class SemanticResult(BaseModel):
    document_id: int
    title: str
    similarity: float
    excerpt: str


class SemanticSearchResponse(BaseModel):
    query: str
    count: int
    results: list[SemanticResult]


class SyncRequest(BaseModel):
    date_from: Optional[str] = Field(None, description="Start datum (YYYY-MM-DD)")
    date_to: Optional[str] = Field(None, description="Eind datum (YYYY-MM-DD)")
    download_documents: bool = Field(False, description="Download documenten")
    index_documents: bool = Field(False, description="Indexeer voor semantic search")


class SyncResponse(BaseModel):
    meetings: int
    documents_found: int
    documents_downloaded: Optional[int] = None
    documents_indexed: Optional[int] = None


class AnnotationCreate(BaseModel):
    content: str = Field(..., description="Inhoud van de annotatie")
    document_id: Optional[int] = Field(None, description="Document ID")
    meeting_id: Optional[int] = Field(None, description="Vergadering ID")
    title: Optional[str] = Field(None, description="Titel")
    tags: Optional[list[str]] = Field(None, description="Tags")


class GremiumResponse(BaseModel):
    id: int
    name: str


class StatisticsResponse(BaseModel):
    database: dict
    index: dict
    municipality: str


class CoalitieAfspraak(BaseModel):
    id: str
    thema: str
    tekst: str
    status: str
    prioriteit: Optional[str] = None
    gerelateerde_besluiten: int = 0


class CoalitieResponse(BaseModel):
    summary: dict
    afspraken: list[CoalitieAfspraak]
    count: int


class UpdateAfspraakRequest(BaseModel):
    new_status: Optional[str] = Field(None, description="Nieuwe status")
    link_meeting_id: Optional[int] = Field(None, description="Meeting ID om te koppelen")


# ==================== API Endpoints ====================

@app.get("/", tags=["Info"])
async def root():
    """API root - basisinformatie."""
    return {
        "name": Config.SERVER_NAME,
        "version": Config.SERVER_VERSION,
        "municipality": Config.MUNICIPALITY_NAME,
        "description": "REST API voor Baarn raadsinformatie"
    }


@app.get("/health", tags=["Info"])
async def health():
    """Health check endpoint."""
    db = get_database()
    stats = db.get_statistics()
    return {
        "status": "healthy",
        "database": {
            "meetings": stats.get('meetings', 0),
            "documents": stats.get('documents', 0)
        }
    }


# ==================== Vergaderingen ====================

@app.get("/api/meetings", response_model=MeetingsResponse, tags=["Vergaderingen"])
async def get_meetings(
    limit: int = Query(20, description="Maximum aantal resultaten", le=100),
    date_from: Optional[str] = Query(None, description="Start datum (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Eind datum (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Zoekterm"),
    api_key: str = Depends(verify_api_key)
):
    """
    Haal een lijst van vergaderingen op met optionele filters.

    - **limit**: Maximum aantal resultaten (default 20, max 100)
    - **date_from**: Filter op start datum
    - **date_to**: Filter op eind datum
    - **search**: Zoek in vergadertitels
    """
    provider = get_meeting_provider()
    meetings = provider.get_meetings(
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        search=search
    )
    return {
        "count": len(meetings),
        "meetings": [
            {"id": m['id'], "title": m['title'], "date": m['date'], "gremium": m.get('gremium_name')}
            for m in meetings
        ]
    }


@app.get("/api/meetings/{meeting_id}", response_model=MeetingDetail, tags=["Vergaderingen"])
async def get_meeting_details(meeting_id: int, api_key: str = Depends(verify_api_key)):
    """
    Haal gedetailleerde informatie op over een specifieke vergadering.

    Inclusief agenda items en gekoppelde documenten.
    """
    provider = get_meeting_provider()
    meeting = provider.get_meeting(meeting_id=meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Vergadering niet gevonden")

    return {
        "id": meeting['id'],
        "title": meeting['title'],
        "date": meeting['date'],
        "location": meeting.get('location'),
        "agenda_items": [{"id": i['id'], "title": i['title']} for i in meeting.get('agenda_items', [])],
        "documents": [{"id": d['id'], "title": d['title'], "has_content": bool(d.get('text_content'))} for d in meeting.get('documents', [])]
    }


@app.get("/api/meetings/{meeting_id}/agenda", tags=["Vergaderingen"])
async def get_agenda_items(meeting_id: int, api_key: str = Depends(verify_api_key)):
    """
    Haal agendapunten op voor een specifieke vergadering.
    """
    provider = get_meeting_provider()
    items = provider.get_agenda_items(meeting_id)
    return {"meeting_id": meeting_id, "count": len(items), "agenda_items": items}


# ==================== Documenten ====================

@app.get("/api/documents/{document_id}", response_model=DocumentResponse, tags=["Documenten"])
async def get_document(document_id: int, api_key: str = Depends(verify_api_key)):
    """
    Haal een specifiek document op met metadata en geëxtraheerde tekst.

    Tekst wordt afgekapt op 10.000 karakters.
    """
    provider = get_document_provider()
    doc = provider.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document niet gevonden")

    text = doc.get('text_content', '')
    return {
        "id": doc['id'],
        "title": doc['title'],
        "has_text": bool(text),
        "text_content": text[:10000] if text else None,
        "truncated": len(text) > 10000 if text else False
    }


@app.get("/api/documents/search", response_model=SearchResponse, tags=["Zoeken"])
async def search_documents(
    query: str = Query(..., description="Zoekterm"),
    limit: int = Query(20, description="Maximum resultaten", le=100),
    api_key: str = Depends(verify_api_key)
):
    """
    Zoek in documenten op titel en inhoud (keyword search).

    Doorzoekt document titels en geëxtraheerde tekst.
    """
    provider = get_document_provider()
    results = provider.search_documents(query, limit)
    return {
        "query": query,
        "count": len(results),
        "results": [
            {"id": d['id'], "title": d['title'], "match_type": d.get('match_type', [])}
            for d in results
        ]
    }


@app.get("/api/documents/semantic-search", response_model=SemanticSearchResponse, tags=["Zoeken"])
async def semantic_search(
    query: str = Query(..., description="Zoekvraag in natuurlijke taal"),
    limit: int = Query(10, description="Maximum resultaten", le=50),
    api_key: str = Depends(verify_api_key)
):
    """
    Semantisch zoeken met AI embeddings.

    Vindt documenten op basis van betekenis, niet alleen exacte keywords.
    Vereist dat embeddings zijn geïndexeerd.
    """
    index = get_document_index()
    results = index.search(query, limit)

    if not results:
        stats = index.get_index_stats()
        if not stats.get('embeddings_available'):
            raise HTTPException(
                status_code=503,
                detail="Embeddings niet beschikbaar. Installeer: pip install sentence-transformers torch"
            )
        if stats.get('indexed_documents', 0) == 0:
            raise HTTPException(
                status_code=503,
                detail="Geen documenten geïndexeerd. Roep /sync aan met index_documents=true"
            )

    return {
        "query": query,
        "count": len(results),
        "results": [
            {
                "document_id": r.document_id,
                "title": r.document_title,
                "similarity": round(r.similarity, 3),
                "excerpt": r.chunk_text[:300]
            }
            for r in results
        ]
    }


# ==================== Gremia ====================

@app.get("/api/gremia", tags=["Gremia"])
async def get_gremia(api_key: str = Depends(verify_api_key)):
    """
    Haal de lijst van gremia (commissies) op.
    """
    provider = get_meeting_provider()
    gremia = provider.get_gremia()
    return {"count": len(gremia), "gremia": [{"id": g['id'], "name": g['name']} for g in gremia]}


# ==================== Annotaties ====================

@app.post("/api/annotations", tags=["Annotaties"])
async def add_annotation(annotation: AnnotationCreate, api_key: str = Depends(verify_api_key)):
    """
    Voeg een annotatie/notitie toe.

    Kan gekoppeld worden aan een document of vergadering.
    """
    db = get_database()
    aid = db.add_annotation(
        content=annotation.content,
        document_id=annotation.document_id,
        meeting_id=annotation.meeting_id,
        title=annotation.title,
        tags=annotation.tags
    )
    return {"success": True, "annotation_id": aid}


@app.get("/api/annotations", tags=["Annotaties"])
async def get_annotations(
    document_id: Optional[int] = Query(None, description="Filter op document"),
    meeting_id: Optional[int] = Query(None, description="Filter op vergadering"),
    search: Optional[str] = Query(None, description="Zoekterm"),
    api_key: str = Depends(verify_api_key)
):
    """
    Haal annotaties op met optionele filters.
    """
    db = get_database()
    annotations = db.get_annotations(
        document_id=document_id,
        meeting_id=meeting_id,
        search=search
    )
    return {"annotations": annotations}


# ==================== Statistieken ====================

@app.get("/api/statistics", response_model=StatisticsResponse, tags=["Info"])
async def get_statistics(api_key: str = Depends(verify_api_key)):
    """
    Haal statistieken op over de database en index.
    """
    db = get_database()
    index = get_document_index()
    return {
        "database": db.get_statistics(),
        "index": index.get_index_stats(),
        "municipality": Config.MUNICIPALITY_NAME
    }


# ==================== Coalitieakkoord ====================

@app.get("/api/coalitie", response_model=CoalitieResponse, tags=["Coalitie"])
async def get_coalitie_akkoord(
    thema: Optional[str] = Query(None, description="Filter op thema"),
    status: Optional[str] = Query(None, description="Filter op status"),
    api_key: str = Depends(verify_api_key)
):
    """
    Haal coalitieakkoord informatie op met afspraken en voortgang.

    - **thema**: Filter op thema (bijv: 'wonen', 'duurzaamheid')
    - **status**: Filter op status (niet_gestart, in_voorbereiding, in_uitvoering, gerealiseerd)
    """
    tracker = get_coalitie_tracker()
    summary = tracker.get_akkoord_summary()
    afspraken = tracker.get_afspraken(thema=thema, status=status)

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


@app.patch("/api/coalitie/{afspraak_id}", tags=["Coalitie"])
async def update_coalitie_afspraak(afspraak_id: str, request: UpdateAfspraakRequest, api_key: str = Depends(verify_api_key)):
    """
    Update de status van een coalitie-afspraak of koppel een besluit.
    """
    tracker = get_coalitie_tracker()
    result = {"afspraak_id": afspraak_id, "success": False}

    if request.new_status:
        if tracker.update_afspraak_status(afspraak_id, request.new_status):
            result["status_updated"] = request.new_status
            result["success"] = True

    if request.link_meeting_id:
        if tracker.link_besluit(afspraak_id, request.link_meeting_id):
            result["meeting_linked"] = request.link_meeting_id
            result["success"] = True

    return result


# ==================== Sync ====================

@app.post("/api/sync", response_model=SyncResponse, tags=["Beheer"])
async def sync_data(request: SyncRequest, api_key: str = Depends(verify_api_key)):
    """
    Synchroniseer data van Notubiz naar de lokale database.

    - **date_from**: Start datum voor sync
    - **date_to**: Eind datum voor sync
    - **download_documents**: Download PDF documenten en extraheer tekst
    - **index_documents**: Indexeer documenten voor semantic search
    """
    meeting_provider = get_meeting_provider()
    doc_provider = get_document_provider()

    meeting_provider.sync_gremia()
    meetings, docs = meeting_provider.sync_meetings(
        date_from=request.date_from,
        date_to=request.date_to
    )

    result = {"meetings": meetings, "documents_found": docs}

    if request.download_documents:
        success, failed = doc_provider.download_pending_documents()
        doc_provider.extract_all_text()
        result["documents_downloaded"] = success

    if request.index_documents:
        index = get_document_index()
        indexed, chunks = index.index_all_documents()
        result["documents_indexed"] = indexed

    return result


# ==================== Main ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
