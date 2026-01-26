#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parallel document download script for faster processing.
Uses ThreadPoolExecutor for concurrent downloads.
"""

import sys
import warnings
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time

# Suppress PDF warnings
warnings.filterwarnings('ignore', category=UserWarning)
logging.getLogger('pdfplumber').setLevel(logging.ERROR)
logging.getLogger('pdfminer').setLevel(logging.ERROR)

# Add parent directory to path
sys.path.insert(0, str(__file__).replace('\\scripts\\parallel_download.py', '').replace('/scripts/parallel_download.py', ''))

from core.database import get_database
from providers.document_provider import DocumentProvider


def download_single_document(doc_id: int) -> tuple:
    """Download a single document. Returns (doc_id, success)."""
    try:
        provider = DocumentProvider()
        success = provider.download_document(doc_id)
        return (doc_id, success)
    except Exception as e:
        return (doc_id, False)


def main():
    """Main function to run parallel downloads."""
    db = get_database()

    # Configuration
    MAX_WORKERS = 8  # Number of parallel downloads
    BATCH_SIZE = 100  # Documents per batch
    REPORT_INTERVAL = 10  # Report progress every N documents

    print("=" * 60)
    print("PARALLEL DOCUMENT DOWNLOAD")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Workers: {MAX_WORKERS}, Batch size: {BATCH_SIZE}")
    print("=" * 60)
    print()

    total_downloaded = 0
    total_failed = 0
    batch_num = 0
    start_time = time.time()

    while True:
        # Get pending documents
        pending = db.get_documents_pending_download()
        if not pending:
            print("No more pending documents!")
            break

        batch_num += 1
        batch = pending[:BATCH_SIZE]
        batch_start = time.time()

        print(f"Batch {batch_num}: Processing {len(batch)} documents...")

        batch_success = 0
        batch_failed = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Submit all tasks
            futures = {
                executor.submit(download_single_document, doc['id']): doc['id']
                for doc in batch
            }

            # Process completed tasks
            for i, future in enumerate(as_completed(futures)):
                doc_id = futures[future]
                try:
                    _, success = future.result()
                    if success:
                        batch_success += 1
                    else:
                        batch_failed += 1
                except Exception:
                    batch_failed += 1

                # Progress report
                if (i + 1) % REPORT_INTERVAL == 0:
                    elapsed = time.time() - batch_start
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    print(f"  Progress: {i + 1}/{len(batch)} ({rate:.1f} docs/sec)")

        batch_elapsed = time.time() - batch_start
        total_downloaded += batch_success
        total_failed += batch_failed

        # Get updated stats
        stats = db.get_statistics()
        doc_stats = stats.get('documents_by_status', {})
        stored = doc_stats.get('stored', 0) + doc_stats.get('text_extracted', 0)
        pending_count = doc_stats.get('pending', 0)
        total = sum(doc_stats.values())
        pct = stored / total * 100 if total > 0 else 0

        print(f"  Batch complete: +{batch_success} downloaded, {batch_failed} failed ({batch_elapsed:.0f}s)")
        print(f"  Overall: {stored}/{total} ({pct:.1f}%) | Pending: {pending_count}")
        print()

        # Stop if all done
        if pending_count == 0:
            break

    # Final summary
    total_time = time.time() - start_time
    print("=" * 60)
    print("DOWNLOAD COMPLETE")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total time: {total_time / 60:.1f} minutes")
    print(f"Downloaded: {total_downloaded}")
    print(f"Failed: {total_failed}")
    print(f"Average rate: {total_downloaded / total_time:.2f} docs/sec")
    print("=" * 60)

    # Final status
    stats = db.get_statistics()
    doc_stats = stats.get('documents_by_status', {})
    print()
    print("Final document status:")
    for status, count in sorted(doc_stats.items()):
        print(f"  {status}: {count}")


if __name__ == '__main__':
    main()
