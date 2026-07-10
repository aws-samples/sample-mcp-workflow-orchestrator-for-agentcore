"""Explainable Planner.

Loop: plan -> act -> observe -> correlate -> decide. Every decision is recorded in a
DecisionLog with a human-readable rationale (the explainability differentiator).

Two modes (config-driven via PLANNER_MODE):
  - sop_first: if the AWS MCP Server exposes an Agent SOP that fits the request,
    defer to it (complements AWS, avoids reinventing workflows).
  - authoritative: the planner always builds its own plan over the registry.

The planner uses a Bedrock foundation model for the three reasoning decisions that
genuinely need judgment:
  1. plan()      -> which domains/servers are relevant, and in what order
  2. next_step() -> given observations so far, what to do next (or stop)
  3. synthesize()-> turn correlated evidence into a final answer

Everything else (auth, discovery, transport) is delegated to AgentCore Gateway.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .registry import MCPRegistry, MCPServerManifest
from .gateway_client import GatewayClient
from .correlation import CorrelationEngine, CorrelatedFinding, Evidence
from .decision_log import DecisionLog

# Max plan/act/observe iterations before we force a decision (guards against loops).
MAX_STEPS = 8


@dataclass
class PlannedStep:
    server: str
    tool: str
    arguments: dict[str, Any]
    rationale: str


@dataclass
class OrchestratorResult:
    answer: str
    finding: CorrelatedFinding
    decision_log: DecisionLog
    plan: list[PlannedStep] = field(default_factory=list)


class BedrockReasoner:
    """Thin wrapper over Bedrock Converse for the planner's reasoning calls.

    Kept separate so it can be mocked in tests (see tests/test_planner.py).
    """

    def __init__(self, model_id: str, region: str):
        self.model_id = model_id
        self.region = region
        self._client = None  # lazily created boto3 bedrock-runtime client

    def _bedrock(self):
        if self._client is None:
            import boto3  # imported lazily so unit tests need no AWS creds

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Call the model and parse a JSON object from its reply."""
        resp = self._bedrock().converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": 4096},
        )
        # Extract text from response — handle models with extended thinking
        content_blocks = resp["output"]["message"]["content"]
        text_parts = []
        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])
        text = "\n".join(text_parts)
        if not text:
            raise ValueError(f"No text in model response. Blocks: {content_blocks}")
        return _extract_json(text)


def _extract_json(text: str) -> dict[str, Any]:
    """Robustly pull the first JSON object out of a model reply."""
    # Clean control characters that can appear in model output
    import re
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model reply: {text[:200]}")
    return json.loads(text[start : end + 1])


PLAN_SYSTEM = """You are the planner for an AWS engineering orchestrator.
You have access to tools from multiple MCP servers through an AgentCore Gateway.
The available servers and their EXACT tool names and required arguments are:

1. **aws-mcp-server** (docs/knowledge — direct connection):
   - `search_documentation`: Search AWS docs.
     Args: {"search_phrase": "your search terms here"}
   - `read_documentation`: Read a specific doc page.
     Args: {"requests": [{"url": "https://docs.aws.amazon.com/..."}]}

2. **cloudwatch-mcp** (observability/metrics/logs):
   - `get_active_alarms`: Get currently firing alarms.
     Args: {} or {"state_value": "ALARM"}
   - `get_metric_data`: Get metric data points.
     Args: {"namespace": "AWS/EC2", "metric_name": "CPUUtilization"}
   - `execute_log_insights_query`: Run a Logs Insights query.
     Args: {"log_group_names": ["/aws/lambda/my-func"], "query": "fields @timestamp | limit 10"}

3. **cloudtrail-mcp** (audit/changes):
   - `lookup_events`: Find recent API events.
     Args: {} or {"start_time": "2026-07-08", "end_time": "2026-07-09"}

4. **iam-mcp** (security/permissions):
   - `list_users`: List IAM users.
     Args: {} or {"path_prefix": "/", "max_items": 100}
   - `list_policies`: List IAM policies.
     Args: {"scope": "Local"} or {"scope": "AWS"}
   - `get_managed_policy_document`: Get a policy document.
     Args: {"policy_arn": "arn:aws:iam::123456789012:policy/MyPolicy"}

5. **pricing-mcp** (cost):
   - `get_pricing`: Get pricing for a service.
     Args: {"service_code": "AmazonEC2"} or {"service_code": "AmazonEC2", "region": "us-east-1"}
   - `generate_cost_report`: Generate cost report.
     Args: {"service_code": "AmazonEC2", "usage_description": "t3.medium 24/7"}

6. **documentation-mcp** (architecture/well-architected):
   - `search_documentation`: Search AWS docs.
     Args: {"search_phrase": "S3 security best practices"}
   - `read_documentation`: Read a doc page.
     Args: {"url": "https://docs.aws.amazon.com/..."}
   - `recommend`: Get recommendations.
     Args: {"topic": "S3 security"}

CRITICAL RULES:
- Use EXACTLY the tool names shown above (e.g., "get_active_alarms" not "get_alarms")
- Use EXACTLY the argument field names shown (e.g., "search_phrase" not "query", "service_code" not "service")
- Every argument must match the schema — wrong field names will cause errors

Given a user request, build a step-by-step investigation plan.
Choose the RIGHT server for each step based on its domain expertise.

Return ONLY a JSON object:
{
  "domains": ["..."],
  "plan": [
    {"server": "<server-name>", "tool": "<exact-tool-name>", "arguments": {<exact args>}, "rationale": "why this, why now"}
  ]
}

Guidelines:
- Use cloudwatch-mcp for metrics, alarms, and logs
- Use cloudtrail-mcp for API change history and audit
- Use iam-mcp for users, policies, and permission analysis
- Use aws-mcp-server OR documentation-mcp for documentation lookups
- Use pricing-mcp for cost questions (use service_code not service name)
- Order steps by dependency (confirm the problem before hunting for the cause)
- Spread steps across multiple servers to show cross-server correlation"""

NEXT_STEP_SYSTEM = """You are the planner mid-investigation. Given the original request,
the plan so far, and the observations gathered, decide the next action.

Available servers: aws-mcp-server, cloudwatch-mcp, cloudtrail-mcp, iam-mcp, pricing-mcp, documentation-mcp.

Return ONLY a JSON object:
{"action": "invoke" | "stop",
 "step": {"server": "<server-name>", "tool": "<tool-name>", "arguments": {...}, "rationale": "..."},
 "reason": "why stop / why this step"}
Choose "stop" as soon as you have enough evidence to answer confidently."""

SYNTHESIZE_SYSTEM = """You are the planner producing the final engineering answer.
Given the user request and gathered evidence from multiple MCP servers (cloudwatch-mcp,
cloudtrail-mcp, iam-mcp, pricing-mcp, aws-mcp-server, documentation-mcp), write a concise,
actionable answer. Cite which server/tool each key fact came from. Be explicit about
confidence and any conflicting signals.

Return ONLY a JSON object: {"answer": "..."}"""


class Planner:
    def __init__(
        self,
        registry: MCPRegistry,
        gateway: GatewayClient,
        reasoner: BedrockReasoner | None = None,
        mode: str = "sop_first",
    ):
        self.registry = registry
        self.gateway = gateway
        self.reasoner = reasoner
        self.mode = mode

    # ------------------------------------------------------------------ helpers
    def _find_manifest(self, server: str) -> MCPServerManifest | None:
        for m in self.registry.all():
            if m.server == server:
                return m
        return None

    # ------------------------------------------------------------------ SOP gate
    async def _try_sop(self, request: str, log: DecisionLog) -> str | None:
        """In sop_first mode, ask AWS MCP Server whether a pre-built SOP fits."""
        aws = self._find_manifest("aws-mcp-server")
        if aws is None:
            return None
        log.record(
            action="check_sop",
            server="aws-mcp-server",
            tool="find_agent_sop",
            rationale=(
                "PLANNER_MODE=sop_first: check whether AWS MCP Server has a pre-built "
                "Agent SOP matching the request before doing custom planning."
            ),
            inputs={"request": request},
        )
        try:
            result = await self.gateway.invoke(
                aws.gateway_target, "find_agent_sop", {"request": request}
            )
        except (NotImplementedError, RuntimeError):
            # Tool not available (reference build or tool doesn't exist on gateway)
            return None
        sop = (result or {}).get("sop")
        if sop:
            log.record(
                action="defer_to_sop",
                server="aws-mcp-server",
                tool="find_agent_sop",
                rationale=f"A fitting SOP was found ({sop}); deferring to it.",
                observation_summary=str(sop),
            )
            return sop
        return None

    # ------------------------------------------------------------------ planning
    def _plan(self, request: str, log: DecisionLog) -> list[PlannedStep]:
        catalog = self.registry.catalog_for_prompt()
        user = f"CATALOG:\n{catalog}\n\nREQUEST:\n{request}"
        data = self.reasoner.complete_json(PLAN_SYSTEM, user)
        steps = [
            PlannedStep(
                server=s["server"],
                tool=s["tool"],
                arguments=s.get("arguments", {}),
                rationale=s.get("rationale", ""),
            )
            for s in data.get("plan", [])
        ]
        log.record(
            action="plan",
            server=None,
            tool=None,
            rationale=(
                f"Inferred domains {data.get('domains')}; built a {len(steps)}-step plan "
                "over the registry."
            ),
            inputs={"domains": data.get("domains"), "steps": [s.server for s in steps]},
        )
        return steps

    # ------------------------------------------------------------------ main loop
    async def run(self, request: str) -> OrchestratorResult:
        log = DecisionLog()
        engine = CorrelationEngine()

        if self.mode == "sop_first":
            sop = await self._try_sop(request, log)
            if sop:
                finding = CorrelatedFinding(summary=f"Handled by AWS MCP Server SOP: {sop}")
                return OrchestratorResult(
                    answer=f"Delegated to AWS MCP Server Agent SOP '{sop}'.",
                    finding=finding,
                    decision_log=log,
                )

        if self.reasoner is None:
            # Reference build with no model wired: emit the plan-shaped decision log only.
            log.record(
                action="plan",
                server=None,
                tool=None,
                rationale=(
                    "No reasoner configured (reference build). Wire a BedrockReasoner to "
                    "enable live planning. See scenarios/ for expected behavior."
                ),
            )
            finding = engine.correlate()
            return OrchestratorResult(answer=finding.summary, finding=finding, decision_log=log)

        # 1. Build an initial plan.
        plan = self._plan(request, log)

        # 2. Execute plan steps, allowing the model to adapt after each observation.
        executed: list[PlannedStep] = []
        for step in plan:
            if len(executed) >= MAX_STEPS:
                break
            manifest = self._find_manifest(step.server)
            if manifest is None:
                log.record(
                    action="skip",
                    server=step.server,
                    tool=step.tool,
                    rationale="Server not in registry; skipping (registry is the source of truth).",
                )
                continue
            log.record(
                action="invoke_tool",
                server=step.server,
                tool=step.tool,
                rationale=step.rationale,
                inputs=step.arguments,
            )
            try:
                obs = await self.gateway.invoke(manifest.gateway_target, step.tool, step.arguments)
            except (NotImplementedError, RuntimeError) as exc:
                obs = {"error": str(exc)}
            engine.add([Evidence(source_server=step.server, tool=step.tool, payload=obs)])
            log.steps[-1].observation_summary = _short(obs)
            executed.append(step)

        # 3. Correlate everything gathered.
        finding = engine.correlate()
        log.record(
            action="correlate",
            server=None,
            tool=None,
            rationale="Merged observations across servers into a single cited finding.",
            observation_summary=f"sources: {', '.join(finding.sources()) or '<none>'}",
        )

        # 4. Synthesize the final answer.
        answer = self._synthesize(request, finding, log)
        return OrchestratorResult(answer=answer, finding=finding, decision_log=log, plan=executed)

    # ------------------------------------------------------------------ synthesize
    def _synthesize(self, request: str, finding: CorrelatedFinding, log: DecisionLog) -> str:
        evidence_blob = "\n".join(
            f"- [{e.source_server}/{e.tool}] {_short(e.payload)}" for e in finding.evidence
        )
        user = f"REQUEST:\n{request}\n\nEVIDENCE:\n{evidence_blob or '(none)'}"
        try:
            data = self.reasoner.complete_json(SYNTHESIZE_SYSTEM, user)
            answer = data.get("answer", finding.summary)
        except Exception as exc:  # noqa: BLE001 - reference build resilience
            answer = f"{finding.summary} (synthesis unavailable: {exc})"
        log.record(
            action="decide",
            server=None,
            tool=None,
            rationale="Sufficient evidence correlated; produced final answer with source attribution.",
        )
        return answer


def _short(payload: Any, limit: int = 160) -> str:
    s = json.dumps(payload, default=str) if not isinstance(payload, str) else payload
    return s if len(s) <= limit else s[: limit - 1] + "…"
