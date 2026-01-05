from __future__ import annotations

import asyncio
import time

import typer
from rich.console import Console
from rich.panel import Panel
from rich.status import Status

from ollabridge.cloud.api_client import CloudApiClient
from ollabridge.cloud.device_config import CloudDeviceCredentials, load_cloud_device_credentials, save_cloud_device_credentials
from ollabridge.node.agent import CloudDeviceConfig, NodeConfig, default_node_id, run_cloud_device, run_node
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
    """Join this machine to an OllaBridge Local Control Plane (outbound-only)."""

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


@app.command("cloud-pair")
def cloud_pair(
    cloud: str = typer.Option(..., "--cloud", help="OllaBridge Cloud base URL (e.g., https://ollabridge.example)"),
    runtime_base_url: str = typer.Option("http://127.0.0.1:11434", "--runtime", help="Local runtime base URL"),
    model: str = typer.Option("", "--ensure-model", help="If set, ensure this chat model exists"),
    poll_interval: int = typer.Option(3, "--poll-interval", help="Seconds between /device/poll calls"),
    max_wait: int = typer.Option(1800, "--max-wait", help="Max seconds to wait for approval"),
):
    """
    Pair this PC with OllaBridge Cloud:
      - POST /device/start
      - show user_code + verification_url
      - poll POST /device/poll until approved
      - save device_id + device_token to ~/.ollabridge/cloud_device.json
    """
    if not is_ollama_installed():
        install_ollama()
    ensure_ollama_server_running()
    if model:
        ensure_model(model)

    client = CloudApiClient(cloud_url=cloud)

    try:
        start = client.device_start()
        console.print(
            Panel(
                f"[bold]User code:[/bold] [bold yellow]{start.user_code}[/bold yellow]\n"
                f"[bold]Verify at:[/bold] {start.verification_url}\n\n"
                f"Open the verification URL, log in, and enter the code.\n"
                f"This code expires in ~{start.expires_in} seconds.",
                title="🔗 OllaBridge Cloud Pairing",
            )
        )

        deadline = time.time() + max_wait
        with Status("Waiting for approval...", console=console) as st:
            while time.time() < deadline:
                pol = client.device_poll(device_code=start.device_code)
                if pol.status == "approved" and pol.approved:
                    creds = CloudDeviceCredentials(
                        cloud_url=cloud.rstrip("/"),
                        device_id=pol.approved.device_id,
                        device_token=pol.approved.device_token,
                    )
                    path = save_cloud_device_credentials(creds)
                    st.stop()
                    console.print(
                        Panel(
                            f"[bold green]✅ Paired successfully[/bold green]\n\n"
                            f"[bold]Cloud:[/bold] {creds.cloud_url}\n"
                            f"[bold]Device ID:[/bold] {creds.device_id}\n"
                            f"[bold]Saved credentials:[/bold] {path}\n\n"
                            f"Next: run [bold]ollabridge-node cloud-connect[/bold]",
                            title="✅ Pairing Complete",
                        )
                    )
                    return
                if pol.status == "expired":
                    st.stop()
                    console.print("[bold red]Pairing expired.[/bold red] Run cloud-pair again.")
                    raise typer.Exit(code=2)

                time.sleep(poll_interval)

        console.print("[bold red]Timed out waiting for approval.[/bold red]")
        raise typer.Exit(code=3)
    finally:
        client.close()


@app.command("cloud-connect")
def cloud_connect(
    cloud: str = typer.Option("", "--cloud", help="Override cloud URL; otherwise use saved credentials"),
    device_id: str = typer.Option("", "--device-id", help="Override device_id; otherwise use saved credentials"),
    device_token: str = typer.Option("", "--device-token", help="Override device_token; otherwise use saved credentials"),
    runtime_base_url: str = typer.Option("http://127.0.0.1:11434", "--runtime", help="Local runtime base URL"),
    model: str = typer.Option("", "--ensure-model", help="If set, ensure this chat model exists"),
):
    """
    Connect this PC to OllaBridge Cloud relay using saved device credentials
    and serve requests over WebSocket.
    """
    if not is_ollama_installed():
        install_ollama()
    ensure_ollama_server_running()
    if model:
        ensure_model(model)

    saved = load_cloud_device_credentials()
    cloud_url = cloud.strip() or (saved.cloud_url if saved else "")
    did = device_id.strip() or (saved.device_id if saved else "")
    tok = device_token.strip() or (saved.device_token if saved else "")

    if not (cloud_url and did and tok):
        console.print(
            "[bold red]Missing Cloud credentials.[/bold red]\n"
            "Run: [bold]ollabridge-node cloud-pair --cloud https://...[/bold]\n"
            "or provide --cloud, --device-id, --device-token."
        )
        raise typer.Exit(code=2)

    cfg = CloudDeviceConfig(cloud_url=cloud_url, device_id=did, device_token=tok, runtime_base_url=runtime_base_url)

    console.print(
        Panel(
            f"[bold green]✅ Cloud device online[/bold green]\n\n"
            f"[bold]Cloud:[/bold] {cloud_url}\n"
            f"[bold]Device ID:[/bold] {did}\n"
            f"[bold]Runtime:[/bold] {runtime_base_url}\n",
            title="☁️  OllaBridge Cloud Device",
        )
    )

    asyncio.run(run_cloud_device(cfg))


if __name__ == "__main__":
    app()
