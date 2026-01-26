#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visit Report provider for werkbezoeken en vergelijkbare verslagen.
"""

import sqlite3
from typing import Dict, List, Optional, Tuple

from core.database import Database, get_database
from core.document_index import get_document_index
from providers.document_provider import DocumentProvider, get_document_provider
from shared.logging_config import get_logger

logger = get_logger('visit-report-provider')


class VisitReportProvider:
    """Provider voor werkbezoek-verslagen."""

    def __init__(self, db: Database = None, document_provider: DocumentProvider = None):
        self.db = db or get_database()
        self.document_provider = document_provider or get_document_provider()
        self.index = get_document_index()

    def add_manual_visit_report(
        self,
        title: str,
        file_base64: str,
        filename: str,
        mime_type: str,
        **metadata
    ) -> int:
        """Create a manual visit report with an uploaded file."""
        document_id = self.document_provider.create_document_from_base64(
            title=title,
            filename=filename,
            mime_type=mime_type,
            file_base64=file_base64,
            source_url=metadata.get('source_url')
        )
        return self.db.add_visit_report(
            title=title,
            source='manual',
            document_id=document_id,
            **metadata
        )

    def import_visit_reports_from_documents(
        self,
        document_ids: List[int],
        **metadata
    ) -> Tuple[int, int]:
        """Create visit reports from existing documents."""
        created = 0
        skipped = 0
        for doc_id in document_ids:
            doc = self.db.get_document(doc_id)
            if not doc:
                skipped += 1
                continue
            try:
                self.db.add_visit_report(
                    title=doc.get('title') or metadata.get('title', 'Werkbezoek'),
                    source='notubiz',
                    source_id=doc.get('notubiz_id'),
                    document_id=doc_id,
                    source_url=doc.get('url'),
                    **metadata
                )
                created += 1
            except sqlite3.IntegrityError:
                skipped += 1
        return created, skipped

    def list_visit_reports(self, **filters) -> List[Dict]:
        return self.db.list_visit_reports(
            date_from=filters.get('date_from'),
            date_to=filters.get('date_to'),
            status=filters.get('status'),
            visit_type=filters.get('visit_type'),
            limit=filters.get('limit', 50),
            offset=filters.get('offset', 0)
        )

    def get_visit_report(self, visit_report_id: int) -> Optional[Dict]:
        report = self.db.get_visit_report(visit_report_id)
        if not report:
            return None
        meeting_ids = self.db.get_visit_report_meetings(visit_report_id)
        report['meeting_ids'] = meeting_ids
        if report.get('document_id'):
            doc = self.db.get_document(report['document_id'])
            if doc:
                report['document'] = {
                    'id': doc['id'],
                    'title': doc['title'],
                    'url': doc.get('url'),
                    'has_text': bool(doc.get('text_content'))
                }
        return report

    def search_visit_reports(self, query: str, limit: int = 50) -> List[Dict]:
        return self.db.search_visit_reports(query, limit=limit)

    def update_visit_report(self, visit_report_id: int, **fields) -> bool:
        return self.db.update_visit_report(visit_report_id, **fields)

    def delete_visit_report(self, visit_report_id: int) -> bool:
        return self.db.soft_delete_visit_report(visit_report_id)

    def link_to_meeting(self, visit_report_id: int, meeting_id: int) -> bool:
        return self.db.link_visit_report_to_meeting(visit_report_id, meeting_id)

    def index_visit_reports(self, visit_report_ids: List[int] = None) -> int:
        """Index linked document text for visit reports."""
        if visit_report_ids:
            report_ids = visit_report_ids
        else:
            report_ids = [r['id'] for r in self.db.list_visit_reports(limit=10000)]

        if not report_ids:
            return 0

        indexed = 0
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, document_id FROM visit_reports WHERE id IN (%s) AND document_id IS NOT NULL'
                % ','.join('?' * len(report_ids)),
                report_ids
            )
            rows = cursor.fetchall()
        for row in rows:
            doc_id = row['document_id']
            if doc_id:
                indexed += self.index.index_document(doc_id)
        return indexed


_visit_report_provider_instance: Optional[VisitReportProvider] = None


def get_visit_report_provider() -> VisitReportProvider:
    global _visit_report_provider_instance
    if _visit_report_provider_instance is None:
        _visit_report_provider_instance = VisitReportProvider()
    return _visit_report_provider_instance
