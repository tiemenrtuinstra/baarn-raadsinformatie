#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document Index voor Baarn Politiek MCP Server.
Semantisch zoeken met embeddings (sentence-transformers).
"""

import json
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from .config import Config
from .database import Database, get_database
from shared.logging_config import get_logger, LogContext

logger = get_logger('document-index')

# Embeddings support
EMBEDDINGS_AVAILABLE = False
model = None

if Config.EMBEDDINGS_ENABLED:
    try:
        from sentence_transformers import SentenceTransformer
        EMBEDDINGS_AVAILABLE = True
        logger.info('Sentence transformers available')
    except ImportError:
        logger.warning(
            'sentence-transformers not installed. '
            'Install with: pip install sentence-transformers torch'
        )


@dataclass
class SearchResult:
    """Search result with similarity score."""
    document_id: int
    chunk_index: int
    chunk_text: str
    similarity: float
    document_title: str = ''
    meeting_date: str = ''


class DocumentIndex:
    """
    Semantische document index met embeddings.

    Gebruikt sentence-transformers voor Nederlands/meertalig.
    Slaat embeddings op in SQLite als BLOB.
    """

    def __init__(self, db: Database = None):
        """Initialize document index."""
        self.db = db or get_database()
        self.model = None
        self.model_name = Config.EMBEDDINGS_MODEL
        self.chunk_size = 500  # characters per chunk
        self.chunk_overlap = 50  # overlap between chunks

        logger.info(f'DocumentIndex initialized (embeddings: {EMBEDDINGS_AVAILABLE})')

    def _load_model(self):
        """Lazy load the embedding model."""
        global model

        if not EMBEDDINGS_AVAILABLE:
            raise RuntimeError('Embeddings not available - install sentence-transformers')

        if model is None:
            logger.info(f'Loading embedding model: {self.model_name}')
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(self.model_name)
            logger.info('Model loaded successfully')

        self.model = model

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks."""
        if not text:
            return []

        chunks = []
        text = text.strip()

        # Simple chunking by character count with overlap
        start = 0
        while start < len(text):
            end = start + self.chunk_size

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end in last 100 chars
                search_start = max(start + self.chunk_size - 100, start)
                for sep in ['. ', '.\n', '? ', '?\n', '! ', '!\n']:
                    pos = text.rfind(sep, search_start, end + 50)
                    if pos > search_start:
                        end = pos + 1
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - self.chunk_overlap

        return chunks

    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding vector for text."""
        self._load_model()
        return self.model.encode(text, convert_to_numpy=True)

    def _embedding_to_bytes(self, embedding: np.ndarray) -> bytes:
        """Convert embedding to bytes for storage."""
        return embedding.astype(np.float32).tobytes()

    def _bytes_to_embedding(self, data: bytes) -> np.ndarray:
        """Convert bytes back to embedding."""
        return np.frombuffer(data, dtype=np.float32)

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def index_document(self, document_id: int) -> int:
        """
        Index a document's text content.

        Args:
            document_id: Database ID of document

        Returns:
            Number of chunks indexed
        """
        if not EMBEDDINGS_AVAILABLE:
            logger.warning('Embeddings not available - skipping indexing')
            return 0

        doc = self.db.get_document(document_id)
        if not doc:
            logger.warning(f'Document not found: {document_id}')
            return 0

        text = doc.get('text_content')
        if not text:
            logger.debug(f'No text content for document {document_id}')
            return 0

        with LogContext(logger, 'index_document', document_id=document_id):
            # Remove existing embeddings
            self._delete_document_embeddings(document_id)

            # Chunk text
            chunks = self._chunk_text(text)
            if not chunks:
                return 0

            # Generate and store embeddings
            for i, chunk in enumerate(chunks):
                embedding = self._get_embedding(chunk)
                self._store_embedding(document_id, i, chunk, embedding)

            logger.info(f'Indexed document {document_id}: {len(chunks)} chunks')
            return len(chunks)

    def _delete_document_embeddings(self, document_id: int):
        """Delete all embeddings for a document."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM embeddings WHERE document_id = ?', (document_id,))

    def _store_embedding(
        self,
        document_id: int,
        chunk_index: int,
        chunk_text: str,
        embedding: np.ndarray
    ):
        """Store embedding in database."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO embeddings (document_id, chunk_index, chunk_text, embedding, model)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                document_id,
                chunk_index,
                chunk_text,
                self._embedding_to_bytes(embedding),
                self.model_name
            ))

    def index_all_documents(self, reindex: bool = False) -> Tuple[int, int]:
        """
        Index all documents with text content.

        Args:
            reindex: Re-index documents that already have embeddings

        Returns:
            Tuple of (documents_indexed, chunks_created)
        """
        if not EMBEDDINGS_AVAILABLE:
            logger.warning('Embeddings not available')
            return 0, 0

        # Get documents with text content
        docs = self.db.get_documents(limit=10000)
        docs_with_text = [d for d in docs if d.get('text_content')]

        if not reindex:
            # Filter out already indexed documents
            indexed_ids = self._get_indexed_document_ids()
            docs_with_text = [d for d in docs_with_text if d['id'] not in indexed_ids]

        with LogContext(logger, 'index_all_documents', count=len(docs_with_text)):
            total_docs = 0
            total_chunks = 0

            for doc in docs_with_text:
                chunks = self.index_document(doc['id'])
                if chunks > 0:
                    total_docs += 1
                    total_chunks += chunks

            logger.info(f'Indexed {total_docs} documents, {total_chunks} chunks')
            return total_docs, total_chunks

    def _get_indexed_document_ids(self) -> set:
        """Get IDs of documents that have embeddings."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT document_id FROM embeddings')
            return {row[0] for row in cursor.fetchall()}

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        """
        Semantic search in indexed documents.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of SearchResult ordered by similarity
        """
        if not EMBEDDINGS_AVAILABLE:
            logger.warning('Embeddings not available - semantic search disabled')
            return []

        with LogContext(logger, 'semantic_search', query=query[:50]):
            # Get query embedding
            query_embedding = self._get_embedding(query)

            # Get all embeddings
            embeddings = self._get_all_embeddings()
            if not embeddings:
                return []

            # Calculate similarities
            results = []
            for emb_data in embeddings:
                doc_embedding = self._bytes_to_embedding(emb_data['embedding'])
                similarity = self._cosine_similarity(query_embedding, doc_embedding)

                results.append(SearchResult(
                    document_id=emb_data['document_id'],
                    chunk_index=emb_data['chunk_index'],
                    chunk_text=emb_data['chunk_text'],
                    similarity=similarity
                ))

            # Sort by similarity (descending)
            results.sort(key=lambda x: x.similarity, reverse=True)

            # Limit and enrich results
            top_results = results[:limit]
            self._enrich_results(top_results)

            return top_results

    def _get_all_embeddings(self) -> List[Dict]:
        """Get all embeddings from database."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT document_id, chunk_index, chunk_text, embedding
                FROM embeddings
            ''')
            return [
                {
                    'document_id': row[0],
                    'chunk_index': row[1],
                    'chunk_text': row[2],
                    'embedding': row[3]
                }
                for row in cursor.fetchall()
            ]

    def _enrich_results(self, results: List[SearchResult]):
        """Add document metadata to results."""
        for result in results:
            doc = self.db.get_document(result.document_id)
            if doc:
                result.document_title = doc.get('title', '')
                # Get meeting date
                if doc.get('meeting_id'):
                    meeting = self.db.get_meeting(meeting_id=doc['meeting_id'])
                    if meeting:
                        result.meeting_date = meeting.get('date', '')

    def get_index_stats(self) -> Dict:
        """Get indexing statistics."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) FROM embeddings')
            total_chunks = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(DISTINCT document_id) FROM embeddings')
            indexed_docs = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM documents WHERE text_content IS NOT NULL')
            docs_with_text = cursor.fetchone()[0]

        return {
            'embeddings_available': EMBEDDINGS_AVAILABLE,
            'model': self.model_name if EMBEDDINGS_AVAILABLE else None,
            'indexed_documents': indexed_docs,
            'total_chunks': total_chunks,
            'documents_with_text': docs_with_text,
            'documents_pending_indexing': docs_with_text - indexed_docs
        }


# Singleton instance
_index_instance = None


def get_document_index() -> DocumentIndex:
    """Get singleton document index instance."""
    global _index_instance
    if _index_instance is None:
        _index_instance = DocumentIndex()
    return _index_instance


if __name__ == '__main__':
    # Test the index
    index = get_document_index()

    print("Index stats:")
    stats = index.get_index_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    if EMBEDDINGS_AVAILABLE and stats['documents_with_text'] > 0:
        print("\nIndexing documents...")
        docs, chunks = index.index_all_documents()
        print(f"Indexed {docs} documents, {chunks} chunks")

        print("\nTesting search...")
        results = index.search("gemeenteraad besluit")
        for r in results[:3]:
            print(f"\n  [{r.similarity:.3f}] {r.document_title}")
            print(f"    {r.chunk_text[:100]}...")
