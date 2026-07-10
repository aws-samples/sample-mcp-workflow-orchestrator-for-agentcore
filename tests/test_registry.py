from pathlib import Path
from orchestrator.registry import MCPRegistry


def test_registry_loads_all_manifests():
    reg = MCPRegistry.load(Path(__file__).resolve().parent.parent / "mcp_registry")
    servers = {m.server for m in reg.all()}
    assert "pricing-mcp" in servers
    assert "cloudwatch-mcp" in servers


def test_domain_routing():
    reg = MCPRegistry.load(Path(__file__).resolve().parent.parent / "mcp_registry")
    cost = {m.server for m in reg.by_domain("cost")}
    assert "pricing-mcp" in cost
