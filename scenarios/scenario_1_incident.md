# Scenario 1 — Production Incident

**Prompt:** "My ECS application is returning 503s after yesterday's deployment."

**Expected explainable plan:**
1. **CloudWatch** `get_metrics` — *why:* confirm error/latency spike and pin the incident window.
2. **CloudTrail** `recent_changes` — *why:* find the deploy/config change in that window.
3. **AWS MCP Server** `search_documentation` — *why:* check relevant service limits/known 503 causes.
4. **IAM** `recent_policy_changes` — *why:* rule out a permission change as the trigger.
5. **Correlate** — merge into a root-cause narrative with source attribution.
6. **Decide** — emit remediation + confidence.

In `sop_first` mode, step 0 checks whether AWS MCP Server has an incident SOP that fits before planning.
