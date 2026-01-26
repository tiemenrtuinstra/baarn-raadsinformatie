#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image Deduplication Migration Script

Scans existing images, finds duplicates using perceptual hashing,
and consolidates them into the shared/ directory.
"""

import os
import sys
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image
import imagehash

from core.config import Config
from core.database import Database
from shared.cli_progress import progress_context, is_interactive

# Setup console - fallback to print for non-interactive
try:
    from rich.console import Console
    console = Console()
except ImportError:
    # Fallback console that just uses print
    class FallbackConsole:
        def print(self, *args, **kwargs):
            # Strip rich markup for plain output
            text = ' '.join(str(a) for a in args)
            import re
            text = re.sub(r'\[/?[^\]]+\]', '', text)
            print(text)
    console = FallbackConsole()


def compute_phash(image_path: Path) -> str | None:
    """Compute perceptual hash for an image."""
    try:
        with Image.open(image_path) as img:
            return str(imagehash.phash(img))
    except Exception as e:
        return None


def scan_images(images_dir: Path) -> List[Tuple[Path, str]]:
    """Scan all images and compute hashes."""
    images = []

    # Find all image files
    all_files = []
    for doc_dir in images_dir.iterdir():
        if doc_dir.is_dir() and doc_dir.name.startswith('doc_'):
            for img_file in doc_dir.iterdir():
                if img_file.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                    all_files.append(img_file)

    console.print(f"[cyan]Gevonden: {len(all_files)} afbeeldingen om te scannen[/cyan]")

    with progress_context("Hashes berekenen...", total=len(all_files)) as tracker:
        for img_path in all_files:
            tracker.update_description(img_path.name[:60])

            phash = compute_phash(img_path)
            if phash:
                images.append((img_path, phash))

            tracker.advance()

    return images


def find_duplicates(images: List[Tuple[Path, str]]) -> Dict[str, List[Path]]:
    """Group images by hash to find duplicates."""
    hash_groups = defaultdict(list)

    for img_path, phash in images:
        hash_groups[phash].append(img_path)

    # Filter to only groups with duplicates
    duplicates = {h: paths for h, paths in hash_groups.items() if len(paths) > 1}

    return duplicates


def migrate_to_shared(
    duplicates: Dict[str, List[Path]],
    shared_dir: Path,
    db: Database,
    dry_run: bool = False
) -> Dict:
    """Move duplicate images to shared directory and update database."""

    stats = {
        'total_duplicates': 0,
        'files_moved': 0,
        'files_deleted': 0,
        'space_saved_bytes': 0,
        'errors': []
    }

    shared_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[cyan]Verwerken van {len(duplicates)} groepen met duplicaten...[/cyan]")

    with progress_context("Dedupliceren...", total=len(duplicates)) as tracker:
        for phash, paths in duplicates.items():
            tracker.update_description(f"Hash {phash[:8]}... ({len(paths)} bestanden)")

            stats['total_duplicates'] += len(paths) - 1  # All but one are duplicates

            # Sort by path to get consistent results
            paths = sorted(paths)

            # First file becomes the canonical one in shared/
            canonical = paths[0]
            ext = canonical.suffix.lower()
            shared_path = shared_dir / f"{phash}{ext}"

            try:
                if not dry_run:
                    # Check if already in database
                    existing = db.find_unique_image_by_hash(phash)

                    if existing:
                        unique_id = existing['id']
                    else:
                        # Move canonical to shared
                        if not shared_path.exists():
                            shutil.copy2(canonical, shared_path)
                            stats['files_moved'] += 1

                        # Get file info
                        file_size = shared_path.stat().st_size
                        try:
                            with Image.open(shared_path) as img:
                                width, height = img.size
                        except:
                            width, height = 0, 0

                        # Add to unique_images table
                        unique_id = db.add_unique_image(
                            image_hash=phash,
                            file_path=str(shared_path),
                            mime_type=f"image/{ext[1:]}",
                            width=width,
                            height=height,
                            file_size=file_size,
                            reference_count=len(paths)
                        )

                    # Update document_images references and delete duplicates
                    for i, img_path in enumerate(paths):
                        # Update database reference by exact file_path match
                        full_path = str(img_path)
                        db.execute_sql('''
                            UPDATE document_images
                            SET image_hash = ?, unique_image_id = ?, file_path = ?
                            WHERE file_path = ?
                        ''', (phash, unique_id, str(shared_path), full_path))

                        # Delete the original file (we have it in shared/)
                        if img_path.exists() and img_path != shared_path:
                            file_size = img_path.stat().st_size
                            img_path.unlink()
                            stats['files_deleted'] += 1
                            stats['space_saved_bytes'] += file_size
                else:
                    # Dry run - just count
                    for img_path in paths[1:]:
                        if img_path.exists():
                            stats['space_saved_bytes'] += img_path.stat().st_size
                            stats['files_deleted'] += 1
                    stats['files_moved'] += 1

            except Exception as e:
                stats['errors'].append(f"{phash}: {str(e)}")

            tracker.advance()

    return stats


def cleanup_empty_dirs(images_dir: Path):
    """Remove empty doc_* directories."""
    removed = 0
    for doc_dir in images_dir.iterdir():
        if doc_dir.is_dir() and doc_dir.name.startswith('doc_'):
            # Check if empty
            if not any(doc_dir.iterdir()):
                doc_dir.rmdir()
                removed += 1
    return removed


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Deduplicate images using perceptual hashing')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--cleanup', action='store_true', help='Also remove empty directories')
    args = parser.parse_args()

    images_dir = Config.DATA_DIR / 'images'
    shared_dir = images_dir / 'shared'

    if not images_dir.exists():
        console.print("[red]Images directory niet gevonden![/red]")
        return

    console.print("[bold cyan]Image Deduplication[/bold cyan]")
    console.print(f"Images directory: {images_dir}")
    console.print(f"Shared directory: {shared_dir}")
    if args.dry_run:
        console.print("[yellow]DRY RUN - geen wijzigingen worden gemaakt[/yellow]")
    console.print()

    # Initialize database
    db = Database()

    # Step 1: Scan images
    console.print("[bold]Stap 1: Afbeeldingen scannen en hashes berekenen[/bold]")
    images = scan_images(images_dir)
    console.print(f"[green]OK: {len(images)} afbeeldingen gescand[/green]\n")

    # Step 2: Find duplicates
    console.print("[bold]Stap 2: Duplicaten identificeren[/bold]")
    duplicates = find_duplicates(images)

    total_duplicate_files = sum(len(paths) - 1 for paths in duplicates.values())
    console.print(f"[green]OK: {len(duplicates)} unieke afbeeldingen met duplicaten gevonden[/green]")
    console.print(f"[green]OK: {total_duplicate_files} duplicate bestanden[/green]\n")

    if not duplicates:
        console.print("[green]Geen duplicaten gevonden - klaar![/green]")
        return

    # Step 3: Migrate
    console.print("[bold]Stap 3: Migreren naar shared directory[/bold]")
    stats = migrate_to_shared(duplicates, shared_dir, db, dry_run=args.dry_run)

    # Results
    console.print("\n[bold cyan]Resultaten:[/bold cyan]")
    console.print(f"  Duplicate groepen: {len(duplicates)}")
    console.print(f"  Bestanden verplaatst naar shared: {stats['files_moved']}")
    console.print(f"  Duplicate bestanden verwijderd: {stats['files_deleted']}")

    space_mb = stats['space_saved_bytes'] / (1024 * 1024)
    console.print(f"  Schijfruimte bespaard: {space_mb:.1f} MB")

    if stats['errors']:
        console.print(f"\n[red]Fouten ({len(stats['errors'])}):[/red]")
        for err in stats['errors'][:10]:
            console.print(f"  [red]•[/red] {err}")
        if len(stats['errors']) > 10:
            console.print(f"  ... en {len(stats['errors']) - 10} meer")

    # Cleanup empty directories
    if args.cleanup and not args.dry_run:
        console.print("\n[bold]Lege mappen opruimen...[/bold]")
        removed = cleanup_empty_dirs(images_dir)
        console.print(f"[green]OK: {removed} lege mappen verwijderd[/green]")

    console.print("\n[green]Klaar![/green]")


if __name__ == '__main__':
    main()
