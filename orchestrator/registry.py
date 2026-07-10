"""Pluggable MCP registry.

Loads one capability manifest (YAML) per MCP server from ``mcp_registry/``.
Adding a server is a config change, not a code change — the planner reasons over
these manifests rather than hard-coding server names.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass
class Capability:
    capability: str
    good_for: str


@dataclass
class MCPServerManifest:
    server: str
    gateway_target: str
    domains: list[str]
    provides: list[Capability]
    preconditions: list[str]

    @classmethod
    def from_dict(cls, d: dict) -> "MCPServerManifest":
        return cls(
            server=d["server"],
            gateway_target=d["gateway_target"],
            domains=list(d.get("domains", [])),
            provides=[Capability(**c) for c in d.get("provides", [])],
            preconditions=list(d.get("preconditions", [])),
        )


class MCPRegistry:
    def __init__(self, manifests: list[MCPServerManifest]):
        self._manifests = manifests

    @classmethod
    def load(cls, directory: str | Path) -> "MCPRegistry":
        directory = Path(directory)
        manifests = []
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            manifests.append(MCPServerManifest.from_dict(data))
        if not manifests:
            raise FileNotFoundError(f"No MCP manifests found in {directory}")
        return cls(manifests)

    def all(self) -> list[MCPServerManifest]:
        return list(self._manifests)

    def by_domain(self, domain: str) -> list[MCPServerManifest]:
        return [m for m in self._manifests if domain in m.domains]

    def catalog_for_prompt(self) -> str:
        """Render a compact catalog the planner LLM can reason over."""
        lines = []
        for m in self._manifests:
            caps = "; ".join(f"{c.capability} ({c.good_for})" for c in m.provides)
            lines.append(f"- {m.server} [domains: {', '.join(m.domains)}]: {caps}")
        return "\n".join(lines)
