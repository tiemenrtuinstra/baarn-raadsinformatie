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
        self.version = Config.NOTUBIZ_API_VERSION
        self.cache_dir = Config.CACHE_DIR
        self.cache_ttl = timedelta(hours=Config.CACHE_TTL_HOURS)
        self._organization_id = None

        logger.info(f'NotubizClient initialized: {self.base_url}')

    def _get_default_params(self) -> Dict:
        """Get default parameters for API requests."""
        return {
            'format': 'json',
            'version': self.version,
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
        use_cache: bool = True
    ) -> Optional[Dict]:
        """Make API request with optional caching."""
        full_params = self._get_default_params()
        if params:
            full_params.update(params)

        # Check cache
        if use_cache:
            cache_path = self._get_cache_path(endpoint, full_params)
            if self._is_cache_valid(cache_path):
                cached = self._read_cache(cache_path)
                if cached:
                    logger.debug(f'Cache hit: {endpoint}')
                    return cached

        # Make request
        url = f"{self.base_url}{endpoint}"
        logger.debug(f'API request: {url}')

        try:
            response = requests.get(url, params=full_params, timeout=30)
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
        if Config.NOTUBIZ_ORGANIZATION_ID:
            self._organization_id = Config.NOTUBIZ_ORGANIZATION_ID
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
        page_size: int = 50
    ) -> Dict:
        """
        Get events (meetings) for an organization.

        Args:
            organization_id: Organization ID (default: Baarn)
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            gremium_id: Filter by gremium
            page: Page number
            page_size: Items per page

        Returns:
            Dict with events and pagination info
        """
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

        # Use organisation-specific endpoint
        response = self._request(f'/organisations/{org_id}/events', params)
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

            if page >= pagination.get('pages', 1):
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
