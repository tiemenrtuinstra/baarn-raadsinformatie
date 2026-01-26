#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dossier Provider voor Baarn Politiek MCP Server.
Genereert automatische dossiers/tijdlijnen per onderwerp.

Een dossier combineert:
- Vergaderingen waar het onderwerp besproken is
- Relevante documenten
- Besluiten en moties
- Transcriptie fragmenten
"""

from typing import Dict, List, Optional
from datetime import datetime, date
from dataclasses import dataclass

from core.config import Config
from core.database import Database, get_database
from shared.logging_config import get_logger, LogContext

logger = get_logger('dossier-provider')


@dataclass
class DossierItem:
    """Item in een dossier tijdlijn."""
    item_type: str  # 'meeting', 'document', 'decision', 'transcript_segment'
    item_id: int
    item_date: str
    title: str
    summary: str = ''
    relevance_score: float = 0.0


class DossierProvider:
    """
    Provider voor automatische dossier/tijdlijn generatie.

    Zoekt alle informatie over een onderwerp en bouwt een
    chronologische tijdlijn met relevante items.
    """

    def __init__(self, db: Database = None):
        """Initialize dossier provider."""
        self.db = db or get_database()
        logger.info('DossierProvider initialized')

    def create_dossier(
        self,
        topic: str,
        date_from: str = None,
        include_transcripts: bool = True
    ) -> Dict:
        """
        Maak een nieuw dossier voor een onderwerp.

        Args:
            topic: Onderwerp (bijv. 'Paleis Soestdijk')
            date_from: Optionele start datum (YYYY-MM-DD)
            include_transcripts: Ook transcripties doorzoeken

        Returns:
            Dict met dossier info en tijdlijn items
        """
        with LogContext(logger, 'create_dossier', topic=topic):
            # Check of dossier al bestaat
            existing = self.db.search_dossiers(topic, limit=1)
            if existing and existing[0].get('topic', '').lower() == topic.lower():
                # Update bestaand dossier
                return self.update_dossier(existing[0]['id'])

            # Maak nieuw dossier
            title = f"Dossier: {topic}"
            dossier_id = self.db.create_dossier(
                title=title,
                topic=topic,
                description=f"Automatisch gegenereerd dossier over {topic}",
                date_from=date_from,
                auto_update=1
            )

            # Verzamel items
            items = self._collect_items(topic, date_from, include_transcripts)

            # Voeg items toe aan dossier
            for item in items:
                self.db.add_dossier_item(
                    dossier_id=dossier_id,
                    item_type=item.item_type,
                    item_id=item.item_id,
                    relevance_score=item.relevance_score,
                    item_date=item.item_date,
                    title=item.title,
                    summary=item.summary
                )

            logger.info(f'Created dossier {dossier_id} with {len(items)} items')

            return self.get_dossier(dossier_id)

    def _collect_items(
        self,
        topic: str,
        date_from: str = None,
        include_transcripts: bool = True
    ) -> List[DossierItem]:
        """Verzamel alle relevante items voor een topic."""
        items = []

        # 1. Zoek vergaderingen
        meetings = self.db.get_meetings(
            search=topic,
            date_from=date_from,
            limit=100
        )
        for m in meetings:
            items.append(DossierItem(
                item_type='meeting',
                item_id=m['id'],
                item_date=m.get('date', ''),
                title=m.get('title', ''),
                summary=m.get('description', '')[:200] if m.get('description') else '',
                relevance_score=1.0  # Direct match
            ))

        # 2. Zoek documenten
        docs = self.db.get_documents(search=topic, limit=100)
        for d in docs:
            # Bepaal relevantie op basis van titel match
            title_lower = (d.get('title') or '').lower()
            topic_lower = topic.lower()
            relevance = 1.0 if topic_lower in title_lower else 0.8

            # Haal meeting date als beschikbaar
            item_date = ''
            if d.get('meeting_id'):
                meeting = self.db.get_meeting(meeting_id=d['meeting_id'])
                if meeting:
                    item_date = meeting.get('date', '')

            items.append(DossierItem(
                item_type='document',
                item_id=d['id'],
                item_date=item_date,
                title=d.get('title', ''),
                summary=self._extract_snippet(d.get('text_content', ''), topic),
                relevance_score=relevance
            ))

        # 3. Zoek in transcripties (semantic search als beschikbaar)
        if include_transcripts:
            try:
                transcription_results = self.db.search_transcriptions(topic, limit=50)
                for t in transcription_results:
                    items.append(DossierItem(
                        item_type='transcript_segment',
                        item_id=t.get('id', 0),
                        item_date=t.get('meeting_date', ''),
                        title=f"Transcriptie: {t.get('meeting_title', '')}",
                        summary=t.get('snippet', '')[:200],
                        relevance_score=0.7
                    ))
            except Exception as e:
                logger.warning(f'Transcription search failed: {e}')

        # 4. Zoek in agenda items met besluiten
        # Dit vereist een directe query
        agenda_items = self._search_agenda_items(topic, date_from)
        for item in agenda_items:
            if item.get('decision'):
                items.append(DossierItem(
                    item_type='decision',
                    item_id=item['id'],
                    item_date=item.get('meeting_date', ''),
                    title=item.get('title', ''),
                    summary=item.get('decision', '')[:200],
                    relevance_score=1.0  # Besluiten zijn belangrijk
                ))

        # Sorteer op datum
        items.sort(key=lambda x: x.item_date or '0000-00-00')

        # Verwijder duplicaten (zelfde item_type + item_id)
        seen = set()
        unique_items = []
        for item in items:
            key = (item.item_type, item.item_id)
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        return unique_items

    def _search_agenda_items(self, topic: str, date_from: str = None) -> List[Dict]:
        """Zoek agenda items met besluiten over een topic."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT ai.*, m.date as meeting_date, m.title as meeting_title
                FROM agenda_items ai
                JOIN meetings m ON ai.meeting_id = m.id
                WHERE (ai.title LIKE ? OR ai.description LIKE ? OR ai.decision LIKE ?)
            '''
            params = [f'%{topic}%', f'%{topic}%', f'%{topic}%']

            if date_from:
                query += ' AND m.date >= ?'
                params.append(date_from)

            query += ' ORDER BY m.date ASC'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _extract_snippet(self, text: str, topic: str, context: int = 150) -> str:
        """Extract snippet rond topic match."""
        if not text:
            return ''

        text_lower = text.lower()
        topic_lower = topic.lower()
        idx = text_lower.find(topic_lower)

        if idx >= 0:
            start = max(0, idx - context)
            end = min(len(text), idx + len(topic) + context)
            snippet = text[start:end]
            if start > 0:
                snippet = '...' + snippet
            if end < len(text):
                snippet = snippet + '...'
            return snippet
        else:
            return text[:context * 2] + '...' if len(text) > context * 2 else text

    def get_dossier(self, dossier_id: int) -> Dict:
        """
        Haal een dossier op met alle tijdlijn items.

        Args:
            dossier_id: Dossier ID

        Returns:
            Dict met dossier info en items
        """
        dossier = self.db.get_dossier(dossier_id)
        if not dossier:
            return {'error': f'Dossier {dossier_id} niet gevonden'}

        items = self.db.get_dossier_items(dossier_id)

        # Groepeer items per type
        by_type = {}
        for item in items:
            item_type = item.get('item_type', 'unknown')
            if item_type not in by_type:
                by_type[item_type] = []
            by_type[item_type].append(item)

        return {
            'id': dossier['id'],
            'title': dossier.get('title', ''),
            'topic': dossier.get('topic', ''),
            'description': dossier.get('description', ''),
            'date_from': dossier.get('date_from'),
            'date_to': dossier.get('date_to'),
            'status': dossier.get('status', 'active'),
            'created_at': dossier.get('created_at'),
            'updated_at': dossier.get('updated_at'),
            'timeline': items,
            'items_by_type': by_type,
            'statistics': {
                'total_items': len(items),
                'meetings': len(by_type.get('meeting', [])),
                'documents': len(by_type.get('document', [])),
                'decisions': len(by_type.get('decision', [])),
                'transcript_segments': len(by_type.get('transcript_segment', []))
            }
        }

    def update_dossier(self, dossier_id: int) -> Dict:
        """
        Update een bestaand dossier met nieuwe informatie.

        Args:
            dossier_id: Dossier ID

        Returns:
            Dict met geupdate dossier
        """
        dossier = self.db.get_dossier(dossier_id)
        if not dossier:
            return {'error': f'Dossier {dossier_id} niet gevonden'}

        topic = dossier.get('topic', '')
        date_from = dossier.get('date_from')

        with LogContext(logger, 'update_dossier', dossier_id=dossier_id):
            # Clear existing items
            self.db.clear_dossier_items(dossier_id)

            # Recollect items
            items = self._collect_items(topic, date_from, include_transcripts=True)

            # Add items
            for item in items:
                self.db.add_dossier_item(
                    dossier_id=dossier_id,
                    item_type=item.item_type,
                    item_id=item.item_id,
                    relevance_score=item.relevance_score,
                    item_date=item.item_date,
                    title=item.title,
                    summary=item.summary
                )

            # Update timestamp
            self.db.update_dossier(dossier_id)

            logger.info(f'Updated dossier {dossier_id} with {len(items)} items')

            return self.get_dossier(dossier_id)

    def list_dossiers(self, status: str = None) -> List[Dict]:
        """
        Lijst alle dossiers op.

        Args:
            status: Filter op status ('active', 'archived')

        Returns:
            Lijst met dossiers
        """
        dossiers = self.db.get_dossiers(status=status)

        # Add item counts
        for dossier in dossiers:
            items = self.db.get_dossier_items(dossier['id'])
            dossier['item_count'] = len(items)

        return dossiers

    def archive_dossier(self, dossier_id: int) -> Dict:
        """
        Archiveer een dossier.

        Args:
            dossier_id: Dossier ID

        Returns:
            Dict met resultaat
        """
        success = self.db.update_dossier(dossier_id, status='archived')
        if success:
            return {'status': 'archived', 'dossier_id': dossier_id}
        return {'error': f'Dossier {dossier_id} niet gevonden'}

    def search_across_dossiers(self, query: str) -> List[Dict]:
        """
        Zoek in alle dossiers.

        Args:
            query: Zoekterm

        Returns:
            Lijst met matching dossiers
        """
        return self.db.search_dossiers(query)

    def get_dossier_timeline_markdown(self, dossier_id: int) -> str:
        """
        Genereer een markdown timeline voor een dossier.

        Args:
            dossier_id: Dossier ID

        Returns:
            Markdown string met tijdlijn
        """
        dossier = self.get_dossier(dossier_id)
        if 'error' in dossier:
            return f"Error: {dossier['error']}"

        lines = []
        lines.append(f"# {dossier['title']}")
        lines.append(f"\n_{dossier.get('description', '')}_\n")
        lines.append(f"**Topic:** {dossier['topic']}")
        lines.append(f"**Status:** {dossier['status']}")
        lines.append(f"**Items:** {dossier['statistics']['total_items']}\n")
        lines.append("---\n")
        lines.append("## Tijdlijn\n")

        current_date = None
        for item in dossier['timeline']:
            item_date = item.get('item_date', '')

            # Date header
            if item_date != current_date:
                current_date = item_date
                if item_date:
                    lines.append(f"\n### {item_date}\n")

            # Item
            item_type = item.get('item_type', 'item')
            icon = {
                'meeting': '📅',
                'document': '📄',
                'decision': '⚖️',
                'transcript_segment': '🎤'
            }.get(item_type, '•')

            lines.append(f"{icon} **{item.get('title', 'Untitled')}**")
            if item.get('summary'):
                lines.append(f"   {item['summary'][:150]}...")
            lines.append("")

        return '\n'.join(lines)


# Singleton instance
_provider_instance = None


def get_dossier_provider() -> DossierProvider:
    """Get singleton dossier provider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = DossierProvider()
    return _provider_instance


if __name__ == '__main__':
    # Test
    provider = get_dossier_provider()
    print("DossierProvider initialized")

    # List existing dossiers
    dossiers = provider.list_dossiers()
    print(f"Existing dossiers: {len(dossiers)}")
