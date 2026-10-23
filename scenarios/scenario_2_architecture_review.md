# Scenario 2 — Architecture Guidance

**Prompt:** "Find current AWS guidance and public pricing inputs for this supplied workload and migration target."

**Expected static plan:**
1. **Documentation** `search_documentation` — find current AWS architecture guidance.
2. **Documentation** `read_documentation` or `recommend` — read or expand from a caller-supplied documentation URL.
3. **Pricing** `get_pricing` — retrieve filtered public pricing for a specified service and Region.
4. **Correlate** — group documentation and pricing observations by source.
5. **Decide** — summarize inputs for a human architecture review.

This sample does not perform an AWS Well-Architected workload review or calculate workload-specific cost. In experimental `sop_first` mode, it tries an unverified managed-workflow check; use `authoritative` for the tested path.
