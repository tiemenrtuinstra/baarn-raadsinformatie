#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baarn Raadsinformatie - Background Sync Service

Draait als achtergrond service (Docker of Windows Service) en houdt
de data automatisch up-to-date door periodiek te synchroniseren.

Kan draaien naast de MCP server (die on-demand door Claude Desktop wordt gestart).
"""

import time
import signal
import sys
from datetime import datetime, timedelta, date
from typing import Optional

from core.config import Config
from core.database import get_database
from core.document_index import get_document_index
from providers.meeting_provider import get_meeting_provider
from providers.document_provider import get_document_provider
from shared.logging_config import get_logger

logger = get_logger('sync-service')

# Sync interval in seconds (default: 6 hours)
SYNC_INTERVAL = int(60 * 60 * 6)

# Global flag for graceful shutdown
_running = True


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global _running
    logger.info(f'Received signal {signum}, shutting down...')
    _running = False


def perform_sync(full_sync: bool = False) -> dict:
    """
    Perform data synchronization.

    Args:
        full_sync: If True, sync all data. If False, only recent changes.

    Returns:
        Dict with sync results
    """
    results = {
        'timestamp': datetime.now().isoformat(),
        'gremia': 0,
        'meetings': 0,
        'documents_found': 0,
        'documents_downloaded': 0,
        'documents_indexed': 0,
        'errors': []
    }

    meeting_provider = get_meeting_provider()
    doc_provider = get_document_provider()

    try:
        # Sync gremia
        logger.info('Syncing gremia...')
        results['gremia'] = meeting_provider.sync_gremia()

        # Determine date range
        if full_sync:
            if Config.FULL_HISTORY_SYNC:
                # Sync all historical data from configured start date
                date_from = Config.FULL_HISTORY_START
                logger.info(f'FULL HISTORY SYNC enabled - syncing from {date_from}')
            else:
                date_from = (date.today() - timedelta(days=Config.AUTO_SYNC_DAYS)).isoformat()
        else:
            # Only last 30 days for incremental sync
            date_from = (date.today() - timedelta(days=30)).isoformat()

        date_to = date.today().isoformat()

        # Sync meetings
        logger.info(f'Syncing meetings from {date_from} to {date_to}...')
        meetings, docs = meeting_provider.sync_meetings(
            date_from=date_from,
            date_to=date_to,
            full_details=True
        )
        results['meetings'] = meetings
        results['documents_found'] = docs

        # Download documents
        if Config.AUTO_DOWNLOAD_DOCS:
            logger.info('Downloading pending documents...')
            success, failed = doc_provider.download_pending_documents()
            results['documents_downloaded'] = success
            if failed > 0:
                results['errors'].append(f'{failed} document downloads failed')

            # Extract text
            doc_provider.extract_all_text()

        # Index documents
        if Config.AUTO_INDEX_DOCS:
            logger.info('Indexing documents...')
            index = get_document_index()
            indexed, chunks = index.index_all_documents()
            results['documents_indexed'] = indexed

        logger.info(f'Sync completed: {meetings} meetings, {docs} documents found')

    except Exception as e:
        logger.error(f'Sync error: {e}')
        results['errors'].append(str(e))

    return results


def check_initial_sync_needed() -> bool:
    """Check if initial full sync is needed."""
    db = get_database()
    stats = db.get_statistics()
    return stats.get('meetings', 0) == 0


def run_service():
    """Run the sync service loop."""
    global _running

    logger.info('=' * 60)
    logger.info('Baarn Raadsinformatie Sync Service starting...')
    logger.info(f'Sync interval: {SYNC_INTERVAL} seconds ({SYNC_INTERVAL / 3600:.1f} hours)')
    logger.info(f'Auto download docs: {Config.AUTO_DOWNLOAD_DOCS}')
    logger.info(f'Auto index docs: {Config.AUTO_INDEX_DOCS}')
    logger.info('=' * 60)

    # Initial sync if database is empty
    if check_initial_sync_needed():
        logger.info('Database empty - performing initial full sync...')
        results = perform_sync(full_sync=True)
        logger.info(f'Initial sync results: {results}')
    else:
        logger.info('Database has data - performing incremental sync...')
        results = perform_sync(full_sync=False)
        logger.info(f'Incremental sync results: {results}')

    last_sync = datetime.now()

    # Main service loop
    while _running:
        try:
            # Check if it's time for next sync
            elapsed = (datetime.now() - last_sync).total_seconds()

            if elapsed >= SYNC_INTERVAL:
                logger.info('Starting scheduled sync...')
                results = perform_sync(full_sync=False)
                logger.info(f'Scheduled sync results: {results}')
                last_sync = datetime.now()

            # Sleep for a bit before checking again
            time.sleep(60)  # Check every minute

        except KeyboardInterrupt:
            logger.info('Keyboard interrupt received')
            _running = False
        except Exception as e:
            logger.error(f'Service loop error: {e}')
            time.sleep(300)  # Wait 5 minutes before retrying

    logger.info('Sync service stopped')


def main():
    """Main entry point."""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if sys.platform == 'win32':
        # Windows-specific signal handling
        signal.signal(signal.SIGBREAK, signal_handler)

    run_service()


if __name__ == '__main__':
    main()
