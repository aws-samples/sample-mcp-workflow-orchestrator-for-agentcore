# Scenarios

These scenarios show the expected shape of the tested **static** planning flow. Supply required service names, metric names, resource identifiers, and time windows in the original request; the planner does not use one tool result to construct later arguments.

| Scenario | Prompt focus | Servers the planner can compose |
|---|---|---|
| 1. Production incident | Reliability signal and recent changes | CloudWatch → CloudTrail → Documentation → IAM |
| 2. Architecture guidance | Current guidance and public pricing | Documentation → Pricing |
| 3. Cost investigation | Known service, metric, and time window | Pricing → CloudWatch → CloudTrail → IAM → Documentation |
| 4. IAM policy review | Supplied managed-policy ARN | IAM → Documentation |

Run live scenarios only in a personal test account with no important workloads or data. Treat the synthesized answer as an investigation aid and validate it against the underlying AWS data before taking action.
