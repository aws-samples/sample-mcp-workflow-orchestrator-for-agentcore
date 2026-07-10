# Scenarios

Each scenario is a worked example showing the expected planning + correlation behavior.
Run any prompt through the CLI to see the live decision log.

| Scenario | Prompt | Servers the planner should compose |
|---|---|---|
| 1. Production incident | "My Lambda timeout suddenly increased." | CloudWatch -> CloudTrail -> AWS MCP (docs/limits) -> IAM |
| 2. Architecture review | "Review my architecture." | Well-Architected -> AWS MCP (docs) -> Pricing |
| 3. Cost optimization | "Reduce my monthly AWS bill." | Pricing -> CloudWatch (utilization) |
| 4. Security review | "Is my IAM policy overly permissive?" | IAM -> AWS MCP (docs) |
