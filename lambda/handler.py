"""Lambda adapter for stdio MCP server tools behind AgentCore Gateway.

AgentCore passes tool arguments in ``event`` and the selected target/tool name in
``context.client_context.custom``. The handler uses that authoritative metadata
rather than guessing a tool from argument names.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "WARNING"))

MCP_SERVER_COMMAND = os.environ.get("MCP_SERVER_COMMAND", "")
_TOOL_DELIMITER = "___"


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Invoke the exact AgentCore-selected, allowlisted MCP tool."""
    if not isinstance(event, dict):
        return _error("Tool arguments must be an object")
    try:
        tool_name = _tool_name_from_context(context)
        if tool_name not in _allowed_tools():
            return _error("The selected tool is not allowed for this Lambda target")
        logger.info("Invoking MCP tool=%s request_id=%s", tool_name, _request_id(context))
        return _invoke_mcp_tool(tool_name, event)
    except subprocess.TimeoutExpired:
        logger.warning("MCP server timed out")
        return _error("MCP server timed out")
    except (TypeError, ValueError) as error:
        logger.warning("Rejected MCP invocation: %s", error)
        return _error(str(error))
    except Exception:
        logger.exception("MCP invocation failed")
        return _error("MCP invocation failed")


def _context_values(context: Any) -> dict[str, Any]:
    custom = getattr(getattr(context, "client_context", None), "custom", None)
    if not isinstance(custom, dict):
        raise TypeError("AgentCore Gateway context metadata is unavailable")
    return custom


def _tool_name_from_context(context: Any) -> str:
    full_name = _context_values(context).get("bedrockAgentCoreToolName")
    if not isinstance(full_name, str) or _TOOL_DELIMITER not in full_name:
        raise ValueError("AgentCore Gateway did not provide a valid tool name")
    _, tool_name = full_name.rsplit(_TOOL_DELIMITER, 1)
    if not tool_name:
        raise ValueError("AgentCore Gateway provided an empty tool name")
    return tool_name


def _request_id(context: Any) -> str:
    value = _context_values(context).get("bedrockAgentCoreAwsRequestId", "unknown")
    return value if isinstance(value, str) else "unknown"


def _allowed_tools() -> set[str]:
    configured = os.environ.get("MCP_ALLOWED_TOOLS", "")
    tools = {tool.strip() for tool in configured.split("|") if tool.strip()}
    if not tools:
        raise ValueError("MCP_ALLOWED_TOOLS is not configured")
    return tools


def _command() -> list[str]:
    if not MCP_SERVER_COMMAND:
        raise ValueError("MCP_SERVER_COMMAND is not configured")
    command = shlex.split(MCP_SERVER_COMMAND)
    if not command or not (command[0].startswith("awslabs.") or command[0] == "python"):
        raise ValueError("MCP_SERVER_COMMAND uses an unsupported executable")
    script_path = shutil.which(command[0])
    if script_path:
        command[0] = script_path
        return command
    if command[0].startswith("awslabs."):
        return [sys.executable, "-m", command[0].replace("-", "_")] + command[1:]
    return command


def _invoke_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Follow MCP's required initialize → initialized → tools/call sequence."""
    process = subprocess.Popen(
        _command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            return _error("MCP subprocess streams are unavailable")
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        lock = threading.Lock()

        def read_stream(stream: Any, destination: list[str]) -> None:
            for line in stream:
                with lock:
                    destination.append(line)

        threading.Thread(target=read_stream, args=(process.stdout, stdout_lines), daemon=True).start()
        threading.Thread(target=read_stream, args=(process.stderr, stderr_lines), daemon=True).start()

        try:
            timeout = max(5, min(int(os.environ.get("MCP_TIMEOUT", "90")), 110))
        except ValueError:
            timeout = 90
        deadline = time.monotonic() + timeout - 5

        initialize = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "lambda-handler", "version": "1.0"},
            },
        }
        process.stdin.write(json.dumps(initialize) + "\n")
        process.stdin.flush()
        initialized_response = _wait_for_response(stdout_lines, lock, 1, deadline)
        if initialized_response is None or "error" in initialized_response:
            return _error("MCP server did not complete initialization")

        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        tool_arguments = dict(arguments)
        # This IAM MCP package declares ctx as a required tool argument for
        # selected read operations. It is injected inside the trusted Lambda
        # adapter, not exposed through the public Gateway schema.
        if "iam" in MCP_SERVER_COMMAND:
            tool_arguments.setdefault("ctx", {"content": [], "isError": False})
        tool_call = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 2,
            "params": {"name": tool_name, "arguments": tool_arguments},
        }
        process.stdin.write(json.dumps(notification) + "\n" + json.dumps(tool_call) + "\n")
        process.stdin.flush()
        tool_response = _wait_for_response(stdout_lines, lock, 2, deadline)
        if tool_response is None:
            logger.warning("MCP tool timed out; stderr lines=%d", len(stderr_lines))
            return _error("MCP server timed out while waiting for a tool response")
        if isinstance(tool_response.get("result"), dict):
            return _normalize_oversized_response(tool_response["result"])
        return _error("MCP server rejected the tool call")
    finally:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _wait_for_response(
    lines: list[str], lock: threading.Lock, request_id: int, deadline: float
) -> dict[str, Any] | None:
    while time.monotonic() < deadline:
        with lock:
            snapshot = list(lines)
        for line in snapshot:
            try:
                message = json.loads(line.strip())
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
        time.sleep(0.1)
    return None


def _normalize_oversized_response(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("content", [])
    if not isinstance(content, list):
        return result
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if parsed.get("error_type") == "result_too_large":
            item["text"] = json.dumps(
                {
                    "status": "partial",
                    "note": "Response exceeded the tool size limit. Refine the query for complete results.",
                }
            )
            result["isError"] = False
    return result


def _error(message: str) -> dict[str, Any]:
    return {"error": message}
