# Contributing

Thanks for your interest! The easiest high-value contribution is a **new MCP server manifest**.

## Add a server
1. Create `mcp_registry/<server>.yaml` following the existing files.
2. Tag it with the right `domains` so the planner can route to it.
3. Add a scenario under `scenarios/` if it enables a new workflow.
4. Run `pytest` and `ruff check .`.

No planner code changes should be needed — if they are, open an issue so we can keep the
registry contract expressive enough to stay declarative.
