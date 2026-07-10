"""Lambda handler for MCP server tools behind AgentCore Gateway.

When the Gateway invokes a Lambda target, it sends just the tool arguments
as the Lambda event payload (not a full JSON-RPC envelope). The Lambda executes
the tool logic and returns the result.

This handler wraps awslabs MCP server packages by spawning them as subprocesses
and translating between the Gateway's direct invocation format and the MCP
server's stdio JSON-RPC protocol.

Environment Variables:
  MCP_SERVER_COMMAND: The MCP server package command (e.g., "awslabs.cloudwatch-mcp-server")
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from typing import Any

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MCP_SERVER_COMMAND = os.environ.get("MCP_SERVER_COMMAND", "")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point.

    The Gateway sends tool arguments directly as the event.
    We initialize the MCP server, then invoke the appropriate tool.
    """
    logger.info("Received event: %s", json.dumps(event, default=str)[:1000])

    if not MCP_SERVER_COMMAND:
        return _error("MCP_SERVER_COMMAND not set")

    # The event IS the tool arguments from the Gateway
    # We need to figure out which tool was called from context
    # The Gateway passes the tool name via the function context or we infer from args
    tool_arguments = event

    try:
        result = _invoke_mcp_tool(tool_arguments)

        # If the server returned a "result_too_large" error, make it friendlier
        if isinstance(result, dict):
            content = result.get("content", [])
            if content and isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        try:
                            parsed = json.loads(text)
                            if parsed.get("error_type") == "result_too_large":
                                msg = parsed.get("message", "")
                                item["text"] = json.dumps({
                                    "status": "partial",
                                    "note": "Response exceeded size limit. Use more specific filters for complete results.",
                                    "suggestion": msg,
                                })
                                result["isError"] = False
                        except (json.JSONDecodeError, TypeError):
                            pass

        return result
    except subprocess.TimeoutExpired:
        return _error("MCP server timed out")
    except Exception as e:
        logger.exception("Error invoking MCP server")
        return _error(str(e))


def _invoke_mcp_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    """Spawn the MCP server, initialize it, list tools, and call the matching tool."""
    command = MCP_SERVER_COMMAND.split()

    # The awslabs packages install console scripts (e.g., "awslabs.cloudwatch-mcp-server")
    # In Lambda containers, pip installs scripts to /var/lang/bin/
    # Try the script directly first, fall back to python -m with underscores
    import shutil
    script_path = shutil.which(command[0])
    if script_path:
        command[0] = script_path
    else:
        # Try common Lambda paths
        for prefix in ["/var/lang/bin/", "/var/task/bin/", "/usr/local/bin/"]:
            candidate = prefix + command[0]
            if os.path.exists(candidate):
                command[0] = candidate
                break
        else:
            # Last resort: try python -m with dots replaced by underscores
            module_name = command[0].replace("-", "_")
            command = [sys.executable, "-m", module_name] + command[1:]

    timeout = int(os.environ.get("MCP_TIMEOUT", "90"))

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    try:
        # MCP servers process messages sequentially over stdio.
        # We need to send initialize, wait for response, then send the tool call.

        # Step 1: Initialize
        init_request = json.dumps({
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "lambda-handler", "version": "1.0"},
            },
        }) + "\n"

        # Step 2: Send initialized notification (required by MCP protocol)
        initialized_notification = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }) + "\n"

        # Step 3: Call the tool
        tool_name = _guess_tool_name(arguments)

        # Some servers require a 'ctx' argument for pydantic validation
        tool_args = dict(arguments)
        if "iam" in MCP_SERVER_COMMAND:
            tool_args["ctx"] = {"content": [], "isError": False}

        call_request = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 2,
            "params": {
                "name": tool_name,
                "arguments": tool_args,
            },
        }) + "\n"

        # Send all messages at once (server reads line by line)
        input_data = init_request + initialized_notification + call_request

        logger.info("Sending to MCP server: tool=%s, args=%s", tool_name, json.dumps(tool_args)[:200])

        # Use threading to read stdout without blocking
        import threading
        stdout_lines = []
        stderr_lines = []
        stdout_lock = threading.Lock()

        def read_stdout():
            for line in proc.stdout:
                with stdout_lock:
                    stdout_lines.append(line)

        def read_stderr():
            for line in proc.stderr:
                stderr_lines.append(line)

        t_out = threading.Thread(target=read_stdout, daemon=True)
        t_err = threading.Thread(target=read_stderr, daemon=True)
        t_out.start()
        t_err.start()

        # Write all input then wait for response
        proc.stdin.write(input_data)
        proc.stdin.flush()

        # Don't close stdin immediately — some servers exit prematurely when stdin closes.
        # Instead, wait for the tool response with a timeout.
        import time
        wait_time = min(timeout - 5, 80)  # Leave buffer before Lambda timeout
        start = time.time()

        while time.time() - start < wait_time:
            # Check if we got the tool response (id=2)
            with stdout_lock:
                lines_snapshot = list(stdout_lines)
            for line in lines_snapshot:
                try:
                    msg = json.loads(line.strip())
                    if isinstance(msg, dict) and msg.get("id") == 2:
                        # Got our response — clean up and return
                        proc.stdin.close()
                        proc.terminate()
                        if "result" in msg:
                            return msg["result"]
                        elif "error" in msg:
                            return {"error": msg["error"].get("message", str(msg["error"]))}
                except (json.JSONDecodeError, ValueError):
                    continue
            time.sleep(0.5)

        # Timeout — close and return what we have
        proc.stdin.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        stderr_data = "".join(stderr_lines)
        if stderr_data:
            logger.warning("MCP stderr: %s", stderr_data[:1000])

        stdout_data = "".join(stdout_lines)
        logger.info("MCP stdout (%d lines): %s", len(stdout_lines), stdout_data[:500])

        # Parse responses — look for the tool/call response (id=2)
        for line in stdout_data.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if isinstance(msg, dict) and msg.get("id") == 2:
                    if "result" in msg:
                        return msg["result"]
                    elif "error" in msg:
                        return {"error": msg["error"].get("message", str(msg["error"]))}
            except json.JSONDecodeError:
                continue

        # If no id=2 response, return all stdout for debugging
        return {"result": "No tool response received", "stdout": stdout_data[:500]}

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _guess_tool_name(arguments: dict[str, Any]) -> str:
    """Map incoming arguments to the actual MCP server tool name.

    The Gateway sends tool arguments to Lambda. We infer the tool from arg patterns.
    These names must match the real tools registered in each awslabs MCP server.
    """
    keys = set(arguments.keys())
    server = MCP_SERVER_COMMAND

    # CloudWatch tools (awslabs.cloudwatch-mcp-server)
    if "cloudwatch" in server:
        if "log_group_names" in keys or "query_string" in keys:
            return "execute_log_insights_query"
        if "namespace" in keys or "metric_name" in keys:
            return "get_metric_data"
        return "get_active_alarms"

    # CloudTrail tools (awslabs.cloudtrail-mcp-server)
    if "cloudtrail" in server:
        return "lookup_events"

    # IAM tools (awslabs.iam-mcp-server)
    if "iam" in server:
        if "policy_arn" in keys:
            return "get_managed_policy_document"
        if "policy_source_arn" in keys or "action_names" in keys:
            return "simulate_principal_policy"
        if "scope" in keys or "only_attached" in keys:
            return "list_policies"
        if "path_prefix" in keys or "max_items" in keys:
            return "list_users"
        return "list_users"

    # Pricing tools (awslabs.aws-pricing-mcp-server)
    if "pricing" in server:
        if "usage_description" in keys:
            return "generate_cost_report"
        return "get_pricing"

    # Documentation tools (awslabs.aws-documentation-mcp-server)
    if "documentation" in server:
        if "url" in keys:
            if "search_phrase" not in keys:
                return "recommend"
            return "read_documentation"
        if "search_phrase" in keys:
            return "search_documentation"
        return "search_documentation"

    # Generic fallback based on args
    if "namespace" in keys or "metric_name" in keys:
        return "get_metric_data"
    if "policy_arn" in keys:
        return "get_managed_policy_document"
    if "search_phrase" in keys:
        return "search_documentation"

    return "list_users"


def _error(message: str) -> dict[str, Any]:
    """Return an error response."""
    return {"error": message}
