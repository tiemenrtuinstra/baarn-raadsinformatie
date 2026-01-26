#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baarn Raadsinformatie REST API Server

FastAPI server die dezelfde functionaliteit biedt als de MCP server,
maar via REST endpoints. Geschikt voor ChatGPT Actions en andere integraties.

Authenticatie via X-API-Key header.
"""

import base64
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends, Security, UploadFile, File, Form
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from core.config import Config
from core.database import get_database
from core.document_index import get_document_index
from core.coalitie_tracker import get_coalitie_tracker
from providers.meeting_provider import get_meeting_provider
from providers.document_provider import get_document_provider
from providers.search_sync_provider import get_search_sync_provider
from providers.document_generator import get_document_generator
from providers.election_program_provider import get_election_program_provider
from providers.standpunt_provider import get_standpunt_provider
from providers.visit_report_provider import get_visit_report_provider
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


def _parse_list(value: Optional[str]) -> Optional[list[str]]:
    """Parse comma-separated list values from form inputs."""
    if not value:
        return None
    items = [item.strip() for item in value.split(',') if item.strip()]
    return items or None


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
    url: Optional[str] = None
    notubiz_url: Optional[str] = None
    has_text: bool
    text_content: Optional[str] = None
    truncated: bool = False


class SearchResult(BaseModel):
    id: int
    title: str
    url: Optional[str] = None
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


class SearchSyncRequest(BaseModel):
    query: str = Field(..., description="Zoekterm (bijv. 'Paleis Soestdijk', 'De Speeldoos')")
    start_date: str = Field("2010-01-01", description="Start datum (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="Eind datum (YYYY-MM-DD), default vandaag")
    download_documents: bool = Field(True, description="Download documenten en extraheer tekst")
    index_documents: bool = Field(True, description="Indexeer voor semantic search")
    limit: int = Field(100, description="Maximum aantal vergaderingen", ge=1, le=500)


class SearchSyncResponse(BaseModel):
    query: str
    date_range: str
    meetings_found: int
    meetings_synced: int
    documents_found: int
    documents_downloaded: int
    documents_indexed: int
    errors: list[str] = []


class AnnotationCreate(BaseModel):
    content: str = Field(..., description="Inhoud van de annotatie")
    document_id: Optional[int] = Field(None, description="Document ID")
    meeting_id: Optional[int] = Field(None, description="Vergadering ID")
    title: Optional[str] = Field(None, description="Titel")
    tags: Optional[list[str]] = Field(None, description="Tags")


@app.get("/upload", response_class=HTMLResponse, include_in_schema=False)
async def upload_portal():
    """Simple local upload portal."""
    return UPLOAD_HTML


@app.post("/upload", dependencies=[Depends(verify_api_key)], include_in_schema=False)
async def upload_file(
    file: UploadFile = File(...),
    title: str = Form(...),
    create_visit_report: bool = Form(True),
    date: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    participants: Optional[str] = Form(None),
    organizations: Optional[str] = Form(None),
    topics: Optional[str] = Form(None),
    visit_type: Optional[str] = Form(None),
    summary: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
):
    """Upload a local file and store it in the database."""
    file_bytes = await file.read()
    max_size = Config.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_size:
        raise HTTPException(status_code=413, detail="File too large for DB storage")

    file_base64 = base64.b64encode(file_bytes).decode('ascii')
    filename = file.filename or 'upload.bin'
    mime_type = file.content_type or 'application/octet-stream'

    if create_visit_report:
        provider = get_visit_report_provider()
        report_id = provider.add_manual_visit_report(
            title=title,
            file_base64=file_base64,
            filename=filename,
            mime_type=mime_type,
            date=date,
            location=location,
            participants=_parse_list(participants),
            organizations=_parse_list(organizations),
            topics=_parse_list(topics),
            visit_type=visit_type,
            summary=summary,
            status=status,
            source_url=source_url
        )
        return {"success": True, "visit_report_id": report_id}

    doc_provider = get_document_provider()
    document_id = doc_provider.create_document_from_base64(
        title=title,
        filename=filename,
        mime_type=mime_type,
        file_base64=file_base64,
        source_url=source_url
    )
    return {"success": True, "document_id": document_id}


# ==================== Upload Portal ====================

UPLOAD_HTML = """
<!doctype html>
<html lang="nl">
  <head>
    <meta charset="utf-8" />
    <title>Baarn Raadsinformatie - Uploader</title>
    <style>
      :root {
        --bg: #f7f4ef;
        --card: #ffffff;
        --ink: #1d1d1b;
        --accent: #0b4f6c;
        --muted: #6b6b6b;
      }
      body { font-family: "Segoe UI", Tahoma, sans-serif; margin: 0; background: var(--bg); color: var(--ink); }
      header { background: linear-gradient(135deg, #0b4f6c, #2a9d8f); color: #fff; padding: 24px; }
      header h1 { margin: 0 0 6px; font-size: 24px; }
      header p { margin: 0; opacity: 0.9; }
      main { max-width: 900px; margin: 24px auto; padding: 0 16px 32px; }
      .card { background: var(--card); border-radius: 12px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.08); }
      .row { margin-bottom: 14px; }
      label { display: block; font-weight: 600; margin-bottom: 6px; }
      input, textarea, select { width: 100%; padding: 10px; box-sizing: border-box; border: 1px solid #ddd; border-radius: 8px; }
      small { color: var(--muted); }
      .inline { display: inline-block; width: auto; margin-right: 12px; }
      .actions { display: flex; gap: 12px; flex-wrap: wrap; }
      button { padding: 10px 16px; border-radius: 8px; border: 0; cursor: pointer; font-weight: 600; }
      .primary { background: var(--accent); color: #fff; }
      .ghost { background: #e8f0f3; color: #0b4f6c; }
      pre { background: #f5f5f5; padding: 12px; border-radius: 8px; white-space: pre-wrap; }
    </style>
  </head>
  <body>
    <header>
      <h1>Werkbezoek/Document Uploader</h1>
      <p>Upload lokale bestanden (PDF/DOCX/PPTX/XLSX) en sla ze op in de database.</p>
    </header>
    <main>
      <div class="card">
        <div class="row">
          <label>Bestand</label>
          <input id="file" type="file" />
        </div>
        <div class="row">
          <label>Titel</label>
          <input id="title" type="text" placeholder="Titel van het document/verslag" />
        </div>
        <div class="row">
          <label>
            <input id="createVisit" type="checkbox" class="inline" checked />
            Werkbezoek-verslag aanmaken
          </label>
          <small>Laat uit om alleen een document te uploaden.</small>
        </div>
        <div class="row">
          <label>Datum (YYYY-MM-DD)</label>
          <input id="date" type="text" placeholder="2026-01-15" />
        </div>
        <div class="row">
          <label>Locatie</label>
          <input id="location" type="text" placeholder="Locatie" />
        </div>
        <div class="row">
          <label>Deelnemers (comma separated)</label>
          <input id="participants" type="text" placeholder="Naam 1, Naam 2" />
        </div>
        <div class="row">
          <label>Organisaties (comma separated)</label>
          <input id="organizations" type="text" placeholder="Organisatie A, Organisatie B" />
        </div>
        <div class="row">
          <label>Onderwerpen/tags (comma separated)</label>
          <input id="topics" type="text" placeholder="wonen, verkeer" />
        </div>
        <div class="row">
          <label>Type werkbezoek</label>
          <input id="visitType" type="text" placeholder="werkbezoek" />
        </div>
        <div class="row">
          <label>Samenvatting</label>
          <textarea id="summary" rows="3"></textarea>
        </div>
        <div class="row">
          <label>Status</label>
          <select id="status">
            <option value="">(default)</option>
            <option value="draft">draft</option>
            <option value="published">published</option>
            <option value="archived">archived</option>
          </select>
        </div>
        <div class="row">
          <label>Bron URL (optioneel)</label>
          <input id="sourceUrl" type="text" placeholder="https://..." />
        </div>
        <div class="row actions">
          <button id="setKeyBtn" class="ghost">API key instellen</button>
          <button id="uploadBtn" class="primary">Upload</button>
        </div>
        <small>De API key wordt opgeslagen in je browser (localStorage) en meegestuurd als header.</small>
      </div>
      <h3>Resultaat</h3>
      <pre id="output"></pre>
    </main>
    <script>
      const uploadBtn = document.getElementById('uploadBtn');
      const setKeyBtn = document.getElementById('setKeyBtn');

      setKeyBtn.addEventListener('click', () => {
        const key = prompt('Voer je X-API-Key in:');
        if (key) {
          localStorage.setItem('baarnApiKey', key.trim());
          alert('API key opgeslagen.');
        }
      });

      uploadBtn.addEventListener('click', async () => {
        const fileInput = document.getElementById('file');
        const file = fileInput.files[0];
        if (!file) {
          alert('Kies eerst een bestand.');
          return;
        }
        const apiKey = (localStorage.getItem('baarnApiKey') || '').trim();
        if (!apiKey) {
          alert('Stel eerst een API key in via "API key instellen".');
          return;
        }
        const formData = new FormData();
        formData.append('file', file);
        formData.append('title', document.getElementById('title').value.trim() || file.name);
        formData.append('create_visit_report', document.getElementById('createVisit').checked);
        formData.append('date', document.getElementById('date').value.trim());
        formData.append('location', document.getElementById('location').value.trim());
        formData.append('participants', document.getElementById('participants').value.trim());
        formData.append('organizations', document.getElementById('organizations').value.trim());
        formData.append('topics', document.getElementById('topics').value.trim());
        formData.append('visit_type', document.getElementById('visitType').value.trim());
        formData.append('summary', document.getElementById('summary').value.trim());
        formData.append('status', document.getElementById('status').value);
        formData.append('source_url', document.getElementById('sourceUrl').value.trim());

        const response = await fetch('/upload', {
          method: 'POST',
          headers: { 'X-API-Key': apiKey },
          body: formData
        });
        const text = await response.text();
        document.getElementById('output').textContent = text;
      });
    </script>
  </body>
</html>
"""


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


# ==================== Verkiezingsprogramma Models ====================

class PartyResponse(BaseModel):
    id: int
    name: str
    abbreviation: Optional[str] = None
    active: bool = True
    website: Optional[str] = None
    color: Optional[str] = None


class PartiesResponse(BaseModel):
    count: int
    parties: list[PartyResponse]


class ElectionProgramResult(BaseModel):
    program_id: int
    party: str
    abbreviation: Optional[str] = None
    year: int
    snippet: str


class ElectionProgramSearchResponse(BaseModel):
    query: str
    count: int
    results: list[ElectionProgramResult]


class PartyPositionComparison(BaseModel):
    topic: str
    year: Optional[int] = None
    parties: dict


class PartySyncResponse(BaseModel):
    timestamp: str
    sources_checked: list[str]
    parties_found: list[dict]
    new_parties: list[str]
    reactivated_parties: list[str]
    deactivated_parties: list[str]
    errors: list[str]


class PartySyncStatusResponse(BaseModel):
    total_parties: int
    active_parties: int
    historical_parties: int
    parties: list[dict]


# ==================== Document Generatie Models ====================

class MotieRequest(BaseModel):
    titel: str = Field(..., description="Titel van de motie")
    indieners: list[str] = Field(..., description="Namen van de indieners")
    partijen: list[str] = Field(..., description="Partijen van de indieners")
    constateringen: list[str] = Field(..., description="Constaterende dat... punten")
    overwegingen: list[str] = Field(..., description="Overwegende dat... punten")
    verzoeken: list[str] = Field(..., description="Verzoekt het college... punten")
    vergadering_datum: Optional[str] = Field(None, description="Datum vergadering (YYYY-MM-DD)")
    agendapunt: Optional[str] = Field(None, description="Agendapunt nummer")
    toelichting: Optional[str] = Field(None, description="Optionele toelichting")


class WijzigingItem(BaseModel):
    oorspronkelijk: str = Field(..., description="Oorspronkelijke tekst")
    wordt: str = Field(..., description="Nieuwe tekst")


class AmendementRequest(BaseModel):
    titel: str = Field(..., description="Titel van het amendement")
    indieners: list[str] = Field(..., description="Namen van de indieners")
    partijen: list[str] = Field(..., description="Partijen van de indieners")
    raadsvoorstel_nummer: str = Field(..., description="Nummer van het raadsvoorstel")
    raadsvoorstel_titel: str = Field(..., description="Titel van het raadsvoorstel")
    wijzigingen: list[WijzigingItem] = Field(..., description="Lijst van tekstwijzigingen")
    toelichting: Optional[str] = Field(None, description="Toelichting op de wijzigingen")
    vergadering_datum: Optional[str] = Field(None, description="Datum vergadering (YYYY-MM-DD)")
    agendapunt: Optional[str] = Field(None, description="Agendapunt nummer")


class DocumentGenerationResponse(BaseModel):
    titel: str
    type: str
    filepath: Optional[str] = None
    filename: Optional[str] = None
    markdown: str
    warning: Optional[str] = None


# ==================== Standpunten Models ====================

class StandpuntCreate(BaseModel):
    party_id: Optional[int] = Field(None, description="Partij ID")
    raadslid_id: Optional[int] = Field(None, description="Raadslid ID")
    topic: str = Field(..., description="Onderwerp")
    position_summary: str = Field(..., description="Korte samenvatting")
    position_text: Optional[str] = Field(None, description="Volledige tekst")
    stance: str = Field("onbekend", description="voor/tegen/neutraal/genuanceerd/onbekend")
    stance_strength: Optional[int] = Field(None, ge=1, le=5, description="Sterkte (1-5)")
    source_type: str = Field(..., description="Type bron")
    source_document_id: Optional[int] = Field(None, description="Document ID bron")
    source_meeting_id: Optional[int] = Field(None, description="Vergadering ID bron")
    source_quote: Optional[str] = Field(None, description="Citaat uit bron")
    position_date: Optional[str] = Field(None, description="Datum (YYYY-MM-DD)")
    subtopic: Optional[str] = Field(None, description="Subonderwerp")
    tags: Optional[list[str]] = Field(None, description="Tags")


class StandpuntResponse(BaseModel):
    id: int
    party_id: Optional[int] = None
    party_name: Optional[str] = None
    raadslid_id: Optional[int] = None
    raadslid_name: Optional[str] = None
    topic: str
    subtopic: Optional[str] = None
    position_summary: str
    position_text: Optional[str] = None
    stance: str
    stance_strength: Optional[int] = None
    source_type: str
    verified: bool = False
    position_date: Optional[str] = None


class StandpuntenSearchResponse(BaseModel):
    count: int
    standpunten: list[dict]


class StandpuntenCompareResponse(BaseModel):
    topic: str
    parties: dict
    summary: Optional[dict] = None


class StandpuntHistoryResponse(BaseModel):
    topic: str
    history: list[dict]


class PartyContextResponse(BaseModel):
    party_id: Optional[int] = None
    party_name: Optional[str] = None
    standpunten_by_topic: dict
    total_standpunten: int


class RaadslidCreate(BaseModel):
    name: str = Field(..., description="Volledige naam")
    party_id: Optional[int] = Field(None, description="Partij ID")
    email: Optional[str] = Field(None, description="E-mailadres")
    start_date: Optional[str] = Field(None, description="Start datum (YYYY-MM-DD)")
    is_wethouder: bool = Field(False, description="Is wethouder")
    is_fractievoorzitter: bool = Field(False, description="Is fractievoorzitter")
    is_steunfractielid: bool = Field(False, description="Is steunfractielid (geen stemrecht in raad)")


class RaadslidResponse(BaseModel):
    id: int
    name: str
    party_id: Optional[int] = None
    party_name: Optional[str] = None
    email: Optional[str] = None
    active: bool = True
    is_wethouder: bool = False
    is_fractievoorzitter: bool = False
    is_steunfractielid: bool = False


class RaadsledenResponse(BaseModel):
    count: int
    raadsleden: list[dict]


class TopicResponse(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    keywords: Optional[str] = None


class TopicsResponse(BaseModel):
    count: int
    topics: list[TopicResponse]


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
    Inclusief download URL naar het originele document.
    """
    provider = get_document_provider()
    doc = provider.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document niet gevonden")

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


@app.get("/api/documents/search", response_model=SearchResponse, tags=["Zoeken"])
async def search_documents(
    query: str = Query(..., description="Zoekterm"),
    limit: int = Query(20, description="Maximum resultaten", le=100),
    api_key: str = Depends(verify_api_key)
):
    """
    Zoek in documenten op titel en inhoud (keyword search).

    Doorzoekt document titels en geëxtraheerde tekst.
    Inclusief download URLs naar de originele documenten.
    """
    provider = get_document_provider()
    results = provider.search_documents(query, limit)
    return {
        "query": query,
        "count": len(results),
        "results": [
            {
                "id": d['id'],
                "title": d['title'],
                "url": d.get('url') or (f"https://api.notubiz.nl/document/{d['notubiz_id']}/1" if d.get('notubiz_id') else None),
                "match_type": d.get('match_type', [])
            }
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


@app.post("/api/search-sync", response_model=SearchSyncResponse, tags=["Beheer"])
async def search_and_sync(request: SearchSyncRequest, api_key: str = Depends(verify_api_key)):
    """
    Zoek naar een specifiek onderwerp en synchroniseer alleen relevante vergaderingen.

    Dit is efficiënter dan een volledige sync wanneer je zoekt naar specifieke dossiers
    zoals "Paleis Soestdijk" of "De Speeldoos".

    - **query**: Zoekterm (bijv. "Paleis Soestdijk")
    - **start_date**: Start datum voor zoeken (default: 2010-01-01)
    - **end_date**: Eind datum (default: vandaag)
    - **download_documents**: Download en extraheer tekst uit documenten
    - **index_documents**: Indexeer documenten voor semantic search
    - **limit**: Maximum aantal vergaderingen om te syncen

    De sync zoekt eerst naar vergaderingen met de zoekterm in titel, beschrijving
    of commissienaam. Als niets gevonden wordt, zoekt het dieper in agenda items
    en document titels.
    """
    provider = get_search_sync_provider()

    result = provider.search_and_sync(
        query=request.query,
        start_date=request.start_date,
        end_date=request.end_date,
        download_docs=request.download_documents,
        index_docs=request.index_documents,
        limit=request.limit
    )

    return result


# ==================== Aankomende Vergaderingen ====================

@app.get("/api/meetings/upcoming", tags=["Vergaderingen"])
async def get_upcoming_meetings(
    period: str = Query(
        "this_week",
        description="Periode: today, tomorrow, this_week, next_week, this_month"
    ),
    include_agenda: bool = Query(True, description="Inclusief agendapunten"),
    include_documents: bool = Query(False, description="Inclusief documenten"),
    api_key: str = Depends(verify_api_key)
):
    """
    Haal aankomende vergaderingen op voor een specifieke periode.

    Handig voor vragen als "wat staat er morgen op de agenda?"

    Periodes:
    - **today**: Vergaderingen vandaag
    - **tomorrow**: Vergaderingen morgen
    - **this_week**: Vergaderingen deze week (ma-zo)
    - **next_week**: Vergaderingen volgende week
    - **this_month**: Alle vergaderingen deze maand
    """
    from datetime import date, timedelta

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
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        date_from = start.isoformat()
        date_to = end.isoformat()
        period_label = f"deze week ({start.strftime('%d-%m')} - {end.strftime('%d-%m')})"
    elif period == 'next_week':
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
        end = start + timedelta(days=6)
        date_from = start.isoformat()
        date_to = end.isoformat()
        period_label = f"volgende week ({start.strftime('%d-%m')} - {end.strftime('%d-%m')})"
    elif period == 'this_month':
        start = today.replace(day=1)
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
                        "url": d.get('url') or (
                            f"https://api.notubiz.nl/document/{d['notubiz_id']}/1"
                            if d.get('notubiz_id') else None
                        )
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


# ==================== Verkiezingsprogramma's ====================

@app.get("/api/parties", response_model=PartiesResponse, tags=["Verkiezingsprogramma's"])
async def list_parties(
    active_only: bool = Query(False, description="Alleen actieve partijen"),
    api_key: str = Depends(verify_api_key)
):
    """
    Lijst alle politieke partijen in Baarn (actief en historisch).

    Retourneert een overzicht van alle partijen die ooit in de gemeente Baarn
    actief zijn geweest, inclusief hun afkorting, website en partijkleur.
    """
    provider = get_election_program_provider()
    provider.initialize_parties()
    parties = provider.get_parties(active_only=active_only)

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


@app.post("/api/parties/sync", response_model=PartySyncResponse, tags=["Verkiezingsprogramma's"])
async def sync_parties(
    initialize_known: bool = Query(True, description="Initialiseer ook bekende historische partijen"),
    api_key: str = Depends(verify_api_key)
):
    """
    Synchroniseer politieke partijen door de gemeente Baarn website te checken.

    Detecteert nieuwe partijen en identificeert partijen die mogelijk
    niet meer actief zijn. Scrape de gemeentelijke website voor actuele fracties.
    """
    provider = get_election_program_provider()

    # Initialize known parties first if requested
    if initialize_known:
        provider.initialize_parties()

    # Check for updates from web
    result = provider.check_and_update_parties_from_web()
    return result


@app.get("/api/parties/sync/status", response_model=PartySyncStatusResponse, tags=["Verkiezingsprogramma's"])
async def get_party_sync_status(api_key: str = Depends(verify_api_key)):
    """
    Bekijk de huidige status van partij-synchronisatie.

    Retourneert aantal actieve en historische partijen en een overzicht
    van alle geregistreerde partijen.
    """
    provider = get_election_program_provider()
    return provider.get_party_sync_status()


@app.get("/api/election-programs/search", response_model=ElectionProgramSearchResponse, tags=["Verkiezingsprogramma's"])
async def search_election_programs(
    query: str = Query(..., description="Zoekterm"),
    party: Optional[str] = Query(None, description="Filter op partij (naam of afkorting)"),
    year_from: Optional[int] = Query(None, description="Vanaf verkiezingsjaar"),
    year_to: Optional[int] = Query(None, description="Tot verkiezingsjaar"),
    limit: int = Query(20, description="Maximum resultaten", ge=1, le=100),
    api_key: str = Depends(verify_api_key)
):
    """
    Zoek in verkiezingsprogramma's van Baarnse politieke partijen.

    Doorzoekt de tekst van alle verkiezingsprogramma's en retourneert
    relevante passages met context.

    - **query**: Zoekterm (bijv. "woningbouw", "duurzaamheid")
    - **party**: Filter op specifieke partij (naam of afkorting)
    - **year_from/year_to**: Filter op verkiezingsjaar
    """
    provider = get_election_program_provider()
    results = provider.search_programs(
        query=query,
        party=party,
        year_from=year_from,
        year_to=year_to,
        limit=limit
    )

    return {
        "query": query,
        "count": len(results),
        "results": [
            {
                "program_id": r.get('id', 0),
                "party": r.get('party_name', ''),
                "abbreviation": r.get('abbreviation'),
                "year": r.get('election_year', 0),
                "snippet": r.get('snippet', '')[:500]
            }
            for r in results
        ]
    }


@app.get("/api/election-programs/compare", response_model=PartyPositionComparison, tags=["Verkiezingsprogramma's"])
async def compare_party_positions(
    topic: str = Query(..., description="Onderwerp (bijv. 'woningbouw', 'duurzaamheid')"),
    parties: Optional[str] = Query(None, description="Partijen om te vergelijken (komma-gescheiden)"),
    year: Optional[int] = Query(None, description="Specifiek verkiezingsjaar"),
    api_key: str = Depends(verify_api_key)
):
    """
    Vergelijk standpunten van partijen over een specifiek onderwerp.

    Zoekt in alle verkiezingsprogramma's naar het opgegeven onderwerp
    en groepeert de resultaten per partij.

    - **topic**: Het onderwerp om te vergelijken
    - **parties**: Optioneel, komma-gescheiden lijst van partijen
    - **year**: Optioneel, specifiek verkiezingsjaar
    """
    provider = get_election_program_provider()

    parties_list = None
    if parties:
        parties_list = [p.strip() for p in parties.split(',')]

    result = provider.compare_positions(
        topic=topic,
        parties=parties_list,
        year=year
    )
    return result


@app.get("/api/election-programs/history", tags=["Verkiezingsprogramma's"])
async def get_party_position_history(
    party: str = Query(..., description="Partij naam of afkorting"),
    topic: str = Query(..., description="Onderwerp"),
    api_key: str = Depends(verify_api_key)
):
    """
    Bekijk de historische ontwikkeling van een partijstandpunt.

    Toont hoe het standpunt van een partij over een bepaald onderwerp
    is veranderd door de jaren heen.

    - **party**: Naam of afkorting van de partij
    - **topic**: Het onderwerp om te volgen
    """
    provider = get_election_program_provider()
    history = provider.get_party_position_history(party=party, topic=topic)

    return {
        "party": party,
        "topic": topic,
        "positions": history
    }


# ==================== Document Generatie ====================

@app.post("/api/documents/motie", response_model=DocumentGenerationResponse, tags=["Document Generatie"])
async def generate_motie(
    request: MotieRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Genereer een motie document in Word formaat.

    Maakt een professioneel motie document conform de Notubiz standaard
    voor de gemeente Baarn.

    **Vereiste velden:**
    - titel: Titel van de motie
    - indieners: Namen van de indieners
    - partijen: Partijen van de indieners
    - constateringen: "Constaterende dat..." punten (minimaal 1)
    - overwegingen: "Overwegende dat..." punten (minimaal 1)
    - verzoeken: "Verzoekt het college..." punten (minimaal 1)

    **Optionele velden:**
    - vergadering_datum: Datum van de vergadering
    - agendapunt: Nummer van het agendapunt
    - toelichting: Nadere toelichting
    """
    generator = get_document_generator()

    result = generator.generate_motie(
        titel=request.titel,
        indieners=request.indieners,
        partijen=request.partijen,
        constateringen=request.constateringen,
        overwegingen=request.overwegingen,
        verzoeken=request.verzoeken,
        vergadering_datum=request.vergadering_datum,
        agendapunt=request.agendapunt,
        toelichting=request.toelichting
    )

    return result


@app.post("/api/documents/amendement", response_model=DocumentGenerationResponse, tags=["Document Generatie"])
async def generate_amendement(
    request: AmendementRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Genereer een amendement document in Word formaat.

    Maakt een professioneel amendement document conform de Notubiz standaard
    voor de gemeente Baarn.

    **Vereiste velden:**
    - titel: Titel van het amendement
    - indieners: Namen van de indieners
    - partijen: Partijen van de indieners
    - raadsvoorstel_nummer: Nummer van het raadsvoorstel
    - raadsvoorstel_titel: Titel van het raadsvoorstel
    - wijzigingen: Lijst van tekstwijzigingen met oorspronkelijke en nieuwe tekst

    **Optionele velden:**
    - toelichting: Toelichting op de wijzigingen
    - vergadering_datum: Datum van de vergadering
    - agendapunt: Nummer van het agendapunt
    """
    generator = get_document_generator()

    # Convert Pydantic models to dicts
    wijzigingen = [w.model_dump() for w in request.wijzigingen]

    result = generator.generate_amendement(
        titel=request.titel,
        indieners=request.indieners,
        partijen=request.partijen,
        raadsvoorstel_nummer=request.raadsvoorstel_nummer,
        raadsvoorstel_titel=request.raadsvoorstel_titel,
        wijzigingen=wijzigingen,
        toelichting=request.toelichting,
        vergadering_datum=request.vergadering_datum,
        agendapunt=request.agendapunt
    )

    return result


# ==================== Standpunten ====================

@app.post("/api/standpunten", tags=["Standpunten"])
async def add_standpunt(
    standpunt: StandpuntCreate,
    api_key: str = Depends(verify_api_key)
):
    """
    Voeg een politiek standpunt toe voor een partij of raadslid.

    Een standpunt moet gekoppeld zijn aan minimaal een partij of raadslid.

    **Stance opties:**
    - voor: Actieve ondersteuning
    - tegen: Expliciet tegen
    - neutraal: Geen duidelijke positie
    - genuanceerd: Gemengd/voorwaardelijk
    - onbekend: Onbekend

    **Source types:**
    verkiezingsprogramma, motie, amendement, debat, stemming, interview, persbericht, website, anders
    """
    provider = get_standpunt_provider()
    result = provider.add_standpunt(
        party_id=standpunt.party_id,
        raadslid_id=standpunt.raadslid_id,
        topic=standpunt.topic,
        position_summary=standpunt.position_summary,
        position_text=standpunt.position_text,
        stance=standpunt.stance,
        stance_strength=standpunt.stance_strength,
        source_type=standpunt.source_type,
        source_document_id=standpunt.source_document_id,
        source_meeting_id=standpunt.source_meeting_id,
        source_quote=standpunt.source_quote,
        position_date=standpunt.position_date,
        subtopic=standpunt.subtopic,
        tags=standpunt.tags
    )
    return result


@app.get("/api/standpunten", response_model=StandpuntenSearchResponse, tags=["Standpunten"])
async def search_standpunten(
    query: Optional[str] = Query(None, description="Zoekterm in standpunten"),
    party_id: Optional[int] = Query(None, description="Filter op partij ID"),
    party_name: Optional[str] = Query(None, description="Filter op partijnaam"),
    raadslid_id: Optional[int] = Query(None, description="Filter op raadslid ID"),
    topic: Optional[str] = Query(None, description="Filter op topic"),
    stance: Optional[str] = Query(None, description="Filter op stance"),
    verified_only: bool = Query(False, description="Alleen geverifieerde standpunten"),
    limit: int = Query(50, description="Maximum resultaten", ge=1, le=200),
    api_key: str = Depends(verify_api_key)
):
    """
    Zoek standpunten met diverse filters.

    Alle filters zijn optioneel en kunnen gecombineerd worden.
    """
    provider = get_standpunt_provider()
    results = provider.search_standpunten(
        query=query,
        party_id=party_id,
        party_name=party_name,
        raadslid_id=raadslid_id,
        topic=topic,
        stance=stance,
        verified_only=verified_only,
        limit=limit
    )
    return {
        "count": len(results),
        "standpunten": results
    }


@app.get("/api/standpunten/compare/{topic}", tags=["Standpunten"])
async def compare_standpunten(
    topic: str,
    party_ids: Optional[str] = Query(None, description="Partij IDs (komma-gescheiden)"),
    include_raadsleden: bool = Query(False, description="Ook individuele raadsleden meenemen"),
    api_key: str = Depends(verify_api_key)
):
    """
    Vergelijk standpunten van verschillende partijen over een specifiek onderwerp.

    Retourneert een overzicht van alle partijstandpunten over het opgegeven topic,
    met hun stance en samenvatting.
    """
    provider = get_standpunt_provider()

    party_ids_list = None
    if party_ids:
        party_ids_list = [int(p.strip()) for p in party_ids.split(',')]

    result = provider.compare_standpunten(
        topic=topic,
        party_ids=party_ids_list,
        include_raadsleden=include_raadsleden
    )
    return result


@app.get("/api/standpunten/history/{topic}", response_model=StandpuntHistoryResponse, tags=["Standpunten"])
async def get_standpunt_history(
    topic: str,
    party_id: Optional[int] = Query(None, description="Filter op partij"),
    raadslid_id: Optional[int] = Query(None, description="Filter op raadslid"),
    api_key: str = Depends(verify_api_key)
):
    """
    Bekijk de historische ontwikkeling van standpunten over een topic.

    Toont hoe standpunten over een onderwerp zijn veranderd door de tijd.
    """
    provider = get_standpunt_provider()
    history = provider.get_standpunt_history(
        topic=topic,
        party_id=party_id,
        raadslid_id=raadslid_id
    )
    return {
        "topic": topic,
        "history": history
    }


@app.get("/api/parties/{party_id}/context", tags=["Standpunten"])
async def get_party_context(
    party_id: int,
    topics: Optional[str] = Query(None, description="Specifieke topics (komma-gescheiden)"),
    api_key: str = Depends(verify_api_key)
):
    """
    Haal context op van een partij voor party-aligned antwoorden.

    Geeft een overzicht van alle standpunten, gegroepeerd per topic.
    Handig voor het beantwoorden van vragen vanuit het perspectief van een partij.
    """
    provider = get_standpunt_provider()

    topics_list = None
    if topics:
        topics_list = [t.strip() for t in topics.split(',')]

    context = provider.get_party_context(
        party_id=party_id,
        topics=topics_list
    )
    return context


@app.get("/api/parties/context/{party_name}", tags=["Standpunten"])
async def get_party_context_by_name(
    party_name: str,
    topics: Optional[str] = Query(None, description="Specifieke topics (komma-gescheiden)"),
    api_key: str = Depends(verify_api_key)
):
    """
    Haal context op van een partij (via naam) voor party-aligned antwoorden.

    Alternatief endpoint dat partijnaam gebruikt in plaats van ID.
    """
    provider = get_standpunt_provider()

    topics_list = None
    if topics:
        topics_list = [t.strip() for t in topics.split(',')]

    context = provider.get_party_context(
        party_name=party_name,
        topics=topics_list
    )
    return context


@app.patch("/api/standpunten/{standpunt_id}/verify", tags=["Standpunten"])
async def verify_standpunt(
    standpunt_id: int,
    verified: bool = Query(True, description="Verificatie status"),
    api_key: str = Depends(verify_api_key)
):
    """
    Markeer een standpunt als geverifieerd.

    Geverifieerde standpunten zijn bevestigd door een menselijke reviewer.
    """
    provider = get_standpunt_provider()
    result = provider.verify_standpunt(
        standpunt_id=standpunt_id,
        verified=verified
    )
    return result


@app.get("/api/standpunten/topics", response_model=TopicsResponse, tags=["Standpunten"])
async def get_standpunt_topics(
    parent_id: Optional[int] = Query(None, description="Filter op parent topic"),
    api_key: str = Depends(verify_api_key)
):
    """
    Haal de lijst van standpunt-topics op.

    Topics zijn de hoofdcategorieen waaronder standpunten worden ingedeeld.
    Subtopics hebben een parent_id die verwijst naar hun hoofdtopic.
    """
    provider = get_standpunt_provider()
    topics = provider.get_topics(parent_id=parent_id)
    return {
        "count": len(topics),
        "topics": topics
    }


# ==================== Raadsleden ====================

@app.get("/api/raadsleden", response_model=RaadsledenResponse, tags=["Raadsleden"])
async def list_raadsleden(
    party_id: Optional[int] = Query(None, description="Filter op partij"),
    active_only: bool = Query(True, description="Alleen actieve raadsleden"),
    api_key: str = Depends(verify_api_key)
):
    """
    Lijst alle raadsleden met optionele filters.

    Retourneert raadsleden inclusief hun partij, rol (wethouder/fractievoorzitter),
    en contactgegevens.
    """
    provider = get_standpunt_provider()
    raadsleden = provider.get_raadsleden(
        party_id=party_id,
        active_only=active_only
    )
    return {
        "count": len(raadsleden),
        "raadsleden": raadsleden
    }


@app.post("/api/raadsleden", tags=["Raadsleden"])
async def add_raadslid(
    raadslid: RaadslidCreate,
    api_key: str = Depends(verify_api_key)
):
    """
    Voeg een raadslid toe aan de database.

    Raadsleden kunnen gekoppeld worden aan een partij en kunnen
    gemarkeerd worden als wethouder of fractievoorzitter.
    """
    provider = get_standpunt_provider()
    result = provider.add_raadslid(
        name=raadslid.name,
        party_id=raadslid.party_id,
        email=raadslid.email,
        start_date=raadslid.start_date,
        is_wethouder=raadslid.is_wethouder,
        is_fractievoorzitter=raadslid.is_fractievoorzitter,
        is_steunfractielid=raadslid.is_steunfractielid
    )
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
