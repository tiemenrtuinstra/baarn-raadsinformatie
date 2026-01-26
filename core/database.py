#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database module voor Baarn Politiek MCP Server.
SQLite database voor meetings, documents, en annotations.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

from .config import Config
from shared.logging_config import get_logger

logger = get_logger('database')


class Database:
    """SQLite database manager voor politieke documenten."""

    def __init__(self, db_path: Path = None):
        """Initialize database connection."""
        self.db_path = db_path or Config.DB_PATH
        self._ensure_db_dir()
        self._init_schema()
        logger.info(f'Database initialized: {self.db_path}')

    def _ensure_db_dir(self):
        """Ensure database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better crash recovery and concurrent access
        conn.execute('PRAGMA journal_mode=WAL')
        # FULL sync: wait for data to be written to disk before continuing
        # This prevents corruption on crash/power loss at cost of some performance
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('PRAGMA wal_autocheckpoint=100')  # Checkpoint more frequently
        conn.execute('PRAGMA busy_timeout=60000')  # 60 second timeout for locks
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f'Database error: {e}')
            raise
        finally:
            conn.close()

    def execute_sql(self, sql: str, params: tuple = ()) -> int:
        """Execute raw SQL and return rows affected."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.rowcount

    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Organizations/Gremia table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS gremia (
                    id INTEGER PRIMARY KEY,
                    notubiz_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    type TEXT,
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Meetings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY,
                    notubiz_id TEXT UNIQUE NOT NULL,
                    gremium_id INTEGER,
                    title TEXT NOT NULL,
                    date DATE NOT NULL,
                    start_time TIME,
                    end_time TIME,
                    location TEXT,
                    status TEXT,
                    description TEXT,
                    video_url TEXT,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (gremium_id) REFERENCES gremia(id)
                )
            ''')

            # Agenda items table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS agenda_items (
                    id INTEGER PRIMARY KEY,
                    notubiz_id TEXT UNIQUE NOT NULL,
                    meeting_id INTEGER NOT NULL,
                    parent_id INTEGER,
                    order_number INTEGER,
                    title TEXT NOT NULL,
                    description TEXT,
                    decision TEXT,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
                    FOREIGN KEY (parent_id) REFERENCES agenda_items(id)
                )
            ''')

            # Documents table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    notubiz_id TEXT UNIQUE,
                    meeting_id INTEGER,
                    agenda_item_id INTEGER,
                    title TEXT NOT NULL,
                    filename TEXT,
                    url TEXT,
                    local_path TEXT,
                    mime_type TEXT,
                    file_size INTEGER,
                    text_content TEXT,
                    text_extracted INTEGER DEFAULT 0,
                    download_status TEXT DEFAULT 'pending',
                    file_blob BLOB,
                    file_storage_mode TEXT DEFAULT 'db',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
                    FOREIGN KEY (agenda_item_id) REFERENCES agenda_items(id)
                )
            ''')

            # Unique images (deduplicated storage)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS unique_images (
                    id INTEGER PRIMARY KEY,
                    image_hash TEXT NOT NULL UNIQUE,
                    file_path TEXT NOT NULL,
                    mime_type TEXT,
                    width INTEGER,
                    height INTEGER,
                    file_size INTEGER,
                    ocr_text TEXT,
                    ocr_status TEXT DEFAULT 'pending',
                    reference_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Document images (references to unique images or direct paths)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS document_images (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL,
                    image_index INTEGER NOT NULL,
                    mime_type TEXT,
                    file_path TEXT NOT NULL,
                    image_hash TEXT,
                    unique_image_id INTEGER,
                    width INTEGER,
                    height INTEGER,
                    file_size INTEGER,
                    ocr_text TEXT,
                    ocr_status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES documents(id),
                    FOREIGN KEY (unique_image_id) REFERENCES unique_images(id)
                )
            ''')

            # Visit reports
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS visit_reports (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    source TEXT NOT NULL,
                    source_id TEXT,
                    title TEXT NOT NULL,
                    date DATE,
                    location TEXT,
                    participants TEXT,
                    organizations TEXT,
                    topics TEXT,
                    visit_type TEXT,
                    summary TEXT,
                    status TEXT DEFAULT 'draft',
                    source_url TEXT,
                    attachments TEXT,
                    deleted_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES documents(id),
                    UNIQUE(source, source_id)
                )
            ''')

            # Visit report ↔ meetings link table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS visit_report_meetings (
                    id INTEGER PRIMARY KEY,
                    visit_report_id INTEGER NOT NULL,
                    meeting_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(visit_report_id, meeting_id),
                    FOREIGN KEY (visit_report_id) REFERENCES visit_reports(id),
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
                )
            ''')

            # Backfill new columns for existing databases
            cursor.execute('PRAGMA table_info(documents)')
            document_columns = {row['name'] for row in cursor.fetchall()}
            if 'file_blob' not in document_columns:
                cursor.execute('ALTER TABLE documents ADD COLUMN file_blob BLOB')
            if 'file_storage_mode' not in document_columns:
                cursor.execute("ALTER TABLE documents ADD COLUMN file_storage_mode TEXT DEFAULT 'db'")

            # Migrate document_images from base64 to filesystem paths + OCR
            cursor.execute('PRAGMA table_info(document_images)')
            image_columns = {row['name'] for row in cursor.fetchall()}
            if 'file_path' not in image_columns:
                cursor.execute('ALTER TABLE document_images ADD COLUMN file_path TEXT')
            if 'width' not in image_columns:
                cursor.execute('ALTER TABLE document_images ADD COLUMN width INTEGER')
            if 'height' not in image_columns:
                cursor.execute('ALTER TABLE document_images ADD COLUMN height INTEGER')
            if 'file_size' not in image_columns:
                cursor.execute('ALTER TABLE document_images ADD COLUMN file_size INTEGER')
            if 'ocr_text' not in image_columns:
                cursor.execute('ALTER TABLE document_images ADD COLUMN ocr_text TEXT')
            if 'ocr_status' not in image_columns:
                cursor.execute("ALTER TABLE document_images ADD COLUMN ocr_status TEXT DEFAULT 'pending'")
            # Image deduplication columns
            if 'image_hash' not in image_columns:
                cursor.execute('ALTER TABLE document_images ADD COLUMN image_hash TEXT')
            if 'unique_image_id' not in image_columns:
                cursor.execute('ALTER TABLE document_images ADD COLUMN unique_image_id INTEGER')

            # Annotations table (user notes on documents)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS annotations (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    meeting_id INTEGER,
                    agenda_item_id INTEGER,
                    title TEXT,
                    content TEXT NOT NULL,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES documents(id),
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
                    FOREIGN KEY (agenda_item_id) REFERENCES agenda_items(id)
                )
            ''')

            # Embeddings table (for semantic search)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    chunk_index INTEGER,
                    chunk_text TEXT,
                    embedding BLOB,
                    model TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES documents(id)
                )
            ''')

            # Sync status table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_status (
                    id INTEGER PRIMARY KEY,
                    entity_type TEXT UNIQUE NOT NULL,
                    last_sync TIMESTAMP,
                    last_sync_from DATE,
                    last_sync_to DATE,
                    items_synced INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'idle',
                    error_message TEXT
                )
            ''')

            # Sync progress tracking (for resumable syncs)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_progress (
                    id INTEGER PRIMARY KEY,
                    sync_id TEXT UNIQUE NOT NULL,
                    sync_type TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    date_from DATE,
                    date_to DATE,
                    total_items INTEGER DEFAULT 0,
                    processed_items INTEGER DEFAULT 0,
                    last_processed_id TEXT,
                    status TEXT DEFAULT 'running',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT
                )
            ''')

            # ==================== Verkiezingsprogramma's ====================

            # Politieke partijen
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parties (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    abbreviation TEXT,
                    website_url TEXT,
                    founded_year INTEGER,
                    active INTEGER DEFAULT 1,
                    color TEXT,
                    logo_url TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Verkiezingsprogramma's
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS election_programs (
                    id INTEGER PRIMARY KEY,
                    party_id INTEGER NOT NULL,
                    election_year INTEGER NOT NULL,
                    election_type TEXT NOT NULL DEFAULT 'gemeenteraad',
                    title TEXT,
                    source_url TEXT,
                    local_path TEXT,
                    text_content TEXT,
                    text_extracted INTEGER DEFAULT 0,
                    download_status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (party_id) REFERENCES parties(id),
                    UNIQUE(party_id, election_year, election_type)
                )
            ''')

            # Partij standpunten (geextraheerd uit programma's)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS party_positions (
                    id INTEGER PRIMARY KEY,
                    party_id INTEGER NOT NULL,
                    election_program_id INTEGER,
                    topic TEXT NOT NULL,
                    position_text TEXT NOT NULL,
                    source_page INTEGER,
                    confidence_score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (party_id) REFERENCES parties(id),
                    FOREIGN KEY (election_program_id) REFERENCES election_programs(id)
                )
            ''')

            # Embeddings voor verkiezingsprogramma's
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS program_embeddings (
                    id INTEGER PRIMARY KEY,
                    election_program_id INTEGER,
                    chunk_index INTEGER,
                    chunk_text TEXT,
                    embedding BLOB,
                    model TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (election_program_id) REFERENCES election_programs(id)
                )
            ''')

            # Scraping configuratie per partij
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS party_scrape_config (
                    id INTEGER PRIMARY KEY,
                    party_id INTEGER NOT NULL UNIQUE,
                    scrape_strategy TEXT NOT NULL DEFAULT 'manual',
                    program_url_pattern TEXT,
                    last_scrape TIMESTAMP,
                    scrape_interval_days INTEGER DEFAULT 30,
                    enabled INTEGER DEFAULT 1,
                    notes TEXT,
                    FOREIGN KEY (party_id) REFERENCES parties(id)
                )
            ''')

            # ==================== Standpunten System ====================

            # Raadsleden (Council Members) table
            # Includes: raadsleden, wethouders, fractievoorzitters, and steunfractieleden
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS raadsleden (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    party_id INTEGER,
                    email TEXT,
                    phone TEXT,
                    photo_url TEXT,
                    bio TEXT,
                    start_date DATE,
                    end_date DATE,
                    is_wethouder INTEGER DEFAULT 0,
                    is_fractievoorzitter INTEGER DEFAULT 0,
                    is_steunfractielid INTEGER DEFAULT 0,
                    active INTEGER DEFAULT 1,
                    notubiz_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (party_id) REFERENCES parties(id)
                )
            ''')

            # Standpunten (Political Positions) table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS standpunten (
                    id INTEGER PRIMARY KEY,
                    party_id INTEGER,
                    raadslid_id INTEGER,
                    topic TEXT NOT NULL,
                    subtopic TEXT,
                    tags TEXT,
                    position_summary TEXT NOT NULL,
                    position_text TEXT,
                    stance TEXT CHECK(stance IN ('voor', 'tegen', 'neutraal', 'genuanceerd', 'onbekend')) DEFAULT 'onbekend',
                    stance_strength INTEGER CHECK(stance_strength BETWEEN 1 AND 5),
                    source_type TEXT NOT NULL CHECK(source_type IN (
                        'verkiezingsprogramma', 'motie', 'amendement', 'debat',
                        'stemming', 'raadsvraag', 'interview', 'persbericht',
                        'coalitieakkoord', 'handmatig'
                    )),
                    source_document_id INTEGER,
                    source_meeting_id INTEGER,
                    source_agenda_item_id INTEGER,
                    source_election_program_id INTEGER,
                    source_url TEXT,
                    source_page INTEGER,
                    source_quote TEXT,
                    extraction_method TEXT CHECK(extraction_method IN ('ai', 'manual', 'semi-auto')) NOT NULL,
                    extraction_model TEXT,
                    confidence_score REAL CHECK(confidence_score BETWEEN 0.0 AND 1.0),
                    verified INTEGER DEFAULT 0,
                    verified_by TEXT,
                    verified_at TIMESTAMP,
                    position_date DATE,
                    valid_from DATE,
                    valid_until DATE,
                    superseded_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT,
                    FOREIGN KEY (party_id) REFERENCES parties(id),
                    FOREIGN KEY (raadslid_id) REFERENCES raadsleden(id),
                    FOREIGN KEY (source_document_id) REFERENCES documents(id),
                    FOREIGN KEY (source_meeting_id) REFERENCES meetings(id),
                    FOREIGN KEY (source_agenda_item_id) REFERENCES agenda_items(id),
                    FOREIGN KEY (source_election_program_id) REFERENCES election_programs(id),
                    FOREIGN KEY (superseded_by) REFERENCES standpunten(id),
                    CHECK (party_id IS NOT NULL OR raadslid_id IS NOT NULL)
                )
            ''')

            # Standpunt Topics (for consistent categorisation)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS standpunt_topics (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    parent_id INTEGER,
                    description TEXT,
                    keywords TEXT,
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_id) REFERENCES standpunt_topics(id)
                )
            ''')

            # ==================== Transcripties (Video/Audio) ====================

            # Transcripties van vergaderingen
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transcriptions (
                    id INTEGER PRIMARY KEY,
                    meeting_id INTEGER,
                    source_type TEXT NOT NULL,
                    source_url TEXT,
                    local_path TEXT,
                    transcript_text TEXT,
                    transcript_language TEXT DEFAULT 'nl',
                    whisper_model TEXT,
                    duration_seconds INTEGER,
                    transcription_status TEXT DEFAULT 'pending',
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
                )
            ''')

            # Embeddings voor transcripties (met timestamps voor video navigatie)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transcription_embeddings (
                    id INTEGER PRIMARY KEY,
                    transcription_id INTEGER NOT NULL,
                    chunk_index INTEGER,
                    chunk_text TEXT,
                    timestamp_start REAL,
                    timestamp_end REAL,
                    embedding BLOB,
                    model TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (transcription_id) REFERENCES transcriptions(id)
                )
            ''')

            # ==================== AI Samenvattingen ====================

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER NOT NULL,
                    summary_type TEXT DEFAULT 'normaal',
                    summary_text TEXT NOT NULL,
                    model_used TEXT,
                    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(entity_type, entity_id, summary_type)
                )
            ''')

            # ==================== Dossiers (Tijdlijnen) ====================

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dossiers (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    description TEXT,
                    date_from DATE,
                    date_to DATE,
                    status TEXT DEFAULT 'active',
                    auto_update INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dossier_items (
                    id INTEGER PRIMARY KEY,
                    dossier_id INTEGER NOT NULL,
                    item_type TEXT NOT NULL,
                    item_id INTEGER NOT NULL,
                    relevance_score REAL,
                    item_date DATE,
                    title TEXT,
                    summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (dossier_id) REFERENCES dossiers(id)
                )
            ''')

            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_meetings_gremium ON meetings(gremium_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_documents_meeting ON documents(meeting_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_images_document ON document_images(document_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_images_hash ON document_images(image_hash)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_unique_images_hash ON unique_images(image_hash)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_agenda_items_meeting ON agenda_items(meeting_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_annotations_document ON annotations(document_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_visit_reports_date ON visit_reports(date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_visit_reports_status ON visit_reports(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_visit_report_meetings_meeting ON visit_report_meetings(meeting_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_election_programs_party ON election_programs(party_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_election_programs_year ON election_programs(election_year)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_party_positions_topic ON party_positions(topic)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_party_positions_party ON party_positions(party_id)')

            # Standpunten indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_raadsleden_party ON raadsleden(party_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_raadsleden_active ON raadsleden(active)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_standpunten_party ON standpunten(party_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_standpunten_raadslid ON standpunten(raadslid_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_standpunten_topic ON standpunten(topic)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_standpunten_stance ON standpunten(stance)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_standpunten_date ON standpunten(position_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_standpunten_source_type ON standpunten(source_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_standpunten_verified ON standpunten(verified)')

            # Transcriptie indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_transcriptions_meeting ON transcriptions(meeting_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_transcriptions_status ON transcriptions(transcription_status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_transcription_embeddings_transcription ON transcription_embeddings(transcription_id)')

            # Summary indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_summaries_entity ON summaries(entity_type, entity_id)')

            # Dossier indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dossiers_topic ON dossiers(topic)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dossiers_status ON dossiers(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dossier_items_dossier ON dossier_items(dossier_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dossier_items_type ON dossier_items(item_type, item_id)')

            logger.info('Database schema initialized')

    # ==================== Gremia ====================

    def upsert_gremium(self, notubiz_id: str, name: str, **kwargs) -> int:
        """Insert or update a gremium."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO gremia (notubiz_id, name, description, type, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(notubiz_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    type = excluded.type,
                    updated_at = CURRENT_TIMESTAMP
            ''', (notubiz_id, name, kwargs.get('description'), kwargs.get('type')))
            return cursor.lastrowid

    def get_gremia(self, active_only: bool = True) -> List[Dict]:
        """Get all gremia."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM gremia'
            if active_only:
                query += ' WHERE active = 1'
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Meetings ====================

    def upsert_meeting(self, notubiz_id: str, title: str, date: str, **kwargs) -> int:
        """Insert or update a meeting."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO meetings (notubiz_id, gremium_id, title, date, start_time, end_time,
                                     location, status, description, video_url, raw_data, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(notubiz_id) DO UPDATE SET
                    title = excluded.title,
                    date = excluded.date,
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    location = excluded.location,
                    status = excluded.status,
                    description = excluded.description,
                    video_url = excluded.video_url,
                    raw_data = excluded.raw_data,
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                notubiz_id,
                kwargs.get('gremium_id'),
                title,
                date,
                kwargs.get('start_time'),
                kwargs.get('end_time'),
                kwargs.get('location'),
                kwargs.get('status'),
                kwargs.get('description'),
                kwargs.get('video_url'),
                json.dumps(kwargs.get('raw_data')) if kwargs.get('raw_data') else None
            ))
            return cursor.lastrowid

    def get_meetings(
        self,
        limit: int = 50,
        offset: int = 0,
        date_from: str = None,
        date_to: str = None,
        gremium_id: int = None,
        search: str = None
    ) -> List[Dict]:
        """Get meetings with optional filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT m.*, g.name as gremium_name
                FROM meetings m
                LEFT JOIN gremia g ON m.gremium_id = g.id
                WHERE 1=1
            '''
            params = []

            if date_from:
                query += ' AND m.date >= ?'
                params.append(date_from)
            if date_to:
                query += ' AND m.date <= ?'
                params.append(date_to)
            if gremium_id:
                query += ' AND m.gremium_id = ?'
                params.append(gremium_id)
            if search:
                query += ' AND (m.title LIKE ? OR m.description LIKE ?)'
                params.extend([f'%{search}%', f'%{search}%'])

            query += ' ORDER BY m.date DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_meeting(self, meeting_id: int = None, notubiz_id: str = None) -> Optional[Dict]:
        """Get a single meeting by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if meeting_id:
                cursor.execute('SELECT * FROM meetings WHERE id = ?', (meeting_id,))
            elif notubiz_id:
                cursor.execute('SELECT * FROM meetings WHERE notubiz_id = ?', (notubiz_id,))
            else:
                return None
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== Agenda Items ====================

    def upsert_agenda_item(self, notubiz_id: str, meeting_id: int, title: str, **kwargs) -> int:
        """Insert or update an agenda item."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO agenda_items (notubiz_id, meeting_id, parent_id, order_number,
                                         title, description, decision, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(notubiz_id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    decision = excluded.decision,
                    raw_data = excluded.raw_data
            ''', (
                notubiz_id,
                meeting_id,
                kwargs.get('parent_id'),
                kwargs.get('order_number'),
                title,
                kwargs.get('description'),
                kwargs.get('decision'),
                json.dumps(kwargs.get('raw_data')) if kwargs.get('raw_data') else None
            ))
            return cursor.lastrowid

    def get_agenda_items(self, meeting_id: int) -> List[Dict]:
        """Get agenda items for a meeting."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM agenda_items
                WHERE meeting_id = ?
                ORDER BY order_number, id
            ''', (meeting_id,))
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Documents ====================

    def upsert_document(self, title: str, url: str = None, **kwargs) -> int:
        """Insert or update a document."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            notubiz_id = kwargs.get('notubiz_id')

            if notubiz_id:
                cursor.execute('''
                    INSERT INTO documents (notubiz_id, meeting_id, agenda_item_id, title, filename,
                                          url, local_path, mime_type, file_size, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(notubiz_id) DO UPDATE SET
                        title = excluded.title,
                        url = excluded.url,
                        local_path = excluded.local_path,
                        mime_type = excluded.mime_type,
                        file_size = excluded.file_size,
                        updated_at = CURRENT_TIMESTAMP
                ''', (
                    notubiz_id,
                    kwargs.get('meeting_id'),
                    kwargs.get('agenda_item_id'),
                    title,
                    kwargs.get('filename'),
                    url,
                    kwargs.get('local_path'),
                    kwargs.get('mime_type'),
                    kwargs.get('file_size')
                ))
            else:
                cursor.execute('''
                    INSERT INTO documents (meeting_id, agenda_item_id, title, filename,
                                          url, local_path, mime_type, file_size)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    kwargs.get('meeting_id'),
                    kwargs.get('agenda_item_id'),
                    title,
                    kwargs.get('filename'),
                    url,
                    kwargs.get('local_path'),
                    kwargs.get('mime_type'),
                    kwargs.get('file_size')
                ))
            return cursor.lastrowid

    def update_document_content(self, document_id: int, text_content: str):
        """Update document text content after extraction."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE documents
                SET text_content = ?, text_extracted = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (text_content, document_id))

    def update_document_status(self, document_id: int, status: str, local_path: str = None):
        """Update document download status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if local_path:
                cursor.execute('''
                    UPDATE documents
                    SET download_status = ?, local_path = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status, local_path, document_id))
            else:
                cursor.execute('''
                    UPDATE documents
                    SET download_status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status, document_id))

    def update_document_file_blob(self, document_id: int, file_bytes: bytes, storage_mode: str = 'db'):
        """Store document file bytes in the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE documents
                SET file_blob = ?, file_storage_mode = ?, local_path = NULL,
                    file_size = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (sqlite3.Binary(file_bytes), storage_mode, len(file_bytes), document_id))

    def add_document_images(self, document_id: int, images: List[Dict[str, Any]]):
        """Store image metadata (paths on filesystem) for a document."""
        if not images:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO document_images
                (document_id, image_index, mime_type, file_path, image_hash, unique_image_id,
                 width, height, file_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (document_id, image.get('index', 0), image.get('mime_type'),
                 image.get('file_path'), image.get('image_hash'), image.get('unique_image_id'),
                 image.get('width'), image.get('height'), image.get('file_size'))
                for image in images
            ])

    # ===== Unique Images (Deduplication) =====

    def find_unique_image_by_hash(self, image_hash: str) -> Optional[Dict]:
        """Find a unique image by its perceptual hash."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, image_hash, file_path, mime_type, width, height,
                       file_size, ocr_text, ocr_status, reference_count
                FROM unique_images WHERE image_hash = ?
            ''', (image_hash,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_unique_image(self, image_hash: str, file_path: str, **kwargs) -> int:
        """Add a new unique image and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO unique_images
                (image_hash, file_path, mime_type, width, height, file_size, reference_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (
                image_hash, file_path, kwargs.get('mime_type'),
                kwargs.get('width'), kwargs.get('height'), kwargs.get('file_size')
            ))
            return cursor.lastrowid

    def increment_unique_image_reference(self, unique_image_id: int):
        """Increment reference count for a unique image."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE unique_images SET reference_count = reference_count + 1
                WHERE id = ?
            ''', (unique_image_id,))

    def decrement_unique_image_reference(self, unique_image_id: int) -> Optional[str]:
        """
        Decrement reference count for a unique image.
        Returns file_path if reference count reaches 0 (should be deleted).
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE unique_images SET reference_count = reference_count - 1
                WHERE id = ?
            ''', (unique_image_id,))
            # Check if we should delete the image
            cursor.execute('''
                SELECT file_path FROM unique_images
                WHERE id = ? AND reference_count <= 0
            ''', (unique_image_id,))
            row = cursor.fetchone()
            if row:
                # Delete the record
                cursor.execute('DELETE FROM unique_images WHERE id = ?', (unique_image_id,))
                return row[0]
            return None

    def update_unique_image_ocr(self, unique_image_id: int, ocr_text: str, status: str = 'completed'):
        """Update OCR text for a unique image."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE unique_images SET ocr_text = ?, ocr_status = ?
                WHERE id = ?
            ''', (ocr_text, status, unique_image_id))

    def get_unique_images_pending_ocr(self, limit: int = 100) -> List[Dict]:
        """Get unique images that need OCR processing."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, image_hash, file_path, mime_type
                FROM unique_images
                WHERE ocr_status = 'pending' AND file_path IS NOT NULL
                ORDER BY created_at
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_deduplication_stats(self) -> Dict:
        """Get image deduplication statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM unique_images')
            unique_count = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM document_images')
            total_refs = cursor.fetchone()[0]
            cursor.execute('SELECT SUM(file_size) FROM unique_images')
            unique_size = cursor.fetchone()[0] or 0
            cursor.execute('SELECT COUNT(*) FROM document_images WHERE unique_image_id IS NOT NULL')
            deduplicated_refs = cursor.fetchone()[0]
            return {
                'unique_images': unique_count,
                'total_references': total_refs,
                'deduplicated_references': deduplicated_refs,
                'saved_references': total_refs - unique_count if total_refs > unique_count else 0,
                'unique_storage_bytes': unique_size
            }

    def clear_document_images(self, document_id: int) -> List[str]:
        """
        Remove stored image records for a document.
        Handles deduplication by decrementing reference counts.

        Returns:
            List of file paths that should be deleted from filesystem
        """
        paths_to_delete = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Get image records before deleting
            cursor.execute('''
                SELECT file_path, unique_image_id FROM document_images
                WHERE document_id = ?
            ''', (document_id,))
            images = cursor.fetchall()

            for row in images:
                file_path, unique_image_id = row
                if unique_image_id:
                    # Decrement reference count, may return path to delete
                    deleted_path = self.decrement_unique_image_reference(unique_image_id)
                    if deleted_path:
                        paths_to_delete.append(deleted_path)
                elif file_path:
                    # Non-deduplicated image, delete directly
                    paths_to_delete.append(file_path)

            cursor.execute('DELETE FROM document_images WHERE document_id = ?', (document_id,))
            return paths_to_delete

    def get_document_images(self, document_id: int) -> List[Dict]:
        """Get all images for a document, including deduplicated image data."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT di.id, di.document_id, di.image_index, di.mime_type,
                       COALESCE(ui.file_path, di.file_path) as file_path,
                       di.image_hash, di.unique_image_id,
                       COALESCE(ui.width, di.width) as width,
                       COALESCE(ui.height, di.height) as height,
                       COALESCE(ui.file_size, di.file_size) as file_size,
                       COALESCE(ui.ocr_text, di.ocr_text) as ocr_text,
                       COALESCE(ui.ocr_status, di.ocr_status) as ocr_status,
                       di.created_at
                FROM document_images di
                LEFT JOIN unique_images ui ON di.unique_image_id = ui.id
                WHERE di.document_id = ?
                ORDER BY di.image_index
            ''', (document_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_images_pending_ocr(self, limit: int = 100) -> List[Dict]:
        """Get images that need OCR processing."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT di.id, di.document_id, di.image_index, di.file_path,
                       di.mime_type, d.title as document_title
                FROM document_images di
                JOIN documents d ON di.document_id = d.id
                WHERE di.ocr_status = 'pending' AND di.file_path IS NOT NULL
                ORDER BY di.created_at
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def update_image_ocr(self, image_id: int, ocr_text: str, status: str = 'completed'):
        """Update OCR text for an image."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE document_images
                SET ocr_text = ?, ocr_status = ?
                WHERE id = ?
            ''', (ocr_text, status, image_id))

    def search_image_ocr(self, query: str, limit: int = 50) -> List[Dict]:
        """Search images by their OCR text."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT di.id, di.document_id, di.image_index, di.file_path,
                       di.ocr_text, d.title as document_title, m.date as meeting_date
                FROM document_images di
                JOIN documents d ON di.document_id = d.id
                LEFT JOIN meetings m ON d.meeting_id = m.id
                WHERE di.ocr_text LIKE ?
                ORDER BY m.date DESC
                LIMIT ?
            ''', (f'%{query}%', limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_document_by_notubiz_id(self, notubiz_id: str) -> Optional[Dict]:
        """Get a document by Notubiz ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM documents WHERE notubiz_id = ?', (notubiz_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_documents(
        self,
        meeting_id: int = None,
        agenda_item_id: int = None,
        search: str = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """Get documents with optional filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM documents WHERE 1=1'
            params = []

            if meeting_id:
                query += ' AND meeting_id = ?'
                params.append(meeting_id)
            if agenda_item_id:
                query += ' AND agenda_item_id = ?'
                params.append(agenda_item_id)
            if search:
                query += ' AND (title LIKE ? OR text_content LIKE ?)'
                params.extend([f'%{search}%', f'%{search}%'])

            query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_document(self, document_id: int) -> Optional[Dict]:
        """Get a single document by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM documents WHERE id = ?', (document_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_documents_pending_download(self) -> List[Dict]:
        """Get documents that need to be downloaded."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM documents
                WHERE download_status = 'pending' AND url IS NOT NULL
            ''')
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Visit Reports ====================

    def add_visit_report(self, title: str, source: str, **kwargs) -> int:
        """Create a visit report entry."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO visit_reports (
                    document_id, source, source_id, title, date, location,
                    participants, organizations, topics, visit_type, summary,
                    status, source_url, attachments, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                kwargs.get('document_id'),
                source,
                kwargs.get('source_id'),
                title,
                kwargs.get('date'),
                kwargs.get('location'),
                json.dumps(kwargs.get('participants')) if kwargs.get('participants') else None,
                json.dumps(kwargs.get('organizations')) if kwargs.get('organizations') else None,
                json.dumps(kwargs.get('topics')) if kwargs.get('topics') else None,
                kwargs.get('visit_type'),
                kwargs.get('summary'),
                kwargs.get('status', 'draft'),
                kwargs.get('source_url'),
                json.dumps(kwargs.get('attachments')) if kwargs.get('attachments') else None
            ))
            return cursor.lastrowid

    def update_visit_report(self, visit_report_id: int, **kwargs) -> bool:
        """Update visit report fields."""
        fields = []
        values = []
        for key, value in kwargs.items():
            if key in {'participants', 'organizations', 'topics', 'attachments'} and value is not None:
                value = json.dumps(value)
            fields.append(f"{key} = ?")
            values.append(value)
        if not fields:
            return False
        values.append(visit_report_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE visit_reports
                SET {", ".join(fields)}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', values)
            return cursor.rowcount > 0

    def get_visit_report(self, visit_report_id: int) -> Optional[Dict]:
        """Get a visit report by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM visit_reports WHERE id = ? AND deleted_at IS NULL', (visit_report_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_visit_reports(
        self,
        date_from: str = None,
        date_to: str = None,
        status: str = None,
        visit_type: str = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """List visit reports with optional filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM visit_reports WHERE deleted_at IS NULL'
            params = []

            if date_from:
                query += ' AND date >= ?'
                params.append(date_from)
            if date_to:
                query += ' AND date <= ?'
                params.append(date_to)
            if status:
                query += ' AND status = ?'
                params.append(status)
            if visit_type:
                query += ' AND visit_type = ?'
                params.append(visit_type)

            query += ' ORDER BY date DESC, created_at DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def search_visit_reports(self, query: str, limit: int = 50) -> List[Dict]:
        """Search visit reports by text fields and linked document content."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT vr.*, d.text_content
                FROM visit_reports vr
                LEFT JOIN documents d ON vr.document_id = d.id
                WHERE vr.deleted_at IS NULL
                  AND (
                    vr.title LIKE ? OR vr.summary LIKE ? OR vr.location LIKE ?
                    OR d.text_content LIKE ?
                  )
                ORDER BY vr.date DESC, vr.created_at DESC
                LIMIT ?
            ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%', limit))
            return [dict(row) for row in cursor.fetchall()]

    def soft_delete_visit_report(self, visit_report_id: int) -> bool:
        """Soft delete a visit report."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE visit_reports
                SET deleted_at = CURRENT_TIMESTAMP, status = 'archived', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (visit_report_id,))
            return cursor.rowcount > 0

    def link_visit_report_to_meeting(self, visit_report_id: int, meeting_id: int) -> bool:
        """Link a visit report to a meeting."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO visit_report_meetings (visit_report_id, meeting_id)
                VALUES (?, ?)
            ''', (visit_report_id, meeting_id))
            return cursor.rowcount > 0

    def get_visit_report_meetings(self, visit_report_id: int) -> List[int]:
        """Get meeting IDs linked to a visit report."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT meeting_id FROM visit_report_meetings WHERE visit_report_id = ?
            ''', (visit_report_id,))
            return [row[0] for row in cursor.fetchall()]

    # ==================== Annotations ====================

    def add_annotation(
        self,
        content: str,
        document_id: int = None,
        meeting_id: int = None,
        agenda_item_id: int = None,
        title: str = None,
        tags: List[str] = None
    ) -> int:
        """Add an annotation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO annotations (document_id, meeting_id, agenda_item_id, title, content, tags)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                document_id,
                meeting_id,
                agenda_item_id,
                title,
                content,
                json.dumps(tags) if tags else None
            ))
            return cursor.lastrowid

    def get_annotations(
        self,
        document_id: int = None,
        meeting_id: int = None,
        search: str = None
    ) -> List[Dict]:
        """Get annotations with optional filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM annotations WHERE 1=1'
            params = []

            if document_id:
                query += ' AND document_id = ?'
                params.append(document_id)
            if meeting_id:
                query += ' AND meeting_id = ?'
                params.append(meeting_id)
            if search:
                query += ' AND (title LIKE ? OR content LIKE ?)'
                params.extend([f'%{search}%', f'%{search}%'])

            query += ' ORDER BY created_at DESC'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def delete_annotation(self, annotation_id: int) -> bool:
        """Delete an annotation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM annotations WHERE id = ?', (annotation_id,))
            return cursor.rowcount > 0

    # ==================== Sync Status ====================

    def update_sync_status(self, entity_type: str, **kwargs):
        """Update sync status for an entity type."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sync_status (entity_type, last_sync, last_sync_from, last_sync_to,
                                        items_synced, status, error_message)
                VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type) DO UPDATE SET
                    last_sync = CURRENT_TIMESTAMP,
                    last_sync_from = excluded.last_sync_from,
                    last_sync_to = excluded.last_sync_to,
                    items_synced = excluded.items_synced,
                    status = excluded.status,
                    error_message = excluded.error_message
            ''', (
                entity_type,
                kwargs.get('date_from'),
                kwargs.get('date_to'),
                kwargs.get('items_synced', 0),
                kwargs.get('status', 'completed'),
                kwargs.get('error_message')
            ))

    def get_sync_status(self, entity_type: str = None) -> List[Dict]:
        """Get sync status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if entity_type:
                cursor.execute('SELECT * FROM sync_status WHERE entity_type = ?', (entity_type,))
            else:
                cursor.execute('SELECT * FROM sync_status')
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Sync Progress (Resumable) ====================

    def start_sync_progress(self, sync_id: str, sync_type: str, phase: str,
                            date_from: str = None, date_to: str = None,
                            total_items: int = 0) -> int:
        """
        Start tracking a new sync operation.

        Args:
            sync_id: Unique identifier for this sync session
            sync_type: 'full' or 'incremental'
            phase: Current phase ('gremia', 'meetings', 'documents', 'indexing')
            date_from: Start date for sync range
            date_to: End date for sync range
            total_items: Total items to process in this phase

        Returns:
            ID of the sync progress record
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO sync_progress
                (sync_id, sync_type, phase, date_from, date_to, total_items,
                 processed_items, status, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 'running', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (sync_id, sync_type, phase, date_from, date_to, total_items))
            return cursor.lastrowid

    def update_sync_progress(self, sync_id: str, processed_items: int = None,
                             last_processed_id: str = None, phase: str = None,
                             total_items: int = None, status: str = None,
                             error_message: str = None):
        """
        Update sync progress. Call this after each item is processed.

        Args:
            sync_id: The sync session identifier
            processed_items: Number of items processed so far
            last_processed_id: ID of the last processed item (for resume)
            phase: Update the current phase
            total_items: Update total items (if discovered during sync)
            status: Update status ('running', 'paused', 'completed', 'failed')
            error_message: Error message if failed
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = ['updated_at = CURRENT_TIMESTAMP']
            params = []

            if processed_items is not None:
                updates.append('processed_items = ?')
                params.append(processed_items)
            if last_processed_id is not None:
                updates.append('last_processed_id = ?')
                params.append(last_processed_id)
            if phase is not None:
                updates.append('phase = ?')
                params.append(phase)
            if total_items is not None:
                updates.append('total_items = ?')
                params.append(total_items)
            if status is not None:
                updates.append('status = ?')
                params.append(status)
                if status == 'completed':
                    updates.append('completed_at = CURRENT_TIMESTAMP')
            if error_message is not None:
                updates.append('error_message = ?')
                params.append(error_message)

            params.append(sync_id)
            cursor.execute(f'''
                UPDATE sync_progress SET {', '.join(updates)} WHERE sync_id = ?
            ''', params)

    def get_sync_progress(self, sync_id: str = None, status: str = None) -> Optional[Dict]:
        """
        Get sync progress.

        Args:
            sync_id: Specific sync session to retrieve
            status: Filter by status (e.g., 'running' to find interrupted syncs)

        Returns:
            Sync progress record or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if sync_id:
                cursor.execute('SELECT * FROM sync_progress WHERE sync_id = ?', (sync_id,))
            elif status:
                cursor.execute('''
                    SELECT * FROM sync_progress WHERE status = ?
                    ORDER BY updated_at DESC LIMIT 1
                ''', (status,))
            else:
                cursor.execute('''
                    SELECT * FROM sync_progress ORDER BY updated_at DESC LIMIT 1
                ''')
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_interrupted_sync(self) -> Optional[Dict]:
        """
        Find the most recent interrupted sync that can be resumed.

        Returns:
            Sync progress record if found, None otherwise
        """
        return self.get_sync_progress(status='running')

    def cleanup_old_sync_progress(self, keep_days: int = 7):
        """Remove old completed sync progress records."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM sync_progress
                WHERE status IN ('completed', 'failed')
                AND updated_at < datetime('now', ?)
            ''', (f'-{keep_days} days',))

    # ==================== Statistics ====================

    def get_statistics(self) -> Dict:
        """Get database statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            stats = {}

            for table in ['gremia', 'meetings', 'agenda_items', 'documents', 'annotations',
                          'parties', 'election_programs', 'raadsleden', 'standpunten',
                          'visit_reports', 'document_images']:
                cursor.execute(f'SELECT COUNT(*) FROM {table}')
                stats[table] = cursor.fetchone()[0]

            # Documents by status
            cursor.execute('''
                SELECT download_status, COUNT(*) FROM documents GROUP BY download_status
            ''')
            stats['documents_by_status'] = {row[0]: row[1] for row in cursor.fetchall()}

            # Date range of meetings
            cursor.execute('SELECT MIN(date), MAX(date) FROM meetings')
            row = cursor.fetchone()
            stats['meetings_date_range'] = {'from': row[0], 'to': row[1]}

            # Standpunten by stance
            cursor.execute('''
                SELECT stance, COUNT(*) FROM standpunten GROUP BY stance
            ''')
            stats['standpunten_by_stance'] = {row[0]: row[1] for row in cursor.fetchall()}

            # Standpunten by verification status
            cursor.execute('SELECT COUNT(*) FROM standpunten WHERE verified = 1')
            stats['standpunten_verified'] = cursor.fetchone()[0]

            return stats

    # ==================== Parties ====================

    def upsert_party(self, name: str, **kwargs) -> int:
        """Insert or update a political party."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO parties (name, abbreviation, website_url, founded_year, active, color, logo_url, description, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    abbreviation = excluded.abbreviation,
                    website_url = excluded.website_url,
                    founded_year = excluded.founded_year,
                    active = excluded.active,
                    color = excluded.color,
                    logo_url = excluded.logo_url,
                    description = excluded.description,
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                name,
                kwargs.get('abbreviation'),
                kwargs.get('website_url'),
                kwargs.get('founded_year'),
                kwargs.get('active', 1),
                kwargs.get('color'),
                kwargs.get('logo_url'),
                kwargs.get('description')
            ))
            # Get the ID (either new or existing)
            cursor.execute('SELECT id FROM parties WHERE name = ?', (name,))
            return cursor.fetchone()[0]

    def get_parties(self, active_only: bool = False) -> List[Dict]:
        """Get all political parties."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM parties'
            if active_only:
                query += ' WHERE active = 1'
            query += ' ORDER BY name'
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def get_party(self, party_id: int = None, name: str = None) -> Optional[Dict]:
        """Get a single party by ID or name."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if party_id:
                cursor.execute('SELECT * FROM parties WHERE id = ?', (party_id,))
            elif name:
                cursor.execute('SELECT * FROM parties WHERE name = ? OR abbreviation = ?', (name, name))
            else:
                return None
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== Election Programs ====================

    def upsert_election_program(self, party_id: int, election_year: int, **kwargs) -> int:
        """Insert or update an election program."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            election_type = kwargs.get('election_type', 'gemeenteraad')
            cursor.execute('''
                INSERT INTO election_programs (party_id, election_year, election_type, title, source_url, local_path, text_content, text_extracted, download_status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(party_id, election_year, election_type) DO UPDATE SET
                    title = excluded.title,
                    source_url = excluded.source_url,
                    local_path = excluded.local_path,
                    text_content = excluded.text_content,
                    text_extracted = excluded.text_extracted,
                    download_status = excluded.download_status,
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                party_id,
                election_year,
                election_type,
                kwargs.get('title'),
                kwargs.get('source_url'),
                kwargs.get('local_path'),
                kwargs.get('text_content'),
                kwargs.get('text_extracted', 0),
                kwargs.get('download_status', 'pending')
            ))
            # Get the ID
            cursor.execute(
                'SELECT id FROM election_programs WHERE party_id = ? AND election_year = ? AND election_type = ?',
                (party_id, election_year, election_type)
            )
            return cursor.fetchone()[0]

    def get_election_programs(
        self,
        party_id: int = None,
        year_from: int = None,
        year_to: int = None,
        search: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get election programs with optional filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT ep.*, p.name as party_name, p.abbreviation as party_abbreviation
                FROM election_programs ep
                JOIN parties p ON ep.party_id = p.id
                WHERE 1=1
            '''
            params = []

            if party_id:
                query += ' AND ep.party_id = ?'
                params.append(party_id)
            if year_from:
                query += ' AND ep.election_year >= ?'
                params.append(year_from)
            if year_to:
                query += ' AND ep.election_year <= ?'
                params.append(year_to)
            if search:
                query += ' AND (ep.title LIKE ? OR ep.text_content LIKE ?)'
                params.extend([f'%{search}%', f'%{search}%'])

            query += ' ORDER BY ep.election_year DESC, p.name LIMIT ?'
            params.append(limit)

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_election_program(self, program_id: int) -> Optional[Dict]:
        """Get a single election program by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ep.*, p.name as party_name, p.abbreviation as party_abbreviation
                FROM election_programs ep
                JOIN parties p ON ep.party_id = p.id
                WHERE ep.id = ?
            ''', (program_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def search_election_programs(
        self,
        query: str,
        party_name: str = None,
        year_from: int = None,
        year_to: int = None,
        limit: int = 20
    ) -> List[Dict]:
        """Search in election programs text content."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            sql = '''
                SELECT ep.id, ep.election_year, ep.title, p.name as party_name, p.abbreviation,
                       substr(ep.text_content, max(1, instr(lower(ep.text_content), lower(?)) - 100), 300) as snippet
                FROM election_programs ep
                JOIN parties p ON ep.party_id = p.id
                WHERE ep.text_content LIKE ?
            '''
            params = [query, f'%{query}%']

            if party_name:
                sql += ' AND (p.name LIKE ? OR p.abbreviation LIKE ?)'
                params.extend([f'%{party_name}%', f'%{party_name}%'])
            if year_from:
                sql += ' AND ep.election_year >= ?'
                params.append(year_from)
            if year_to:
                sql += ' AND ep.election_year <= ?'
                params.append(year_to)

            sql += ' ORDER BY ep.election_year DESC LIMIT ?'
            params.append(limit)

            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Party Positions ====================

    def add_party_position(self, party_id: int, topic: str, position_text: str, **kwargs) -> int:
        """Add a party position on a topic."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO party_positions (party_id, election_program_id, topic, position_text, source_page, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                party_id,
                kwargs.get('election_program_id'),
                topic,
                position_text,
                kwargs.get('source_page'),
                kwargs.get('confidence_score')
            ))
            return cursor.lastrowid

    def get_party_positions(self, topic: str = None, party_id: int = None) -> List[Dict]:
        """Get party positions, optionally filtered by topic or party."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT pp.*, p.name as party_name, p.abbreviation, ep.election_year
                FROM party_positions pp
                JOIN parties p ON pp.party_id = p.id
                LEFT JOIN election_programs ep ON pp.election_program_id = ep.id
                WHERE 1=1
            '''
            params = []

            if topic:
                query += ' AND pp.topic LIKE ?'
                params.append(f'%{topic}%')
            if party_id:
                query += ' AND pp.party_id = ?'
                params.append(party_id)

            query += ' ORDER BY p.name, ep.election_year DESC'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Party Scrape Config ====================

    def upsert_party_scrape_config(self, party_id: int, **kwargs) -> int:
        """Insert or update scrape config for a party."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO party_scrape_config (party_id, scrape_strategy, program_url_pattern, scrape_interval_days, enabled, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(party_id) DO UPDATE SET
                    scrape_strategy = excluded.scrape_strategy,
                    program_url_pattern = excluded.program_url_pattern,
                    scrape_interval_days = excluded.scrape_interval_days,
                    enabled = excluded.enabled,
                    notes = excluded.notes
            ''', (
                party_id,
                kwargs.get('scrape_strategy', 'manual'),
                kwargs.get('program_url_pattern'),
                kwargs.get('scrape_interval_days', 30),
                kwargs.get('enabled', 1),
                kwargs.get('notes')
            ))
            return cursor.lastrowid

    def get_party_scrape_configs(self, enabled_only: bool = True) -> List[Dict]:
        """Get all party scrape configurations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT psc.*, p.name as party_name, p.website_url
                FROM party_scrape_config psc
                JOIN parties p ON psc.party_id = p.id
            '''
            if enabled_only:
                query += ' WHERE psc.enabled = 1'
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Raadsleden ====================

    def upsert_raadslid(self, name: str, **kwargs) -> int:
        """Insert or update a council member."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Check if exists by name
            cursor.execute('SELECT id FROM raadsleden WHERE name = ?', (name,))
            existing = cursor.fetchone()

            if existing:
                # Update existing
                cursor.execute('''
                    UPDATE raadsleden SET
                        party_id = COALESCE(?, party_id),
                        email = COALESCE(?, email),
                        phone = COALESCE(?, phone),
                        photo_url = COALESCE(?, photo_url),
                        bio = COALESCE(?, bio),
                        start_date = COALESCE(?, start_date),
                        end_date = COALESCE(?, end_date),
                        is_wethouder = COALESCE(?, is_wethouder),
                        is_fractievoorzitter = COALESCE(?, is_fractievoorzitter),
                        is_steunfractielid = COALESCE(?, is_steunfractielid),
                        active = COALESCE(?, active),
                        notubiz_id = COALESCE(?, notubiz_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (
                    kwargs.get('party_id'),
                    kwargs.get('email'),
                    kwargs.get('phone'),
                    kwargs.get('photo_url'),
                    kwargs.get('bio'),
                    kwargs.get('start_date'),
                    kwargs.get('end_date'),
                    kwargs.get('is_wethouder'),
                    kwargs.get('is_fractievoorzitter'),
                    kwargs.get('is_steunfractielid'),
                    kwargs.get('active'),
                    kwargs.get('notubiz_id'),
                    existing[0]
                ))
                return existing[0]
            else:
                # Insert new
                cursor.execute('''
                    INSERT INTO raadsleden (name, party_id, email, phone, photo_url, bio,
                                           start_date, end_date, is_wethouder, is_fractievoorzitter,
                                           is_steunfractielid, active, notubiz_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    name,
                    kwargs.get('party_id'),
                    kwargs.get('email'),
                    kwargs.get('phone'),
                    kwargs.get('photo_url'),
                    kwargs.get('bio'),
                    kwargs.get('start_date'),
                    kwargs.get('end_date'),
                    kwargs.get('is_wethouder', 0),
                    kwargs.get('is_fractievoorzitter', 0),
                    kwargs.get('is_steunfractielid', 0),
                    kwargs.get('active', 1),
                    kwargs.get('notubiz_id')
                ))
                return cursor.lastrowid

    def get_raadsleden(self, party_id: int = None, active_only: bool = True) -> List[Dict]:
        """Get all council members."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT r.*, p.name as party_name, p.abbreviation as party_abbreviation
                FROM raadsleden r
                LEFT JOIN parties p ON r.party_id = p.id
                WHERE 1=1
            '''
            params = []

            if active_only:
                query += ' AND r.active = 1'
            if party_id:
                query += ' AND r.party_id = ?'
                params.append(party_id)

            query += ' ORDER BY p.name, r.name'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_raadslid(self, raadslid_id: int = None, name: str = None) -> Optional[Dict]:
        """Get a single council member by ID or name."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if raadslid_id:
                cursor.execute('''
                    SELECT r.*, p.name as party_name, p.abbreviation as party_abbreviation
                    FROM raadsleden r
                    LEFT JOIN parties p ON r.party_id = p.id
                    WHERE r.id = ?
                ''', (raadslid_id,))
            elif name:
                cursor.execute('''
                    SELECT r.*, p.name as party_name, p.abbreviation as party_abbreviation
                    FROM raadsleden r
                    LEFT JOIN parties p ON r.party_id = p.id
                    WHERE r.name LIKE ?
                ''', (f'%{name}%',))
            else:
                return None
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== Standpunten ====================

    def add_standpunt(self, topic: str, position_summary: str, **kwargs) -> int:
        """Add a new standpunt."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO standpunten (
                    party_id, raadslid_id, topic, subtopic, tags,
                    position_summary, position_text, stance, stance_strength,
                    source_type, source_document_id, source_meeting_id,
                    source_agenda_item_id, source_election_program_id,
                    source_url, source_page, source_quote,
                    extraction_method, extraction_model, confidence_score,
                    position_date, valid_from, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                kwargs.get('party_id'),
                kwargs.get('raadslid_id'),
                topic,
                kwargs.get('subtopic'),
                json.dumps(kwargs.get('tags')) if kwargs.get('tags') else None,
                position_summary,
                kwargs.get('position_text'),
                kwargs.get('stance', 'onbekend'),
                kwargs.get('stance_strength', 3),
                kwargs.get('source_type', 'handmatig'),
                kwargs.get('source_document_id'),
                kwargs.get('source_meeting_id'),
                kwargs.get('source_agenda_item_id'),
                kwargs.get('source_election_program_id'),
                kwargs.get('source_url'),
                kwargs.get('source_page'),
                kwargs.get('source_quote'),
                kwargs.get('extraction_method', 'manual'),
                kwargs.get('extraction_model'),
                kwargs.get('confidence_score'),
                kwargs.get('position_date'),
                kwargs.get('valid_from'),
                kwargs.get('created_by')
            ))
            return cursor.lastrowid

    def update_standpunt(self, standpunt_id: int, **kwargs) -> bool:
        """Update an existing standpunt."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build dynamic update query
            updates = []
            params = []

            for field in ['topic', 'subtopic', 'position_summary', 'position_text',
                          'stance', 'stance_strength', 'source_quote', 'valid_until']:
                if field in kwargs:
                    updates.append(f'{field} = ?')
                    params.append(kwargs[field])

            if kwargs.get('tags'):
                updates.append('tags = ?')
                params.append(json.dumps(kwargs['tags']))

            if not updates:
                return False

            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.append(standpunt_id)

            cursor.execute(f'''
                UPDATE standpunten SET {', '.join(updates)} WHERE id = ?
            ''', params)
            return cursor.rowcount > 0

    def get_standpunten(
        self,
        party_id: int = None,
        raadslid_id: int = None,
        topic: str = None,
        stance: str = None,
        source_type: str = None,
        date_from: str = None,
        date_to: str = None,
        verified_only: bool = False,
        include_superseded: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """Get standpunten with filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT s.*,
                       p.name as party_name, p.abbreviation as party_abbreviation,
                       r.name as raadslid_name,
                       d.title as source_document_title,
                       m.title as source_meeting_title
                FROM standpunten s
                LEFT JOIN parties p ON s.party_id = p.id
                LEFT JOIN raadsleden r ON s.raadslid_id = r.id
                LEFT JOIN documents d ON s.source_document_id = d.id
                LEFT JOIN meetings m ON s.source_meeting_id = m.id
                WHERE 1=1
            '''
            params = []

            if party_id:
                query += ' AND s.party_id = ?'
                params.append(party_id)
            if raadslid_id:
                query += ' AND s.raadslid_id = ?'
                params.append(raadslid_id)
            if topic:
                query += ' AND s.topic LIKE ?'
                params.append(f'%{topic}%')
            if stance:
                query += ' AND s.stance = ?'
                params.append(stance)
            if source_type:
                query += ' AND s.source_type = ?'
                params.append(source_type)
            if date_from:
                query += ' AND s.position_date >= ?'
                params.append(date_from)
            if date_to:
                query += ' AND s.position_date <= ?'
                params.append(date_to)
            if verified_only:
                query += ' AND s.verified = 1'
            if not include_superseded:
                query += ' AND s.superseded_by IS NULL'

            query += ' ORDER BY s.position_date DESC, s.created_at DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_standpunt(self, standpunt_id: int) -> Optional[Dict]:
        """Get a single standpunt with full details."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT s.*,
                       p.name as party_name, p.abbreviation as party_abbreviation,
                       r.name as raadslid_name,
                       d.title as source_document_title,
                       m.title as source_meeting_title, m.date as source_meeting_date
                FROM standpunten s
                LEFT JOIN parties p ON s.party_id = p.id
                LEFT JOIN raadsleden r ON s.raadslid_id = r.id
                LEFT JOIN documents d ON s.source_document_id = d.id
                LEFT JOIN meetings m ON s.source_meeting_id = m.id
                WHERE s.id = ?
            ''', (standpunt_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def search_standpunten(self, query: str, **filters) -> List[Dict]:
        """Full-text search in standpunten."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            sql = '''
                SELECT s.*, p.name as party_name, r.name as raadslid_name
                FROM standpunten s
                LEFT JOIN parties p ON s.party_id = p.id
                LEFT JOIN raadsleden r ON s.raadslid_id = r.id
                WHERE (s.position_summary LIKE ? OR s.position_text LIKE ? OR s.topic LIKE ?)
            '''
            params = [f'%{query}%', f'%{query}%', f'%{query}%']

            if filters.get('party_id'):
                sql += ' AND s.party_id = ?'
                params.append(filters['party_id'])
            if filters.get('stance'):
                sql += ' AND s.stance = ?'
                params.append(filters['stance'])
            if not filters.get('include_superseded'):
                sql += ' AND s.superseded_by IS NULL'

            sql += ' ORDER BY s.position_date DESC LIMIT ?'
            params.append(filters.get('limit', 50))

            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def compare_standpunten_by_topic(self, topic: str, party_ids: List[int] = None) -> Dict:
        """Compare positions on a topic across parties."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = '''
                SELECT s.*, p.name as party_name, p.abbreviation
                FROM standpunten s
                JOIN parties p ON s.party_id = p.id
                WHERE s.topic LIKE ? AND s.superseded_by IS NULL
            '''
            params = [f'%{topic}%']

            if party_ids:
                placeholders = ','.join(['?'] * len(party_ids))
                query += f' AND s.party_id IN ({placeholders})'
                params.extend(party_ids)

            query += ' ORDER BY p.name, s.position_date DESC'
            cursor.execute(query, params)

            rows = [dict(row) for row in cursor.fetchall()]

            # Group by party
            by_party = {}
            for row in rows:
                party_name = row['party_name']
                if party_name not in by_party:
                    by_party[party_name] = []
                by_party[party_name].append(row)

            return {
                'topic': topic,
                'parties': by_party,
                'total_standpunten': len(rows)
            }

    def get_standpunt_history(
        self,
        party_id: int = None,
        raadslid_id: int = None,
        topic: str = None
    ) -> List[Dict]:
        """Get historical evolution of positions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT s.*, p.name as party_name, r.name as raadslid_name
                FROM standpunten s
                LEFT JOIN parties p ON s.party_id = p.id
                LEFT JOIN raadsleden r ON s.raadslid_id = r.id
                WHERE 1=1
            '''
            params = []

            if party_id:
                query += ' AND s.party_id = ?'
                params.append(party_id)
            if raadslid_id:
                query += ' AND s.raadslid_id = ?'
                params.append(raadslid_id)
            if topic:
                query += ' AND s.topic LIKE ?'
                params.append(f'%{topic}%')

            query += ' ORDER BY s.topic, s.position_date ASC, s.created_at ASC'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def verify_standpunt(self, standpunt_id: int, verified_by: str) -> bool:
        """Mark standpunt as manually verified."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE standpunten
                SET verified = 1, verified_by = ?, verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (verified_by, standpunt_id))
            return cursor.rowcount > 0

    def supersede_standpunt(self, old_id: int, new_id: int) -> bool:
        """Mark a standpunt as superseded by a newer one."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE standpunten
                SET superseded_by = ?, valid_until = CURRENT_DATE, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_id, old_id))
            return cursor.rowcount > 0

    # ==================== Standpunt Topics ====================

    def add_standpunt_topic(self, name: str, **kwargs) -> int:
        """Add a topic to the taxonomy."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO standpunt_topics (name, parent_id, description, keywords)
                VALUES (?, ?, ?, ?)
            ''', (
                name,
                kwargs.get('parent_id'),
                kwargs.get('description'),
                kwargs.get('keywords')
            ))
            # Get the ID
            cursor.execute('SELECT id FROM standpunt_topics WHERE name = ?', (name,))
            return cursor.fetchone()[0]

    def get_standpunt_topics(self, parent_id: int = None, active_only: bool = True) -> List[Dict]:
        """Get topic taxonomy."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM standpunt_topics WHERE 1=1'
            params = []

            if parent_id is not None:
                query += ' AND parent_id = ?'
                params.append(parent_id)
            elif parent_id is None:
                query += ' AND parent_id IS NULL'

            if active_only:
                query += ' AND active = 1'

            query += ' ORDER BY name'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


    # ==================== Transcriptions ====================

    def add_transcription(self, source_type: str, **kwargs) -> int:
        """Add a new transcription record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transcriptions (meeting_id, source_type, source_url, local_path,
                                           transcript_text, transcript_language, whisper_model,
                                           duration_seconds, transcription_status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                kwargs.get('meeting_id'),
                source_type,
                kwargs.get('source_url'),
                kwargs.get('local_path'),
                kwargs.get('transcript_text'),
                kwargs.get('transcript_language', 'nl'),
                kwargs.get('whisper_model'),
                kwargs.get('duration_seconds'),
                kwargs.get('transcription_status', 'pending'),
                kwargs.get('error_message')
            ))
            return cursor.lastrowid

    def update_transcription(self, transcription_id: int, **kwargs) -> bool:
        """Update transcription status and content."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []

            for field in ['transcript_text', 'transcript_language', 'whisper_model',
                          'duration_seconds', 'transcription_status', 'error_message', 'local_path']:
                if field in kwargs:
                    updates.append(f'{field} = ?')
                    params.append(kwargs[field])

            if not updates:
                return False

            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.append(transcription_id)

            cursor.execute(f'''
                UPDATE transcriptions SET {', '.join(updates)} WHERE id = ?
            ''', params)
            return cursor.rowcount > 0

    def get_transcription(self, transcription_id: int = None, meeting_id: int = None) -> Optional[Dict]:
        """Get a transcription by ID or meeting ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if transcription_id:
                cursor.execute('SELECT * FROM transcriptions WHERE id = ?', (transcription_id,))
            elif meeting_id:
                cursor.execute('SELECT * FROM transcriptions WHERE meeting_id = ? ORDER BY id DESC LIMIT 1', (meeting_id,))
            else:
                return None
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_transcriptions_pending(self) -> List[Dict]:
        """Get transcriptions that need processing."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.*, m.title as meeting_title, m.date as meeting_date, m.video_url
                FROM transcriptions t
                LEFT JOIN meetings m ON t.meeting_id = m.id
                WHERE t.transcription_status = 'pending'
                ORDER BY m.date DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def get_meetings_without_transcription(self) -> List[Dict]:
        """Get meetings with video_url but no transcription."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*
                FROM meetings m
                LEFT JOIN transcriptions t ON m.id = t.meeting_id
                WHERE m.video_url IS NOT NULL
                  AND m.video_url != ''
                  AND t.id IS NULL
                ORDER BY m.date DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def search_transcriptions(self, query: str, limit: int = 20) -> List[Dict]:
        """Search in transcription text content."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.*, m.title as meeting_title, m.date as meeting_date,
                       substr(t.transcript_text, max(1, instr(lower(t.transcript_text), lower(?)) - 100), 300) as snippet
                FROM transcriptions t
                LEFT JOIN meetings m ON t.meeting_id = m.id
                WHERE t.transcript_text LIKE ?
                  AND t.transcription_status = 'completed'
                ORDER BY m.date DESC
                LIMIT ?
            ''', (query, f'%{query}%', limit))
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Transcription Embeddings ====================

    def add_transcription_embedding(self, transcription_id: int, chunk_index: int,
                                    chunk_text: str, embedding: bytes, **kwargs) -> int:
        """Add embedding for transcription chunk."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transcription_embeddings (transcription_id, chunk_index, chunk_text,
                                                     timestamp_start, timestamp_end, embedding, model)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                transcription_id,
                chunk_index,
                chunk_text,
                kwargs.get('timestamp_start'),
                kwargs.get('timestamp_end'),
                embedding,
                kwargs.get('model')
            ))
            return cursor.lastrowid

    def delete_transcription_embeddings(self, transcription_id: int):
        """Delete all embeddings for a transcription."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM transcription_embeddings WHERE transcription_id = ?', (transcription_id,))

    def get_all_transcription_embeddings(self) -> List[Dict]:
        """Get all transcription embeddings for search."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT te.*, t.meeting_id, m.title as meeting_title, m.date as meeting_date
                FROM transcription_embeddings te
                JOIN transcriptions t ON te.transcription_id = t.id
                LEFT JOIN meetings m ON t.meeting_id = m.id
            ''')
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Summaries ====================

    def upsert_summary(self, entity_type: str, entity_id: int, summary_text: str, **kwargs) -> int:
        """Insert or update a summary."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            summary_type = kwargs.get('summary_type', 'normaal')
            cursor.execute('''
                INSERT INTO summaries (entity_type, entity_id, summary_type, summary_text, model_used)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, entity_id, summary_type) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    model_used = excluded.model_used,
                    generated_at = CURRENT_TIMESTAMP
            ''', (
                entity_type,
                entity_id,
                summary_type,
                summary_text,
                kwargs.get('model_used')
            ))
            cursor.execute(
                'SELECT id FROM summaries WHERE entity_type = ? AND entity_id = ? AND summary_type = ?',
                (entity_type, entity_id, summary_type)
            )
            return cursor.fetchone()[0]

    def get_summary(self, entity_type: str, entity_id: int, summary_type: str = 'normaal') -> Optional[Dict]:
        """Get a summary for an entity."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM summaries
                WHERE entity_type = ? AND entity_id = ? AND summary_type = ?
            ''', (entity_type, entity_id, summary_type))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_summaries_for_entity(self, entity_type: str, entity_id: int) -> List[Dict]:
        """Get all summaries for an entity."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM summaries
                WHERE entity_type = ? AND entity_id = ?
                ORDER BY summary_type
            ''', (entity_type, entity_id))
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Dossiers ====================

    def create_dossier(self, title: str, topic: str, **kwargs) -> int:
        """Create a new dossier."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO dossiers (title, topic, description, date_from, date_to, status, auto_update)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                title,
                topic,
                kwargs.get('description'),
                kwargs.get('date_from'),
                kwargs.get('date_to'),
                kwargs.get('status', 'active'),
                kwargs.get('auto_update', 1)
            ))
            return cursor.lastrowid

    def update_dossier(self, dossier_id: int, **kwargs) -> bool:
        """Update a dossier."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []

            for field in ['title', 'topic', 'description', 'date_from', 'date_to', 'status', 'auto_update']:
                if field in kwargs:
                    updates.append(f'{field} = ?')
                    params.append(kwargs[field])

            if not updates:
                return False

            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.append(dossier_id)

            cursor.execute(f'''
                UPDATE dossiers SET {', '.join(updates)} WHERE id = ?
            ''', params)
            return cursor.rowcount > 0

    def get_dossier(self, dossier_id: int) -> Optional[Dict]:
        """Get a dossier by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM dossiers WHERE id = ?', (dossier_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_dossiers(self, status: str = None, limit: int = 50) -> List[Dict]:
        """Get all dossiers."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM dossiers WHERE 1=1'
            params = []

            if status:
                query += ' AND status = ?'
                params.append(status)

            query += ' ORDER BY updated_at DESC LIMIT ?'
            params.append(limit)

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def add_dossier_item(self, dossier_id: int, item_type: str, item_id: int, **kwargs) -> int:
        """Add an item to a dossier."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO dossier_items (dossier_id, item_type, item_id, relevance_score,
                                          item_date, title, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                dossier_id,
                item_type,
                item_id,
                kwargs.get('relevance_score'),
                kwargs.get('item_date'),
                kwargs.get('title'),
                kwargs.get('summary')
            ))
            return cursor.lastrowid

    def get_dossier_items(self, dossier_id: int) -> List[Dict]:
        """Get all items in a dossier, ordered by date."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM dossier_items
                WHERE dossier_id = ?
                ORDER BY item_date ASC, id ASC
            ''', (dossier_id,))
            return [dict(row) for row in cursor.fetchall()]

    def clear_dossier_items(self, dossier_id: int):
        """Remove all items from a dossier (for rebuild)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM dossier_items WHERE dossier_id = ?', (dossier_id,))

    def search_dossiers(self, query: str, limit: int = 20) -> List[Dict]:
        """Search dossiers by topic or title."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM dossiers
                WHERE title LIKE ? OR topic LIKE ? OR description LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
            ''', (f'%{query}%', f'%{query}%', f'%{query}%', limit))
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Database Integrity ====================

    def check_integrity(self, quick: bool = True) -> Dict[str, Any]:
        """
        Check database integrity.

        Args:
            quick: Use quick_check (faster) instead of full integrity_check

        Returns:
            Dict with 'ok' boolean and 'details' string
        """
        pragma = 'quick_check' if quick else 'integrity_check'
        try:
            with self._get_connection() as conn:
                result = conn.execute(f'PRAGMA {pragma}').fetchone()
                is_ok = result[0] == 'ok'
                if not is_ok:
                    logger.error(f'Database integrity check failed: {result[0]}')
                return {
                    'ok': is_ok,
                    'details': result[0],
                    'check_type': pragma
                }
        except Exception as e:
            logger.error(f'Integrity check error: {e}')
            return {
                'ok': False,
                'details': str(e),
                'check_type': pragma
            }

    def backup_schema(self, backup_path: Path = None) -> bool:
        """
        Backup database schema and metadata (without large BLOBs).

        This creates a lightweight backup of all metadata that can be used
        to rebuild the database. Document files can be re-downloaded from Notubiz.

        Args:
            backup_path: Path for backup file. Defaults to db_path.schema.backup

        Returns:
            True if backup successful
        """
        if backup_path is None:
            backup_path = self.db_path.with_suffix('.schema.backup')

        try:
            # Tables to fully backup (small metadata)
            full_tables = [
                'gremia', 'meetings', 'agenda_items', 'sync_status',
                'parties', 'election_programs', 'party_positions',
                'party_scrape_configs', 'raadsleden', 'standpunten',
                'standpunt_topics', 'annotations', 'visit_reports',
                'visit_report_meetings', 'transcriptions', 'summaries',
                'dossiers', 'dossier_items'
            ]

            # Documents table: backup metadata but not file_blob
            with sqlite3.connect(self.db_path, timeout=30.0) as src:
                with sqlite3.connect(backup_path) as dst:
                    src.row_factory = sqlite3.Row

                    # Copy schema
                    for table in src.execute(
                        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall():
                        if table['sql']:
                            dst.execute(table['sql'])

                    # Copy full tables
                    for table in full_tables:
                        try:
                            rows = src.execute(f'SELECT * FROM {table}').fetchall()
                            if rows:
                                cols = rows[0].keys()
                                placeholders = ','.join(['?' for _ in cols])
                                col_names = ','.join(cols)
                                dst.executemany(
                                    f'INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})',
                                    [tuple(row) for row in rows]
                                )
                        except sqlite3.OperationalError:
                            pass  # Table doesn't exist yet

                    # Documents: copy without file_blob
                    try:
                        rows = src.execute('''
                            SELECT id, notubiz_id, meeting_id, agenda_item_id, title,
                                   filename, url, local_path, mime_type, file_size,
                                   text_content, text_extracted, download_status,
                                   NULL as file_blob, file_storage_mode,
                                   created_at, updated_at
                            FROM documents
                        ''').fetchall()
                        if rows:
                            dst.executemany('''
                                INSERT OR REPLACE INTO documents
                                (id, notubiz_id, meeting_id, agenda_item_id, title,
                                 filename, url, local_path, mime_type, file_size,
                                 text_content, text_extracted, download_status,
                                 file_blob, file_storage_mode, created_at, updated_at)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            ''', [tuple(row) for row in rows])
                    except sqlite3.OperationalError:
                        pass

                    dst.commit()

            backup_size = backup_path.stat().st_size / (1024 * 1024)
            logger.info(f'Schema backup created: {backup_path} ({backup_size:.1f} MB)')
            return True

        except Exception as e:
            logger.error(f'Schema backup failed: {e}')
            return False

    def restore_from_schema_backup(self, backup_path: Path) -> bool:
        """
        Restore database from schema backup.

        Note: This restores metadata only. Documents will need to be re-downloaded.

        Args:
            backup_path: Path to schema backup file

        Returns:
            True if restore successful
        """
        if not backup_path.exists():
            logger.error(f'Backup file not found: {backup_path}')
            return False

        try:
            # Create new database from backup
            import shutil
            temp_path = self.db_path.with_suffix('.restore.tmp')

            shutil.copy2(backup_path, temp_path)

            # Verify the backup
            with sqlite3.connect(temp_path) as conn:
                result = conn.execute('PRAGMA quick_check').fetchone()
                if result[0] != 'ok':
                    logger.error('Backup file is corrupt')
                    temp_path.unlink()
                    return False

            # Replace current database
            if self.db_path.exists():
                corrupt_path = self.db_path.with_suffix('.corrupt')
                self.db_path.rename(corrupt_path)
                logger.info(f'Moved corrupt database to: {corrupt_path}')

            temp_path.rename(self.db_path)
            logger.info(f'Database restored from: {backup_path}')

            # Mark all documents for re-download
            with self._get_connection() as conn:
                conn.execute('''
                    UPDATE documents
                    SET download_status = 'pending', file_blob = NULL
                    WHERE file_blob IS NOT NULL OR download_status = 'stored'
                ''')
                logger.info('Marked documents for re-download')

            return True

        except Exception as e:
            logger.error(f'Restore failed: {e}')
            return False


# Singleton instance
_db_instance = None


def get_database() -> Database:
    """Get singleton database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


if __name__ == '__main__':
    # Test database
    db = get_database()
    print("Database initialized successfully")
    print(f"Statistics: {db.get_statistics()}")
