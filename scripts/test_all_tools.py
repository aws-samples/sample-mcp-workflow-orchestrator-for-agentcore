"""Test all 14 tools across 6 MCP servers.

Usage:
  python scripts/test_all_tools.py

This script invokes each tool with valid arguments and reports success/failure.
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from orchestrator.gateway_client import GatewayClient

GW_URL = os.getenv(
    "AGENTCORE_GATEWAY_URL",
    "",
)
REGION = os.getenv("AWS_REGION", "us-east-1")

# Load from .env if not set
if not GW_URL:
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("AGENTCORE_GATEWAY_URL="):
                GW_URL = line.split("=", 1)[1].strip()
            elif line.startswith("AWS_REGION="):
                REGION = line.split("=", 1)[1].strip()

if not GW_URL:
    print("ERROR: Set AGENTCORE_GATEWAY_URL in .env or environment")
    sys.exit(1)


async def test_tool(gw, target, tool, args, label):
    """Test a single tool and return pass/fail."""
    try:
        result = await gw.invoke(target, tool, args)
        text = json.dumps(result, default=str)
        # Check for errors
        is_error = result.get("isError", False)
        has_error_text = "Error executing tool" in text or "Unknown tool" in text
        # result_too_large is actually a success (server responded with real data)
        is_too_large = "result_too_large" in text

        if is_error or (has_error_text and not is_too_large):
            print(f"  ❌ {label}")
            print(f"     {text[:300]}")
            return False
        else:
            print(f"  ✅ {label}")
            print(f"     {text[:200]}")
            return True
    except Exception as e:
        print(f"  ❌ {label}")
        print(f"     EXCEPTION: {str(e)[:200]}")
        return False


async def main():
    gw = GatewayClient(GW_URL, REGION)
    results = {"passed": 0, "failed": 0, "total": 0}

    # ─── STEP 1: aws-mcp-server (2 tools) ────────────────────────────────
    print()
    print("═" * 70)
    print("  STEP 1: aws-mcp-server (2 tools)")
    print("═" * 70)
    print()

    tests = [
        ("aws-mcp-server", "search_documentation",
         {"search_phrase": "Lambda cold start optimization"},
         "search_documentation"),
        ("aws-mcp-server", "read_documentation",
         {"requests": [{"url": "https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html"}]},
         "read_documentation"),
    ]
    for target, tool, args, label in tests:
        results["total"] += 1
        if await test_tool(gw, target, tool, args, f"{target} / {label}"):
            results["passed"] += 1
        else:
            results["failed"] += 1
        print()

    # ─── STEP 2: cloudwatch-mcp (3 tools) ────────────────────────────────
    print("═" * 70)
    print("  STEP 2: cloudwatch-mcp (3 tools)")
    print("═" * 70)
    print()

    tests = [
        ("cloudwatch-mcp", "get_active_alarms",
         {},
         "get_active_alarms"),
        ("cloudwatch-mcp", "get_metric_data",
         {"namespace": "AWS/Lambda", "metric_name": "Invocations"},
         "get_metric_data"),
        ("cloudwatch-mcp", "execute_log_insights_query",
         {"log_group_names": ["/aws/lambda/mcp-cloudwatch"],
          "query_string": "fields @timestamp, @message | sort @timestamp desc | limit 5",
          "start_time": "2026-07-09T00:00:00Z",
          "end_time": "2026-07-10T23:59:59Z"},
         "execute_log_insights_query"),
    ]
    for target, tool, args, label in tests:
        results["total"] += 1
        if await test_tool(gw, target, tool, args, f"{target} / {label}"):
            results["passed"] += 1
        else:
            results["failed"] += 1
        print()

    # ─── STEP 3: cloudtrail-mcp (1 tool) ─────────────────────────────────
    print("═" * 70)
    print("  STEP 3: cloudtrail-mcp (1 tool)")
    print("═" * 70)
    print()

    tests = [
        ("cloudtrail-mcp", "lookup_events",
         {},
         "lookup_events"),
    ]
    for target, tool, args, label in tests:
        results["total"] += 1
        if await test_tool(gw, target, tool, args, f"{target} / {label}"):
            results["passed"] += 1
        else:
            results["failed"] += 1
        print()

    # ─── STEP 4: iam-mcp (3 tools) ───────────────────────────────────────
    print("═" * 70)
    print("  STEP 4: iam-mcp (3 tools)")
    print("═" * 70)
    print()

    tests = [
        ("iam-mcp", "list_users",
         {},
         "list_users"),
        ("iam-mcp", "list_policies",
         {"scope": "Local"},
         "list_policies"),
        ("iam-mcp", "get_managed_policy_document",
         {"policy_arn": "arn:aws:iam::aws:policy/ReadOnlyAccess", "version_id": "v1"},
         "get_managed_policy_document"),
    ]
    for target, tool, args, label in tests:
        results["total"] += 1
        if await test_tool(gw, target, tool, args, f"{target} / {label}"):
            results["passed"] += 1
        else:
            results["failed"] += 1
        print()

    # ─── STEP 5: pricing-mcp (2 tools) ───────────────────────────────────
    print("═" * 70)
    print("  STEP 5: pricing-mcp (2 tools)")
    print("═" * 70)
    print()

    tests = [
        ("pricing-mcp", "get_pricing",
         {"service_code": "AmazonEC2", "region": "us-east-1",
          "filters": [{"Field": "instanceType", "Type": "TERM_MATCH", "Value": "t3.medium"}]},
         "get_pricing"),
        ("pricing-mcp", "generate_cost_report",
         {"service_code": "AmazonEC2", "pricing_data": "t3.medium on-demand us-east-1"},
         "generate_cost_report"),
    ]
    for target, tool, args, label in tests:
        results["total"] += 1
        if await test_tool(gw, target, tool, args, f"{target} / {label}"):
            results["passed"] += 1
        else:
            results["failed"] += 1
        print()

    # ─── STEP 6: documentation-mcp (3 tools) ─────────────────────────────
    print("═" * 70)
    print("  STEP 6: documentation-mcp (3 tools)")
    print("═" * 70)
    print()

    tests = [
        ("documentation-mcp", "search_documentation",
         {"search_phrase": "S3 bucket security best practices"},
         "search_documentation"),
        ("documentation-mcp", "read_documentation",
         {"url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html"},
         "read_documentation"),
        ("documentation-mcp", "recommend",
         {"url": "https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html"},
         "recommend"),
    ]
    for target, tool, args, label in tests:
        results["total"] += 1
        if await test_tool(gw, target, tool, args, f"{target} / {label}"):
            results["passed"] += 1
        else:
            results["failed"] += 1
        print()

    # ─── Summary ──────────────────────────────────────────────────────────
    print("═" * 70)
    print(f"  RESULTS: {results['passed']}/{results['total']} passed, {results['failed']} failed")
    print("═" * 70)
    print()

    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
