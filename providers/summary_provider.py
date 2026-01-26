#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Summary Provider voor Baarn Politiek MCP Server.
Genereert AI samenvattingen van documenten en vergaderingen.

Samenvattingen worden gecached in de database voor hergebruik.
De LLM wordt aangestuurd door de MCP client (Claude).
"""

from typing import Dict, List, Optional
from datetime import datetime

from core.config import Config
from core.database import Database, get_database
from shared.logging_config import get_logger, LogContext

logger = get_logger('summary-provider')


class SummaryProvider:
    """
    Provider voor AI samenvattingen.

    Genereert en cached samenvattingen van:
    - Documenten (PDF tekst)
    - Vergaderingen (agenda + documenten + transcript)
    - Topics (alle info over een onderwerp)
    """

    def __init__(self, db: Database = None):
        """Initialize summary provider."""
        self.db = db or get_database()
        logger.info('SummaryProvider initialized')

    def get_document_for_summary(self, document_id: int) -> Dict:
        """
        Haal document content op voor samenvatting.

        Args:
            document_id: Document ID

        Returns:
            Dict met document info en tekst voor samenvatting
        """
        doc = self.db.get_document(document_id)
        if not doc:
            return {'error': f'Document {document_id} niet gevonden'}

        text_content = doc.get('text_content', '')
        if not text_content:
            return {'error': f'Document {document_id} heeft geen tekst content'}

        # Check for existing summary
        existing = self.db.get_summary('document', document_id)

        return {
            'document_id': document_id,
            'title': doc.get('title', ''),
            'text_content': text_content,
            'text_length': len(text_content),
            'existing_summary': existing.get('summary_text') if existing else None,
            'meeting_id': doc.get('meeting_id')
        }

    def save_document_summary(
        self,
        document_id: int,
        summary_text: str,
        summary_type: str = 'normaal',
        model_used: str = None
    ) -> Dict:
        """
        Sla een gegenereerde samenvatting op.

        Args:
            document_id: Document ID
            summary_text: De gegenereerde samenvatting
            summary_type: 'kort', 'normaal', of 'lang'
            model_used: Welk model is gebruikt

        Returns:
            Dict met resultaat
        """
        summary_id = self.db.upsert_summary(
            entity_type='document',
            entity_id=document_id,
            summary_text=summary_text,
            summary_type=summary_type,
            model_used=model_used
        )

        return {
            'summary_id': summary_id,
            'document_id': document_id,
            'summary_type': summary_type,
            'status': 'saved'
        }

    def get_meeting_for_summary(self, meeting_id: int) -> Dict:
        """
        Haal vergadering content op voor samenvatting.

        Args:
            meeting_id: Meeting ID

        Returns:
            Dict met vergadering info voor samenvatting
        """
        meeting = self.db.get_meeting(meeting_id=meeting_id)
        if not meeting:
            return {'error': f'Vergadering {meeting_id} niet gevonden'}

        # Get agenda items
        agenda_items = self.db.get_agenda_items(meeting_id)

        # Get documents with text
        docs = self.db.get_documents(meeting_id=meeting_id)
        docs_with_text = [d for d in docs if d.get('text_content')]

        # Get transcription if available
        transcription = self.db.get_transcription(meeting_id=meeting_id)

        # Build content for summarization
        content_parts = []

        # Meeting info
        content_parts.append(f"# Vergadering: {meeting.get('title', '')}")
        content_parts.append(f"Datum: {meeting.get('date', '')}")
        if meeting.get('description'):
            content_parts.append(f"Beschrijving: {meeting['description']}")

        # Agenda
        if agenda_items:
            content_parts.append("\n## Agenda")
            for item in agenda_items:
                content_parts.append(f"- {item.get('title', '')}")
                if item.get('decision'):
                    content_parts.append(f"  Besluit: {item['decision']}")

        # Document snippets
        if docs_with_text:
            content_parts.append("\n## Documenten")
            for doc in docs_with_text[:5]:  # Limit to 5 docs
                content_parts.append(f"\n### {doc.get('title', '')}")
                text = doc.get('text_content', '')[:2000]  # First 2000 chars
                content_parts.append(text)

        # Transcription snippet
        if transcription and transcription.get('transcript_text'):
            content_parts.append("\n## Transcriptie (fragment)")
            transcript = transcription['transcript_text'][:3000]  # First 3000 chars
            content_parts.append(transcript)

        combined_content = '\n'.join(content_parts)

        # Check existing summary
        existing = self.db.get_summary('meeting', meeting_id)

        return {
            'meeting_id': meeting_id,
            'title': meeting.get('title', ''),
            'date': meeting.get('date', ''),
            'content_for_summary': combined_content,
            'content_length': len(combined_content),
            'agenda_items_count': len(agenda_items),
            'documents_count': len(docs_with_text),
            'has_transcription': transcription is not None,
            'existing_summary': existing.get('summary_text') if existing else None
        }

    def save_meeting_summary(
        self,
        meeting_id: int,
        summary_text: str,
        summary_type: str = 'normaal',
        model_used: str = None
    ) -> Dict:
        """
        Sla een vergadering samenvatting op.

        Args:
            meeting_id: Meeting ID
            summary_text: De gegenereerde samenvatting
            summary_type: 'kort', 'normaal', of 'lang'
            model_used: Welk model is gebruikt

        Returns:
            Dict met resultaat
        """
        summary_id = self.db.upsert_summary(
            entity_type='meeting',
            entity_id=meeting_id,
            summary_text=summary_text,
            summary_type=summary_type,
            model_used=model_used
        )

        return {
            'summary_id': summary_id,
            'meeting_id': meeting_id,
            'summary_type': summary_type,
            'status': 'saved'
        }

    def get_topic_content(self, topic: str, date_from: str = None) -> Dict:
        """
        Verzamel alle content over een topic voor samenvatting.

        Args:
            topic: Onderwerp om te zoeken
            date_from: Optionele start datum

        Returns:
            Dict met alle relevante content
        """
        # Search documents
        docs = self.db.get_documents(search=topic, limit=20)

        # Search meetings
        meetings = self.db.get_meetings(search=topic, limit=20, date_from=date_from)

        # Search transcriptions
        transcription_results = self.db.search_transcriptions(topic, limit=10)

        # Build content
        content_parts = []
        content_parts.append(f"# Alle informatie over: {topic}")

        if meetings:
            content_parts.append("\n## Relevante vergaderingen")
            for m in meetings[:10]:
                content_parts.append(f"- {m.get('date', '')}: {m.get('title', '')}")

        if docs:
            content_parts.append("\n## Relevante documenten")
            for d in docs[:10]:
                content_parts.append(f"\n### {d.get('title', '')}")
                if d.get('text_content'):
                    # Find relevant snippet
                    text = d['text_content']
                    idx = text.lower().find(topic.lower())
                    if idx >= 0:
                        start = max(0, idx - 200)
                        end = min(len(text), idx + 500)
                        snippet = text[start:end]
                        content_parts.append(f"...{snippet}...")
                    else:
                        content_parts.append(text[:500])

        if transcription_results:
            content_parts.append("\n## Uit video/audio transcripties")
            for t in transcription_results[:5]:
                content_parts.append(
                    f"- {t.get('meeting_title', '')} ({t.get('meeting_date', '')}): "
                    f"{t.get('snippet', t.get('chunk_text', ''))[:200]}..."
                )

        combined = '\n'.join(content_parts)

        return {
            'topic': topic,
            'content_for_summary': combined,
            'content_length': len(combined),
            'meetings_found': len(meetings),
            'documents_found': len(docs),
            'transcription_matches': len(transcription_results)
        }

    def get_summary(
        self,
        entity_type: str,
        entity_id: int,
        summary_type: str = 'normaal'
    ) -> Optional[Dict]:
        """
        Haal een bestaande samenvatting op.

        Args:
            entity_type: 'document', 'meeting', of 'dossier'
            entity_id: ID van de entiteit
            summary_type: Type samenvatting

        Returns:
            Dict met samenvatting of None
        """
        return self.db.get_summary(entity_type, entity_id, summary_type)

    def list_summaries(
        self,
        entity_type: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Lijst alle samenvattingen op.

        Args:
            entity_type: Filter op type
            limit: Maximum aantal

        Returns:
            Lijst met samenvattingen
        """
        # Note: This would need a new DB method for full functionality
        # For now, return empty list - summaries are accessed per entity
        return []


# Singleton instance
_provider_instance = None


def get_summary_provider() -> SummaryProvider:
    """Get singleton summary provider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = SummaryProvider()
    return _provider_instance


if __name__ == '__main__':
    # Test
    provider = get_summary_provider()
    print("SummaryProvider initialized")
