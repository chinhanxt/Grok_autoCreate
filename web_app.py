#!/usr/bin/env python3
"""
Grok & x.ai Account Creator - Web UI Launcher
"""
import sys
import os
import argparse
import uvicorn
from rich.console import Console
from rich.panel import Panel

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Launch Grok & x.ai Account Creator Web UI")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7860, help="Port to bind (default: 7860)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    # Add project root to sys.path
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        from core.tor_launcher import ensure_local_tors
        ensure_local_tors()
    except Exception as exc:
        console.print(f"[bold yellow]⚠ Tor chưa online:[/bold yellow] {exc}")

    url = f"http://{args.host}:{args.port}"
    console.print(Panel(
        f"[bold cyan]⚡ Grok & x.ai Account Creator Web Dashboard ⚡[/bold cyan]\n\n"
        f"[bold green]✔ Server Running At:[/bold green] [bold underline]{url}[/bold underline]\n"
        f"[dim]Powered by FastAPI & Scrapling Stealth Camoufox Engine[/dim]",
        border_style="cyan"
    ))

    uvicorn.run(
        "web.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
