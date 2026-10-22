"""Guarded live integration test for deployed MCP tools.

Run only in a declared disposable sandbox account:
  MCP_INTEGRATION_TEST=1 MCP_SANDBOX_ACCOUNT_ID=123456789012 \
    python scripts/test_all_tools.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.gateway_client import GatewayClient


def _load_settings() -> tuple[str, str]:
    gateway_url = os.getenv("AGENTCORE_GATEWAY_URL", "")
    region = os.getenv("AWS_REGION", "us-east-1")
    if gateway_url:
        return gateway_url, region
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key == "AGENTCORE_GATEWAY_URL":
                gateway_url = value.strip()
            elif key == "AWS_REGION":
                region = value.strip()
    if not gateway_url:
        raise RuntimeError("Set AGENTCORE_GATEWAY_URL in .env or the environment")
    return gateway_url, region


def _verify_sandbox(region: str) -> None:
    if os.getenv("MCP_INTEGRATION_TEST") != "1":
        raise RuntimeError("Set MCP_INTEGRATION_TEST=1 to run live tests")
    expected_account = os.getenv("MCP_SANDBOX_ACCOUNT_ID", "")
    if not expected_account.isdigit() or len(expected_account) != 12:
        raise RuntimeError("Set MCP_SANDBOX_ACCOUNT_ID to the 12-digit sandbox account ID")
    actual_account = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
    if actual_account != expected_account:
        raise RuntimeError(
            f"Refusing to test account {actual_account}; expected sandbox {expected_account}"
        )


def _is_error(result: object) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("error") or result.get("isError"):
        return True
    for item in result.get("content", []):
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text", "")
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("error"):
            return True
    return False


async def _test_tool(gateway: GatewayClient, target: str, tool: str, args: dict) -> bool:
    label = f"{target} / {tool}"
    try:
        result = await gateway.invoke(target, tool, args)
    except Exception as error:  # noqa: BLE001 - integration harness reports failure type only
        print(f"FAIL {label}: {type(error).__name__}")
        return False
    if _is_error(result):
        print(f"FAIL {label}: tool returned an error")
        return False
    print(f"PASS {label}")
    return True


async def _run() -> int:
    gateway_url, region = _load_settings()
    _verify_sandbox(region)
    gateway = GatewayClient(gateway_url, region)
    policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
    policy_version = boto3.client("iam", region_name=region).get_policy(
        PolicyArn=policy_arn
    )["Policy"]["DefaultVersionId"]
    now = datetime.now(UTC)
    start = (now - timedelta(hours=1)).isoformat()
    end = now.isoformat()
    tests = [
        ("aws-mcp-server", "search_documentation", {"search_phrase": "Lambda cold start optimization"}),
        ("aws-mcp-server", "read_documentation", {"requests": [{"url": "https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html"}]}),
        ("cloudwatch-mcp", "get_active_alarms", {}),
        ("cloudwatch-mcp", "get_metric_data", {"namespace": "AWS/Lambda", "metric_name": "Invocations"}),
        ("cloudwatch-mcp", "execute_log_insights_query", {"log_group_names": ["/aws/lambda/mcp-cloudwatch"], "query_string": "fields @timestamp | limit 5", "start_time": start, "end_time": end}),
        ("cloudtrail-mcp", "lookup_events", {}),
        ("iam-mcp", "list_users", {}),
        ("iam-mcp", "list_policies", {"scope": "Local"}),
        ("iam-mcp", "get_managed_policy_document", {"policy_arn": policy_arn, "version_id": policy_version}),
        ("pricing-mcp", "get_pricing", {"service_code": "AmazonEC2", "region": "us-east-1", "filters": [{"Field": "instanceType", "Type": "TERM_MATCH", "Value": "t3.medium"}], "max_results": 1}),
        ("pricing-mcp", "generate_cost_report", {"pricing_data": {"service_code": "AmazonEC2", "region": "us-east-1"}, "service_name": "Amazon EC2"}),
        ("documentation-mcp", "search_documentation", {"search_phrase": "S3 bucket security best practices"}),
        ("documentation-mcp", "read_documentation", {"url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html"}),
        ("documentation-mcp", "recommend", {"url": "https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html"}),
    ]
    results = [await _test_tool(gateway, target, tool, args) for target, tool, args in tests]
    passed = sum(results)
    print(f"RESULTS: {passed}/{len(tests)} passed, {len(tests) - passed} failed")
    return 0 if all(results) else 1


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_run()))
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
