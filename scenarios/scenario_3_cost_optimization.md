# Scenario 3 — Cost Optimization

**Prompt:** "Reduce my monthly AWS bill."

**Expected explainable plan:**
1. **CloudWatch** `get_metrics` — *why:* find under-utilized / over-provisioned resources from utilization metrics.
2. **Pricing** `get_current_pricing` — *why:* quantify current spend for the top services/resources.
3. **Pricing** `list_savings_plans` — *why:* identify Reserved Instances / Savings Plans that cut committed-use cost.
4. **Correlate** — *why:* combine utilization + pricing into ranked savings opportunities with estimated monthly impact.
5. **Decide** — *why:* emit recommendations sorted by estimated savings, with confidence.

**Domains exercised:** `cost`, `optimization`, `observability`.

Note how the planner pulls CloudWatch (an `incident`/`observability` server) into a *cost* workflow — because
utilization evidence strengthens rightsizing recommendations. This cross-domain reuse is exactly what the
capability-manifest routing enables without any planner code changes.
