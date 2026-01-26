#!/usr/bin/env python3
"""Index documents for semantic search."""

import warnings
warnings.filterwarnings('ignore')
import logging
logging.getLogger('sentence_transformers').setLevel(logging.WARNING)

import sqlite3
import sys
import time

sys.path.insert(0, 'c:/xampp/htdocs/baarn-politiek-mcp')

from core.document_index import DocumentIndex
from core.database import Database

def main():
    # Use WAL mode for better concurrency
    db_path = 'c:/xampp/htdocs/baarn-politiek-mcp/data/baarn.db'
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=60000')
    conn.close()

    db = Database()
    index = DocumentIndex(db)

    # Get documents that need indexing
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title FROM documents
            WHERE text_content IS NOT NULL
            AND text_content != ''
            AND id NOT IN (SELECT DISTINCT document_id FROM embeddings)
        """)
        docs = cursor.fetchall()

    print(f'=== SEMANTIC SEARCH INDEXING ===')
    print(f'Documents to index: {len(docs)}')

    if len(docs) == 0:
        # Show current stats
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(DISTINCT document_id) FROM embeddings')
            indexed = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM embeddings')
            chunks = cursor.fetchone()[0]
        print(f'All documents with text are already indexed!')
        print(f'Total: {indexed} documents, {chunks} embeddings')
        return

    # Index in batches with progress
    max_docs = 500  # Limit for this run
    batch_size = 50
    start = time.time()
    total_indexed = 0
    total_chunks = 0
    errors = 0

    for batch_start in range(0, min(len(docs), max_docs), batch_size):
        batch = docs[batch_start:batch_start + batch_size]
        batch_chunks = 0

        for doc_id, title in batch:
            try:
                chunks = index.index_document(doc_id)
                batch_chunks += chunks
                total_indexed += 1
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f'  Error indexing {doc_id}: {str(e)[:50]}')

        total_chunks += batch_chunks
        elapsed = time.time() - start
        rate = total_indexed / elapsed if elapsed > 0 else 0
        remaining = min(max_docs, len(docs)) - total_indexed
        eta = remaining / rate if rate > 0 else 0

        print(f'Progress: {total_indexed}/{min(max_docs, len(docs))} | {total_chunks} chunks | {rate:.1f} docs/sec | ETA: {eta:.0f}s')

    elapsed = time.time() - start
    print()
    print(f'=== DONE ===')
    print(f'Indexed {total_indexed} documents with {total_chunks} chunks in {elapsed:.1f}s')
    if errors > 0:
        print(f'Errors: {errors}')

if __name__ == '__main__':
    main()
