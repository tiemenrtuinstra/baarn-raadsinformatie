#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standpunt Provider for Baarn Raadsinformatie MCP Server.
Manages extraction, storage and analysis of political positions.
"""

import json
from datetime import date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from core.config import Config
from core.database import Database, get_database
from shared.logging_config import get_logger

logger = get_logger('standpunt-provider')


class Stance(Enum):
    """Possible stances on a position."""
    VOOR = 'voor'
    TEGEN = 'tegen'
    NEUTRAAL = 'neutraal'
    GENUANCEERD = 'genuanceerd'
    ONBEKEND = 'onbekend'


class SourceType(Enum):
    """Source types for standpunten."""
    VERKIEZINGSPROGRAMMA = 'verkiezingsprogramma'
    MOTIE = 'motie'
    AMENDEMENT = 'amendement'
    DEBAT = 'debat'
    STEMMING = 'stemming'
    RAADSVRAAG = 'raadsvraag'
    INTERVIEW = 'interview'
    PERSBERICHT = 'persbericht'
    COALITIEAKKOORD = 'coalitieakkoord'
    HANDMATIG = 'handmatig'


class ExtractionMethod(Enum):
    """Method of standpunt extraction."""
    AI = 'ai'
    MANUAL = 'manual'
    SEMI_AUTO = 'semi-auto'


@dataclass
class StandpuntExtraction:
    """Result of AI extraction."""
    topic: str
    subtopic: Optional[str]
    position_summary: str
    position_text: str
    stance: Stance
    stance_strength: int  # 1-5
    confidence: float  # 0.0-1.0
    source_quote: Optional[str]
    tags: List[str]


class StandpuntProvider:
    """Provider for standpunten of parties and council members."""

    # Predefined topics for Baarn
    DEFAULT_TOPICS = [
        {'name': 'Woningbouw', 'keywords': ['woning', 'huur', 'koop', 'bouw', 'sociale huur', 'starterswoningen']},
        {'name': 'Duurzaamheid', 'keywords': ['klimaat', 'energie', 'milieu', 'groen', 'CO2', 'duurzaam']},
        {'name': 'Mobiliteit', 'keywords': ['verkeer', 'fiets', 'auto', 'parkeren', 'OV', 'mobiliteit']},
        {'name': 'Zorg en Welzijn', 'keywords': ['zorg', 'WMO', 'ouderen', 'jeugd', 'welzijn', 'sociaal']},
        {'name': 'Economie', 'keywords': ['economie', 'ondernemers', 'winkel', 'bedrijven', 'werkgelegenheid']},
        {'name': 'Cultuur en Erfgoed', 'keywords': ['cultuur', 'erfgoed', 'monumenten', 'kunst', 'museum', 'Paleis Soestdijk']},
        {'name': 'Veiligheid', 'keywords': ['veiligheid', 'politie', 'handhaving', 'criminaliteit']},
        {'name': 'Financien', 'keywords': ['belasting', 'OZB', 'begroting', 'financien', 'bezuiniging']},
        {'name': 'Ruimtelijke Ordening', 'keywords': ['bestemmingsplan', 'omgevingsvisie', 'buitengebied']},
        {'name': 'Sport en Recreatie', 'keywords': ['sport', 'recreatie', 'vereniging', 'zwembad']},
    ]

    def __init__(self, db: Database = None):
        self.db = db or get_database()
        logger.info('StandpuntProvider initialised')

    # ==================== Raadsleden Management ====================

    def get_raadsleden(self, party_id: int = None, active_only: bool = True) -> List[Dict]:
        """Get council members."""
        return self.db.get_raadsleden(party_id=party_id, active_only=active_only)

    def get_raadslid(self, raadslid_id: int = None, name: str = None) -> Optional[Dict]:
        """Get specific council member."""
        return self.db.get_raadslid(raadslid_id=raadslid_id, name=name)

    def add_raadslid(self, name: str, party_id: int = None, party_name: str = None, **kwargs) -> Dict:
        """Add council member."""
        if party_name and not party_id:
            party = self.db.get_party(name=party_name)
            if party:
                party_id = party['id']

        raadslid_id = self.db.upsert_raadslid(name=name, party_id=party_id, **kwargs)
        return {
            'success': True,
            'raadslid_id': raadslid_id,
            'name': name,
            'party_id': party_id
        }

    # ==================== AI Extraction ====================

    def extract_standpunten_from_document(
        self,
        document_id: int,
        party_id: int = None,
        topics: List[str] = None,
        ai_model: str = 'claude'
    ) -> List[StandpuntExtraction]:
        """
        Extract standpunten from a document using AI.

        Args:
            document_id: ID of the document to analyse
            party_id: Party ID if known
            topics: Specific topics to search for (optional)
            ai_model: AI model to use

        Returns:
            List of extracted standpunten
        """
        # Get document content
        doc = self.db.get_document(document_id)
        if not doc or not doc.get('text_content'):
            logger.warning(f'Document {document_id} has no text content')
            return []

        text = doc['text_content']

        # Build extraction prompt
        prompt = self._build_extraction_prompt(text, topics)

        # Note: Actual AI extraction would require integration with LLM API
        # For now, return empty list - AI extraction to be implemented
        logger.info(f'AI extraction prepared for document {document_id} (implementation pending)')
        return []

    def extract_standpunten_from_text(
        self,
        text: str,
        party_id: int = None,
        topics: List[str] = None
    ) -> List[StandpuntExtraction]:
        """
        Extract standpunten from raw text.

        This is a placeholder for AI-based extraction.
        In production, this would call an LLM API.
        """
        # Placeholder implementation
        logger.info('Text-based standpunt extraction (implementation pending)')
        return []

    def _build_extraction_prompt(self, text: str, topics: List[str] = None) -> str:
        """Build prompt for AI extraction."""
        topics_str = ', '.join(topics) if topics else 'alle relevante politieke onderwerpen'

        return f"""Analyseer de volgende Nederlandse politieke tekst en extraheer standpunten.

TEKST:
{text[:10000]}

INSTRUCTIES:
1. Identificeer standpunten over: {topics_str}
2. Voor elk standpunt, bepaal:
   - Topic (onderwerp)
   - Standpunt samenvatting (max 200 woorden)
   - Positie: voor/tegen/neutraal/genuanceerd
   - Sterkte van positie (1-5)
   - Relevante citaten uit de tekst
3. Wees objectief en citeer letterlijk waar mogelijk
4. Geef confidence score (0.0-1.0) per standpunt

OUTPUT FORMAT (JSON):
{{
  "standpunten": [
    {{
      "topic": "...",
      "subtopic": "...",
      "position_summary": "...",
      "stance": "voor|tegen|neutraal|genuanceerd",
      "stance_strength": 1-5,
      "confidence": 0.0-1.0,
      "source_quote": "letterlijk citaat",
      "tags": ["tag1", "tag2"]
    }}
  ]
}}
"""

    # ==================== Manual Entry ====================

    def add_standpunt(
        self,
        topic: str,
        position_summary: str,
        party_id: int = None,
        raadslid_id: int = None,
        party_name: str = None,
        raadslid_name: str = None,
        stance: str = 'onbekend',
        stance_strength: int = 3,
        source_type: str = 'handmatig',
        source_document_id: int = None,
        source_meeting_id: int = None,
        position_date: str = None,
        **kwargs
    ) -> int:
        """
        Add standpunt manually.

        Args:
            topic: Subject
            position_summary: Short summary
            party_id/party_name: Party (one of these)
            raadslid_id/raadslid_name: Council member (one of these)
            stance: voor/tegen/neutraal/genuanceerd/onbekend
            ...

        Returns:
            ID of new standpunt
        """
        # Resolve party_name to party_id if needed
        if party_name and not party_id:
            party = self.db.get_party(name=party_name)
            if party:
                party_id = party['id']

        # Resolve raadslid_name to raadslid_id if needed
        if raadslid_name and not raadslid_id:
            raadslid = self.db.get_raadslid(name=raadslid_name)
            if raadslid:
                raadslid_id = raadslid['id']

        standpunt_id = self.db.add_standpunt(
            topic=topic,
            position_summary=position_summary,
            party_id=party_id,
            raadslid_id=raadslid_id,
            stance=stance,
            stance_strength=stance_strength,
            source_type=source_type,
            source_document_id=source_document_id,
            source_meeting_id=source_meeting_id,
            position_date=position_date or date.today().isoformat(),
            extraction_method='manual',
            **kwargs
        )
        return {
            'success': True,
            'standpunt_id': standpunt_id,
            'topic': topic,
            'stance': stance
        }

    def save_extracted_standpunten(
        self,
        extractions: List[StandpuntExtraction],
        party_id: int = None,
        raadslid_id: int = None,
        source_document_id: int = None,
        source_meeting_id: int = None,
        ai_model: str = None
    ) -> List[int]:
        """Save AI-extracted standpunten to database."""
        ids = []
        for extraction in extractions:
            standpunt_id = self.db.add_standpunt(
                topic=extraction.topic,
                subtopic=extraction.subtopic,
                position_summary=extraction.position_summary,
                position_text=extraction.position_text,
                stance=extraction.stance.value,
                stance_strength=extraction.stance_strength,
                party_id=party_id,
                raadslid_id=raadslid_id,
                source_document_id=source_document_id,
                source_meeting_id=source_meeting_id,
                source_quote=extraction.source_quote,
                extraction_method='ai',
                extraction_model=ai_model,
                confidence_score=extraction.confidence,
                tags=extraction.tags
            )
            ids.append(standpunt_id)
        return ids

    # ==================== Search & Query ====================

    def search_standpunten(
        self,
        query: str = None,
        party_id: int = None,
        party_name: str = None,
        raadslid_id: int = None,
        raadslid_name: str = None,
        topic: str = None,
        stance: str = None,
        date_from: str = None,
        date_to: str = None,
        verified_only: bool = False,
        limit: int = 50
    ) -> List[Dict]:
        """
        Search standpunten with various filters.
        """
        # Resolve party name to ID if needed
        if party_name and not party_id:
            party_obj = self.db.get_party(name=party_name)
            if party_obj:
                party_id = party_obj['id']

        # Resolve raadslid name to ID if needed
        if raadslid_name and not raadslid_id:
            raadslid_obj = self.db.get_raadslid(name=raadslid_name)
            if raadslid_obj:
                raadslid_id = raadslid_obj['id']

        standpunten = self.db.get_standpunten(
            party_id=party_id,
            raadslid_id=raadslid_id,
            topic=topic,
            stance=stance,
            date_from=date_from,
            date_to=date_to,
            verified_only=verified_only,
            limit=limit
        )

        # Apply text search if query provided
        if query:
            query_lower = query.lower()
            standpunten = [
                s for s in standpunten
                if query_lower in (s.get('position_summary', '') or '').lower()
                or query_lower in (s.get('position_text', '') or '').lower()
                or query_lower in (s.get('topic', '') or '').lower()
            ]

        return standpunten

    def compare_standpunten(
        self,
        topic: str,
        party_ids: List[int] = None,
        include_raadsleden: bool = False
    ) -> Dict:
        """
        Compare standpunten of different parties on a specific topic.

        Returns:
            {
                'topic': str,
                'parties': {
                    'VVD': {'stance': 'voor', 'summary': '...', 'standpunten': [...]},
                    'D66': {'stance': 'tegen', 'summary': '...', 'standpunten': [...]},
                }
                'summary': 'Overview of differences and similarities'
            }
        """
        result = {
            'topic': topic,
            'parties': {},
            'raadsleden': {} if include_raadsleden else None,
            'summary': None
        }

        # Get all parties or filter by IDs
        all_parties = self.db.get_parties(active_only=True)
        if party_ids:
            all_parties = [
                p for p in all_parties
                if p['id'] in party_ids
            ]

        for party in all_parties:
            standpunten = self.db.get_standpunten(
                party_id=party['id'],
                topic=topic,
                include_superseded=False
            )

            if standpunten:
                # Get most recent/confident standpunt
                primary = max(standpunten, key=lambda s: (
                    s.get('position_date') or '',
                    s.get('confidence_score') or 0
                ))

                result['parties'][party['name']] = {
                    'party_id': party['id'],
                    'abbreviation': party.get('abbreviation'),
                    'stance': primary.get('stance'),
                    'stance_strength': primary.get('stance_strength'),
                    'summary': primary.get('position_summary'),
                    'standpunten': standpunten
                }

        # Generate comparison summary
        result['summary'] = self._generate_comparison_summary(result)

        return result

    def get_standpunt_history(
        self,
        topic: str,
        party_id: int = None,
        raadslid_id: int = None
    ) -> List[Dict]:
        """
        Track historical development of standpunten.

        Returns:
            Chronological list of standpunten with evolution markers
        """
        return self.db.get_standpunt_history(
            party_id=party_id,
            raadslid_id=raadslid_id,
            topic=topic
        )

    def get_party_context(
        self,
        party_id: int = None,
        party_name: str = None,
        topics: List[str] = None,
        limit_per_topic: int = 3
    ) -> Dict:
        """
        Get party context for answering questions aligned with a party.

        Useful for: "Answer this question from VVD perspective"

        Returns:
            {
                'party': {...},
                'standpunten_by_topic': {
                    'Woningbouw': [...],
                    'Duurzaamheid': [...]
                },
                'recent_positions': [...],
                'key_themes': [...]
            }
        """
        party_obj = None
        if party_id:
            party_obj = self.db.get_party(party_id=party_id)
        elif party_name:
            party_obj = self.db.get_party(name=party_name)

        if not party_obj:
            return {'error': f'Party not found: {party_id or party_name}'}

        result = {
            'party': party_obj,
            'standpunten_by_topic': {},
            'recent_positions': [],
            'key_themes': []
        }

        # Get standpunten grouped by topic
        topics_to_query = topics or [t['name'] for t in self.DEFAULT_TOPICS]

        for topic in topics_to_query:
            standpunten = self.db.get_standpunten(
                party_id=party_obj['id'],
                topic=topic,
                include_superseded=False,
                limit=limit_per_topic
            )
            if standpunten:
                result['standpunten_by_topic'][topic] = standpunten

        # Get most recent positions across all topics
        result['recent_positions'] = self.db.get_standpunten(
            party_id=party_obj['id'],
            include_superseded=False,
            limit=10
        )

        # Determine key themes (topics with most/strongest positions)
        topic_counts = {}
        for topic, sps in result['standpunten_by_topic'].items():
            if sps:
                avg_strength = sum(s.get('stance_strength') or 3 for s in sps) / len(sps)
                topic_counts[topic] = {'count': len(sps), 'avg_strength': avg_strength}

        result['key_themes'] = sorted(
            topic_counts.items(),
            key=lambda x: (x[1]['count'], x[1]['avg_strength']),
            reverse=True
        )[:5]

        return result

    def _generate_comparison_summary(self, comparison: Dict) -> str:
        """Generate a summary of position comparison."""
        parties = comparison['parties']
        if not parties:
            return "Geen standpunten gevonden voor dit onderwerp."

        # Group by stance
        voor = [p for p, d in parties.items() if d.get('stance') == 'voor']
        tegen = [p for p, d in parties.items() if d.get('stance') == 'tegen']
        neutraal = [p for p, d in parties.items() if d.get('stance') in ('neutraal', 'genuanceerd')]

        parts = []
        if voor:
            parts.append(f"VOOR: {', '.join(voor)}")
        if tegen:
            parts.append(f"TEGEN: {', '.join(tegen)}")
        if neutraal:
            parts.append(f"NEUTRAAL/GENUANCEERD: {', '.join(neutraal)}")

        return " | ".join(parts) if parts else "Geen duidelijke posities"

    # ==================== Verification & Maintenance ====================

    def verify_standpunt(self, standpunt_id: int, verified: bool = True, verified_by: str = 'system') -> Dict:
        """Mark standpunt as verified or unverified."""
        if verified:
            success = self.db.verify_standpunt(standpunt_id, verified_by)
        else:
            # Unverify - update verified to 0
            success = self.db.update_standpunt(standpunt_id, verified=0, verified_by=None, verified_at=None)
        return {'success': success, 'standpunt_id': standpunt_id, 'verified': verified}

    def get_unverified_standpunten(self, limit: int = 50) -> List[Dict]:
        """Get unverified standpunten for review."""
        return self.db.get_standpunten(verified_only=False, limit=limit)

    def initialise_topics(self) -> int:
        """Initialise default topic taxonomy."""
        count = 0
        for topic in self.DEFAULT_TOPICS:
            self.db.add_standpunt_topic(
                name=topic['name'],
                keywords=json.dumps(topic['keywords'])
            )
            count += 1
        logger.info(f'Initialised {count} default topics')
        return count

    def get_topics(self, parent_id: int = None) -> List[Dict]:
        """Get all topics, optionally filtered by parent."""
        return self.db.get_standpunt_topics(parent_id=parent_id)

    def get_statistics(self) -> Dict:
        """Get standpunten statistics."""
        stats = self.db.get_statistics()
        return {
            'total_standpunten': stats.get('standpunten', 0),
            'standpunten_by_stance': stats.get('standpunten_by_stance', {}),
            'verified_count': stats.get('standpunten_verified', 0),
            'total_raadsleden': stats.get('raadsleden', 0),
            'total_parties': stats.get('parties', 0)
        }


# Singleton instance
_provider_instance = None


def get_standpunt_provider() -> StandpuntProvider:
    """Get singleton StandpuntProvider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = StandpuntProvider()
    return _provider_instance


if __name__ == '__main__':
    # Test provider
    provider = get_standpunt_provider()
    print("StandpuntProvider initialised successfully")
    print(f"Statistics: {provider.get_statistics()}")
