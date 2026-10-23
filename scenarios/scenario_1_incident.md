# Scenario 1 — Production Incident

**Prompt:** "My ECS application is returning 503s after yesterday's deployment. Use this supplied time window and relevant metric names."

**Expected static plan:**
1. **CloudWatch** `get_metric_data` — confirm whether the supplied error or latency metric changed.
2. **CloudTrail** `lookup_events` — inspect API activity in the caller-supplied time window.
3. **AWS MCP Server** `search_documentation` — find current troubleshooting guidance for the service.
4. **IAM** `list_policies` — list managed policies for later human inspection if permissions are relevant.
5. **Correlate** — group observations with their source-server labels.
6. **Decide** — summarize supported findings and missing evidence.

The plan is static: output from one call is not used to construct later tool arguments. In experimental `sop_first` mode, the planner tries an unverified managed-workflow check before planning; use `authoritative` for the tested path.
