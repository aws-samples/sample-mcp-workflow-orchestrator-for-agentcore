from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

HANDLER_PATH = Path(__file__).resolve().parent.parent / "lambda" / "handler.py"
SPEC = importlib.util.spec_from_file_location("mcp_lambda_handler", HANDLER_PATH)
assert SPEC and SPEC.loader
handler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handler)


def _context(tool_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        client_context=SimpleNamespace(
            custom={
                "bedrockAgentCoreToolName": tool_name,
                "bedrockAgentCoreAwsRequestId": "request-123",
            }
        )
    )


def test_handler_extracts_exact_gateway_tool_name():
    assert handler._tool_name_from_context(_context("documentation-mcp___read_documentation")) == "read_documentation"


def test_handler_uses_context_not_argument_heuristics(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_TOOLS", "read_documentation|recommend")
    observed = {}

    def fake_invoke(tool_name, arguments):
        observed["tool"] = tool_name
        observed["arguments"] = arguments
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(handler, "_invoke_mcp_tool", fake_invoke)
    result = handler.lambda_handler(
        {"url": "https://docs.aws.amazon.com/example"},
        _context("documentation-mcp___read_documentation"),
    )

    assert result["content"][0]["text"] == "ok"
    assert observed["tool"] == "read_documentation"


def test_handler_rejects_tool_not_in_environment_allowlist(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_TOOLS", "get_pricing")
    result = handler.lambda_handler({}, _context("pricing-mcp___generate_cost_report"))
    assert result["error"] == "The selected tool is not allowed for this Lambda target"
