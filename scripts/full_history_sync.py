#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Full History Sync Script

Synchroniseert ALLE historische data van Notubiz naar de lokale database.
Dit omvat vergaderingen en documenten vanaf 2010 tot nu.

Gebruik:
    python scripts/full_history_sync.py [--start-date 2010-01-01] [--download-docs] [--index-docs]

Dit kan lang duren afhankelijk van de hoeveelheid data!
"""

import sys
import argparse
from pathlib import Path
from datetime import date

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import get_database
from core.document_index import get_document_index
from providers.meeting_provider import get_meeting_provider
from providers.document_provider import get_document_provider
from shared.logging_config import get_logger

logger = get_logger('full-history-sync')


def full_history_sync(
    start_date: str = '2010-01-01',
    download_docs: bool = True,
    index_docs: bool = False
):
    """
    Perform full historical sync.

    Args:
        start_date: Start date for sync (YYYY-MM-DD)
        download_docs: Download PDF documents
        index_docs: Index documents for semantic search
    """
    meeting_provider = get_meeting_provider()
    doc_provider = get_document_provider()

    end_date = date.today().isoformat()

    print("=" * 60)
    print("FULL HISTORY SYNC")
    print("=" * 60)
    print(f"Date range: {start_date} to {end_date}")
    print(f"Download documents: {download_docs}")
    print(f"Index documents: {index_docs}")
    print("=" * 60)
    print()

    # Step 1: Sync gremia
    print("Step 1/4: Syncing gremia (commissies)...")
    gremia_count = meeting_provider.sync_gremia()
    print(f"  -> {gremia_count} gremia synced")
    print()

    # Step 2: Sync meetings
    print(f"Step 2/4: Syncing meetings from {start_date}...")
    print("  This may take several minutes...")
    meetings, docs = meeting_provider.sync_meetings(
        date_from=start_date,
        date_to=end_date,
        full_details=True
    )
    print(f"  -> {meetings} meetings synced")
    print(f"  -> {docs} documents found")
    print()

    # Step 3: Download documents
    if download_docs:
        print("Step 3/4: Downloading documents...")
        print("  This may take a while for large archives...")
        success, failed = doc_provider.download_pending_documents()
        print(f"  -> {success} documents downloaded")
        if failed > 0:
            print(f"  -> {failed} downloads failed")

        print("  Extracting text from PDFs...")
        doc_provider.extract_all_text()
        print("  -> Text extraction complete")
    else:
        print("Step 3/4: Skipping document download")
    print()

    # Step 4: Index documents
    if index_docs:
        print("Step 4/4: Indexing documents for semantic search...")
        index = get_document_index()
        indexed, chunks = index.index_all_documents()
        print(f"  -> {indexed} documents indexed")
        print(f"  -> {chunks} text chunks created")
    else:
        print("Step 4/4: Skipping document indexing")
    print()

    # Summary
    db = get_database()
    stats = db.get_statistics()

    print("=" * 60)
    print("SYNC COMPLETE")
    print("=" * 60)
    print(f"Total meetings in database: {stats.get('meetings', 0)}")
    print(f"Total documents in database: {stats.get('documents', 0)}")
    print(f"Total agenda items: {stats.get('agenda_items', 0)}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Synchronize all historical data from Notubiz'
    )
    parser.add_argument(
        '--start-date',
        default='2010-01-01',
        help='Start date for sync (YYYY-MM-DD, default: 2010-01-01)'
    )
    parser.add_argument(
        '--download-docs',
        action='store_true',
        default=True,
        help='Download PDF documents (default: True)'
    )
    parser.add_argument(
        '--no-download-docs',
        action='store_true',
        help='Skip document download'
    )
    parser.add_argument(
        '--index-docs',
        action='store_true',
        help='Index documents for semantic search'
    )

    args = parser.parse_args()

    download = args.download_docs and not args.no_download_docs

    full_history_sync(
        start_date=args.start_date,
        download_docs=download,
        index_docs=args.index_docs
    )


if __name__ == '__main__':
    main()
