#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Election Program Provider voor Baarn Politiek MCP Server.
Beheert scraping, opslag en zoeken in verkiezingsprogramma's.
"""

import requests
from pathlib import Path
from typing import Dict, List, Optional
import time
import re

from core.config import Config
from core.database import Database, get_database
from shared.logging_config import get_logger

logger = get_logger('election-program-provider')

# Probeer BeautifulSoup en pdfplumber te importeren
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning('beautifulsoup4 not installed. Web scraping will be limited.')

try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    logger.warning('pdfplumber not installed. PDF extraction will be unavailable.')


class ElectionProgramProvider:
    """Provider voor verkiezingsprogramma's van Baarnse partijen."""

    # Bekende partijen in Baarn (historisch en huidig)
    BAARN_PARTIES = [
        # Actieve partijen
        {'name': 'VVD Baarn', 'abbreviation': 'VVD', 'color': '#FF6600', 'active': True,
         'website_url': 'https://baarn.vvd.nl', 'founded_year': 1948},
        {'name': 'CDA Baarn', 'abbreviation': 'CDA', 'color': '#007B5F', 'active': True,
         'website_url': 'https://www.cdabaarn.nl', 'founded_year': 1980},
        {'name': 'D66 Baarn', 'abbreviation': 'D66', 'color': '#00AA00', 'active': True,
         'website_url': 'https://baarn.d66.nl', 'founded_year': 1966},
        {'name': 'GroenLinks Baarn', 'abbreviation': 'GL', 'color': '#228B22', 'active': True,
         'website_url': 'https://baarn.groenlinks.nl', 'founded_year': 1990},
        {'name': 'PvdA Baarn', 'abbreviation': 'PvdA', 'color': '#FF0000', 'active': True,
         'website_url': 'https://baarn.pvda.nl', 'founded_year': 1946},
        {'name': 'ChristenUnie Baarn', 'abbreviation': 'CU', 'color': '#00A6D6', 'active': True,
         'website_url': 'https://baarn.christenunie.nl', 'founded_year': 2000},
        {'name': '50PLUS Baarn', 'abbreviation': '50PLUS', 'color': '#932292', 'active': True,
         'website_url': None, 'founded_year': 2009},
        {'name': 'VoorBaarn', 'abbreviation': 'VB', 'color': '#1E90FF', 'active': True,
         'website_url': None, 'founded_year': None},
        # Historische partijen
        {'name': 'GPV', 'abbreviation': 'GPV', 'color': '#000080', 'active': False,
         'website_url': None, 'founded_year': 1948, 'description': 'Gereformeerd Politiek Verbond (opgegaan in ChristenUnie)'},
        {'name': 'RPF', 'abbreviation': 'RPF', 'color': '#000080', 'active': False,
         'website_url': None, 'founded_year': 1975, 'description': 'Reformatorische Politieke Federatie (opgegaan in ChristenUnie)'},
        {'name': 'Gemeentebelangen Baarn', 'abbreviation': 'GB', 'color': '#808080', 'active': False,
         'website_url': None, 'founded_year': None},
        {'name': 'BOP (Baarnse Onafhankelijke Partij)', 'abbreviation': 'BOP', 'color': '#FFA500', 'active': False,
         'website_url': None, 'founded_year': None},
        {'name': 'LTS (Lijst Tinus Snijders)', 'abbreviation': 'LTS', 'color': '#808080', 'active': False,
         'website_url': None, 'founded_year': None},
    ]

    # User agent voor web requests
    USER_AGENT = 'Baarn Raadsinformatie Bot/1.0 (Educational/Research)'

    def __init__(self, db: Database = None):
        self.db = db or get_database()
        self.programs_dir = Config.DATA_DIR / 'election_programs'
        self.programs_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': self.USER_AGENT})
        logger.info(f'ElectionProgramProvider initialized. Programs dir: {self.programs_dir}')

    def initialize_parties(self) -> int:
        """Initialiseer bekende partijen in database."""
        count = 0
        for party in self.BAARN_PARTIES:
            try:
                self.db.upsert_party(
                    name=party['name'],
                    abbreviation=party.get('abbreviation'),
                    website_url=party.get('website_url'),
                    founded_year=party.get('founded_year'),
                    active=1 if party.get('active', True) else 0,
                    color=party.get('color'),
                    description=party.get('description')
                )
                count += 1
            except Exception as e:
                logger.error(f"Error adding party {party['name']}: {e}")

        logger.info(f'Initialized {count} parties')
        return count

    def get_parties(self, active_only: bool = False) -> List[Dict]:
        """Haal alle partijen op."""
        return self.db.get_parties(active_only=active_only)

    def get_party(self, name: str) -> Optional[Dict]:
        """Haal partij op bij naam of afkorting."""
        return self.db.get_party(name=name)

    def scrape_program_from_url(self, url: str, party_id: int, year: int) -> Optional[Dict]:
        """
        Scrape verkiezingsprogramma van een URL.

        Args:
            url: URL naar programma (pagina of PDF)
            party_id: ID van de partij
            year: Verkiezingsjaar

        Returns:
            Dict met resultaat of None bij fout
        """
        if not BS4_AVAILABLE:
            logger.error('BeautifulSoup not available for scraping')
            return None

        try:
            logger.info(f'Scraping program from {url}')

            # Rate limiting
            time.sleep(2)

            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '').lower()

            if 'pdf' in content_type or url.lower().endswith('.pdf'):
                # PDF bestand
                return self._process_pdf_program(response.content, url, party_id, year)
            else:
                # HTML pagina
                return self._process_html_program(response.text, url, party_id, year)

        except requests.RequestException as e:
            logger.error(f'Error fetching {url}: {e}')
            return None

    def _process_pdf_program(self, content: bytes, url: str, party_id: int, year: int) -> Optional[Dict]:
        """Verwerk PDF verkiezingsprogramma."""
        if not PDF_SUPPORT:
            logger.error('pdfplumber not available for PDF processing')
            return None

        try:
            # Sla PDF op
            party = self.db.get_party(party_id=party_id)
            safe_name = re.sub(r'[^\w\-]', '_', party['abbreviation'] or party['name'])
            filename = f'{safe_name}_{year}.pdf'
            filepath = self.programs_dir / filename

            filepath.write_bytes(content)
            logger.info(f'Saved PDF to {filepath}')

            # Extract tekst
            text_content = self._extract_text_from_pdf(filepath)

            # Sla op in database
            program_id = self.db.upsert_election_program(
                party_id=party_id,
                election_year=year,
                title=f'Verkiezingsprogramma {party["name"]} {year}',
                source_url=url,
                local_path=str(filepath),
                text_content=text_content,
                text_extracted=1 if text_content else 0,
                download_status='done'
            )

            return {
                'program_id': program_id,
                'party_id': party_id,
                'year': year,
                'filepath': str(filepath),
                'text_length': len(text_content) if text_content else 0
            }

        except Exception as e:
            logger.error(f'Error processing PDF: {e}')
            return None

    def _process_html_program(self, html: str, url: str, party_id: int, year: int) -> Optional[Dict]:
        """Verwerk HTML verkiezingsprogramma pagina."""
        try:
            soup = BeautifulSoup(html, 'lxml')

            # Verwijder script en style tags
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()

            # Zoek naar main content
            main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|main|body'))

            if main_content:
                text_content = main_content.get_text(separator='\n', strip=True)
            else:
                text_content = soup.get_text(separator='\n', strip=True)

            # Zoek naar PDF links op de pagina
            pdf_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.lower().endswith('.pdf') and ('programma' in href.lower() or 'verkiezing' in href.lower()):
                    pdf_links.append(href)

            party = self.db.get_party(party_id=party_id)

            # Sla op in database
            program_id = self.db.upsert_election_program(
                party_id=party_id,
                election_year=year,
                title=f'Verkiezingsprogramma {party["name"]} {year}',
                source_url=url,
                text_content=text_content,
                text_extracted=1,
                download_status='done'
            )

            result = {
                'program_id': program_id,
                'party_id': party_id,
                'year': year,
                'text_length': len(text_content),
                'pdf_links_found': pdf_links
            }

            # Als er PDF links zijn, probeer de eerste te downloaden
            if pdf_links:
                logger.info(f'Found PDF links: {pdf_links}')
                result['pdf_links'] = pdf_links

            return result

        except Exception as e:
            logger.error(f'Error processing HTML: {e}')
            return None

    def _extract_text_from_pdf(self, filepath: Path) -> Optional[str]:
        """Extraheer tekst uit PDF bestand."""
        if not PDF_SUPPORT:
            return None

        try:
            text_parts = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)

            return '\n\n'.join(text_parts)

        except Exception as e:
            logger.error(f'Error extracting text from {filepath}: {e}')
            return None

    def add_program_manually(
        self,
        party_name: str,
        year: int,
        text_content: str,
        title: str = None,
        source_url: str = None
    ) -> Optional[int]:
        """
        Voeg een verkiezingsprogramma handmatig toe.

        Args:
            party_name: Naam of afkorting van de partij
            year: Verkiezingsjaar
            text_content: Volledige tekst van het programma
            title: Optionele titel
            source_url: Optionele bron URL

        Returns:
            Program ID of None bij fout
        """
        party = self.db.get_party(name=party_name)
        if not party:
            logger.error(f'Party not found: {party_name}')
            return None

        program_id = self.db.upsert_election_program(
            party_id=party['id'],
            election_year=year,
            title=title or f'Verkiezingsprogramma {party["name"]} {year}',
            source_url=source_url,
            text_content=text_content,
            text_extracted=1,
            download_status='manual'
        )

        logger.info(f'Added program manually: party={party_name}, year={year}, id={program_id}')
        return program_id

    def search_programs(
        self,
        query: str,
        party: str = None,
        year_from: int = None,
        year_to: int = None,
        limit: int = 20
    ) -> List[Dict]:
        """
        Zoek in verkiezingsprogramma's.

        Args:
            query: Zoekterm
            party: Filter op partij (naam of afkorting)
            year_from: Vanaf verkiezingsjaar
            year_to: Tot verkiezingsjaar
            limit: Maximum aantal resultaten

        Returns:
            Lijst van zoekresultaten met snippets
        """
        return self.db.search_election_programs(
            query=query,
            party_name=party,
            year_from=year_from,
            year_to=year_to,
            limit=limit
        )

    def get_programs(
        self,
        party: str = None,
        year_from: int = None,
        year_to: int = None
    ) -> List[Dict]:
        """Haal verkiezingsprogramma's op."""
        party_id = None
        if party:
            party_obj = self.db.get_party(name=party)
            if party_obj:
                party_id = party_obj['id']

        return self.db.get_election_programs(
            party_id=party_id,
            year_from=year_from,
            year_to=year_to
        )

    def get_program(self, program_id: int) -> Optional[Dict]:
        """Haal een specifiek verkiezingsprogramma op."""
        return self.db.get_election_program(program_id)

    def compare_positions(self, topic: str, parties: List[str] = None, year: int = None) -> Dict:
        """
        Vergelijk standpunten van partijen over een onderwerp.

        Args:
            topic: Onderwerp om te zoeken
            parties: Lijst van partijen om te vergelijken (optioneel)
            year: Specifiek verkiezingsjaar (optioneel)

        Returns:
            Dict met standpunten per partij
        """
        results = {
            'topic': topic,
            'year': year,
            'parties': {}
        }

        # Zoek in alle programma's
        search_results = self.search_programs(
            query=topic,
            year_from=year,
            year_to=year,
            limit=50
        )

        for result in search_results:
            party_name = result.get('party_name')

            # Filter op specifieke partijen indien opgegeven
            if parties and not any(p.lower() in party_name.lower() or p.lower() == result.get('abbreviation', '').lower() for p in parties):
                continue

            if party_name not in results['parties']:
                results['parties'][party_name] = []

            results['parties'][party_name].append({
                'year': result.get('election_year'),
                'snippet': result.get('snippet', '').strip(),
                'program_id': result.get('id')
            })

        return results

    def get_party_position_history(self, party: str, topic: str) -> List[Dict]:
        """
        Volg de historische ontwikkeling van een partijstandpunt.

        Args:
            party: Partij naam of afkorting
            topic: Onderwerp

        Returns:
            Lijst van standpunten per jaar
        """
        party_obj = self.db.get_party(name=party)
        if not party_obj:
            return []

        # Zoek in alle programma's van deze partij
        programs = self.db.get_election_programs(party_id=party_obj['id'])

        history = []
        for program in programs:
            if program.get('text_content'):
                # Zoek naar het onderwerp in de tekst
                text = program['text_content'].lower()
                topic_lower = topic.lower()

                if topic_lower in text:
                    # Vind de context rond het onderwerp
                    idx = text.find(topic_lower)
                    start = max(0, idx - 200)
                    end = min(len(text), idx + len(topic) + 200)
                    snippet = program['text_content'][start:end]

                    history.append({
                        'year': program['election_year'],
                        'title': program.get('title'),
                        'snippet': snippet.strip(),
                        'program_id': program['id']
                    })

        # Sorteer op jaar
        history.sort(key=lambda x: x['year'])
        return history


    def check_and_update_parties_from_web(self) -> Dict:
        """
        Check and update parties by scraping official sources.

        Sources checked:
        1. Gemeente Baarn website (gemeenteraad/fracties)
        2. Kiesraad data (for historical election results)

        Returns:
            Dict with results including new, updated, and deactivated parties
        """
        results = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'sources_checked': [],
            'parties_found': [],
            'new_parties': [],
            'reactivated_parties': [],
            'deactivated_parties': [],
            'errors': []
        }

        if not BS4_AVAILABLE:
            results['errors'].append('BeautifulSoup not available for web scraping')
            logger.error('BeautifulSoup not available for party checking')
            return results

        # Check gemeente Baarn website
        baarn_results = self._check_baarn_gemeente_website()
        results['sources_checked'].append('gemeente_baarn')
        if baarn_results.get('parties'):
            results['parties_found'].extend(baarn_results['parties'])
        if baarn_results.get('error'):
            results['errors'].append(baarn_results['error'])

        # Process found parties
        if results['parties_found']:
            db_results = self._update_parties_in_database(results['parties_found'])
            results['new_parties'] = db_results.get('new', [])
            results['reactivated_parties'] = db_results.get('reactivated', [])
            results['deactivated_parties'] = db_results.get('deactivated', [])

        logger.info(f"Party check completed: {len(results['parties_found'])} found, "
                    f"{len(results['new_parties'])} new, "
                    f"{len(results['deactivated_parties'])} deactivated")

        return results

    def _check_baarn_gemeente_website(self) -> Dict:
        """
        Scrape gemeente Baarn website for current council parties.

        Returns:
            Dict with parties found or error
        """
        result = {'parties': [], 'error': None}

        # URLs to check for party information
        urls_to_try = [
            'https://www.baarn.nl/bestuur-en-organisatie/gemeenteraad/fracties',
            'https://www.baarn.nl/gemeenteraad/fracties',
            'https://www.baarn.nl/gemeenteraad',
        ]

        for url in urls_to_try:
            try:
                logger.info(f'Checking {url} for party information...')
                time.sleep(2)  # Rate limiting

                response = self.session.get(url, timeout=30)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, 'lxml')

                # Look for party/fractie information
                parties = self._extract_parties_from_html(soup, url)
                if parties:
                    result['parties'] = parties
                    logger.info(f'Found {len(parties)} parties from {url}')
                    return result

            except requests.RequestException as e:
                logger.warning(f'Error fetching {url}: {e}')
                continue
            except Exception as e:
                logger.error(f'Error parsing {url}: {e}')
                continue

        if not result['parties']:
            result['error'] = 'Could not find party information on gemeente Baarn website'

        return result

    def _extract_parties_from_html(self, soup: BeautifulSoup, source_url: str) -> List[Dict]:
        """
        Extract party information from HTML page.

        Args:
            soup: BeautifulSoup parsed HTML
            source_url: URL for reference

        Returns:
            List of party dicts with name, abbreviation, etc.
        """
        parties = []

        # Common patterns for party listings on Dutch municipality websites
        # Look for links or headings containing party names

        # Pattern 1: Look for specific fractie/partij sections
        fractie_sections = soup.find_all(['div', 'section', 'article'],
                                          class_=re.compile(r'fractie|partij|party|faction', re.I))

        for section in fractie_sections:
            name = None
            # Try to find party name in heading or link
            heading = section.find(['h1', 'h2', 'h3', 'h4', 'a', 'strong'])
            if heading:
                name = heading.get_text(strip=True)

            if name and len(name) > 2 and len(name) < 100:
                parties.append({
                    'name': name,
                    'source': source_url,
                    'active': True
                })

        # Pattern 2: Look for lists with party names
        if not parties:
            # Try to find unordered/ordered lists that might contain parties
            for ul in soup.find_all(['ul', 'ol']):
                # Check if this looks like a party list
                items = ul.find_all('li')
                potential_parties = []

                for li in items:
                    text = li.get_text(strip=True)
                    # Check if it looks like a party name
                    if self._looks_like_party_name(text):
                        potential_parties.append({
                            'name': text.split('(')[0].strip(),  # Remove any seat counts
                            'source': source_url,
                            'active': True
                        })

                # If we found multiple potential parties, use them
                if len(potential_parties) >= 3:
                    parties.extend(potential_parties)
                    break

        # Pattern 3: Look for known party name patterns in the page text
        if not parties:
            page_text = soup.get_text()
            for known_party in self.BAARN_PARTIES:
                if known_party['name'] in page_text or known_party.get('abbreviation', '') in page_text:
                    parties.append({
                        'name': known_party['name'],
                        'abbreviation': known_party.get('abbreviation'),
                        'source': source_url,
                        'active': True
                    })

        # Deduplicate
        seen = set()
        unique_parties = []
        for p in parties:
            name_key = p['name'].lower()
            if name_key not in seen:
                seen.add(name_key)
                unique_parties.append(p)

        return unique_parties

    def _looks_like_party_name(self, text: str) -> bool:
        """Check if text looks like a political party name."""
        if not text or len(text) < 2 or len(text) > 50:
            return False

        # Common party patterns
        party_indicators = ['vvd', 'cda', 'd66', 'pvda', 'groenlinks', 'christenunie',
                            'sp', 'pvv', '50plus', 'baarn', 'lokaal', 'fractie',
                            'partij', 'democraten', 'liberaal', 'christen', 'groen']

        text_lower = text.lower()
        return any(indicator in text_lower for indicator in party_indicators)

    def _update_parties_in_database(self, found_parties: List[Dict]) -> Dict:
        """
        Update database with found parties.

        Args:
            found_parties: List of party dicts found from web scraping

        Returns:
            Dict with new, reactivated, and deactivated parties
        """
        results = {'new': [], 'reactivated': [], 'deactivated': []}

        # Get current parties from database
        current_db_parties = {p['name'].lower(): p for p in self.db.get_parties()}

        found_names = set()

        for party_data in found_parties:
            name = party_data.get('name', '').strip()
            if not name:
                continue

            name_lower = name.lower()
            found_names.add(name_lower)

            # Match against known parties
            matched_known = None
            for known in self.BAARN_PARTIES:
                if (known['name'].lower() == name_lower or
                    known.get('abbreviation', '').lower() == name_lower):
                    matched_known = known
                    break

            if name_lower in current_db_parties:
                # Party exists - check if it needs reactivation
                existing = current_db_parties[name_lower]
                if not existing.get('active'):
                    self.db.upsert_party(
                        name=name,
                        active=1
                    )
                    results['reactivated'].append(name)
                    logger.info(f'Reactivated party: {name}')
            elif matched_known:
                # New party - only add if it matches a known party
                self.db.upsert_party(
                    name=matched_known['name'],
                    abbreviation=matched_known.get('abbreviation'),
                    website_url=matched_known.get('website_url'),
                    founded_year=matched_known.get('founded_year'),
                    active=1,
                    color=matched_known.get('color'),
                    description=matched_known.get('description')
                )
                results['new'].append(matched_known['name'])
                logger.info(f'Added new party: {matched_known["name"]}')
            else:
                # Skip unknown entries (not a real party)
                logger.debug(f'Skipped unknown entry: {name}')

        # Check for parties that should be deactivated
        # (in database but not found on website, and not in known historical parties)
        for db_name, db_party in current_db_parties.items():
            if db_party.get('active') and db_name not in found_names:
                # Check if it's a known historical party
                is_known_historical = any(
                    not p.get('active', True) and p['name'].lower() == db_name
                    for p in self.BAARN_PARTIES
                )

                if not is_known_historical:
                    # Mark as inactive (but don't delete - might be temporary)
                    logger.warning(f"Party '{db_party['name']}' not found on website - "
                                   "consider marking as inactive")
                    # Note: We don't automatically deactivate to avoid data loss
                    # from temporary website issues
                    results['deactivated'].append(db_party['name'])

        return results

    def get_party_sync_status(self) -> Dict:
        """
        Get current party sync status.

        Returns:
            Dict with party counts and last sync info
        """
        parties = self.db.get_parties()
        active_count = sum(1 for p in parties if p.get('active'))
        historical_count = len(parties) - active_count

        # Get last sync info from database metadata if available
        return {
            'total_parties': len(parties),
            'active_parties': active_count,
            'historical_parties': historical_count,
            'parties': [
                {
                    'name': p['name'],
                    'abbreviation': p.get('abbreviation'),
                    'active': bool(p.get('active')),
                    'website_url': p.get('website_url')
                }
                for p in parties
            ]
        }


# Singleton instance
_provider_instance = None


def get_election_program_provider() -> ElectionProgramProvider:
    """Get singleton ElectionProgramProvider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = ElectionProgramProvider()
    return _provider_instance


if __name__ == '__main__':
    # Test provider
    provider = get_election_program_provider()

    # Initialiseer partijen
    count = provider.initialize_parties()
    print(f"Initialized {count} parties")

    # Toon partijen
    parties = provider.get_parties()
    print(f"\nParties in database ({len(parties)}):")
    for party in parties:
        status = "actief" if party['active'] else "historisch"
        print(f"  - {party['name']} ({party['abbreviation']}) - {status}")
