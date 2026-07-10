"""MCP client over Amazon Bedrock AgentCore Gateway.

AgentCore Gateway exposes all registered MCP servers behind ONE MCP endpoint, with
managed auth and native semantic tool search. This client sends JSON-RPC requests
to the gateway using SigV4 authentication.

For the managed AWS MCP Server (https://aws-mcp.us-east-1.api.aws/mcp), we connect
directly with MCP session management since it requires stateful sessions.
"""
from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request
import urllib.error


# The managed AWS MCP Server endpoint (requires session-based MCP, no OAuth)
AWS_MCP_SERVER_URL = "https://aws-mcp.us-east-1.api.aws/mcp"


class GatewayClient:
    def __init__(self, gateway_url: str, region: str):
        self.gateway_url = gateway_url
        self.region = region
        self._session = boto3.Session(region_name=region)
        self._credentials = self._session.get_credentials().get_frozen_credentials()
        self._request_id = 0
        # Session ID for the managed AWS MCP Server (direct connection)
        self._aws_mcp_session_id: str | None = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _sign_request(self, url: str, body: bytes, headers: dict) -> dict:
        """Sign an HTTP request with SigV4 for bedrock-agentcore."""
        request = AWSRequest(method="POST", url=url, data=body, headers=headers)
        SigV4Auth(self._credentials, "bedrock-agentcore", self.region).add_auth(request)
        return dict(request.headers)

    def _call_gateway(self, method: str, params: dict | None = None) -> Any:
        """Send a JSON-RPC request to the AgentCore Gateway."""
        payload = {"jsonrpc": "2.0", "method": method, "id": self._next_id()}
        if params is not None:
            payload["params"] = params

        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        signed_headers = self._sign_request(self.gateway_url, body, headers)

        req = urllib.request.Request(
            self.gateway_url, data=body, headers=signed_headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise RuntimeError(f"Gateway HTTP {e.code}: {error_body[:500]}") from e

        if "error" in response_data:
            err = response_data["error"]
            raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
        return response_data.get("result")

    def _call_aws_mcp_direct(self, method: str, params: dict | None = None) -> Any:
        """Send a JSON-RPC request directly to the managed AWS MCP Server (session-based)."""
        # Initialize session if needed
        if self._aws_mcp_session_id is None:
            self._init_aws_mcp_session()

        payload = {"jsonrpc": "2.0", "method": method, "id": self._next_id()}
        if params is not None:
            payload["params"] = params

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Mcp-Session-Id": self._aws_mcp_session_id,
        }

        req = urllib.request.Request(
            AWS_MCP_SERVER_URL, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise RuntimeError(f"AWS MCP Server HTTP {e.code}: {error_body[:500]}") from e

        if "error" in response_data:
            err = response_data["error"]
            raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
        return response_data.get("result")

    def _init_aws_mcp_session(self):
        """Initialize an MCP session with the AWS MCP Server."""
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": self._next_id(),
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcp-workflow-orchestrator", "version": "0.1.0"},
            },
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        req = urllib.request.Request(
            AWS_MCP_SERVER_URL, data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            # Extract session ID from response headers
            session_id = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
            if not session_id:
                raise RuntimeError("AWS MCP Server did not return a session ID")
            self._aws_mcp_session_id = session_id

    async def search_tools(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Use Gateway's semantic tool search to shortlist relevant tools."""
        result = self._call_gateway("tools/search", {"query": query, "limit": limit})
        return result.get("tools", []) if result else []

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all tools available through the gateway."""
        result = self._call_gateway("tools/list")
        return result.get("tools", []) if result else []

    async def invoke(self, gateway_target: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool — routes to either the Gateway or AWS MCP Server directly.

        - aws-mcp-server tools → direct connection (session-based, no OAuth needed)
        - Lambda-backed tools → via Gateway (IAM auth)

        Responses exceeding MAX_RESPONSE_CHARS are truncated with a note.
        """
        if gateway_target == "aws-mcp-server":
            full_name = f"aws___{tool}" if "___" not in tool else tool
            result = self._call_aws_mcp_direct("tools/call", {"name": full_name, "arguments": arguments})
        else:
            full_name = f"{gateway_target}___{tool}" if "___" not in tool else tool
            result = self._call_gateway("tools/call", {"name": full_name, "arguments": arguments})

        return self._truncate_if_needed(result) if result else {}

    @staticmethod
    def _truncate_if_needed(result: dict[str, Any], max_chars: int = 50000) -> dict[str, Any]:
        """Truncate oversized responses to keep context window manageable."""
        if not isinstance(result, dict):
            return result

        content = result.get("content", [])
        if not content or not isinstance(content, list):
            return result

        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if len(text) > max_chars:
                    item["text"] = text[:max_chars] + f"\n\n[TRUNCATED: response was {len(text)} chars, showing first {max_chars}. Use more specific filters for complete results.]"

        return result
