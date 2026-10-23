# Scenario 3 — Cost Investigation

**Prompt:** "Investigate a recent cost increase for this specified AWS service, metric, Region, and time window."

**Expected static plan:**
1. **Pricing** `get_pricing` — retrieve filtered public pricing for the specified service and Region.
2. **CloudWatch** `get_metric_data` — inspect the specified utilization metric.
3. **CloudTrail** `lookup_events` — inspect API activity in the supplied time window.
4. **IAM** `list_policies` — list managed policies for later human inspection.
5. **Documentation** `search_documentation` — find current cost-optimization guidance.
6. **Correlate and decide** — summarize source-labelled observations and evidence gaps.

The sample does not query account billing records or calculate actual savings. Use Cost Explorer or Cost and Usage Reports to confirm the billed-cost delta.
