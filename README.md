# AWS MCP Workflow Orchestrator

> As MCP server catalogs grow, the hard problem shifts from building individual tools to **coordinating them intelligently**. This orchestrator solves that — it's the reasoning layer that decides which servers to call, when, and how to stitch their outputs into one coherent answer.

A **reference architecture for building multi-MCP-server systems** on Amazon Bedrock AgentCore. Instead of connecting to one server at a time, it shows how to plan multi-step investigations across multiple servers, execute them through a single Gateway connection, correlate cross-server evidence, and produce a cited answer — all while recording **why** each decision was made in an auditable log.

The six AWS MCP servers included (CloudWatch, CloudTrail, IAM, Pricing, Documentation, AWS MCP Server) are one example configuration. **The architecture is the value, not the specific servers.** You can adapt the pattern to internal tools, third-party APIs, or domain-specific services without rewriting the orchestration loop. A new server still needs a reviewed manifest, container package, Gateway schema and allowlist, scoped IAM actions, and an exact tool argument contract in the planner prompt.

**Use this as a blueprint** for building any multi-MCP-server system where you need explainable coordination, pluggable server discovery, and cross-server evidence correlation.

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

> ⚠️ **Disclaimer**: This project is provided as sample/educational code and is NOT intended for production use without additional security hardening. See [SECURITY.md](SECURITY.md) for production recommendations.

---

## When to Use This

Use this project when you need to:

- **Build a multi-MCP-server architecture** — you want a proven pattern for coordinating 2+ MCP servers behind a single gateway with a planner that routes intelligently
- **Adapt it to your own domain** — use the same orchestration loop with reviewed manifests, container packaging, Gateway tool schemas, allowlists, scoped IAM actions, and planner argument contracts for your own databases, internal APIs, or SaaS tools
- **Understand multi-server orchestration** — you want to learn how an AI agent decides which MCP servers to call, in what order, and how to combine their outputs
- **Audit agent reasoning** — you need a human-readable decision log that records *why* each tool was chosen (explainability, compliance, debugging)
- **Build on top of AgentCore** — you want a reference pattern showing how to integrate AgentCore Gateway, Lambda-hosted MCP servers, and Bedrock reasoning in one architecture

## When NOT to Use This

- **You just need one MCP server** — if your use case involves a single server (e.g., only CloudWatch), connect it directly to your agent. No orchestration layer needed.
- **You want a production-ready managed solution** — use [AWS DevOps Agent](https://aws.amazon.com/devops-agent/) (GA) or [AWS MCP Server Agent SOPs](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html) instead. They're battle-tested, fully managed, and require no infrastructure maintenance.
- **You don't need explainability** — if you don't care *why* the agent chose a particular tool and just want the answer, managed black-box solutions are simpler and faster to adopt.
- **You need multi-turn planning** — this orchestrator currently runs a single-pass plan. If your workflow requires chaining outputs (step N feeds into step N+1), you'll need to extend it or wait for that feature.

---

## Why This Exists

AWS has dozens of MCP servers — CloudWatch, CloudTrail, IAM, Pricing, Documentation — each exposing tools for a specific domain. But when you ask a cross-cutting question like *"My ECS service returns 503s — what happened?"*, no single server has the full answer. You need to:

1. Check CloudWatch for error metrics and logs
2. Check CloudTrail for what was deployed and when
3. Check IAM for any permission changes
4. Cross-reference all of that to find the root cause
5. Look up best practices for the fix

**Today, this orchestration happens manually.** AWS's managed solutions (DevOps Agent, AWS MCP Server SOPs) do this as a black box — you can't see or modify the reasoning.

**This repo is the open, explainable alternative.** It shows how to build a multi-MCP-server system with an AI planner that reasons across servers and records every decision. The orchestration loop is reusable across domains; each added server still requires an explicit, reviewed tool and deployment contract.

---

## What It Does

```
You: "Someone changed IAM policies last night. Check who, what alarms fired, and give me security recommendations."

Orchestrator:
  Step 1 → iam-mcp / list_policies          (found 3 customer policies)
  Step 2 → cloudtrail-mcp / lookup_events   (found AssumeRole + policy changes)
  Step 3 → cloudwatch-mcp / get_active_alarms (no alarms firing)
  Step 4 → documentation-mcp / search_documentation (S3 security best practices)
  Step 5 → Correlate evidence from 4 servers
  Step 6 → Synthesize answer with citations

Answer: "Your account has 3 customer policies. CloudTrail shows AssumeRole events
from... No alarms are firing. Recommended: enable CloudTrail metric filters for
IAM changes..." [Sources: iam-mcp, cloudtrail-mcp, cloudwatch-mcp, documentation-mcp]
```

---

## Key Features

- **Multi-server orchestration** — 6 MCP servers, 14 tools, all coordinated by a single planner
- **Explainable planning** — every step records *why* a server was chosen (decision log you can audit)
- **Declarative capability registry** — YAML manifests describe available capabilities; Gateway schemas, allowlists, IAM actions, and planner argument contracts remain explicit and reviewable
- **Evidence correlation** — merges outputs across servers, attributes sources
- **Hosted on AWS** — Lambda functions behind an `AWS_IAM`-authorized AgentCore Gateway with action-scoped, read-only Lambda permissions
- **One-command deploy** — `./scripts/deploy_lambda_servers.sh` creates everything from zero in a dedicated sandbox account

---

## Architecture

```
Your machine (CLI)
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Orchestrator (this repo)                                    │
│  ┌─────────┐  ┌──────────┐  ┌─────────────┐  ┌──────────┐    │
│  │ Planner │→ │ Registry │→ │ Gateway     │→ │ Correlate│    │
│  │(Bedrock)│  │ (YAML)   │  │ Client      │  │ Engine   │    │
│  └─────────┘  └──────────┘  └─────────────┘  └──────────┘    │
└──────────────────────┬───────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────────────────┐
        │              │                          │
        ▼              ▼                          ▼
  AgentCore Gateway    AWS MCP Server       (direct session)
        │              (managed remote)
        ├── Lambda: cloudwatch-mcp
        ├── Lambda: cloudtrail-mcp
        ├── Lambda: iam-mcp
        ├── Lambda: pricing-mcp
        └── Lambda: documentation-mcp
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full write-up.

---

## Quickstart

### Prerequisites

- Python 3.11+
- AWS CLI v2 with configured credentials
- [Finch](https://github.com/runfinch/finch) (or Docker) for container builds
- A **dedicated sandbox** AWS account with Bedrock + AgentCore access in `us-east-1`

> Deploy only in a sandbox account. The tools read account metadata such as CloudTrail events, CloudWatch data, and IAM policies.

### Deploy

```bash
git clone https://github.com/aws-samples/sample-mcp-workflow-orchestrator-for-agentcore
cd sample-mcp-workflow-orchestrator-for-agentcore

# Confirm you are using the intended sandbox account
aws sts get-caller-identity

# Deploy all infrastructure (Lambda, ECR, Gateway, IAM roles).
# The script refuses to run if the account ID does not match.
./scripts/deploy_lambda_servers.sh --sandbox-account-id <your-sandbox-account-id> --region us-east-1

# Copy the output into .env
cp .env.example .env
# Edit .env with the AGENTCORE_GATEWAY_URL from deploy output
```

The deploy script creates an `AWS_IAM`-authorized Gateway and verifies that an unsigned request is denied before it attaches any targets. It stops if any fixed-name resource already exists. Inspect collisions first; only remove them when you know they belong to a previous run of this sample.

### Install & Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the orchestrator
python -m orchestrator.cli "What are my CloudWatch alarms in us-east-1?"
```

### Test All Tools

The live test calls real AWS APIs, so it requires an explicit opt-in and the sandbox account ID:

```bash
MCP_INTEGRATION_TEST=1 \
MCP_SANDBOX_ACCOUNT_ID=<your-sandbox-account-id> \
python scripts/test_all_tools.py
```

Expected output: `RESULTS: 14/14 passed, 0 failed`

### Tear Down

Preview what will be deleted, then delete. Both commands verify that the active AWS account matches the declared personal test account:

```bash
./scripts/destroy_lambda_servers.sh \
  --sandbox-account-id <your-test-account-id> \
  --region us-east-1 \
  --dry-run

./scripts/destroy_lambda_servers.sh \
  --sandbox-account-id <your-test-account-id> \
  --region us-east-1
```

The script deletes fixed-name sample resources, including all images in the matching ECR repositories. Use a personal test account with no important workloads or data, and inspect any name collision before cleanup.

---

## Adding a New MCP Server

The registry makes capability discovery declarative while keeping every executable contract explicit and reviewable.

### Step 1: Create a YAML manifest

```yaml
# mcp_registry/s3.yaml
server: s3-mcp
gateway_target: s3-mcp
domains: [storage, security, data]
provides:
  - capability: list_buckets
    good_for: "listing S3 buckets and their configurations"
  - capability: get_bucket_policy
    good_for: "checking bucket policies for public access or misconfigurations"
preconditions: [region]
```

### Step 2: Create a Dockerfile

```dockerfile
# lambda/Dockerfile.s3
FROM public.ecr.aws/lambda/python:3.12
RUN pip install --no-cache-dir awslabs.mcp-lambda-handler awslabs.s3-mcp-server
ENV MCP_SERVER_COMMAND="awslabs.s3-mcp-server"
ENV MCP_TIMEOUT="90"
COPY handler.py ${LAMBDA_TASK_ROOT}/
CMD ["handler.lambda_handler"]
```

### Step 3: Add to the deploy script

In `scripts/deploy_lambda_servers.sh` and the planner contract:

1. Add your server to the `SERVERS` list.
2. Add its tool names to the `allowed_tools` function. The Lambda handler rejects any tool not on this list.
3. Add an `add_target` call with the exact Gateway input schema.
4. Add only the AWS API actions the server needs to the Lambda role policy.
5. Add the same tool names and argument fields to `PLAN_SYSTEM` in `orchestrator/planner.py` so the model can construct schema-valid calls.
6. Add a safe integration-test case and validate it in a personal test account with no important workloads or data.

Then redeploy.

### Step 4: Validate the Integration

The planner automatically sees the capability name and description from the YAML registry, but it also needs the explicit argument contract described above. This keeps the reusable orchestration loop unchanged without asking the model to guess a new tool's fields.

---

## Repository Layout

```
orchestrator/           Core Python package
  planner.py            Explainable planner (plan → act → observe → correlate → decide)
  registry.py           Loads YAML manifests, presents capability catalog
  gateway_client.py     MCP client (Gateway + direct AWS MCP Server)
  correlation.py        Evidence correlation engine
  decision_log.py       Structured reasoning trace
  config.py             Settings from .env
  cli.py                CLI entrypoint

lambda/                 Lambda container images
  handler.py            Generic handler (spawns MCP server subprocess)
  Dockerfile.*          One per MCP server

mcp_registry/           Pluggable server manifests (the extensibility contract)
  aws_mcp_server.yaml
  cloudwatch.yaml
  cloudtrail.yaml
  iam.yaml
  pricing.yaml
  documentation.yaml

scripts/                Infrastructure automation
  deploy_lambda_servers.sh    One-command full deployment
  destroy_lambda_servers.sh   One-command teardown
  test_all_tools.py           Validates all 14 tools

scenarios/              Example prompts and expected reasoning
tests/                  Unit tests (no AWS credentials needed)
docs/                   Architecture documentation
```

---

## How It Works

See [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) for the detailed flow.

---

## Limitations

| Limitation | Detail | Workaround |
|-----------|--------|------------|
| **Pricing queries require filters** | The AWS Pricing API returns 300K+ chars for unfiltered queries; the server returns a "use more specific filters" suggestion | Pass `service_code` + `filters` + `max_results` for targeted results |
| **Single-pass planner** | The planner can't use output from step N as input to step N+1 in the same run (e.g., get a policy ARN then read it) | Run again with the specific ARN, or implement multi-turn planning |
| **Lambda cold starts** | First invocation of each Lambda takes 5-15s (container image startup) | Subsequent calls are fast; use provisioned concurrency for production |
| **aws-mcp-server auth** | The managed AWS MCP Server's `call_aws`/`run_script` tools require OAuth (session-based auth for write operations) | Use `search_documentation`/`read_documentation` (work without auth); Lambda targets handle all AWS API calls via IAM |
| **Stdio MCP server buffering** | Some MCP servers (async/FastMCP-based) may have output buffering issues in Lambda's subprocess model | The handler uses threading + stdin close to force output; works for all tested servers |

---

## Contributing

Issues and PRs welcome — especially:
- New server manifests under `mcp_registry/`
- New Dockerfiles under `lambda/`
- Planner prompt improvements
- Multi-turn planning support

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

MIT-0. See [`LICENSE`](LICENSE).
