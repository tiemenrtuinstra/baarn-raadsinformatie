#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI Progress Output Helper.

Provides rich progress output when running interactively (TTY),
falls back to standard logging when running as background service.
"""

import sys
from contextlib import contextmanager
from typing import Optional, Iterator

# Detect interactive mode
INTERACTIVE = sys.stdout.isatty()

if INTERACTIVE:
    try:
        from rich.console import Console
        from rich.progress import (
            Progress,
            SpinnerColumn,
            TextColumn,
            BarColumn,
            TaskProgressColumn,
            TimeElapsedColumn,
        )
        from rich.table import Table
        from rich.panel import Panel
        from rich import box
        RICH_AVAILABLE = True
    except ImportError:
        RICH_AVAILABLE = False
        INTERACTIVE = False
else:
    RICH_AVAILABLE = False

# Console instance for interactive output
console = Console() if RICH_AVAILABLE else None


def is_interactive() -> bool:
    """Check if running in interactive mode with rich support."""
    return INTERACTIVE and RICH_AVAILABLE


def print_header(title: str):
    """Print a header/banner."""
    if is_interactive():
        console.print()
        console.print(Panel(title, style="bold blue", box=box.DOUBLE))
        console.print()
    # Non-interactive: rely on logging


def print_status(message: str, style: str = ""):
    """Print a status message."""
    if is_interactive():
        console.print(f"  {message}", style=style)
    # Non-interactive: rely on logging


def print_success(message: str):
    """Print a success message."""
    if is_interactive():
        console.print(f"  [green]✓[/green] {message}")


def print_error(message: str):
    """Print an error message."""
    if is_interactive():
        console.print(f"  [red]✗[/red] {message}")


def print_warning(message: str):
    """Print a warning message."""
    if is_interactive():
        console.print(f"  [yellow]![/yellow] {message}")


@contextmanager
def progress_context(
    description: str = "Processing...",
    total: Optional[int] = None,
    completed: int = 0
) -> Iterator[Optional["ProgressTracker"]]:
    """
    Context manager for progress tracking.

    In interactive mode, shows a two-line progress display:
    Line 1: Current item description
    Line 2: Progress bar with percentage

    Args:
        description: Initial description text
        total: Total number of items
        completed: Number of items already completed (for resume)

    Usage:
        with progress_context("Downloading", total=100, completed=50) as tracker:
            for item in items:
                tracker.update_description(f"Processing {item}")
                # do work
                tracker.advance()
    """
    if is_interactive() and total is not None:
        from rich.live import Live
        from rich.table import Table
        from rich.text import Text

        class TwoLineProgress:
            def __init__(self, total: int, completed: int = 0):
                self.total = total
                self.completed = completed
                self.item_text = ""
                self.description = description

            def render(self):
                # Line 1: Current item
                table = Table.grid(padding=0)
                table.add_column()

                # Item line (truncated to fit)
                item_display = self.item_text[:100] if self.item_text else self.description
                table.add_row(Text(f"  {self.description}: {item_display}", style="cyan"))

                # Progress bar line
                pct = (self.completed / self.total * 100) if self.total > 0 else 0
                bar_width = 50
                filled = int(bar_width * self.completed / self.total) if self.total > 0 else 0
                bar = "[green]" + "━" * filled + "[/green][white]" + "━" * (bar_width - filled) + "[/white]"

                # Time remaining estimate
                progress_text = f"  {bar} {pct:5.1f}% ({self.completed}/{self.total})"
                table.add_row(Text.from_markup(progress_text))

                return table

        progress = TwoLineProgress(total, completed)

        with Live(progress.render(), console=console, refresh_per_second=4, transient=True) as live:
            tracker = TwoLineTracker(progress, live)
            yield tracker
    else:
        yield DummyTracker()


class ProgressTracker:
    """Wrapper for rich progress tracking."""

    def __init__(self, progress: "Progress", task_id: int):
        self.progress = progress
        self.task_id = task_id

    def advance(self, amount: int = 1):
        """Advance progress by amount."""
        self.progress.advance(self.task_id, amount)

    def update_description(self, description: str):
        """Update the task description."""
        self.progress.update(self.task_id, description=description)

    def update(self, completed: int = None, description: str = None):
        """Update progress with new values."""
        kwargs = {}
        if completed is not None:
            kwargs['completed'] = completed
        if description is not None:
            kwargs['description'] = description
        if kwargs:
            self.progress.update(self.task_id, **kwargs)


class TwoLineTracker:
    """Progress tracker with two-line display using Rich Live."""

    def __init__(self, progress, live):
        self.progress = progress
        self.live = live

    def advance(self, amount: int = 1):
        """Advance progress by amount."""
        self.progress.completed += amount
        self.live.update(self.progress.render())

    def update_description(self, description: str):
        """Update the current item description."""
        self.progress.item_text = description
        self.live.update(self.progress.render())

    def update(self, completed: int = None, description: str = None):
        """Update progress with new values."""
        if completed is not None:
            self.progress.completed = completed
        if description is not None:
            self.progress.item_text = description
        self.live.update(self.progress.render())


class ProgressTrackerTwoLine:
    """Legacy progress tracker (kept for compatibility)."""

    def __init__(self, progress: "Progress", task_id: int):
        self.progress = progress
        self.task_id = task_id

    def advance(self, amount: int = 1):
        """Advance progress by amount."""
        self.progress.advance(self.task_id, amount)

    def update_description(self, description: str):
        """Update the current item description (shown on line above bar)."""
        self.progress.update(self.task_id, item=description)

    def update(self, completed: int = None, description: str = None):
        """Update progress with new values."""
        kwargs = {}
        if completed is not None:
            kwargs['completed'] = completed
        if description is not None:
            kwargs['item'] = description
        if kwargs:
            self.progress.update(self.task_id, **kwargs)


class DummyTracker:
    """Dummy tracker for non-interactive mode."""

    def advance(self, amount: int = 1):
        pass

    def update_description(self, description: str):
        pass

    def update(self, completed: int = None, description: str = None):
        pass


def print_summary(results: dict, duration_seconds: float = None):
    """Print a summary table of sync results."""
    if not is_interactive():
        return

    console.print()

    # Create summary table
    table = Table(
        title="Sync Voltooid",
        box=box.ROUNDED,
        show_header=False,
        title_style="bold green",
    )
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")

    if duration_seconds:
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)
        if minutes > 0:
            table.add_row("Duur", f"{minutes}m {seconds}s")
        else:
            table.add_row("Duur", f"{seconds}s")

    if 'gremia' in results:
        table.add_row("Gremia", str(results['gremia']))

    if 'meetings' in results:
        table.add_row("Vergaderingen", str(results['meetings']))

    if 'documents_found' in results:
        table.add_row("Documenten gevonden", str(results['documents_found']))

    if 'documents_downloaded' in results:
        table.add_row("Documenten gedownload", str(results['documents_downloaded']))

    if 'documents_indexed' in results:
        table.add_row("Documenten geindexeerd", str(results['documents_indexed']))

    if results.get('errors'):
        table.add_row("Fouten", f"[red]{len(results['errors'])}[/red]")

    console.print(table)

    # Print errors if any
    if results.get('errors'):
        console.print()
        console.print("[red]Fouten:[/red]")
        for error in results['errors']:
            console.print(f"  [red]•[/red] {error}")

    console.print()
