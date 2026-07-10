"""Local CLI entrypoint."""
from __future__ import annotations
import argparse
import asyncio
import os
from pathlib import Path

from rich.console import Console

from .config import settings
from .registry import MCPRegistry
from .gateway_client import GatewayClient
from .planner import Planner, BedrockReasoner

console = Console()


async def _run(request: str, no_model: bool) -> None:
    settings.validate()
    registry_dir = Path(__file__).resolve().parent.parent / "mcp_registry"
    registry = MCPRegistry.load(registry_dir)
    gateway = GatewayClient(settings.gateway_url, settings.region)

    # Wire a Bedrock reasoner unless disabled (or credentials absent for a dry run).
    reasoner = None
    if not no_model:
        reasoner = BedrockReasoner(settings.planner_model_id, settings.region)

    planner = Planner(registry, gateway, reasoner=reasoner, mode=settings.planner_mode)

    console.rule("[bold]MCP Registry")
    console.print(registry.catalog_for_prompt())
    console.rule(f"[bold]Planning (mode={settings.planner_mode})")
    result = await planner.run(request)
    console.print(result.decision_log.to_markdown())
    console.rule("[bold]Answer")
    console.print(result.answer)


def main() -> None:
    parser = argparse.ArgumentParser(description="AWS MCP Workflow Orchestrator")
    parser.add_argument("request", help="Natural-language engineering request")
    parser.add_argument(
        "--no-model",
        action="store_true",
        help="Skip Bedrock; print the plan-shaped decision log only (offline dry run).",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.request, args.no_model))


if __name__ == "__main__":
    main()
