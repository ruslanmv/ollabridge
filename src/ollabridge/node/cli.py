from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel

from ollabridge.node.agent import NodeConfig, default_node_id, run_node
from ollabridge.utils.installer import (
    ensure_model,
    ensure_ollama_server_running,
    install_ollama,
    is_ollama_installed,
)


app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def join(
    control: str = typer.Option(..., "--control", help="Control Plane base URL (e.g., https://gateway.example)"),
    token: str = typer.Option(..., "--token", help="Enrollment token from the Control Plane"),
    runtime_base_url: str = typer.Option("http://127.0.0.1:11434", "--runtime", help="Local runtime base URL"),
    node_id: str = typer.Option("", "--node-id", help="Stable node identifier"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags for routing"),
    capacity: int = typer.Option(1, "--capacity", help="Concurrent capacity hint"),
    model: str = typer.Option("", "--ensure-model", help="If set, ensure this chat model exists"),
):
    """Join this machine to an OllaBridge Control Plane (outbound-only)."""

    if not is_ollama_installed():
        install_ollama()
    ensure_ollama_server_running()
    if model:
        ensure_model(model)

    nid = node_id.strip() or default_node_id()
    t = [x.strip() for x in tags.split(",") if x.strip()]
    cfg = NodeConfig(control=control, token=token, node_id=nid, runtime_base_url=runtime_base_url, tags=t, capacity=capacity)

    console.print(
        Panel(
            f"[bold green]✅ Node online[/bold green]\n\n"
            f"[bold]Control:[/bold] {control}\n"
            f"[bold]Node ID:[/bold] {nid}\n"
            f"[bold]Runtime:[/bold] {runtime_base_url}\n"
            f"[bold]Tags:[/bold] {', '.join(t) or '-'}\n",
            title="🛰️  OllaBridge Node",
        )
    )

    asyncio.run(run_node(cfg))


if __name__ == "__main__":
    app()
