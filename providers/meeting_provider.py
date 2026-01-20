#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meeting Provider voor Baarn Politiek MCP Server.
Synchroniseert vergaderingen van Notubiz naar de lokale database.
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

from core.config import Config
from core.database import Database, get_database
from shared.logging_config import get_logger, LogContext
from .notubiz_client import NotubizClient, get_notubiz_client

logger = get_logger('meeting-provider')


class MeetingProvider:
    """Provider voor vergaderingen en agendapunten."""

    def __init__(self, db: Database = None, client: NotubizClient = None):
        """Initialize meeting provider."""
        self.db = db or get_database()
        self.client = client or get_notubiz_client()
        logger.info('MeetingProvider initialized')

    def sync_gremia(self) -> int:
        """
        Synchroniseer gremia (commissies) van Notubiz naar database.

        Returns:
            Number of gremia synced
        """
        with LogContext(logger, 'sync_gremia'):
            gremia = self.client.get_gremia()
            count = 0

            logger.debug(f'Retrieved {len(gremia)} gremia from API')

            for gremium in gremia:
                # Handle both dict and unexpected formats
                if isinstance(gremium, dict):
                    # Notubiz uses 'title' for gremium name
                    name = gremium.get('title') or gremium.get('name', 'Unknown')
                    self.db.upsert_gremium(
                        notubiz_id=str(gremium.get('id')),
                        name=name,
                        description=gremium.get('description'),
                        type=gremium.get('body')  # body indicates council/college/other
                    )
                    count += 1
                else:
                    logger.warning(f'Unexpected gremium format: {type(gremium)} - {gremium}')

            logger.info(f'Synced {count} gremia')
            return count

    def sync_meetings(
        self,
        date_from: str = None,
        date_to: str = None,
        gremium_id: str = None,
        full_details: bool = True
    ) -> Tuple[int, int]:
        """
        Synchroniseer vergaderingen van Notubiz naar database.

        Args:
            date_from: Start datum (YYYY-MM-DD), default: 1 jaar geleden
            date_to: Eind datum (YYYY-MM-DD), default: vandaag
            gremium_id: Filter op specifiek gremium
            full_details: Haal ook agenda items en documenten op

        Returns:
            Tuple of (meetings_synced, documents_found)
        """
        # Default date range: last year
        if not date_from:
            date_from = (date.today() - timedelta(days=365)).isoformat()
        if not date_to:
            date_to = date.today().isoformat()

        with LogContext(logger, 'sync_meetings', date_from=date_from, date_to=date_to):
            # Get all events
            events = self.client.get_all_events(
                date_from=date_from,
                date_to=date_to,
                gremium_id=gremium_id
            )

            meetings_count = 0
            documents_count = 0

            for event in events:
                # Store basic meeting info
                meeting_db_id = self._store_meeting(event)
                meetings_count += 1

                # Fetch and store details
                if full_details and meeting_db_id:
                    # Extract ID from @attributes or directly
                    attrs = event.get('@attributes', {})
                    notubiz_id = str(attrs.get('id') or event.get('id'))
                    docs = self._sync_meeting_details(notubiz_id, meeting_db_id)
                    documents_count += docs

            # Update sync status
            self.db.update_sync_status(
                'meetings',
                date_from=date_from,
                date_to=date_to,
                items_synced=meetings_count,
                status='completed'
            )

            logger.info(f'Synced {meetings_count} meetings, {documents_count} documents')
            return meetings_count, documents_count

    def _store_meeting(self, event: Dict) -> Optional[int]:
        """Store a meeting event in database."""
        try:
            # Extract ID from @attributes or directly
            attrs = event.get('@attributes', {})
            notubiz_id = str(attrs.get('id') or event.get('id'))

            # Parse date and time from nested structure
            # Structure: start_dates.start_date.@attributes.{date, time}
            event_date = ''
            start_time = None
            start_dates = event.get('start_dates', {})
            if start_dates:
                start_date_data = start_dates.get('start_date', {})
                if isinstance(start_date_data, dict):
                    date_attrs = start_date_data.get('@attributes', {})
                    event_date = date_attrs.get('date', '')
                    start_time = date_attrs.get('time')
            # Fallback to direct fields
            if not event_date:
                event_date = event.get('date', event.get('start_date', ''))
            if not start_time:
                start_time = event.get('start_time')
            end_time = event.get('end_time')

            # Get gremium ID from database - try category_id from attributes
            gremium_id = None
            category_id = attrs.get('category_id')
            if category_id:
                gremia = self.db.get_gremia()
                for g in gremia:
                    if g['notubiz_id'] == str(category_id):
                        gremium_id = g['id']
                        break
            # Fallback: check gremium field
            if not gremium_id and 'gremium' in event:
                gremium = event['gremium']
                gremia = self.db.get_gremia() if 'gremia' not in dir() else gremia
                for g in gremia:
                    if g['notubiz_id'] == str(gremium.get('id')):
                        gremium_id = g['id']
                        break

            return self.db.upsert_meeting(
                notubiz_id=notubiz_id,
                title=event.get('title', event.get('name', 'Unnamed meeting')),
                date=event_date,
                gremium_id=gremium_id,
                start_time=start_time,
                end_time=end_time,
                location=event.get('location'),
                status=event.get('status'),
                description=event.get('description'),
                video_url=event.get('video_url'),
                raw_data=event
            )
        except Exception as e:
            logger.error(f'Error storing meeting: {e}')
            return None

    def _sync_meeting_details(self, notubiz_id: str, meeting_db_id: int) -> int:
        """
        Sync meeting details including agenda items and documents.

        Returns:
            Number of documents found
        """
        meeting_details = self.client.get_meeting(notubiz_id)
        if not meeting_details:
            return 0

        documents_count = 0

        # Process agenda items
        agenda_items = meeting_details.get('agenda_items', meeting_details.get('agendaitems', []))
        for item in agenda_items:
            docs = self._store_agenda_item(item, meeting_db_id)
            documents_count += docs

        # Process top-level documents
        documents = meeting_details.get('documents', [])
        for doc in documents:
            self._store_document(doc, meeting_db_id)
            documents_count += 1

        return documents_count

    def _extract_agenda_title(self, item: Dict) -> str:
        """Extract title from agenda item, handling Notubiz structure."""
        # Try type_data.attributes[0].value (Notubiz format)
        type_data = item.get('type_data', {})
        if type_data:
            attrs = type_data.get('attributes', [])
            if attrs and isinstance(attrs, list) and len(attrs) > 0:
                title = attrs[0].get('value')
                if title:
                    return title
        # Fallback to direct fields
        return item.get('title') or item.get('name') or 'Unnamed item'

    def _store_agenda_item(
        self,
        item: Dict,
        meeting_db_id: int,
        parent_id: int = None
    ) -> int:
        """Store agenda item and its documents."""
        try:
            title = self._extract_agenda_title(item)
            item_id = self.db.upsert_agenda_item(
                notubiz_id=str(item.get('id')),
                meeting_id=meeting_db_id,
                title=title,
                parent_id=parent_id,
                order_number=item.get('order', item.get('number')),
                description=item.get('description'),
                decision=item.get('decision'),
                raw_data=item
            )

            documents_count = 0

            # Store documents for this agenda item
            documents = item.get('documents', [])
            for doc in documents:
                self._store_document(doc, meeting_db_id, item_id)
                documents_count += 1

            # Process sub-items recursively
            sub_items = item.get('sub_items', item.get('children', []))
            for sub_item in sub_items:
                docs = self._store_agenda_item(sub_item, meeting_db_id, item_id)
                documents_count += docs

            return documents_count
        except Exception as e:
            logger.error(f'Error storing agenda item: {e}')
            return 0

    def _store_document(
        self,
        doc: Dict,
        meeting_db_id: int,
        agenda_item_id: int = None
    ):
        """Store document reference in database."""
        try:
            url = self.client.get_document_url(doc)

            self.db.upsert_document(
                title=doc.get('title', doc.get('name', 'Unnamed document')),
                url=url,
                notubiz_id=str(doc.get('id')) if doc.get('id') else None,
                meeting_id=meeting_db_id,
                agenda_item_id=agenda_item_id,
                filename=doc.get('filename'),
                mime_type=doc.get('mime_type', doc.get('content_type'))
            )
        except Exception as e:
            logger.error(f'Error storing document: {e}')

    def get_meetings(
        self,
        limit: int = 50,
        offset: int = 0,
        date_from: str = None,
        date_to: str = None,
        gremium_id: int = None,
        search: str = None
    ) -> List[Dict]:
        """Get meetings from database with filters."""
        return self.db.get_meetings(
            limit=limit,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
            gremium_id=gremium_id,
            search=search
        )

    def get_meeting(self, meeting_id: int = None, notubiz_id: str = None) -> Optional[Dict]:
        """Get single meeting with all related data."""
        meeting = self.db.get_meeting(meeting_id=meeting_id, notubiz_id=notubiz_id)
        if not meeting:
            return None

        # Add agenda items
        meeting['agenda_items'] = self.db.get_agenda_items(meeting['id'])

        # Add documents
        meeting['documents'] = self.db.get_documents(meeting_id=meeting['id'])

        # Add annotations
        meeting['annotations'] = self.db.get_annotations(meeting_id=meeting['id'])

        return meeting

    def get_agenda_items(self, meeting_id: int) -> List[Dict]:
        """Get agenda items for a meeting."""
        return self.db.get_agenda_items(meeting_id)

    def get_gremia(self) -> List[Dict]:
        """Get all gremia from database."""
        return self.db.get_gremia()


# Singleton instance
_provider_instance = None


def get_meeting_provider() -> MeetingProvider:
    """Get singleton meeting provider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = MeetingProvider()
    return _provider_instance


if __name__ == '__main__':
    # Test the provider
    provider = get_meeting_provider()

    print("Syncing gremia...")
    count = provider.sync_gremia()
    print(f"Synced {count} gremia")

    print("\nGremia in database:")
    for g in provider.get_gremia():
        print(f"  - {g['name']}")

    print("\nSyncing recent meetings...")
    meetings, docs = provider.sync_meetings(
        date_from=(date.today() - timedelta(days=30)).isoformat(),
        date_to=date.today().isoformat()
    )
    print(f"Synced {meetings} meetings with {docs} documents")
