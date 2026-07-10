# Scenario 4 — Security Review

**Prompt:** "Is my IAM policy overly permissive?" (policy document supplied as context)

**Expected explainable plan:**
1. **IAM** `analyze_policy` — *why:* detect wildcard actions/resources and other risky statements.
2. **AWS MCP Server** `search_documentation` — *why:* confirm *why* each flagged permission is risky and find the least-privilege pattern.
3. **Correlate** — *why:* combine the policy analysis with documented best practice into an explained risk list.
4. **Decide** — *why:* recommend least-privilege alternatives with rationale and confidence.

**Domains exercised:** `security`, `docs`.

This is the shortest workflow — a good demonstration that the planner scales *down*: it should NOT pull in
CloudWatch/Pricing/CloudTrail when the request is purely about policy permissiveness.
