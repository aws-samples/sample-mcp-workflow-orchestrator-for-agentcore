"""Planner tests using a mocked reasoner and gateway (no AWS creds needed)."""
from __future__ import annotations
import asyncio
from pathlib import Path

from orchestrator.registry import MCPRegistry
from orchestrator.planner import Planner, BedrockReasoner


class FakeReasoner(BedrockReasoner):
    def __init__(self, plan_servers):
        self._plan_servers = plan_servers

    def complete_json(self, system: str, user: str):
        if "CATALOG" in user:  # plan() call
            return {
                "domains": ["cost"],
                "plan": [
                    {"server": s, "tool": "get_current_pricing", "arguments": {}, "rationale": "test"}
                    for s in self._plan_servers
                ],
            }
        return {"answer": "Test answer citing pricing-mcp."}  # synthesize() call


class FakeGateway:
    def __init__(self):
        self.calls = []

    async def invoke(self, target, tool, args):
        self.calls.append((target, tool))
        return {"ok": True, "tool": tool}


def _registry():
    return MCPRegistry.load(Path(__file__).resolve().parent.parent / "mcp_registry")


def test_planner_executes_plan_and_synthesizes():
    reg = _registry()
    planner = Planner(reg, FakeGateway(), reasoner=FakeReasoner(["pricing-mcp"]), mode="authoritative")
    result = asyncio.new_event_loop().run_until_complete(planner.run("Reduce my bill."))
    assert "pricing-mcp" in result.finding.sources()
    assert "answer" and result.answer
    actions = [s.action for s in result.decision_log.steps]
    assert "plan" in actions and "invoke_tool" in actions and "decide" in actions


def test_planner_skips_unknown_server():
    reg = _registry()
    planner = Planner(reg, FakeGateway(), reasoner=FakeReasoner(["does-not-exist"]), mode="authoritative")
    result = asyncio.new_event_loop().run_until_complete(planner.run("x"))
    assert any(s.action == "skip" for s in result.decision_log.steps)


def test_reference_build_without_reasoner():
    reg = _registry()
    planner = Planner(reg, FakeGateway(), reasoner=None, mode="authoritative")
    result = asyncio.new_event_loop().run_until_complete(planner.run("x"))
    assert result.decision_log.steps  # still produces a decision log
