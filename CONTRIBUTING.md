# Contributing

Thanks for your interest! A useful contribution is a reviewed MCP server integration.

## Add a server

1. Create `mcp_registry/<server>.yaml` following the existing manifests, including capability names, descriptions, domains, and preconditions.
2. Add a Dockerfile under `lambda/` that packages the server.
3. In `scripts/deploy_lambda_servers.sh`, add the server name, exact Gateway input schema, Lambda tool allowlist, and only the AWS API actions it needs.
4. Add the same exact tool names and argument fields to `PLAN_SYSTEM` in `orchestrator/planner.py`. Manifests currently do not contain complete input schemas, so the planner prompt must be updated explicitly.
5. Add a safe case to the guarded live integration harness.
6. Run `pytest -q` and `ruff check .`.
7. Validate live behavior only in a personal test account with no important workloads or data.

Keep the reusable orchestration loop unchanged unless the contribution requires a new orchestration capability. Never commit credentials, account output, customer data, or internal references.
