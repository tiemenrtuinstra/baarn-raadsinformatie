#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search & Sync Script

Zoekt naar een specifiek onderwerp in historische data en synchroniseert
alleen relevante vergaderingen en documenten.

Gebruik:
    python scripts/search_sync.py "Paleis Soestdijk"
    python scripts/search_sync.py "De Speeldoos" --start-date 2015-01-01
    python scripts/search_sync.py "woningbouw" --limit 50 --no-index

Dit is efficienter dan een volledige sync wanneer je zoekt naar specifieke dossiers.
"""

import sys
import argparse
from pathlib import Path
from datetime import date

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from providers.search_sync_provider import get_search_sync_provider
from shared.logging_config import get_logger

logger = get_logger('search-sync-cli')


def search_and_sync(
    query: str,
    start_date: str = '2010-01-01',
    end_date: str = None,
    download_docs: bool = True,
    index_docs: bool = True,
    limit: int = 100
):
    """
    Search for a topic and sync relevant meetings.

    Args:
        query: Search term (e.g. "Paleis Soestdijk")
        start_date: Start date for search (YYYY-MM-DD)
        end_date: End date (default: today)
        download_docs: Download PDF documents
        index_docs: Index documents for semantic search
        limit: Maximum meetings to sync
    """
    if not end_date:
        end_date = date.today().isoformat()

    print("=" * 60)
    print("SEARCH & SYNC")
    print("=" * 60)
    print(f"Zoekterm: {query}")
    print(f"Periode: {start_date} tot {end_date}")
    print(f"Max vergaderingen: {limit}")
    print(f"Download documenten: {download_docs}")
    print(f"Indexeer documenten: {index_docs}")
    print("=" * 60)
    print()

    provider = get_search_sync_provider()

    print(f"Zoeken naar '{query}' in historische data...")
    print()

    result = provider.search_and_sync(
        query=query,
        start_date=start_date,
        end_date=end_date,
        download_docs=download_docs,
        index_docs=index_docs,
        limit=limit
    )

    print()
    print("=" * 60)
    print("RESULTATEN")
    print("=" * 60)
    print(f"Vergaderingen gevonden: {result['meetings_found']}")
    print(f"Vergaderingen gesynchroniseerd: {result['meetings_synced']}")
    print(f"Documenten gevonden: {result['documents_found']}")
    print(f"Documenten gedownload: {result['documents_downloaded']}")
    print(f"Documenten geindexeerd: {result['documents_indexed']}")

    if result.get('errors'):
        print()
        print("Fouten:")
        for error in result['errors']:
            print(f"  - {error}")

    print("=" * 60)

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Search for a topic and sync relevant meetings from Notubiz',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Voorbeelden:
  python scripts/search_sync.py "Paleis Soestdijk"
  python scripts/search_sync.py "De Speeldoos" --start-date 2015-01-01
  python scripts/search_sync.py "woningbouw" --limit 50
  python scripts/search_sync.py "duurzaamheid" --no-index
        """
    )
    parser.add_argument(
        'query',
        help='Zoekterm (bijv. "Paleis Soestdijk", "De Speeldoos")'
    )
    parser.add_argument(
        '--start-date',
        default='2010-01-01',
        help='Start datum (YYYY-MM-DD, default: 2010-01-01)'
    )
    parser.add_argument(
        '--end-date',
        default=None,
        help='Eind datum (YYYY-MM-DD, default: vandaag)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum aantal vergaderingen (default: 100)'
    )
    parser.add_argument(
        '--no-download',
        action='store_true',
        help='Skip document download'
    )
    parser.add_argument(
        '--no-index',
        action='store_true',
        help='Skip document indexing'
    )

    args = parser.parse_args()

    search_and_sync(
        query=args.query,
        start_date=args.start_date,
        end_date=args.end_date,
        download_docs=not args.no_download,
        index_docs=not args.no_index,
        limit=args.limit
    )


if __name__ == '__main__':
    main()
