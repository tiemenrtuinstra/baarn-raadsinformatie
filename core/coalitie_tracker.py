#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coalitie Tracker voor Baarn Raadsinformatie Server.
Beheert het coalitieakkoord en trackt de voortgang van afspraken.
"""

import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

from core.config import Config
from core.database import get_database
from shared.logging_config import get_logger

logger = get_logger('coalitie-tracker')


class CoalitieTracker:
    """Tracker voor coalitieakkoord afspraken."""

    AKKOORD_FILE = Config.DATA_DIR / 'coalitieakkoord.yaml'

    STATUS_OPTIONS = [
        'niet_gestart',
        'in_voorbereiding',
        'in_uitvoering',
        'gerealiseerd',
        'gewijzigd',
        'vervallen'
    ]

    def __init__(self):
        """Initialize tracker."""
        self.db = get_database()
        self._akkoord = None

    def load_akkoord(self) -> Optional[Dict]:
        """Load coalitieakkoord from YAML file."""
        if not self.AKKOORD_FILE.exists():
            logger.warning(f'Coalitieakkoord niet gevonden: {self.AKKOORD_FILE}')
            return None

        try:
            with open(self.AKKOORD_FILE, 'r', encoding='utf-8') as f:
                self._akkoord = yaml.safe_load(f)
            return self._akkoord
        except Exception as e:
            logger.error(f'Fout bij laden coalitieakkoord: {e}')
            return None

    def save_akkoord(self) -> bool:
        """Save coalitieakkoord to YAML file."""
        if not self._akkoord:
            return False

        try:
            # Update rapportage
            self._update_rapportage()

            with open(self.AKKOORD_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(self._akkoord, f, allow_unicode=True, default_flow_style=False)
            return True
        except Exception as e:
            logger.error(f'Fout bij opslaan coalitieakkoord: {e}')
            return False

    def _update_rapportage(self):
        """Update rapportage sectie met actuele statistieken."""
        if not self._akkoord:
            return

        totaal = 0
        per_status = {s: 0 for s in self.STATUS_OPTIONS}

        themas = self._akkoord.get('themas', {})
        for thema_data in themas.values():
            for afspraak in thema_data.get('afspraken', []):
                totaal += 1
                status = afspraak.get('status', 'niet_gestart')
                if status in per_status:
                    per_status[status] += 1

        self._akkoord['rapportage'] = {
            'laatste_update': datetime.now().isoformat(),
            'totaal_afspraken': totaal,
            'per_status': per_status
        }

    def get_akkoord_summary(self) -> Dict:
        """Get summary of coalitieakkoord."""
        if not self._akkoord:
            self.load_akkoord()

        if not self._akkoord:
            return {'error': 'Coalitieakkoord niet beschikbaar'}

        meta = self._akkoord.get('meta', {})
        self._update_rapportage()

        return {
            'gemeente': meta.get('gemeente'),
            'periode': meta.get('periode'),
            'partijen': meta.get('partijen', []),
            'vastgesteld': meta.get('vastgesteld'),
            'rapportage': self._akkoord.get('rapportage', {})
        }

    def get_afspraken(self, thema: str = None, status: str = None) -> List[Dict]:
        """Get afspraken, optionally filtered."""
        if not self._akkoord:
            self.load_akkoord()

        if not self._akkoord:
            return []

        afspraken = []
        themas = self._akkoord.get('themas', {})

        for thema_key, thema_data in themas.items():
            if thema and thema.lower() not in thema_key.lower():
                continue

            for afspraak in thema_data.get('afspraken', []):
                if status and afspraak.get('status') != status:
                    continue

                afspraken.append({
                    'thema': thema_data.get('naam', thema_key),
                    'thema_key': thema_key,
                    **afspraak
                })

        return afspraken

    def get_afspraak(self, afspraak_id: str) -> Optional[Dict]:
        """Get specific afspraak by ID."""
        if not self._akkoord:
            self.load_akkoord()

        if not self._akkoord:
            return None

        for thema_key, thema_data in self._akkoord.get('themas', {}).items():
            for afspraak in thema_data.get('afspraken', []):
                if afspraak.get('id') == afspraak_id:
                    return {
                        'thema': thema_data.get('naam', thema_key),
                        'thema_key': thema_key,
                        **afspraak
                    }

        return None

    def update_afspraak_status(self, afspraak_id: str, new_status: str) -> bool:
        """Update status of an afspraak."""
        if new_status not in self.STATUS_OPTIONS:
            logger.error(f'Ongeldige status: {new_status}')
            return False

        if not self._akkoord:
            self.load_akkoord()

        if not self._akkoord:
            return False

        for thema_data in self._akkoord.get('themas', {}).values():
            for afspraak in thema_data.get('afspraken', []):
                if afspraak.get('id') == afspraak_id:
                    afspraak['status'] = new_status
                    self.save_akkoord()
                    logger.info(f'Status {afspraak_id} bijgewerkt naar {new_status}')
                    return True

        return False

    def link_besluit(self, afspraak_id: str, meeting_id: int) -> bool:
        """Link a meeting/besluit to an afspraak."""
        if not self._akkoord:
            self.load_akkoord()

        if not self._akkoord:
            return False

        for thema_data in self._akkoord.get('themas', {}).values():
            for afspraak in thema_data.get('afspraken', []):
                if afspraak.get('id') == afspraak_id:
                    if 'gerelateerde_besluiten' not in afspraak:
                        afspraak['gerelateerde_besluiten'] = []
                    if meeting_id not in afspraak['gerelateerde_besluiten']:
                        afspraak['gerelateerde_besluiten'].append(meeting_id)
                        self.save_akkoord()
                        logger.info(f'Besluit {meeting_id} gekoppeld aan {afspraak_id}')
                    return True

        return False

    def find_related_documents(self, afspraak_id: str, limit: int = 10) -> List[Dict]:
        """Find documents related to an afspraak based on zoektermen."""
        afspraak = self.get_afspraak(afspraak_id)
        if not afspraak:
            return []

        zoektermen = afspraak.get('zoektermen', [])
        if not zoektermen:
            return []

        # Search for each term
        all_results = []
        for term in zoektermen:
            docs = self.db.get_documents(search=term, limit=limit)
            for doc in docs:
                if doc not in all_results:
                    doc['matched_term'] = term
                    all_results.append(doc)

        return all_results[:limit]

    def auto_update_statuses(self) -> Dict:
        """
        Automatically update statuses based on found documents.
        Returns summary of updates.
        """
        if not self._akkoord:
            self.load_akkoord()

        if not self._akkoord:
            return {'error': 'Coalitieakkoord niet beschikbaar'}

        updates = []

        for thema_key, thema_data in self._akkoord.get('themas', {}).items():
            for afspraak in thema_data.get('afspraken', []):
                afspraak_id = afspraak.get('id')
                current_status = afspraak.get('status', 'niet_gestart')

                # Skip already completed or cancelled
                if current_status in ['gerealiseerd', 'vervallen']:
                    continue

                # Find related documents
                docs = self.find_related_documents(afspraak_id, limit=20)

                if docs:
                    # Link found documents
                    for doc in docs:
                        meeting_id = doc.get('meeting_id')
                        if meeting_id:
                            self.link_besluit(afspraak_id, meeting_id)

                    # Update status if still "niet_gestart"
                    if current_status == 'niet_gestart' and len(docs) > 0:
                        afspraak['status'] = 'in_voorbereiding'
                        updates.append({
                            'afspraak_id': afspraak_id,
                            'old_status': current_status,
                            'new_status': 'in_voorbereiding',
                            'documents_found': len(docs)
                        })

        if updates:
            self.save_akkoord()

        return {
            'updates': updates,
            'total_updated': len(updates)
        }


# Singleton instance
_tracker_instance = None


def get_coalitie_tracker() -> CoalitieTracker:
    """Get singleton coalitie tracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = CoalitieTracker()
    return _tracker_instance


if __name__ == '__main__':
    # Test the tracker
    tracker = CoalitieTracker()

    print("Loading coalitieakkoord...")
    akkoord = tracker.load_akkoord()

    if akkoord:
        print("\nSummary:")
        summary = tracker.get_akkoord_summary()
        for key, value in summary.items():
            print(f"  {key}: {value}")

        print("\nAfspraken:")
        afspraken = tracker.get_afspraken()
        for a in afspraken[:5]:
            print(f"  - [{a['status']}] {a['tekst'][:50]}...")

        print(f"\nTotaal: {len(afspraken)} afspraken")
    else:
        print("Coalitieakkoord niet gevonden of fout bij laden")
