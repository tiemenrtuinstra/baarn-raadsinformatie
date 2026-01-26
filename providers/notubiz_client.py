#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notubiz API Client voor Baarn Politiek MCP Server.
Handles alle communicatie met de Notubiz API.
"""

import requests
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from functools import lru_cache

from core.config import Config
from shared.logging_config import get_logger

logger = get_logger('notubiz-client')


class NotubizClient:
    """Client voor de Notubiz API."""

    def __init__(self):
        """Initialize Notubiz API client."""
        self.base_url = Config.NOTUBIZ_API_URL
        self.token = Config.NOTUBIZ_API_TOKEN
        self.auth_token = Config.NOTUBIZ_AUTH_TOKEN
        self.version = Config.NOTUBIZ_API_VERSION
        self.cache_dir = Config.CACHE_DIR
        self.cache_ttl = timedelta(hours=Config.CACHE_TTL_HOURS)
        self._organization_id = None

        auth_status = "with auth token" if self.auth_token else "public only"
        logger.info(f'NotubizClient initialized: {self.base_url} ({auth_status})')

    def has_auth_token(self) -> bool:
        """Check if authenticated access is available."""
        return bool(self.auth_token)

    def _get_auth_headers(self) -> Dict:
        """Get headers for authenticated requests."""
        if not self.auth_token:
            return {}
        return {'Authorization': f'Bearer {self.auth_token}'}

    def _get_default_params(self, lang: str = 'nl-nl') -> Dict:
        """Get default parameters for API requests."""
        return {
            'format': 'json',
            'version': self.version,
            'lang': lang,
            'application_token': self.token
        }

    def _get_cache_path(self, endpoint: str, params: Dict) -> Path:
        """Generate cache file path for a request."""
        cache_key = hashlib.md5(
            f"{endpoint}:{json.dumps(params, sort_keys=True)}".encode()
        ).hexdigest()
        return self.cache_dir / f"{cache_key}.json"

    def _is_cache_valid(self, cache_path: Path) -> bool:
        """Check if cache file is still valid."""
        if not cache_path.exists():
            return False
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        return datetime.now() - mtime < self.cache_ttl

    def _read_cache(self, cache_path: Path) -> Optional[Dict]:
        """Read data from cache."""
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f'Cache read error: {e}')
            return None

    def _write_cache(self, cache_path: Path, data: Dict):
        """Write data to cache."""
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f'Cache write error: {e}')

    def _request(
        self,
        endpoint: str,
        params: Dict = None,
        use_cache: bool = True,
        use_auth: bool = False
    ) -> Optional[Dict]:
        """Make API request with optional caching and authentication."""
        full_params = self._get_default_params()
        if params:
            full_params.update(params)

        # Get headers for authenticated requests
        headers = self._get_auth_headers() if use_auth else {}

        # Check cache (include auth status in cache key)
        cache_key_suffix = '_auth' if use_auth and self.auth_token else ''
        if use_cache:
            cache_path = self._get_cache_path(
                endpoint + cache_key_suffix, full_params
            )
            if self._is_cache_valid(cache_path):
                cached = self._read_cache(cache_path)
                if cached:
                    logger.debug(f'Cache hit: {endpoint}')
                    return cached

        # Make request
        url = f"{self.base_url}{endpoint}"
        auth_info = " (auth)" if use_auth and headers else ""
        logger.debug(f'API request: {url}{auth_info}')

        try:
            response = requests.get(
                url, params=full_params, headers=headers, timeout=30
            )
            response.raise_for_status()
            data = response.json()

            # Cache response
            if use_cache:
                self._write_cache(cache_path, data)

            return data
        except requests.exceptions.RequestException as e:
            logger.error(f'API request failed: {endpoint} - {e}')
            return None

    def get_organizations(self) -> List[Dict]:
        """Get list of all organizations."""
        response = self._request('/organisations')
        if response and 'organisations' in response:
            orgs = response['organisations']
            # Handle nested structure: {'organisation': [...]}
            if isinstance(orgs, dict) and 'organisation' in orgs:
                return orgs['organisation']
            # Handle direct list
            elif isinstance(orgs, list):
                return orgs
        return []

    def find_organization_by_name(self, name: str) -> Optional[Dict]:
        """Find organization by name (case-insensitive)."""
        orgs = self.get_organizations()
        name_lower = name.lower()
        candidates = []
        for org in orgs:
            org_name = org.get('name', '').lower()
            if name_lower in org_name:
                # Prefer non-OLD versions
                if '(old)' not in org_name:
                    return org
                candidates.append(org)
        # Return first candidate if no non-OLD found
        return candidates[0] if candidates else None

    def get_organization_id(self) -> Optional[str]:
        """Get the Baarn organization ID."""
        if self._organization_id:
            return self._organization_id

        # Check config first
        if Config.NOTUBIZ_ORGANISATION_ID:
            self._organization_id = Config.NOTUBIZ_ORGANISATION_ID
            return self._organization_id

        # Find Baarn
        org = self.find_organization_by_name(Config.MUNICIPALITY_NAME)
        if org:
            # ID can be in @attributes or directly on org
            attrs = org.get('@attributes', {})
            org_id = attrs.get('id') or org.get('id')
            self._organization_id = str(org_id)
            logger.info(f"Found organization: {org.get('name')} (ID: {self._organization_id})")
            return self._organization_id

        logger.error(f'Organization not found: {Config.MUNICIPALITY_NAME}')
        return None

    def get_gremia(self, organization_id: str = None) -> List[Dict]:
        """Get gremia (committees) for an organization."""
        org_id = organization_id or self.get_organization_id()
        if not org_id:
            logger.warning('No organization ID found')
            return []

        response = self._request(f'/organisations/{org_id}/gremia')
        logger.debug(f'Gremia response keys: {response.keys() if response else None}')

        if response and 'gremia' in response:
            gremia = response['gremia']
            logger.info(f'Retrieved {len(gremia)} gremia from API')

            # Log first gremium structure for debugging
            if gremia and len(gremia) > 0:
                first = gremia[0]
                logger.debug(f'First gremium type: {type(first)}, value: {first}')

            # Apply filter if configured
            if Config.GREMIA_FILTER:
                gremia = [
                    g for g in gremia
                    if isinstance(g, dict) and any(f.lower() in g.get('name', '').lower() for f in Config.GREMIA_FILTER)
                ]
            return gremia
        logger.warning(f'No gremia found in response: {response}')
        return []

    def get_events(
        self,
        organization_id: str = None,
        date_from: str = None,
        date_to: str = None,
        gremium_id: str = None,
        page: int = 1,
        page_size: int = 50,
        sort_field: str = 'start_date',
        sort_order: str = 'DESC',
        has_future_broadcast: bool = None,
        is_not_canceled: bool = None,
        template: bool = False
    ) -> Dict:
        """
        Get events (meetings) for an organization.

        Args:
            organization_id: Organization ID (default: Baarn)
            date_from: Start date (YYYY-MM-DD HH:MM:SS or YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD HH:MM:SS or YYYY-MM-DD)
            gremium_id: Filter by gremium
            page: Page number
            page_size: Items per page (per_page in API)
            sort_field: Sort field (start_date, etc.)
            sort_order: Sort order (ASC, DESC)
            has_future_broadcast: Filter for events with future broadcasts
            is_not_canceled: Filter for non-canceled events
            template: Include template events

        Returns:
            Dict with events and pagination info
        """
        org_id = organization_id or self.get_organization_id()
        if not org_id:
            return {'events': [], 'pagination': {}}

        params = {
            'organisation_id': org_id,
            'page': page,
            'per_page': page_size,
            'sort_field': sort_field,
            'sort_order': sort_order,
            'template': 'true' if template else 'false',
            'user_permission_group': ''
        }

        if date_from:
            # Format: YYYY-MM-DD HH:MM:SS
            if ' ' not in date_from:
                date_from = f'{date_from} 00:00:00'
            params['date_from'] = date_from
        if date_to:
            if ' ' not in date_to:
                date_to = f'{date_to} 23:59:59'
            params['date_to'] = date_to
        if gremium_id:
            params['gremium_id'] = gremium_id
        if has_future_broadcast is not None:
            params['has_future_broadcast'] = 'true' if has_future_broadcast else 'false'
        if is_not_canceled is not None:
            params['is_not_canceled'] = 'true' if is_not_canceled else 'false'

        # Use global events endpoint (not organisation-specific) for better compatibility
        response = self._request('/events', params)
        if response and 'events' in response:
            events_data = response['events']
            # Handle nested structure: {'events': {'event': [...], '@attributes': {...}}}
            if isinstance(events_data, dict) and 'event' in events_data:
                events_list = events_data['event']
                # Ensure it's a list (single item might not be a list)
                if not isinstance(events_list, list):
                    events_list = [events_list]
                return {
                    'events': events_list,
                    'pagination': events_data.get('@attributes', {})
                }
            # Handle direct list
            elif isinstance(events_data, list):
                return {
                    'events': events_data,
                    'pagination': response.get('pagination', {})
                }
        return {'events': [], 'pagination': {}}

    def get_all_events(
        self,
        date_from: str = None,
        date_to: str = None,
        gremium_id: str = None
    ) -> List[Dict]:
        """Get all events with pagination handling."""
        all_events = []
        page = 1

        while True:
            result = self.get_events(
                date_from=date_from,
                date_to=date_to,
                gremium_id=gremium_id,
                page=page
            )

            events = result.get('events', [])
            if not events:
                break

            all_events.extend(events)
            pagination = result.get('pagination', {})

            # Support both 'pages' and 'total_pages' keys
            total_pages = pagination.get('total_pages') or pagination.get('pages', 1)
            has_more = pagination.get('has_more_pages', False)

            if page >= total_pages and not has_more:
                break

            page += 1

        logger.info(f'Fetched {len(all_events)} events')
        return all_events

    def get_meeting(self, meeting_id: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Get detailed meeting information.

        Args:
            meeting_id: Notubiz meeting ID
            use_cache: Use cached data if available

        Returns:
            Meeting details including agenda items and documents
        """
        response = self._request(f'/events/meetings/{meeting_id}', use_cache=use_cache)
        if response and 'meeting' in response:
            return response['meeting']
        return None

    def get_document_url(self, document: Dict) -> Optional[str]:
        """Extract download URL from document object."""
        # Notubiz documents have different structures
        if 'url' in document:
            return document['url']
        if 'links' in document:
            for link in document.get('links', []):
                if link.get('rel') == 'download':
                    return link.get('href')
        if 'media' in document:
            media = document['media']
            if isinstance(media, dict) and 'url' in media:
                return media['url']
        return None

    def get_meetings_by_ids(
        self,
        meeting_ids: List[str],
        use_cache: bool = True
    ) -> List[Dict]:
        """
        Get meeting details by IDs using v3.53.0 API.

        This endpoint works WITHOUT any token and returns full meeting details
        including agenda items and documents for historical meetings!

        Args:
            meeting_ids: List of Notubiz meeting/event IDs
            use_cache: Use cache for responses

        Returns:
            List of meeting dicts with full details
        """
        if not meeting_ids:
            return []

        # Build URL with multiple meeting_ids[] params
        url = f"{self.base_url}/events/meetings/"
        params = {
            'version': '3.53.0',
            'format': 'json',
        }

        # Check cache
        cache_key = f"meetings_by_ids_{','.join(sorted(meeting_ids))}"
        if use_cache:
            cache_path = self.cache_dir / f"{cache_key}.json"
            if self._is_cache_valid(cache_path):
                cached = self._read_cache(cache_path)
                if cached:
                    return cached.get('meetings', [])

        try:
            # requests handles list params with same key
            response = requests.get(
                url,
                params={**params, 'meeting_ids[]': meeting_ids},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            meetings = data.get('meetings', [])

            # Cache response
            if use_cache:
                cache_path = self.cache_dir / f"{cache_key}.json"
                self._write_cache(cache_path, {'meetings': meetings})

            logger.info(f'Fetched {len(meetings)} meetings by ID')
            return meetings
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to fetch meetings by ID: {e}')
            return []

    def get_historical_events(
        self,
        organization_id: str = None,
        date_from: str = None,
        date_to: str = None,
        gremium_id: str = None,
        page: int = 1,
        page_size: int = 50
    ) -> Dict:
        """
        Get historical events using authenticated access.

        This endpoint requires auth token for accessing past meetings.
        Falls back to regular get_events if no auth token available.
        """
        if not self.has_auth_token():
            logger.warning(
                'No auth token - historical events may be limited to upcoming'
            )
            return self.get_events(
                organization_id, date_from, date_to, gremium_id, page, page_size
            )

        org_id = organization_id or self.get_organization_id()
        if not org_id:
            return {'events': [], 'pagination': {}}

        params = {
            'page': page,
            'pagesize': page_size
        }

        if date_from:
            params['date_from'] = date_from
        if date_to:
            params['date_to'] = date_to
        if gremium_id:
            params['gremium_id'] = gremium_id

        response = self._request(
            f'/organisations/{org_id}/events',
            params,
            use_auth=True
        )
        if response and 'events' in response:
            events_data = response['events']
            if isinstance(events_data, dict) and 'event' in events_data:
                events_list = events_data['event']
                if not isinstance(events_list, list):
                    events_list = [events_list]
                return {
                    'events': events_list,
                    'pagination': events_data.get('@attributes', {})
                }
            elif isinstance(events_data, list):
                return {
                    'events': events_data,
                    'pagination': response.get('pagination', {})
                }
        return {'events': [], 'pagination': {}}

    def get_all_historical_events(
        self,
        date_from: str = None,
        date_to: str = None,
        gremium_id: str = None
    ) -> List[Dict]:
        """Get all historical events with pagination handling."""
        all_events = []
        page = 1

        while True:
            result = self.get_historical_events(
                date_from=date_from,
                date_to=date_to,
                gremium_id=gremium_id,
                page=page
            )

            events = result.get('events', [])
            if not events:
                break

            all_events.extend(events)
            pagination = result.get('pagination', {})

            # Support both 'pages' and 'total_pages' keys
            total_pages = pagination.get('total_pages') or pagination.get('pages', 1)
            has_more = pagination.get('has_more_pages', False)

            if page >= total_pages and not has_more:
                break

            page += 1

        logger.info(f'Fetched {len(all_events)} historical events')
        return all_events

    def download_document(
        self,
        document_id: str,
        use_auth: bool = True
    ) -> Optional[bytes]:
        """
        Download document content directly from Notubiz.

        Note: Document downloads work with the public token as Bearer header!
        No special auth token needed for document access.

        Args:
            document_id: Notubiz document ID
            use_auth: Use Bearer auth (works with public token)

        Returns:
            Document content as bytes, or None if failed
        """
        url = f"{self.base_url}/document/{document_id}/1"
        # Public token works as Bearer for document downloads!
        headers = {'Authorization': f'Bearer {self.token}'} if use_auth else {}

        try:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            logger.debug(f'Downloaded document {document_id}: {len(response.content)} bytes')
            return response.content
        except requests.exceptions.RequestException as e:
            logger.error(f'Document download failed {document_id}: {e}')
            return None

    def get_media(self, event_ids: List[str], use_cache: bool = True) -> List[Dict]:
        """
        Get media (video/audio) information for events.

        This is important for getting video URLs for transcription!

        Args:
            event_ids: List of event/meeting IDs
            use_cache: Use cache for responses

        Returns:
            List of media objects with video URLs
        """
        if not event_ids:
            return []

        url = f"{self.base_url}/media"
        params = {
            'version': '3.72.0',
            'lang': 'nl-nl',
            'format': 'json'
        }

        # Check cache
        cache_key = f"media_{','.join(sorted(event_ids))}"
        if use_cache:
            cache_path = self.cache_dir / f"{cache_key}.json"
            if self._is_cache_valid(cache_path):
                cached = self._read_cache(cache_path)
                if cached:
                    return cached.get('media', [])

        try:
            response = requests.get(
                url,
                params={**params, 'event_id[]': event_ids},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            media_list = data.get('media', [])

            # Cache response
            if use_cache:
                cache_path = self.cache_dir / f"{cache_key}.json"
                self._write_cache(cache_path, {'media': media_list})

            logger.info(f'Fetched media for {len(event_ids)} events: {len(media_list)} items')
            return media_list
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to fetch media: {e}')
            return []

    def get_encoder_plannings(self, event_id: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Get encoder/broadcast planning for an event.

        Useful for finding live stream schedules.

        Args:
            event_id: Event/meeting ID
            use_cache: Use cache for responses

        Returns:
            Encoder planning info or None
        """
        params = {
            'format': 'json',
            'version': '2.1.15',
            'lang': 'nl-nl',
            'event_id': event_id
        }

        response = self._request('/media/encoder_plannings', params, use_cache=use_cache)
        return response

    def get_module_items(
        self,
        item_ids: List[str],
        organization_id: str = None,
        use_cache: bool = True
    ) -> List[Dict]:
        """
        Get module items by IDs.

        Args:
            item_ids: List of item IDs
            organization_id: Organization ID
            use_cache: Use cache

        Returns:
            List of module items
        """
        if not item_ids:
            return []

        org_id = organization_id or self.get_organization_id()

        url = f"{self.base_url}/modules/0/items/"
        params = {
            'version': '3.56.0',
            'lang': 'nl-nl',
            'format': 'json',
            'organisation': org_id
        }

        # Check cache
        cache_key = f"module_items_{','.join(sorted(item_ids))}"
        if use_cache:
            cache_path = self.cache_dir / f"{cache_key}.json"
            if self._is_cache_valid(cache_path):
                cached = self._read_cache(cache_path)
                if cached:
                    return cached.get('items', [])

        try:
            response = requests.get(
                url,
                params={**params, 'ids[]': item_ids},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            items = data.get('items', [])

            # Cache response
            if use_cache:
                cache_path = self.cache_dir / f"{cache_key}.json"
                self._write_cache(cache_path, {'items': items})

            return items
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to fetch module items: {e}')
            return []

    def get_organization_details(self, organization_id: str = None) -> Optional[Dict]:
        """
        Get detailed organization information.

        Args:
            organization_id: Organization ID

        Returns:
            Organization details
        """
        org_id = organization_id or self.get_organization_id()
        if not org_id:
            return None

        response = self._request(f'/organisations/{org_id}')
        if response and 'organisation' in response:
            return response['organisation']
        return response

    def get_dashboard_settings(self, organization_id: str = None) -> Optional[Dict]:
        """
        Get organization dashboard settings.

        Args:
            organization_id: Organization ID

        Returns:
            Dashboard settings
        """
        org_id = organization_id or self.get_organization_id()
        if not org_id:
            return None

        return self._request(f'/organisations/{org_id}/dashboard_settings')

    def get_entity_type_settings(
        self,
        organization_id: str = None,
        entity_types: List[str] = None
    ) -> Optional[Dict]:
        """
        Get entity type settings for organization.

        Args:
            organization_id: Organization ID
            entity_types: List of entity types (e.g., ['events'])

        Returns:
            Entity type settings
        """
        org_id = organization_id or self.get_organization_id()
        if not org_id:
            return None

        params = {
            'default_field_values': 'true'
        }

        if entity_types:
            for i, et in enumerate(entity_types):
                params[f'entity_types[{i}]'] = et

        return self._request(f'/organisations/{org_id}/entity_type_settings', params)

    def get_organization_image_url(
        self,
        image_type: str = 'organisationLogo',
        organization_id: str = None,
        size: str = '200x200'
    ) -> str:
        """
        Get URL for organization image.

        Args:
            image_type: 'organisationLogo' or 'dashboardheader'
            organization_id: Organization ID
            size: Image size (e.g., '200x200', '3000x64', '2000x320')

        Returns:
            Image URL on assets.notubiz.nl
        """
        org_id = organization_id or self.get_organization_id()
        base = 'https://assets.notubiz.nl'
        return f'{base}/organisation/{org_id}/user-images/{image_type}?size={size}'

    def get_upcoming_broadcasts(self, limit: int = 10) -> List[Dict]:
        """
        Get upcoming events with live broadcasts.

        Returns:
            List of events with future broadcasts
        """
        from datetime import date, timedelta
        today = date.today()
        future = today + timedelta(days=30)

        result = self.get_events(
            date_from=today.isoformat(),
            date_to=future.isoformat(),
            has_future_broadcast=True,
            is_not_canceled=True,
            sort_order='ASC',
            page_size=limit
        )
        return result.get('events', [])

    def get_video_url_for_meeting(self, meeting_id: str) -> Optional[str]:
        """
        Get video/stream URL for a meeting.

        Args:
            meeting_id: Meeting/event ID

        Returns:
            Video URL if available
        """
        media_list = self.get_media([meeting_id])
        for media in media_list:
            # Look for video URL in media object
            if 'video_url' in media:
                return media['video_url']
            if 'stream_url' in media:
                return media['stream_url']
            if 'url' in media:
                return media['url']
            # Check nested structures
            if 'media' in media and isinstance(media['media'], dict):
                nested = media['media']
                for key in ['video_url', 'stream_url', 'url']:
                    if key in nested:
                        return nested[key]
        return None

    def get_auth_status(self) -> Dict:
        """Get status of authentication configuration."""
        return {
            'has_auth_token': self.has_auth_token(),
            'can_access_historical_via_search': True,  # Via raadsinformatie.nl + v3.53.0 API
            'can_access_historical_direct': self.has_auth_token(),  # Direct listing
            'can_download_documents': True,  # Works with public token as Bearer!
            'can_get_media': True,  # Video/audio URLs
            'api_url': self.base_url,
            'api_version': self.version,
            'organization_id': self.get_organization_id(),
            'note': 'Historical data accessible via raadsinformatie.nl search + v3.53.0 API. '
                    'Document downloads work with public token as Bearer. '
                    'Media endpoints available for video/stream URLs.'
        }

    def clear_cache(self):
        """Clear all cached API responses."""
        count = 0
        for cache_file in self.cache_dir.glob('*.json'):
            try:
                cache_file.unlink()
                count += 1
            except Exception as e:
                logger.warning(f'Failed to delete cache file: {e}')
        logger.info(f'Cleared {count} cache files')
        return count

    def cleanup_expired_cache(self) -> int:
        """
        Remove expired cache files to free disk space.

        Returns:
            Number of files deleted
        """
        count = 0
        total_size = 0
        for cache_file in self.cache_dir.glob('*.json'):
            try:
                if not self._is_cache_valid(cache_file):
                    size = cache_file.stat().st_size
                    cache_file.unlink()
                    count += 1
                    total_size += size
            except Exception as e:
                logger.warning(f'Failed to cleanup cache file: {e}')

        if count > 0:
            logger.info(f'Cleaned up {count} expired cache files ({total_size / 1024:.1f} KB)')
        return count


# Singleton instance
_client_instance = None


def get_notubiz_client() -> NotubizClient:
    """Get singleton Notubiz client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = NotubizClient()
    return _client_instance


if __name__ == '__main__':
    # Test the client
    client = get_notubiz_client()

    print("Finding Baarn organization...")
    org_id = client.get_organization_id()
    print(f"Organization ID: {org_id}")

    print("\nGetting gremia...")
    gremia = client.get_gremia()
    for g in gremia[:5]:
        print(f"  - {g.get('name')} (ID: {g.get('id')})")

    print("\nGetting recent events...")
    from datetime import date
    today = date.today()
    last_month = today - timedelta(days=30)

    result = client.get_events(
        date_from=last_month.isoformat(),
        date_to=today.isoformat()
    )
    for event in result['events'][:5]:
        print(f"  - {event.get('date')}: {event.get('title')}")
