#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search Analyzer voor Baarn Politiek MCP Server.
Combineert keyword en semantisch zoeken.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field

from core.database import get_database
from core.document_index import get_document_index, SearchResult
from providers.document_provider import get_document_provider
from shared.logging_config import get_logger

logger = get_logger('search-analyzer')


@dataclass
class CombinedSearchResult:
    """Combined search result from multiple sources."""
    document_id: int
    title: str
    score: float
    match_sources: List[str] = field(default_factory=list)
    excerpt: str = ''
    meeting_date: str = ''
    meeting_id: Optional[int] = None


class SearchAnalyzer:
    """
    Combineert verschillende zoekmethoden voor optimale resultaten.

    - Keyword search: Exacte matches in titel en inhoud
    - Semantic search: Betekenis-gebaseerd zoeken met embeddings
    """

    def __init__(self):
        """Initialize search analyzer."""
        self.db = get_database()
        self.doc_provider = get_document_provider()
        self.doc_index = get_document_index()
        logger.info('SearchAnalyzer initialized')

    def search(
        self,
        query: str,
        limit: int = 20,
        include_keyword: bool = True,
        include_semantic: bool = True,
        keyword_weight: float = 0.4,
        semantic_weight: float = 0.6
    ) -> List[CombinedSearchResult]:
        """
        Gecombineerde zoekfunctie.

        Args:
            query: Zoekvraag
            limit: Maximum aantal resultaten
            include_keyword: Include keyword search results
            include_semantic: Include semantic search results
            keyword_weight: Weight for keyword results (0-1)
            semantic_weight: Weight for semantic results (0-1)

        Returns:
            List of combined search results, sorted by score
        """
        results_map: Dict[int, CombinedSearchResult] = {}

        # Keyword search
        if include_keyword:
            keyword_results = self._keyword_search(query, limit * 2)
            for doc, score in keyword_results:
                doc_id = doc['id']
                if doc_id not in results_map:
                    results_map[doc_id] = CombinedSearchResult(
                        document_id=doc_id,
                        title=doc.get('title', ''),
                        score=0,
                        meeting_id=doc.get('meeting_id')
                    )
                results_map[doc_id].score += score * keyword_weight
                results_map[doc_id].match_sources.append('keyword')

        # Semantic search
        if include_semantic:
            semantic_results = self._semantic_search(query, limit * 2)
            for result in semantic_results:
                doc_id = result.document_id
                if doc_id not in results_map:
                    results_map[doc_id] = CombinedSearchResult(
                        document_id=doc_id,
                        title=result.document_title,
                        score=0,
                        meeting_date=result.meeting_date
                    )
                results_map[doc_id].score += result.similarity * semantic_weight
                results_map[doc_id].match_sources.append('semantic')
                if not results_map[doc_id].excerpt:
                    results_map[doc_id].excerpt = result.chunk_text[:200]

        # Sort by combined score
        sorted_results = sorted(
            results_map.values(),
            key=lambda x: x.score,
            reverse=True
        )

        return sorted_results[:limit]

    def _keyword_search(self, query: str, limit: int) -> List[tuple]:
        """
        Keyword search in documents.

        Returns list of (document, score) tuples.
        """
        docs = self.doc_provider.search_documents(query, limit)

        results = []
        query_lower = query.lower()

        for doc in docs:
            score = 0.0

            # Title match is worth more
            title = (doc.get('title') or '').lower()
            if query_lower in title:
                score += 0.6
                if title.startswith(query_lower):
                    score += 0.2

            # Content match
            content = (doc.get('text_content') or '').lower()
            if query_lower in content:
                # More occurrences = higher score (capped)
                count = content.count(query_lower)
                score += min(0.4, count * 0.05)

            if score > 0:
                results.append((doc, score))

        return sorted(results, key=lambda x: x[1], reverse=True)

    def _semantic_search(self, query: str, limit: int) -> List[SearchResult]:
        """Semantic search using embeddings."""
        try:
            return self.doc_index.search(query, limit)
        except Exception as e:
            logger.warning(f'Semantic search failed: {e}')
            return []

    def search_meetings(
        self,
        query: str,
        limit: int = 20,
        date_from: str = None,
        date_to: str = None
    ) -> List[Dict]:
        """
        Zoek in vergaderingen.

        Args:
            query: Zoekvraag
            limit: Maximum resultaten
            date_from: Start datum filter
            date_to: Eind datum filter

        Returns:
            List of matching meetings
        """
        meetings = self.db.get_meetings(
            search=query,
            limit=limit,
            date_from=date_from,
            date_to=date_to
        )

        # Add relevance info
        query_lower = query.lower()
        for meeting in meetings:
            meeting['match_in_title'] = query_lower in (meeting.get('title') or '').lower()
            meeting['match_in_description'] = query_lower in (meeting.get('description') or '').lower()

        return meetings

    def get_related_documents(
        self,
        document_id: int,
        limit: int = 5
    ) -> List[Dict]:
        """
        Vind gerelateerde documenten op basis van semantische gelijkenis.

        Args:
            document_id: Document om gerelateerde voor te vinden
            limit: Maximum aantal resultaten

        Returns:
            List of related documents
        """
        doc = self.db.get_document(document_id)
        if not doc or not doc.get('text_content'):
            return []

        # Use first part of document as query
        query_text = doc['text_content'][:500]

        results = self._semantic_search(query_text, limit + 1)

        # Filter out the source document
        related = [
            {
                'document_id': r.document_id,
                'title': r.document_title,
                'similarity': round(r.similarity, 3),
                'meeting_date': r.meeting_date
            }
            for r in results
            if r.document_id != document_id
        ]

        return related[:limit]


# Singleton instance
_analyzer_instance = None


def get_search_analyzer() -> SearchAnalyzer:
    """Get singleton search analyzer instance."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = SearchAnalyzer()
    return _analyzer_instance


if __name__ == '__main__':
    # Test the analyzer
    analyzer = get_search_analyzer()

    print("Testing combined search...")
    results = analyzer.search("gemeenteraad besluit", limit=5)

    for r in results:
        print(f"\n[{r.score:.3f}] {r.title}")
        print(f"  Sources: {', '.join(r.match_sources)}")
        if r.excerpt:
            print(f"  {r.excerpt[:100]}...")
