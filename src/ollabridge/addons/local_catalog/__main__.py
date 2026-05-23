"""
CLI: ``python -m ollabridge.addons.local_catalog``.

Commands:

    sync           — pull the local runtime catalog, score, persist
    stats          — print the local catalog summary
    show           — list top-recommended models
    pull <model>   — start an ``ollama pull`` and stream progress
    test <router>  — health-check a single model
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from ollabridge.addons.local_catalog.client import LocalRuntimeClient
from ollabridge.addons.local_catalog.health import LocalModelHealthChecker
from ollabridge.addons.local_catalog.pulls import LocalPullManager
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.sync_service import LocalCatalogSyncService
from ollabridge.core.settings import settings


def _bootstrap() -> tuple[
    LocalCatalogRepository, LocalCatalogSyncService, LocalRuntimeClient,
    LocalModelHealthChecker, LocalPullManager,
]:
    repo = LocalCatalogRepository()
    repo.load()
    svc = LocalCatalogSyncService(repository=repo)
    client = LocalRuntimeClient(base_url=settings.OLLAMA_BASE_URL)
    health = LocalModelHealthChecker(repository=repo)
    pulls = LocalPullManager(repository=repo)
    return repo, svc, client, health, pulls


async def _cmd_sync(args: argparse.Namespace) -> int:
    _repo, svc, client, _hc, _pulls = _bootstrap()
    node_id = args.node or settings.LOCAL_NODE_ID or "local"
    result = await svc.sync_node(node_id=node_id, client=client, auto_enable_top=args.auto_enable)
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.ok else 1


async def _cmd_stats(args: argparse.Namespace) -> int:
    repo, *_ = _bootstrap()
    print(json.dumps(repo.stats(args.node).model_dump(mode="json"), indent=2))
    return 0


async def _cmd_show(args: argparse.Namespace) -> int:
    repo, *_ = _bootstrap()
    top = repo.list_top(args.node)[: args.limit]
    if not top:
        print("(no top-recommended models — run `sync` first)")
        return 0
    for m in top:
        print(
            f"#{m.rank}  {m.router_model_id}   {m.display_name or ''}\n"
            f"        score={m.score:.3f} param={m.parameter_size or '?'} "
            f"quant={m.quantization or '?'} status={m.setup_status.value} "
            f"latency_ms={m.latency_observed_ms or '?'}"
        )
    return 0


async def _cmd_pull(args: argparse.Namespace) -> int:
    repo, _svc, client, _hc, pulls = _bootstrap()
    node_id = args.node or settings.LOCAL_NODE_ID or "local"
    progress = await pulls.start(node_id=node_id, external_model_id=args.model, client=client)
    print(f"pull started: node={progress.node_id} model={progress.external_model_id}")
    # Crude progress-display loop.
    last_pct = -1.0
    while True:
        await asyncio.sleep(1.0)
        p = pulls.get(node_id, args.model)
        if not p:
            break
        if p.progress_pct != last_pct:
            print(f"  {p.status}: {p.progress_pct}%  ({p.completed_bytes}/{p.total_bytes} bytes)")
            last_pct = p.progress_pct
        if p.status in ("completed", "error"):
            print(f"final: {p.status}{' — ' + p.error if p.error else ''}")
            return 0 if p.status == "completed" else 1
    return 1


async def _cmd_test(args: argparse.Namespace) -> int:
    repo, _svc, client, health, _pulls = _bootstrap()
    ok = await health.check_one(args.router_model_id, client, force=True)
    m = repo.get(args.router_model_id)
    if not m:
        print(f"model not found: {args.router_model_id}", file=sys.stderr)
        return 2
    print(json.dumps({
        "ok": ok,
        "router_model_id": m.router_model_id,
        "setup_status": m.setup_status.value,
        "latency_ms": m.latency_observed_ms,
        "error": m.last_error,
    }, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="local-catalog", description="OllaBridge local catalog CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="Discover local models and refresh catalog")
    p_sync.add_argument("--node", default=None, help="Override node id (default: settings.LOCAL_NODE_ID)")
    p_sync.add_argument("--auto-enable", type=int, default=3)
    p_sync.set_defaults(func=_cmd_sync)

    p_stats = sub.add_parser("stats", help="Print local catalog stats")
    p_stats.add_argument("--node", default=None)
    p_stats.set_defaults(func=_cmd_stats)

    p_show = sub.add_parser("show", help="Print top-recommended models")
    p_show.add_argument("--node", default=None)
    p_show.add_argument("--limit", type=int, default=5)
    p_show.set_defaults(func=_cmd_show)

    p_pull = sub.add_parser("pull", help="Pull a model via the local runtime")
    p_pull.add_argument("--node", default=None)
    p_pull.add_argument("model", help="Model tag, e.g. qwen2.5:14b")
    p_pull.set_defaults(func=_cmd_pull)

    p_test = sub.add_parser("test", help="Run a 1-token probe against one model")
    p_test.add_argument("router_model_id", help="<node_id>:<model_tag>")
    p_test.set_defaults(func=_cmd_test)

    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
