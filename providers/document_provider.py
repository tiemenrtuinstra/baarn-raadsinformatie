#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document Provider voor Baarn Raadsinformatie Server.
Downloads en verwerkt documenten van Notubiz.

Storage modes:
- KEEP_PDF_FILES=false (default): Download PDF, extract text, delete PDF
  → Alleen tekst in database, minimale disk space
- KEEP_PDF_FILES=true: Download PDF, extract text, keep PDF
  → Tekst in database + originele PDFs op disk
"""

import os
import requests
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote

from core.config import Config
from core.database import Database, get_database
from shared.logging_config import get_logger, LogContext

logger = get_logger('document-provider')

# PDF text extraction
try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    logger.warning('pdfplumber not installed - PDF text extraction disabled')


class DocumentProvider:
    """Provider voor document downloads en text extractie."""

    def __init__(self, db: Database = None):
        """Initialize document provider."""
        self.db = db or get_database()
        self.documents_dir = Config.DOCUMENTS_DIR
        self.keep_files = getattr(Config, 'KEEP_PDF_FILES', False)

        if self.keep_files:
            self.documents_dir.mkdir(parents=True, exist_ok=True)

        mode = "keeping PDFs" if self.keep_files else "text-only (PDFs deleted after extraction)"
        logger.info(f'DocumentProvider initialized: {mode}')

    def download_pending_documents(self, limit: int = None) -> Tuple[int, int]:
        """
        Download alle pending documents.

        Args:
            limit: Maximum number of documents to download

        Returns:
            Tuple of (successful, failed) downloads
        """
        pending = self.db.get_documents_pending_download()
        if limit:
            pending = pending[:limit]

        with LogContext(logger, 'download_pending', count=len(pending)):
            success = 0
            failed = 0

            for doc in pending:
                if self.download_document(doc['id']):
                    success += 1
                else:
                    failed += 1

            logger.info(f'Downloaded {success}/{len(pending)} documents')
            return success, failed

    def download_document(self, document_id: int) -> bool:
        """
        Download a single document, extract text, optionally delete PDF.

        Storage mode:
        - KEEP_PDF_FILES=false: Download to temp, extract text, delete file
        - KEEP_PDF_FILES=true: Download to documents dir, extract text, keep file

        Args:
            document_id: Database ID of document

        Returns:
            True if successful
        """
        doc = self.db.get_document(document_id)
        if not doc:
            logger.error(f'Document not found: {document_id}')
            return False

        url = doc.get('url')
        if not url:
            logger.warning(f'No URL for document {document_id}')
            self.db.update_document_status(document_id, 'no_url')
            return False

        try:
            # Determine where to save
            if self.keep_files:
                local_path = self._generate_local_path(doc)
                temp_file = None
            else:
                # Use temp file that will be deleted
                suffix = Path(urlparse(url).path).suffix or '.pdf'
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                local_path = Path(temp_file.name)
                temp_file.close()

            # Download file
            logger.debug(f'Downloading: {url}')
            response = requests.get(url, timeout=60, stream=True)
            response.raise_for_status()

            # Save file
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size = local_path.stat().st_size
            logger.debug(f'Downloaded {file_size} bytes to {local_path}')

            # Extract text if PDF
            text_content = None
            if local_path.suffix.lower() == '.pdf':
                text_content = self._extract_text_from_file(local_path)

            # Update database
            if self.keep_files:
                self.db.update_document_status(document_id, 'downloaded', str(local_path))
            else:
                self.db.update_document_status(document_id, 'text_extracted', None)

            if text_content:
                self.db.update_document_content(document_id, text_content)
                logger.info(f'Document {document_id}: extracted {len(text_content)} chars')
            else:
                logger.warning(f'Document {document_id}: no text extracted')

            # Cleanup temp file if not keeping
            if not self.keep_files and local_path.exists():
                local_path.unlink()
                logger.debug(f'Deleted temp file: {local_path}')

            return True

        except requests.exceptions.RequestException as e:
            logger.error(f'Download failed for document {document_id}: {e}')
            self.db.update_document_status(document_id, 'download_failed')
            return False
        except Exception as e:
            logger.error(f'Error processing document {document_id}: {e}')
            self.db.update_document_status(document_id, 'error')
            # Cleanup on error
            if not self.keep_files and 'local_path' in locals() and local_path.exists():
                local_path.unlink()
            return False

    def _generate_local_path(self, doc: Dict) -> Path:
        """Generate local file path for document."""
        # Get filename from document or URL
        filename = doc.get('filename')
        if not filename and doc.get('url'):
            url_path = urlparse(doc['url']).path
            filename = unquote(os.path.basename(url_path))

        if not filename:
            # Generate from title
            title = doc.get('title', 'document')
            # Sanitize title
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_'))[:50]
            filename = f"{safe_title}.pdf"

        # Add document ID to ensure uniqueness
        doc_id = doc.get('id', 0)
        name, ext = os.path.splitext(filename)
        unique_filename = f"{doc_id}_{name}{ext}"

        return self.documents_dir / unique_filename

    def _extract_text_from_file(self, file_path: Path) -> Optional[str]:
        """
        Extract text content from a PDF file.

        Args:
            file_path: Path to PDF file

        Returns:
            Extracted text or None
        """
        if not PDF_SUPPORT:
            logger.warning('PDF extraction not available - pdfplumber not installed')
            return None

        try:
            text_parts = []

            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)

            return '\n\n'.join(text_parts) if text_parts else None

        except Exception as e:
            logger.error(f'Text extraction failed for {file_path}: {e}')
            return None

    def extract_text(self, document_id: int) -> Optional[str]:
        """
        Extract text content from an already-downloaded document.
        Only works if KEEP_PDF_FILES=true.

        Args:
            document_id: Database ID of document

        Returns:
            Extracted text or None
        """
        doc = self.db.get_document(document_id)
        if not doc:
            return None

        local_path = doc.get('local_path')
        if not local_path or not Path(local_path).exists():
            logger.warning(f'Document file not found: {document_id}')
            return None

        full_text = self._extract_text_from_file(Path(local_path))

        if full_text:
            self.db.update_document_content(document_id, full_text)
            logger.info(f'Extracted text from document {document_id}: {len(full_text)} chars')

        return full_text

    def extract_all_text(self) -> Tuple[int, int]:
        """
        Extract text from all downloaded documents without extracted text.

        Returns:
            Tuple of (successful, failed) extractions
        """
        # Find documents needing extraction
        docs = self.db.get_documents()
        need_extraction = [
            d for d in docs
            if d.get('download_status') == 'downloaded'
            and not d.get('text_extracted')
            and d.get('local_path')
        ]

        success = 0
        failed = 0

        with LogContext(logger, 'extract_all_text', count=len(need_extraction)):
            for doc in need_extraction:
                if self.extract_text(doc['id']):
                    success += 1
                else:
                    failed += 1

        return success, failed

    def get_document(self, document_id: int) -> Optional[Dict]:
        """Get document with content."""
        doc = self.db.get_document(document_id)
        if not doc:
            return None

        # Add file info if available
        if doc.get('local_path') and Path(doc['local_path']).exists():
            doc['file_exists'] = True
            doc['file_size'] = Path(doc['local_path']).stat().st_size
        else:
            doc['file_exists'] = False

        return doc

    def get_documents(
        self,
        meeting_id: int = None,
        agenda_item_id: int = None,
        search: str = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """Get documents with filters."""
        return self.db.get_documents(
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            search=search,
            limit=limit,
            offset=offset
        )

    def search_documents(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Search documents by title and content.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching documents with relevance info
        """
        # Simple keyword search in database
        docs = self.db.get_documents(search=query, limit=limit)

        # Add match info
        query_lower = query.lower()
        for doc in docs:
            title_match = query_lower in (doc.get('title') or '').lower()
            content_match = query_lower in (doc.get('text_content') or '').lower()
            doc['match_type'] = []
            if title_match:
                doc['match_type'].append('title')
            if content_match:
                doc['match_type'].append('content')

        return docs

    def get_document_content(self, document_id: int) -> Optional[str]:
        """Get extracted text content of a document."""
        doc = self.db.get_document(document_id)
        if doc:
            return doc.get('text_content')
        return None

    def get_storage_stats(self) -> Dict:
        """Get storage statistics."""
        total_files = 0
        total_size = 0

        for file in self.documents_dir.iterdir():
            if file.is_file():
                total_files += 1
                total_size += file.stat().st_size

        db_stats = self.db.get_statistics()

        return {
            'files_on_disk': total_files,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'documents_in_db': db_stats.get('documents', 0),
            'documents_by_status': db_stats.get('documents_by_status', {})
        }


# Singleton instance
_provider_instance = None


def get_document_provider() -> DocumentProvider:
    """Get singleton document provider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = DocumentProvider()
    return _provider_instance


if __name__ == '__main__':
    # Test the provider
    provider = get_document_provider()

    print("Storage stats:")
    stats = provider.get_storage_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\nPending documents:")
    from core.database import get_database
    db = get_database()
    pending = db.get_documents_pending_download()
    print(f"  {len(pending)} documents pending download")

    if pending[:3]:
        print("\nDownloading first 3 documents...")
        success, failed = provider.download_pending_documents(limit=3)
        print(f"  Downloaded: {success}, Failed: {failed}")
