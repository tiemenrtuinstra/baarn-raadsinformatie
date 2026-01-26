#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search & Sync Provider voor Baarn Raadsinformatie Server.

Zoekt in historische data en synchroniseert alleen relevante documenten.
Dit is efficiënter dan een volledige sync wanneer je zoekt naar specifieke dossiers.
"""

from datetime import date
import requests
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
            # Use authenticated endpoint if available for historical data
            logger.info(f'Fetching events from {start_date} to {end_date}...')
            if self.client.has_auth_token():
                logger.info('Using authenticated access for historical data')
                all_events = self.client.get_all_historical_events(
                    date_from=start_date,
                    date_to=end_date
                )
            else:
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

            # Step 3b: Web search documents (raadsinformatie.nl) and store in DB
            raadsinfo = self._search_raadsinformatie_documents(query, limit=limit)
            results['raadsinformatie_items_found'] = raadsinfo.get('items_found', 0)
            results['raadsinformatie_documents_added'] = raadsinfo.get('documents_added', 0)

            # Step 4: Download documents
            download_needed = (
                results['meetings_synced'] > 0 or
                results['raadsinformatie_documents_added'] > 0
            )
            if download_docs and download_needed:
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

    def _search_raadsinformatie_documents(self, query: str, limit: int = 100) -> Dict:
        """
        Search documents via raadsinformatie.nl search endpoint.

        Uses the discovered v3.53.0 API to fetch full meeting details
        for any event IDs found, which works WITHOUT authentication!
        """
        results = {
            'items_found': 0,
            'documents_added': 0,
            'meetings_found': 0,
            'meetings_synced': 0
        }
        if not query:
            return results

        org_id = Config.NOTUBIZ_ORGANISATION_ID or self.client.get_organization_id()
        if not org_id:
            logger.warning('No organization ID available for raadsinformatie search')
            return results

        base_url = Config.RAADSINFORMATIE_BASE_URL.rstrip('/')
        per_page = 25
        page = 1

        # Collect event IDs to fetch full details
        event_ids = set()

        while results['items_found'] < limit:
            remaining = max(1, limit - results['items_found'])
            page_limit = min(per_page, remaining)
            params = [
                ('keywords', query),
                ('search', 'send'),
                ('limit', str(page_limit)),
                ('page', str(page)),
                ('filter[organisations][]', str(org_id)),
            ]
            url = f'{base_url}/zoeken/result'
            try:
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code != 200:
                    logger.warning(f'Raadsinformatie search failed: {resp.status_code}')
                    break
                body = resp.text.strip()
                if body in ('"no results"', 'no results'):
                    break
                data = resp.json()
            except Exception as e:
                logger.warning(f'Raadsinformatie search error: {e}')
                break

            items = data.get('items', [])
            if not items:
                break

            results['items_found'] += len(items)
            for item in items:
                item_type = item.get('type')

                # Collect event IDs for fetching full meeting details
                if item_type == 'event':
                    event_id = item.get('id')
                    if event_id:
                        event_ids.add(str(event_id))
                        results['meetings_found'] += 1

                # Also add documents directly
                elif item_type == 'document':
                    doc_id = item.get('id')
                    if not doc_id:
                        continue
                    title = item.get('title') or 'Untitled document'
                    doc_url = f"{Config.NOTUBIZ_API_URL}/document/{doc_id}/1"
                    self.db.upsert_document(
                        notubiz_id=str(doc_id),
                        title=title,
                        url=doc_url
                    )
                    results['documents_added'] += 1

            if len(items) < page_limit:
                break
            page += 1

        logger.info(
            f"Raadsinformatie search: {results['items_found']} items, "
            f"{results['meetings_found']} events, "
            f"{results['documents_added']} documents"
        )

        # Fetch full meeting details using v3.53.0 API (no auth needed!)
        if event_ids:
            logger.info(f'Fetching full details for {len(event_ids)} meetings via v3.53.0 API...')
            synced = self._sync_meetings_by_ids(list(event_ids))
            results['meetings_synced'] = synced
            logger.info(f'Synced {synced} meetings with full details')

        return results

    def _sync_meetings_by_ids(self, meeting_ids: List[str]) -> int:
        """
        Sync meetings by their IDs using the v3.53.0 API.

        This endpoint works WITHOUT any token and returns full meeting details
        including agenda items and documents for historical meetings!

        Args:
            meeting_ids: List of Notubiz meeting/event IDs

        Returns:
            Number of meetings successfully synced
        """
        if not meeting_ids:
            return 0

        synced_count = 0

        # Fetch meetings in batches of 10 to avoid URL length limits
        batch_size = 10
        for i in range(0, len(meeting_ids), batch_size):
            batch = meeting_ids[i:i + batch_size]

            try:
                meetings = self.client.get_meetings_by_ids(batch)

                for meeting in meetings:
                    try:
                        meeting_db_id = self._store_meeting_v3(meeting)
                        if meeting_db_id:
                            self._store_agenda_items_v3(meeting_db_id, meeting)
                            synced_count += 1
                    except Exception as e:
                        logger.error(f'Error storing meeting: {e}')

            except Exception as e:
                logger.error(f'Error fetching meetings batch: {e}')

        return synced_count

    def _store_meeting_v3(self, meeting: Dict) -> Optional[int]:
        """Store meeting from v3.53.0 API format in database."""
        meeting_id = str(meeting.get('id', ''))
        if not meeting_id:
            return None

        # Get date - plannings is a list in v3.53.0 format
        plannings = meeting.get('plannings', [])
        start_date = None
        if plannings and isinstance(plannings, list) and len(plannings) > 0:
            start_date = plannings[0].get('start_date')
        elif isinstance(plannings, dict):
            start_date = plannings.get('start_date')

        # Get gremium
        gremium = meeting.get('gremium', {})
        gremium_id = str(gremium.get('id', '')) if gremium else None

        # Get meeting title from attributes (v3.53.0 format)
        title = 'Vergadering'
        attributes = meeting.get('attributes', [])
        if attributes and isinstance(attributes, list) and len(attributes) > 0:
            title = attributes[0].get('value', title)

        # Store meeting
        return self.db.upsert_meeting(
            notubiz_id=meeting_id,
            title=title,
            date=start_date,
            gremium_id=gremium_id,
            location=meeting.get('location'),
            status=meeting.get('last_modified')  # Use last_modified as status indicator
        )

    def _store_agenda_items_v3(self, meeting_db_id: int, meeting: Dict):
        """Store agenda items and documents from v3.53.0 API format."""
        agenda_items = meeting.get('agenda_items', [])

        for idx, item in enumerate(agenda_items):
            item_id = str(item.get('id', ''))

            # Get title from heading or type_data
            title = item.get('heading', '')
            if not title:
                type_data = item.get('type_data', {})
                if type_data:
                    attrs = type_data.get('attributes', [])
                    if attrs and isinstance(attrs, list) and len(attrs) > 0:
                        title = attrs[0].get('value', '')
            if not title:
                title = f'Agendapunt {idx + 1}'

            agenda_item_db_id = self.db.upsert_agenda_item(
                notubiz_id=item_id,
                meeting_id=meeting_db_id,
                title=title,
                description=item.get('description'),
                order=idx
            )

            # Store documents
            documents = item.get('documents', [])
            for doc in documents:
                self._store_document_v3(meeting_db_id, agenda_item_db_id, doc)

    def _store_document_v3(self, meeting_id: int, agenda_item_id: int, doc: Dict):
        """Store document from v3.53.0 API format in database."""
        doc_id = str(doc.get('id', ''))
        if not doc_id:
            return

        # Get URL - v3.53.0 format has 'url' directly
        url = doc.get('url')
        if not url:
            # Fallback to constructing URL
            url = f"{Config.NOTUBIZ_API_URL}/document/{doc_id}/1"

        self.db.upsert_document(
            notubiz_id=doc_id,
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            title=doc.get('title', 'Untitled'),
            document_type=doc.get('type'),
            url=url
        )

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
