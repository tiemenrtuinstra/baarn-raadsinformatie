#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interactive CLI Application Framework.

Provides a full-screen CLI interface with:
- Header banner
- Scrolling log area
- Progress bar
- Fixed status bar at bottom with keyboard shortcuts
"""

import sys
from typing import Optional, Callable
from datetime import datetime

# Check for TTY and Rich
INTERACTIVE = sys.stdout.isatty()

if INTERACTIVE:
    try:
        from rich.console import Console, Group
        from rich.layout import Layout
        from rich.panel import Panel
        from rich.text import Text
        from rich.table import Table
        from rich.live import Live
        from rich import box
        RICH_AVAILABLE = True
    except ImportError:
        RICH_AVAILABLE = False
        INTERACTIVE = False
else:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


class CLIApp:
    """Full-screen CLI application with status bar."""

    def __init__(self, title: str = "Application"):
        self.title = title
        self.logs: list[tuple[str, str]] = []  # (style, message)
        self.max_logs = 50  # Keep last N log entries
        self.progress_text = ""
        self.progress_pct = 0.0
        self.progress_current = 0
        self.progress_total = 0
        self.status_text = ""
        self.paused = False
        self.live: Optional[Live] = None
        self._controls = [
            ("p/spatie", "pauzeren"),
            ("q", "stoppen"),
        ]

    def set_controls(self, controls: list[tuple[str, str]]):
        """Set the keyboard controls to display."""
        self._controls = controls

    def _make_layout(self) -> "Layout":
        """Create the screen layout."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),  # Log area with progress integrated
            Layout(name="status", size=1),
        )
        return layout

    def _render_header(self) -> "Panel":
        """Render the header panel."""
        return Panel(
            Text(self.title, style="bold white", justify="center"),
            style="blue",
            box=box.DOUBLE,
        )

    def _render_logs(self) -> "Panel":
        """Render the log area with progress at bottom."""
        table = Table.grid(padding=(0, 1))
        table.add_column("time", style="dim", width=8)
        table.add_column("message")

        # Show last N logs that fit
        visible_logs = self.logs[-25:]  # Leave room for progress
        for timestamp, style, message in visible_logs:
            # Parse Rich markup in message
            try:
                msg_text = Text.from_markup(message)
            except Exception:
                msg_text = Text(message)
            table.add_row(timestamp, msg_text)

        # Add progress bar at bottom of log area
        if self.progress_total > 0:
            table.add_row("", Text(""))  # Spacer
            table.add_row("", Text(f"  {self.progress_text[:80]}", style="cyan"))

            bar_width = 50
            filled = int(bar_width * self.progress_pct / 100)
            bar_text = Text("  ")
            bar_text.append("━" * filled, style="green")
            bar_text.append("━" * (bar_width - filled), style="dim")
            bar_text.append(f" {self.progress_pct:5.1f}% ", style="bold white")
            bar_text.append(f"({self.progress_current}/{self.progress_total})", style="dim")
            if self.paused:
                bar_text.append("  GEPAUZEERD", style="bold yellow")
            table.add_row("", bar_text)

        return Panel(table, title="Log", border_style="dim")

    def _render_progress(self) -> "Panel":
        """Render the progress bar."""
        if self.progress_total > 0:
            bar_width = 60
            filled = int(bar_width * self.progress_pct / 100)
            bar = "━" * filled + "╸" + "━" * (bar_width - filled - 1)

            progress_line = Text()
            progress_line.append("  ")
            progress_line.append(self.progress_text[:80], style="cyan")
            progress_line.append("\n  ")
            progress_line.append(bar[:filled], style="green")
            progress_line.append(bar[filled:], style="dim white")
            progress_line.append(f" {self.progress_pct:5.1f}% ", style="bold")
            progress_line.append(f"({self.progress_current}/{self.progress_total})", style="dim")

            if self.paused:
                progress_line.append("  [GEPAUZEERD]", style="bold yellow")
        else:
            progress_line = Text("  Wachten...", style="dim")

        return Panel(progress_line, border_style="dim", box=box.SIMPLE)

    def _render_status(self) -> "Text":
        """Render the status bar at the bottom."""
        status = Text()

        # Keyboard shortcuts
        for key, action in self._controls:
            status.append(f" [{key}] ", style="bold cyan on dark_blue")
            status.append(f"{action} ", style="white on dark_blue")

        # Fill remaining space
        remaining = console.width - len(status.plain) if console else 80
        status.append(" " * max(0, remaining), style="on dark_blue")

        return status

    def render(self) -> "Layout":
        """Render the full layout."""
        layout = self._make_layout()
        layout["header"].update(self._render_header())
        layout["body"].update(self._render_logs())  # Progress is now inside logs
        layout["status"].update(self._render_status())
        return layout

    def log(self, message: str, style: str = ""):
        """Add a log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append((timestamp, style, message))
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]
        self._refresh()

    def log_success(self, message: str):
        """Log a success message."""
        self.log(f"[green]OK[/green] {message}")

    def log_error(self, message: str):
        """Log an error message."""
        self.log(f"[red]X[/red] {message}", style="red")

    def log_warning(self, message: str):
        """Log a warning message."""
        self.log(f"[yellow]![/yellow] {message}", style="yellow")

    def log_info(self, message: str):
        """Log an info message."""
        self.log(f"[cyan]>[/cyan] {message}")

    def set_progress(self, current: int, total: int, text: str = ""):
        """Update progress bar."""
        self.progress_current = current
        self.progress_total = total
        self.progress_pct = (current / total * 100) if total > 0 else 0
        self.progress_text = text
        self._refresh()

    def set_paused(self, paused: bool):
        """Set paused state."""
        self.paused = paused
        self._refresh()

    def _refresh(self):
        """Refresh the display."""
        if self.live:
            self.live.update(self.render())

    def start(self):
        """Start the live display."""
        if not INTERACTIVE or not RICH_AVAILABLE:
            return

        # Clear screen
        console.clear()

        self.live = Live(
            self.render(),
            console=console,
            refresh_per_second=4,
            screen=True,
        )
        self.live.start()

    def stop(self):
        """Stop the live display."""
        if self.live:
            self.live.stop()
            self.live = None


# Singleton instance
_app: Optional[CLIApp] = None


def get_cli_app(title: str = "Application") -> CLIApp:
    """Get or create the CLI app instance."""
    global _app
    if _app is None:
        _app = CLIApp(title)
    return _app


def is_cli_available() -> bool:
    """Check if interactive CLI is available."""
    return INTERACTIVE and RICH_AVAILABLE
