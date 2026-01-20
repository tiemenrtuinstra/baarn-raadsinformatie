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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f'Database error: {e}')
            raise
        finally:
            conn.close()

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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
                    FOREIGN KEY (agenda_item_id) REFERENCES agenda_items(id)
                )
            ''')

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

            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_meetings_gremium ON meetings(gremium_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_documents_meeting ON documents(meeting_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_agenda_items_meeting ON agenda_items(meeting_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_annotations_document ON annotations(document_id)')

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

    # ==================== Statistics ====================

    def get_statistics(self) -> Dict:
        """Get database statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            stats = {}

            for table in ['gremia', 'meetings', 'agenda_items', 'documents', 'annotations']:
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

            return stats


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
