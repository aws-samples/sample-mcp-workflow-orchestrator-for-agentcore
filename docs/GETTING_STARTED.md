# Getting Started

## Prerequisites

- **Python 3.11+**
- **AWS CLI v2** with configured credentials (needs Bedrock + AgentCore + Lambda + ECR + IAM permissions)
- **Finch** (`brew install finch && finch vm init`) or Docker for container builds
- **jq** (`brew install jq`)
- **AWS Region**: `us-east-1` (AgentCore Gateway supported region)
- **A dedicated sandbox AWS account.** The tools read account metadata such as CloudTrail events, CloudWatch data, and IAM policies. Do not use a production or shared account.

## Step 1: Deploy Infrastructure

Confirm the account first, then pass its ID to the script. The script refuses to run if the IDs do not match.

```bash
aws sts get-caller-identity
./scripts/deploy_lambda_servers.sh --sandbox-account-id <your-sandbox-account-id> --region us-east-1
```

This creates:
- 2 IAM roles (Lambda execution role with action-scoped, read-only permissions, and a Gateway role that can invoke only the 5 sample functions)
- 5 ECR repositories
- 5 Docker images (one per MCP server, built from `lambda/Dockerfile.*`)
- 5 Lambda functions
- 1 AgentCore Gateway with `AWS_IAM` inbound authorization and 5 Lambda targets

The AWS MCP Server documentation tools are not a Gateway target. The orchestrator connects to them directly over a session-based MCP connection.

Before it attaches any targets, the script sends an unsigned request to the Gateway and stops unless it gets `401` or `403`.

The script is not idempotent. It stops if any of its resources already exist. To redeploy, run the tear-down script first.

**Output**: Copy the `AGENTCORE_GATEWAY_URL` from the output. The calling identity needs `bedrock-agentcore:InvokeGateway` on the Gateway ARN that the script prints.

## Step 2: Configure

```bash
cp .env.example .env
```

Edit `.env`:
```bash
AGENTCORE_GATEWAY_URL=https://<your-gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp
AWS_REGION=us-east-1
PLANNER_MODE=authoritative
PLANNER_MODEL_ID=us.anthropic.claude-sonnet-5
```

`authoritative` is the tested mode. `sop_first` is experimental; see [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## Step 3: Install Python Package

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Step 4: Verify All Tools Work

The live test calls real AWS APIs, so it requires an explicit opt-in and checks that your credentials belong to the sandbox account:

```bash
MCP_INTEGRATION_TEST=1 \
MCP_SANDBOX_ACCOUNT_ID=<your-sandbox-account-id> \
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

Preview what would be deleted first. The script verifies that the active AWS account matches the declared personal test account before listing or deleting resources:
```bash
./scripts/destroy_lambda_servers.sh \
  --sandbox-account-id <your-test-account-id> \
  --region us-east-1 \
  --dry-run
```

After reviewing the preview, remove all sample resources:

```bash
./scripts/destroy_lambda_servers.sh \
  --sandbox-account-id <your-test-account-id> \
  --region us-east-1
```

The tear-down deletes resources by their fixed sample names, including all ECR images. Use a personal test account with no important workloads or data. If deployment reports a name collision, inspect that resource first; do not assume the cleanup script owns it.

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
| Deploy says a resource already exists | Inspect the existing resource. Only if you know it came from this sample, preview cleanup with the matching `--sandbox-account-id`, then remove it. |
| Gateway returns 403 for your calls | Grant your identity `bedrock-agentcore:InvokeGateway` on the Gateway ARN printed by the deploy script |

## Adding a New Server

See the "Adding a New MCP Server" section in the [README](../README.md).
