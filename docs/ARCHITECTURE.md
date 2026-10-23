# Architecture

## Design Principles

1. **Build on, don't compete** — Uses AgentCore Gateway for routing/auth, Bedrock for reasoning, Lambda for compute. The orchestration logic is the value-add layer on top.

2. **Explainability over black-box** — Every decision is recorded with a rationale. You can audit, debug, and improve the reasoning.

3. **Declarative discovery, explicit execution contracts** — YAML manifests define capability names, domains, and descriptions for planner discovery. Gateway schemas, Lambda allowlists, IAM actions, and planner argument contracts remain explicit review points.

4. **Domain-specific over generic** — Instead of one "do anything" tool, each server exposes purpose-built interfaces. This sample uses one shared action-scoped, read-only Lambda role; production deployments should separate roles by trust boundary.

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  Orchestrator (Python, runs locally)                                │
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│  │ CLI      │ →  │ Planner  │ →  │ Gateway  │ →  │ Correlation  │  │
│  │          │    │ (Bedrock)│    │ Client   │    │ Engine       │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────────┘  │
│                       ↕                ↕                            │
│               ┌──────────────┐   ┌──────────┐                      │
│               │ MCP Registry │   │ Decision │                      │
│               │ (YAML files) │   │ Log      │                      │
│               └──────────────┘   └──────────┘                      │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────────────┐
              │             │                     │
              ▼             ▼                     ▼
   AgentCore Gateway   AWS MCP Server     (direct MCP session)
   (SigV4 auth)       (remote managed)
              │
    ┌─────────┼─────────┬──────────┬──────────┐
    │         │         │          │          │
    ▼         ▼         ▼          ▼          ▼
 Lambda    Lambda    Lambda     Lambda     Lambda
 CW-MCP   CT-MCP   IAM-MCP   Price-MCP  Doc-MCP
    │         │         │          │          │
    ▼         ▼         ▼          ▼          ▼
CloudWatch CloudTrail  IAM     Pricing   Documentation
  APIs       APIs     APIs      APIs       APIs
```

## Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| **Planner** | `orchestrator/planner.py` | Calls Bedrock to plan, execute, and synthesize. The "brain." |
| **Registry** | `orchestrator/registry.py` | Loads YAML manifests, generates capability catalog for the planner prompt |
| **Gateway Client** | `orchestrator/gateway_client.py` | Routes tool calls to Gateway (Lambda targets) or AWS MCP Server (direct session) |
| **Correlation Engine** | `orchestrator/correlation.py` | Groups observations across servers and retains source attribution for synthesis |
| **Decision Log** | `orchestrator/decision_log.py` | Records every reasoning step for auditability |
| **Lambda Handler** | `lambda/handler.py` | Spawns stdio MCP servers as subprocesses in Lambda containers |

## Auth Model

```
Orchestrator → Gateway:     SigV4 (your AWS credentials)
Gateway → Lambda:           IAM invoke (Gateway role)
Lambda → AWS APIs:          IAM (action-scoped, read-only Lambda execution role)
Orchestrator → AWS MCP:     Direct session-based MCP, not through the Gateway (docs tools only)
```

The Gateway uses `AWS_IAM` inbound authorization, so unsigned requests are rejected. The deploy script checks this before it attaches any targets. No OAuth is used.

## Why Lambda Instead of AgentCore Runtime?

AgentCore Runtime creates hostnames with underscores (e.g., `cloudwatch_mcp-xxx`), which are invalid DNS names per RFC 1035. The Gateway rejects URLs with underscores. Lambda avoids this entirely — the Gateway invokes Lambda by ARN, no URL needed.

**Alternative:** If you use hyphenated names (e.g., `cloudwatch-mcp` instead of `cloudwatch_mcp`), AgentCore Runtime produces valid DNS hostnames and works correctly with the Gateway. This simplifies deployment — no Dockerfiles, no ECR, no custom handler — since Runtime manages the MCP server lifecycle for you. The orchestrator itself requires no changes either way; the Gateway abstraction means the planner doesn't know or care whether a target is a Lambda or a Runtime.

## The Extensibility Contract

Adding a new Lambda-backed MCP server requires:
1. A YAML manifest in `mcp_registry/` for capability discovery and domain routing
2. A Dockerfile in `lambda/` to package the server
3. A deploy-script entry with the Gateway input schema, Lambda allowlist, and scoped IAM actions
4. The exact tool and argument contract in `PLAN_SYSTEM` in `orchestrator/planner.py`
5. A guarded integration-test case validated in a personal test account with no important workloads or data

The orchestration loop does not need to change, but these explicit contracts prevent the planner and Gateway from guessing how a new tool is invoked.
