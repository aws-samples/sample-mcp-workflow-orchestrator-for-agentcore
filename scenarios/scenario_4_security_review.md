# Scenario 4 — IAM Policy Review

**Prompt:** "Read this managed policy ARN and find current AWS least-privilege guidance."

**Expected static plan:**
1. **IAM** `get_managed_policy_document` — read the caller-supplied managed policy ARN and version.
2. **AWS MCP Server** or **Documentation** `search_documentation` — find current IAM least-privilege guidance.
3. **Correlate** — group the policy document and guidance by source.
4. **Decide** — summarize statements a human should inspect.

The IAM MCP server runs in its default read-only mode. This sample does not automatically prove that a policy is safe or unsafe and does not modify IAM resources.
