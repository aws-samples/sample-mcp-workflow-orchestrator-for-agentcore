# Getting Started

## Prerequisites

- **Python 3.11+**
- **AWS CLI v2** with configured credentials (needs Bedrock + AgentCore + Lambda + ECR + IAM permissions)
- **Finch** (`brew install finch && finch vm init`) or Docker for container builds
- **jq** (`brew install jq`)
- **AWS Region**: `us-east-1` (AgentCore Gateway supported region)

## Step 1: Deploy Infrastructure

```bash
./scripts/deploy_lambda_servers.sh --region us-east-1
```

This creates:
- 2 IAM roles (Lambda execution + Gateway)
- 5 ECR repositories
- 5 Docker images (one per MCP server, built from `lambda/Dockerfile.*`)
- 5 Lambda functions
- 1 AgentCore Gateway with 6 targets (5 Lambda + 1 remote AWS MCP Server)

The script is idempotent — run it again to update existing resources.

**Output**: Copy the `AGENTCORE_GATEWAY_URL` from the output.

## Step 2: Configure

```bash
cp .env.example .env
```

Edit `.env`:
```bash
AGENTCORE_GATEWAY_URL=https://<your-gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp
AWS_REGION=us-east-1
PLANNER_MODE=sop_first
PLANNER_MODEL_ID=us.anthropic.claude-sonnet-5
```

## Step 3: Install Python Package

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Step 4: Verify All Tools Work

```bash
python scripts/test_all_tools.py
```

Expected output: `RESULTS: 14/14 passed, 0 failed`

## Step 5: Run the Orchestrator

```bash
python -m orchestrator.cli "What are my CloudWatch alarms in us-east-1?"
python -m orchestrator.cli "List my IAM users and policies"
python -m orchestrator.cli "Give me a security overview of my account"
```

## Tear Down

Remove all AWS resources:

```bash
./scripts/destroy_lambda_servers.sh --region us-east-1
```

Preview what would be deleted:
```bash
./scripts/destroy_lambda_servers.sh --region us-east-1 --dry-run
```

Keep IAM roles for reuse:
```bash
./scripts/destroy_lambda_servers.sh --region us-east-1 --keep-roles
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `finch vm init` required | Run `finch vm init` to start the Finch VM |
| Midway expired | Re-authenticate with your credential provider |
| Gateway returns 404 | Wait 15-30s after deploy for targets to sync |
| Lambda timeout | Increase `LAMBDA_TIMEOUT` in deploy script (default 120s) |
| "result_too_large" from pricing | Use more specific filters (`service_code` + `filters` + `max_results`) |
| Unit test failures | Run `pip install -e ".[dev]"` first |

## Adding a New Server

See the "Adding a New MCP Server" section in the [README](../README.md).
