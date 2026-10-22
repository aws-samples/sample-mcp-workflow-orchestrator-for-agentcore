# Security

## Reporting a vulnerability

Report potential vulnerabilities through the [AWS vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/). Do not create a public issue containing sensitive details.

## Scope

This is sample and educational code. Deploy it only in a dedicated sandbox account. It is not a production-ready deployment without a review of your identity model, data classification, networking, package supply chain, monitoring, and operational controls.

## Current safeguards

- The deployment script requires an explicit sandbox account ID and verifies it with AWS STS.
- The AgentCore Gateway uses `AWS_IAM` inbound authorization.
- Before data-bearing Lambda targets are attached, deployment sends an unsigned MCP request and requires `401` or `403`.
- The Gateway execution role can invoke only the five sample Lambda functions.
- The Lambda execution role uses action-scoped, read-only permissions for the exposed MCP tools instead of `ReadOnlyAccess`.
- The IAM MCP server runs in its default read-only mode; the sample does not pass its `--allow-write` opt-in flag or expose mutating IAM tools.
- The Lambda adapter takes the selected tool name from AgentCore context metadata and validates it against a per-function allowlist.
- The handler does not log raw tool arguments or raw tool output by default.

## Important limitations

- The five Lambda functions currently share one action-scoped execution role. A production deployment should use separate per-server roles and resource-level restrictions where AWS supports them.
- The Lambda functions are not placed in a VPC. They use public AWS endpoints; the documentation server also requires outbound access to AWS documentation.
- Tool responses, CloudTrail events, IAM policy documents, and resource identifiers can be sensitive. Do not submit secrets, customer data, regulated data, or production incident data through this sample.
- The planner and synthesis model are not an authorization system. Review all recommendations before acting on them.
- ECR scan-on-push is enabled, but the sample does not block deployment on scan findings. Pin container base-image digests and establish a patch process before production use.

## Required validation

Before a live test:

```bash
aws sts get-caller-identity
ruff check .
pytest -q
```

Run the integration harness only with explicit sandbox confirmation:

```bash
MCP_INTEGRATION_TEST=1 \
MCP_SANDBOX_ACCOUNT_ID=123456789012 \
python scripts/test_all_tools.py
```

## Cleanup

The teardown script deletes Gateway targets, the Gateway, Lambda functions, ECR repositories and images, and IAM roles. Review the configured account and Region before running it. Never run cleanup against a shared or production account.
