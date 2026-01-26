#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baarn Raadsinformatie - Background Sync Service

Draait als achtergrond service (Docker of Windows Service) en houdt
de data automatisch up-to-date door periodiek te synchroniseren.

Kan draaien naast de MCP server (die on-demand door Claude Desktop wordt gestart).
"""

import time
import signal
import sys
import uuid
import threading
from datetime import datetime, timedelta, date
from typing import Optional

# Windows keyboard input
if sys.platform == 'win32':
    import msvcrt
    HAS_KEYBOARD = True
else:
    HAS_KEYBOARD = False

from core.config import Config
from core.database import get_database
from core.document_index import get_document_index
from providers.meeting_provider import get_meeting_provider
from providers.document_provider import get_document_provider
from providers.election_program_provider import get_election_program_provider
from providers.notubiz_client import get_notubiz_client
from shared.logging_config import get_logger
from shared.cli_progress import (
    is_interactive,
    print_header as _print_header,
    print_status as _print_status,
    print_success as _print_success,
    print_error as _print_error,
    print_warning as _print_warning,
    print_summary,
    progress_context,
)
from shared.cli_app import CLIApp, is_cli_available

# Global CLI app instance
_cli_app: CLIApp | None = None


def _use_tui() -> bool:
    """Check if we should use the full-screen TUI."""
    return _cli_app is not None and _cli_app.live is not None


def print_header(title: str):
    """Print header - uses TUI if active."""
    if not _use_tui():
        _print_header(title)


def print_status(message: str, style: str = ""):
    """Print status - routes to TUI log if active."""
    if _use_tui():
        _cli_app.log_info(message)
    else:
        _print_status(message, style)


def print_success(message: str):
    """Print success - routes to TUI log if active."""
    if _use_tui():
        _cli_app.log_success(message)
    else:
        _print_success(message)


def print_error(message: str):
    """Print error - routes to TUI log if active."""
    if _use_tui():
        _cli_app.log_error(message)
    else:
        _print_error(message)


def print_warning(message: str):
    """Print warning - routes to TUI log if active."""
    if _use_tui():
        _cli_app.log_warning(message)
    else:
        _print_warning(message)

logger = get_logger('sync-service')

# Sync interval in seconds (default: 6 hours)
SYNC_INTERVAL = int(60 * 60 * 6)

# Party sync interval in seconds (default: 24 hours - parties don't change often)
PARTY_SYNC_INTERVAL = int(60 * 60 * 24)

# Global flags for control
_running = True
_stop_requested = False
_paused = False


def clear_console():
    """Clear console screen (Windows/Unix)."""
    import os
    if sys.platform == 'win32':
        os.system('cls')
    else:
        os.system('clear')


def check_keyboard() -> str | None:
    """Check for keyboard input (Windows only). Returns key pressed or None."""
    global _stop_requested, _paused
    if HAS_KEYBOARD and is_interactive():
        while msvcrt.kbhit():
            key = msvcrt.getch()
            if key in (b'q', b'Q', b'\x03'):  # q, Q, or Ctrl+C
                _stop_requested = True
                return 'quit'
            elif key in (b'p', b'P'):  # p or P for pause
                _paused = not _paused
                return 'pause'
            elif key in (b' ',):  # Space also toggles pause
                _paused = not _paused
                return 'pause'
    return None


def is_paused() -> bool:
    """Check if sync is paused."""
    return _paused


def should_stop() -> bool:
    """Check if stop was requested (including keyboard check)."""
    check_keyboard()
    return not _running or _stop_requested


def wait_if_paused():
    """Wait while paused, checking for unpause or quit."""
    global _paused
    if not _paused:
        return

    if is_interactive():
        print_warning("Gepauzeerd - druk 'p' of spatie om verder te gaan, 'q' om te stoppen")

    while _paused and not _stop_requested:
        key = check_keyboard()
        if key == 'quit':
            break
        time.sleep(0.1)

    if is_interactive() and not _stop_requested:
        print_status("Hervat...", style="cyan")


def request_stop():
    """Request graceful stop of sync."""
    global _stop_requested
    _stop_requested = True
    logger.info('Stop requested')

# Track last party sync
_last_party_sync: Optional[datetime] = None


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global _running, _stop_requested
    logger.info(f'Received signal {signum}, shutting down...')
    _running = False
    _stop_requested = True
    if is_interactive():
        print_warning("Stop signaal ontvangen - bezig met afsluiten...")


def perform_sync(full_sync: bool = False, resume_sync_id: str = None) -> dict:
    """
    Perform data synchronization with progress tracking for resume capability.

    Args:
        full_sync: If True, sync all data. If False, only recent changes.
        resume_sync_id: If provided, resume this interrupted sync instead of starting new.

    Returns:
        Dict with sync results
    """
    start_time = time.time()

    results = {
        'timestamp': datetime.now().isoformat(),
        'sync_id': None,
        'resumed': False,
        'gremia': 0,
        'meetings': 0,
        'documents_found': 0,
        'documents_downloaded': 0,
        'images_ocr': 0,
        'documents_indexed': 0,
        'integrity_ok': True,
        'schema_backup': False,
        'errors': []
    }

    meeting_provider = get_meeting_provider()
    doc_provider = get_document_provider()
    db = get_database()

    # Check for interrupted sync to resume
    interrupted = db.get_interrupted_sync()
    if interrupted and not resume_sync_id:
        resume_sync_id = interrupted['sync_id']
        logger.info(f"Found interrupted sync {resume_sync_id} at phase '{interrupted['phase']}', "
                    f"processed {interrupted['processed_items']}/{interrupted['total_items']} items")
        if is_interactive():
            print_warning(f"Hervat onderbroken sync: {interrupted['phase']} "
                         f"({interrupted['processed_items']}/{interrupted['total_items']})")
        results['resumed'] = True

    # Generate or use sync ID
    sync_id = resume_sync_id or f"sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    results['sync_id'] = sync_id
    sync_type = 'full' if full_sync else 'incremental'

    # Determine starting phase (for resume)
    start_phase = 'gremia'
    skip_until_id = None
    if interrupted and resume_sync_id:
        start_phase = interrupted['phase']
        skip_until_id = interrupted.get('last_processed_id')

    # Pre-sync: create schema backup (lightweight, metadata only)
    if start_phase == 'gremia':  # Only backup at start, not on resume
        logger.info('Creating schema backup before sync...')
        if is_interactive():
            print_status("Schema backup maken...", style="cyan")
        results['schema_backup'] = db.backup_schema()
        if results['schema_backup']:
            if is_interactive():
                print_success("Schema backup gemaakt")
        else:
            logger.warning('Schema backup failed, continuing with sync')
            if is_interactive():
                print_warning("Schema backup mislukt")

    # Determine date range
    if full_sync:
        if Config.FULL_HISTORY_SYNC:
            date_from = Config.FULL_HISTORY_START
            logger.info(f'FULL HISTORY SYNC enabled - syncing from {date_from}')
        else:
            date_from = (date.today() - timedelta(days=Config.AUTO_SYNC_DAYS)).isoformat()
    else:
        date_from = (date.today() - timedelta(days=30)).isoformat()
    date_to = date.today().isoformat()

    # Use stored date range if resuming
    if interrupted and resume_sync_id:
        date_from = interrupted.get('date_from') or date_from
        date_to = interrupted.get('date_to') or date_to

    try:
        # Phase 1: Sync gremia
        if start_phase in ['gremia']:
            logger.info('Syncing gremia...')
            if is_interactive():
                print_status("Synchroniseren gremia...", style="cyan")

            db.start_sync_progress(sync_id, sync_type, 'gremia', date_from, date_to)
            results['gremia'] = meeting_provider.sync_gremia()
            db.update_sync_progress(sync_id, processed_items=results['gremia'],
                                    phase='meetings', status='running')
            if is_interactive():
                print_success(f"Gremia: {results['gremia']} gesynchroniseerd")
            start_phase = 'meetings'  # Move to next phase

        # Phase 2: Sync meetings
        if start_phase in ['meetings']:
            logger.info(f'Syncing meetings from {date_from} to {date_to}...')
            if is_interactive():
                print_status(f"Synchroniseren vergaderingen ({date_from} → {date_to})...", style="cyan")

            db.update_sync_progress(sync_id, phase='meetings')
            meetings, docs = meeting_provider.sync_meetings(
                date_from=date_from,
                date_to=date_to,
                full_details=True,
                stop_callback=should_stop
            )
            results['meetings'] = meetings
            results['documents_found'] = docs

            # Check if stopped during meeting sync
            if should_stop():
                logger.info('Stop requested after meeting sync')
                db.update_sync_progress(sync_id, processed_items=meetings, status='interrupted')
                if is_interactive():
                    print_warning(f"Vergaderingen: {meetings} gesynchroniseerd (onderbroken)")
                raise KeyboardInterrupt("Stop requested")

            db.update_sync_progress(sync_id, processed_items=meetings, phase='documents')
            if is_interactive():
                print_success(f"Vergaderingen: {meetings} gesynchroniseerd, {docs} documenten gevonden")
            start_phase = 'documents'

        # Phase 3: Download documents
        if start_phase in ['documents'] and Config.AUTO_DOWNLOAD_DOCS:
            logger.info('Downloading pending documents...')
            pending = db.get_documents_pending_download()

            # Track resume progress
            already_processed = 0
            total_documents = len(pending)

            # If resuming, skip already processed documents
            if skip_until_id and interrupted and interrupted['phase'] == 'documents':
                original_count = len(pending)
                pending = [d for d in pending if str(d['id']) > skip_until_id]
                already_processed = original_count - len(pending)
                logger.info(f'Resuming documents: skipping {already_processed} already processed')

            pending_count = len(pending)
            db.update_sync_progress(sync_id, phase='documents', total_items=total_documents)

            if pending_count > 0:
                # Log for non-interactive (Docker/AI)
                if already_processed > 0:
                    logger.info(f'Downloading {pending_count} documents (resuming from {already_processed}/{total_documents})...')
                else:
                    logger.info(f'Downloading {total_documents} documents...')

                if is_interactive():
                    if already_processed > 0:
                        print_status(f"Downloaden {pending_count} documenten (hervat vanaf {already_processed}/{total_documents})...", style="cyan")
                    else:
                        print_status(f"Downloaden {total_documents} documenten...", style="cyan")

                # Use TUI progress or fallback progress_context
                if _use_tui():
                    # TUI mode - update directly
                    success = 0
                    failed = 0
                    for i, doc in enumerate(pending):
                        wait_if_paused()

                        if should_stop():
                            logger.info('Stop requested during document download')
                            print_warning("Stop aangevraagd - sync onderbroken")
                            db.update_sync_progress(sync_id, processed_items=i,
                                                    last_processed_id=str(doc['id']),
                                                    status='interrupted')
                            raise KeyboardInterrupt("Stop requested")

                        title = doc.get('title', 'Document')[:60]
                        doc_desc = f"{doc['notubiz_id']} {title}"
                        current = already_processed + i + 1
                        _cli_app.set_progress(current, total_documents, doc_desc)
                        _cli_app.set_paused(_paused)

                        if doc_provider.download_document(doc['id']):
                            success += 1
                        else:
                            failed += 1

                        if (i + 1) % 10 == 0:
                            db.update_sync_progress(sync_id, processed_items=i + 1,
                                                    last_processed_id=str(doc['id']))
                else:
                    # Non-TUI mode - use progress_context
                    with progress_context("Downloaden", total=total_documents, completed=already_processed) as tracker:
                        success = 0
                        failed = 0
                        for i, doc in enumerate(pending):
                            wait_if_paused()

                            if should_stop():
                                logger.info('Stop requested during document download')
                                if is_interactive():
                                    print_warning("Stop aangevraagd - sync onderbroken")
                                db.update_sync_progress(sync_id, processed_items=i,
                                                        last_processed_id=str(doc['id']),
                                                        status='interrupted')
                                raise KeyboardInterrupt("Stop requested")

                            title = doc.get('title', 'Document')[:60]
                            doc_desc = f"{doc['notubiz_id']} {title}"

                            if is_interactive():
                                tracker.update_description(doc_desc)

                            if doc_provider.download_document(doc['id']):
                                success += 1
                            else:
                                failed += 1

                            if (i + 1) % 10 == 0:
                                db.update_sync_progress(sync_id, processed_items=i + 1,
                                                        last_processed_id=str(doc['id']))

                            # Log progress every 100 documents (non-interactive/Docker)
                            if not is_interactive() and (i + 1) % 100 == 0:
                                current = already_processed + i + 1
                                pct = (current / total_documents * 100) if total_documents > 0 else 0
                                logger.info(f'Download progress: {current}/{total_documents} ({pct:.1f}%) - {success} OK, {failed} failed')

                            tracker.advance()

                results['documents_downloaded'] = success
                logger.info(f'Document download complete: {success} downloaded, {failed} failed')

                if failed > 0:
                    results['errors'].append(f'{failed} document downloads failed')
                    if is_interactive():
                        print_warning(f"Documenten: {success} gedownload, {failed} mislukt")
                elif is_interactive():
                    print_success(f"Documenten: {success} gedownload")
            else:
                logger.info('No new documents to download')
                if is_interactive():
                    print_success("Documenten: geen nieuwe downloads nodig")

            # Extract text
            doc_provider.extract_all_text()
            db.update_sync_progress(sync_id, phase='ocr')
            start_phase = 'ocr'

        # Phase 4: OCR on images
        if start_phase in ['ocr']:
            logger.info('Processing OCR on images...')
            if is_interactive():
                print_status("OCR verwerken van afbeeldingen...", style="cyan")
            db.update_sync_progress(sync_id, phase='ocr')
            ocr_success, ocr_failed = doc_provider.process_pending_ocr()
            results['images_ocr'] = ocr_success
            if ocr_success > 0 or ocr_failed > 0:
                if is_interactive():
                    if ocr_failed > 0:
                        print_warning(f"OCR: {ocr_success} verwerkt, {ocr_failed} mislukt")
                    else:
                        print_success(f"OCR: {ocr_success} afbeeldingen verwerkt")
            else:
                if is_interactive():
                    print_success("OCR: geen nieuwe afbeeldingen")
            db.update_sync_progress(sync_id, phase='indexing')
            start_phase = 'indexing'

        # Phase 5: Index documents
        if start_phase in ['indexing'] and Config.AUTO_INDEX_DOCS:
            logger.info('Indexing documents...')
            if is_interactive():
                print_status("Indexeren documenten...", style="cyan")
            db.update_sync_progress(sync_id, phase='indexing')
            index = get_document_index()
            indexed, chunks = index.index_all_documents(stop_callback=should_stop)
            results['documents_indexed'] = indexed
            db.update_sync_progress(sync_id, processed_items=indexed)
            if is_interactive():
                if should_stop():
                    print_warning(f"Geindexeerd: {indexed} documenten (onderbroken)")
                else:
                    print_success(f"Geindexeerd: {indexed} documenten, {chunks} chunks")

        # Mark sync as completed
        db.update_sync_progress(sync_id, status='completed')
        logger.info(f'Sync {sync_id} completed: {results["meetings"]} meetings, '
                    f'{results["documents_found"]} documents found')

    except Exception as e:
        logger.error(f'Sync error: {e}')
        results['errors'].append(str(e))
        # Mark sync as failed but keep progress for potential resume
        db.update_sync_progress(sync_id, status='failed', error_message=str(e))
        if is_interactive():
            print_error(f"Sync fout: {e}")

    # Post-sync: integrity check
    logger.info('Running database integrity check...')
    if is_interactive():
        print_status("Database integriteit controleren...", style="cyan")
    integrity = db.check_integrity(quick=True)
    results['integrity_ok'] = integrity['ok']
    if integrity['ok']:
        logger.info('Database integrity check passed')
        if is_interactive():
            print_success("Database integriteit OK")
    else:
        logger.error(f"Database integrity check FAILED: {integrity['details']}")
        results['errors'].append(f"Integrity check failed: {integrity['details']}")
        if is_interactive():
            print_error(f"Database integriteit MISLUKT: {integrity['details']}")

    # Post-sync: cleanup expired cache
    client = get_notubiz_client()
    expired = client.cleanup_expired_cache()
    if expired > 0:
        logger.info(f'Cleaned up {expired} expired cache files')

    # Cleanup old sync progress records
    db.cleanup_old_sync_progress(keep_days=7)

    # Print summary in interactive mode
    duration = time.time() - start_time
    if is_interactive():
        print_summary(results, duration)

    return results


def check_initial_sync_needed() -> bool:
    """Check if initial full sync is needed."""
    db = get_database()
    stats = db.get_statistics()
    return stats.get('meetings', 0) == 0


def perform_party_sync() -> dict:
    """
    Sync political parties from official sources.

    Returns:
        Dict with party sync results
    """
    global _last_party_sync

    results = {
        'timestamp': datetime.now().isoformat(),
        'parties_initialized': 0,
        'parties_updated': 0,
        'new_parties': [],
        'errors': []
    }

    try:
        logger.info('Starting party sync...')
        if is_interactive():
            print_status("Synchroniseren politieke partijen...", style="cyan")

        provider = get_election_program_provider()

        # Initialize known parties
        initialized = provider.initialize_parties()
        results['parties_initialized'] = initialized

        # Check for updates from web
        web_results = provider.check_and_update_parties_from_web()

        results['new_parties'] = web_results.get('new_parties', [])
        results['parties_updated'] = len(web_results.get('new_parties', [])) + len(web_results.get('reactivated_parties', []))
        results['errors'] = web_results.get('errors', [])

        _last_party_sync = datetime.now()

        logger.info(f"Party sync completed: {results['parties_initialized']} initialized, "
                    f"{results['parties_updated']} updated")

        if is_interactive():
            print_success(f"Partijen: {results['parties_initialized']} geinitialiseerd, "
                         f"{results['parties_updated']} bijgewerkt")

    except Exception as e:
        logger.error(f'Party sync error: {e}')
        results['errors'].append(str(e))
        if is_interactive():
            print_error(f"Partij sync fout: {e}")

    return results


def run_service():
    """Run the sync service loop."""
    global _running, _last_party_sync, _cli_app

    logger.info('=' * 60)
    logger.info('Baarn Raadsinformatie Sync Service starting...')
    logger.info(f'Sync interval: {SYNC_INTERVAL} seconds ({SYNC_INTERVAL / 3600:.1f} hours)')
    logger.info(f'Party sync interval: {PARTY_SYNC_INTERVAL} seconds ({PARTY_SYNC_INTERVAL / 3600:.1f} hours)')
    logger.info(f'Auto download docs: {Config.AUTO_DOWNLOAD_DOCS}')
    logger.info(f'Auto index docs: {Config.AUTO_INDEX_DOCS}')
    logger.info('=' * 60)

    # Start TUI if available
    if is_interactive() and is_cli_available():
        _cli_app = CLIApp("Baarn Raadsinformatie Sync Service")
        _cli_app.start()
        _cli_app.log_info(f"Sync interval: {SYNC_INTERVAL / 3600:.1f} uur")
        _cli_app.log_info(f"Auto download: {'Ja' if Config.AUTO_DOWNLOAD_DOCS else 'Nee'}")
        _cli_app.log_info(f"Auto index: {'Ja' if Config.AUTO_INDEX_DOCS else 'Nee'}")
    elif is_interactive():
        # Fallback to simple CLI
        clear_console()
        print_header("Baarn Raadsinformatie Sync Service")
        print_status(f"Sync interval: {SYNC_INTERVAL / 3600:.1f} uur")
        print_status(f"Auto download: {'Ja' if Config.AUTO_DOWNLOAD_DOCS else 'Nee'}")
        print_status(f"Auto index: {'Ja' if Config.AUTO_INDEX_DOCS else 'Nee'}")
        print_status("")
        print_status("[bold]Toetsen:[/bold]")
        print_status("  [cyan]p[/cyan] of [cyan]spatie[/cyan] = pauzeren/hervatten")
        print_status("  [cyan]q[/cyan] = stoppen (sync wordt netjes afgerond)")
        print_status("")

    # Initial party sync to populate parties
    logger.info('Performing initial party sync...')
    if is_interactive():
        print_status("Initiele partij sync...", style="bold cyan")
    party_results = perform_party_sync()
    logger.info(f'Initial party sync results: {party_results}')

    # Initial sync or full history sync
    if check_initial_sync_needed() or Config.FULL_HISTORY_SYNC:
        if Config.FULL_HISTORY_SYNC:
            logger.info(f'FULL HISTORY SYNC enabled - syncing from {Config.FULL_HISTORY_START}...')
            if is_interactive():
                print_status(f"Volledige historie sync ({Config.FULL_HISTORY_START} → vandaag)...", style="bold cyan")
        else:
            logger.info('Database empty - performing initial full sync...')
            if is_interactive():
                print_status("Database leeg - volledige sync starten...", style="bold cyan")
        results = perform_sync(full_sync=True)
        logger.info(f'Full sync results: {results}')
    else:
        logger.info('Database has data - performing incremental sync...')
        if is_interactive():
            print_status("Incrementele sync starten...", style="bold cyan")
        results = perform_sync(full_sync=False)
        logger.info(f'Incremental sync results: {results}')

    last_sync = datetime.now()

    # Main service loop
    while _running:
        try:
            now = datetime.now()

            # Check if it's time for next data sync
            elapsed = (now - last_sync).total_seconds()
            if elapsed >= SYNC_INTERVAL:
                logger.info('Starting scheduled sync...')
                if is_interactive():
                    print_status("Geplande sync starten...", style="bold cyan")
                results = perform_sync(full_sync=False)
                logger.info(f'Scheduled sync results: {results}')
                last_sync = now

            # Check if it's time for next party sync
            if _last_party_sync:
                party_elapsed = (now - _last_party_sync).total_seconds()
                if party_elapsed >= PARTY_SYNC_INTERVAL:
                    logger.info('Starting scheduled party sync...')
                    if is_interactive():
                        print_status("Geplande partij sync starten...", style="bold cyan")
                    party_results = perform_party_sync()
                    logger.info(f'Scheduled party sync results: {party_results}')

            # Sleep for a bit before checking again
            time.sleep(60)  # Check every minute

        except KeyboardInterrupt:
            logger.info('Keyboard interrupt received')
            _running = False
        except Exception as e:
            logger.error(f'Service loop error: {e}')
            time.sleep(300)  # Wait 5 minutes before retrying

    # Stop TUI
    if _cli_app:
        _cli_app.stop()

    logger.info('Sync service stopped')


def main():
    """Main entry point."""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if sys.platform == 'win32':
        # Windows-specific signal handling
        signal.signal(signal.SIGBREAK, signal_handler)

    run_service()


if __name__ == '__main__':
    main()
