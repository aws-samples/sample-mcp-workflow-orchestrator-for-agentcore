# Scenario 2 — Architecture Review

**Prompt:** "Review my architecture." (workload description supplied as context)

**Expected explainable plan:**
1. **Well-Architected** `review_workload` — *why:* evaluate the workload against the six WA pillars to surface risks.
2. **AWS MCP Server** `search_documentation` — *why:* pull current AWS recommendations/best practices for the flagged areas.
3. **Pricing** `get_current_pricing` — *why:* estimate the cost impact of the proposed improvements.
4. **Well-Architected** `recommendations` — *why:* produce a prioritized improvement list grounded in the findings above.
5. **Correlate** — *why:* combine pillar findings + docs + cost into one optimization report with source attribution.
6. **Decide** — *why:* emit the report and confidence.

**Domains exercised:** `architecture`, `docs`, `cost`, `optimization`.

In `sop_first` mode, the planner first checks for a Well-Architected review SOP on AWS MCP Server; if one fits, it defers to it.
