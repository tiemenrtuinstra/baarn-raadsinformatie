#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search & Sync Provider voor Baarn Raadsinformatie Server.

Zoekt in historische data en synchroniseert alleen relevante documenten.
Dit is efficiënter dan een volledige sync wanneer je zoekt naar specifieke dossiers.
"""

from datetime import date
from typing import Dict, List, Optional, Tuple

from core.config import Config
from core.database import get_database
from core.document_index import get_document_index
from providers.notubiz_client import get_notubiz_client
from providers.meeting_provider import get_meeting_provider
from providers.document_provider import get_document_provider
from shared.logging_config import get_logger

logger = get_logger('search-sync')


class SearchSyncProvider:
    """
    Provider voor zoeken en synchroniseren op basis van zoektermen.

    Zoekt door historische Notubiz data en synchroniseert alleen
    vergaderingen en documenten die relevant zijn voor de zoekterm.
    """

    def __init__(self):
        self.db = get_database()
        self.client = get_notubiz_client()
        self.meeting_provider = get_meeting_provider()
        self.doc_provider = get_document_provider()

    def search_and_sync(
        self,
        query: str,
        start_date: str = "2010-01-01",
        end_date: str = None,
        download_docs: bool = True,
        index_docs: bool = True,
        limit: int = 100
    ) -> Dict:
        """
        Zoek naar een onderwerp en synchroniseer relevante vergaderingen.

        Args:
            query: Zoekterm (bijv. "Paleis Soestdijk", "De Speeldoos")
            start_date: Startdatum voor zoeken (default: 2010-01-01)
            end_date: Einddatum (default: vandaag)
            download_docs: Download documenten en extraheer tekst
            index_docs: Indexeer documenten voor semantic search
            limit: Maximum aantal vergaderingen om te syncen

        Returns:
            Dict met resultaten:
            - query: de zoekterm
            - meetings_found: aantal gevonden vergaderingen
            - meetings_synced: aantal gesynchroniseerde vergaderingen
            - documents_found: aantal gevonden documenten
            - documents_downloaded: aantal gedownloade documenten
            - documents_indexed: aantal geïndexeerde documenten
        """
        if not end_date:
            end_date = date.today().isoformat()

        logger.info(f'Search & Sync: "{query}" from {start_date} to {end_date}')

        results = {
            'query': query,
            'date_range': f'{start_date} to {end_date}',
            'meetings_found': 0,
            'meetings_synced': 0,
            'documents_found': 0,
            'documents_downloaded': 0,
            'documents_indexed': 0,
            'errors': []
        }

        try:
            # Step 1: Get all events from the date range
            logger.info(f'Fetching events from {start_date} to {end_date}...')
            all_events = self.client.get_all_events(
                date_from=start_date,
                date_to=end_date
            )
            logger.info(f'Found {len(all_events)} total events')

            # Step 2: Filter events matching the query
            query_lower = query.lower()
            matching_events = []

            for event in all_events:
                # Check title
                title = event.get('title', '') or ''
                if query_lower in title.lower():
                    matching_events.append(event)
                    continue

                # Check description
                description = event.get('description', '') or ''
                if query_lower in description.lower():
                    matching_events.append(event)
                    continue

                # Check gremium name
                gremium = event.get('gremium', {})
                if isinstance(gremium, dict):
                    gremium_name = gremium.get('title', '') or gremium.get('name', '') or ''
                    if query_lower in gremium_name.lower():
                        matching_events.append(event)

            # Limit results
            if len(matching_events) > limit:
                logger.info(f'Limiting from {len(matching_events)} to {limit} meetings')
                matching_events = matching_events[:limit]

            results['meetings_found'] = len(matching_events)
            logger.info(f'Found {len(matching_events)} meetings matching "{query}"')

            if not matching_events:
                logger.info('No matching meetings found, trying broader search...')
                # Try searching in meeting details (agenda items)
                matching_events = self._search_in_meeting_details(
                    all_events, query_lower, limit
                )
                results['meetings_found'] = len(matching_events)

            # Step 3: Sync matching meetings
            for event in matching_events:
                try:
                    meeting_id = self._sync_single_meeting(event)
                    if meeting_id:
                        results['meetings_synced'] += 1
                except Exception as e:
                    logger.error(f'Error syncing meeting: {e}')
                    results['errors'].append(str(e))

            # Step 4: Download documents
            if download_docs and results['meetings_synced'] > 0:
                logger.info('Downloading documents for synced meetings...')
                success, failed = self.doc_provider.download_pending_documents()
                results['documents_downloaded'] = success

                # Extract text
                self.doc_provider.extract_all_text()

                # Count documents found
                stats = self.db.get_statistics()
                results['documents_found'] = stats.get('documents', 0)

            # Step 5: Index documents for semantic search
            if index_docs and results['documents_downloaded'] > 0:
                logger.info('Indexing documents for semantic search...')
                try:
                    index = get_document_index()
                    indexed, chunks = index.index_all_documents()
                    results['documents_indexed'] = indexed
                except Exception as e:
                    logger.error(f'Indexing error: {e}')
                    results['errors'].append(f'Indexing: {str(e)}')

            logger.info(f'Search & Sync complete: {results}')

        except Exception as e:
            logger.error(f'Search & Sync error: {e}')
            results['errors'].append(str(e))

        return results

    def _search_in_meeting_details(
        self,
        events: List[Dict],
        query_lower: str,
        limit: int
    ) -> List[Dict]:
        """Search in meeting details (agenda items) for query."""
        matching = []

        for event in events:
            if len(matching) >= limit:
                break

            # Get meeting details
            event_id = self._get_event_id(event)
            if not event_id:
                continue

            try:
                meeting_details = self.client.get_meeting(event_id)
                if not meeting_details:
                    continue

                # Check agenda items
                agenda_items = meeting_details.get('agenda_items', [])
                for item in agenda_items:
                    title = item.get('title', '') or ''
                    if query_lower in title.lower():
                        matching.append(event)
                        break

                    # Check documents in agenda item
                    documents = item.get('documents', [])
                    for doc in documents:
                        doc_title = doc.get('title', '') or ''
                        if query_lower in doc_title.lower():
                            matching.append(event)
                            break

            except Exception as e:
                logger.debug(f'Error checking meeting {event_id}: {e}')

        return matching

    def _get_event_id(self, event: Dict) -> Optional[str]:
        """Extract event ID from event dict."""
        attrs = event.get('@attributes', {})
        return str(attrs.get('id') or event.get('id', ''))

    def _sync_single_meeting(self, event: Dict) -> Optional[int]:
        """Sync a single meeting and its documents."""
        event_id = self._get_event_id(event)
        if not event_id:
            return None

        # Get full meeting details
        meeting_details = self.client.get_meeting(event_id)
        if not meeting_details:
            return None

        # Store meeting
        meeting_db_id = self._store_meeting(event, meeting_details)

        # Store agenda items and documents
        if meeting_db_id:
            self._store_agenda_items(meeting_db_id, meeting_details)

        return meeting_db_id

    def _store_meeting(self, event: Dict, details: Dict = None) -> Optional[int]:
        """Store meeting in database."""
        event_id = self._get_event_id(event)

        # Get date
        start_dates = event.get('start_dates', {})
        event_date = None
        if start_dates:
            start_date_data = start_dates.get('start_date', {})
            if isinstance(start_date_data, dict):
                date_attrs = start_date_data.get('@attributes', {})
                event_date = date_attrs.get('date', '')

        # Get gremium
        gremium = event.get('gremium', {})
        gremium_id = None
        if isinstance(gremium, dict):
            gremium_id = str(gremium.get('id', ''))

        # Store in database
        return self.db.upsert_meeting(
            notubiz_id=event_id,
            title=event.get('title', 'Untitled'),
            date=event_date,
            gremium_id=gremium_id,
            location=details.get('location') if details else None,
            status=event.get('status')
        )

    def _store_agenda_items(self, meeting_id: int, details: Dict):
        """Store agenda items and documents."""
        agenda_items = details.get('agenda_items', [])

        for idx, item in enumerate(agenda_items):
            item_attrs = item.get('@attributes', {})
            item_notubiz_id = str(item_attrs.get('id') or item.get('id', ''))

            # Extract title from type_data
            title = self._extract_title(item)

            item_id = self.db.upsert_agenda_item(
                notubiz_id=item_notubiz_id,
                meeting_id=meeting_id,
                title=title,
                description=item.get('description'),
                order=idx
            )

            # Store documents
            documents = item.get('documents', [])
            if isinstance(documents, dict) and 'document' in documents:
                documents = documents['document']
                if not isinstance(documents, list):
                    documents = [documents]

            for doc in documents:
                self._store_document(meeting_id, item_id, doc)

    def _extract_title(self, item: Dict) -> str:
        """Extract title from agenda item."""
        type_data = item.get('type_data', {})
        if type_data:
            attrs = type_data.get('attributes', [])
            if attrs and isinstance(attrs, list) and len(attrs) > 0:
                title = attrs[0].get('value')
                if title:
                    return title
        return item.get('title') or item.get('name') or 'Unnamed item'

    def _store_document(self, meeting_id: int, agenda_item_id: int, doc: Dict):
        """Store document in database."""
        doc_attrs = doc.get('@attributes', {})
        doc_id = str(doc_attrs.get('id') or doc.get('id', ''))

        # Get URL
        url = doc.get('url')
        if not url:
            media = doc.get('media', {})
            if isinstance(media, dict):
                url = media.get('url')

        self.db.upsert_document(
            notubiz_id=doc_id,
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            title=doc.get('title', 'Untitled'),
            document_type=doc.get('type'),
            url=url
        )


# Singleton instance
_provider_instance = None


def get_search_sync_provider() -> SearchSyncProvider:
    """Get singleton search sync provider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = SearchSyncProvider()
    return _provider_instance
