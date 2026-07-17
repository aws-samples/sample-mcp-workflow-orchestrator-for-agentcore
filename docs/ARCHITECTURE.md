# Architecture

## Design Principles

1. **Build on, don't compete** — Uses AgentCore Gateway for routing/auth, Bedrock for reasoning, Lambda for compute. The orchestration logic is the value-add layer on top.

2. **Explainability over black-box** — Every decision is recorded with a rationale. You can audit, debug, and improve the reasoning.

3. **Pluggability over hard-coding** — Server manifests (YAML) define what's available. The planner never names a specific server in its code.

4. **Domain-specific over generic** — Instead of one "do anything" tool, each server handles its domain with proper permissions, scoped IAM roles, and purpose-built interfaces.

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
| **Correlation Engine** | `orchestrator/correlation.py` | Merges evidence across servers, tracks sources, flags conflicts |
| **Decision Log** | `orchestrator/decision_log.py` | Records every reasoning step for auditability |
| **Lambda Handler** | `lambda/handler.py` | Spawns stdio MCP servers as subprocesses in Lambda containers |

## Auth Model

```
Orchestrator → Gateway:     SigV4 (your AWS credentials)
Gateway → Lambda:           IAM invoke (Gateway role)
Lambda → AWS APIs:          IAM (Lambda execution role with ReadOnlyAccess)
Orchestrator → AWS MCP:     Session-based MCP (no OAuth for docs tools)
```

No OAuth anywhere. All IAM within your account.

## Why Lambda Instead of AgentCore Runtime?

AgentCore Runtime creates hostnames with underscores (e.g., `cloudwatch_mcp-xxx`), which are invalid DNS names per RFC 1035. The Gateway rejects URLs with underscores. Lambda avoids this entirely — the Gateway invokes Lambda by ARN, no URL needed.

**Alternative:** If you use hyphenated names (e.g., `cloudwatch-mcp` instead of `cloudwatch_mcp`), AgentCore Runtime produces valid DNS hostnames and works correctly with the Gateway. This simplifies deployment — no Dockerfiles, no ECR, no custom handler — since Runtime manages the MCP server lifecycle for you. The orchestrator itself requires no changes either way; the Gateway abstraction means the planner doesn't know or care whether a target is a Lambda or a Runtime.

## The Pluggability Contract

Adding a new MCP server requires:
1. A YAML manifest in `mcp_registry/` (declares capabilities and domains)
2. A Dockerfile in `lambda/` (packages the server for Lambda)
3. An entry in the deploy script (registers as a Gateway target with tool schemas)

The planner reads manifests at runtime. It automatically incorporates new servers into its reasoning without any code changes to `planner.py`.
