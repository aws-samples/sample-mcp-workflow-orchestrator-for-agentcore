# How It Works

## The Orchestration Loop

The orchestrator follows a **Plan → Act → Observe → Correlate → Decide** loop:

```
User Request
    │
    ▼
1. REGISTRY: Load mcp_registry/*.yaml
   → Knows which servers exist, what they can do, which domains they cover
    │
    ▼
2. SOP CHECK (experimental, only if mode=sop_first):
   → Tries to ask AWS MCP Server whether a pre-built workflow matches
   → If the check fails or finds nothing, proceeds to custom planning
   → Not covered by the integration test; use authoritative mode for tested behavior
    │
    ▼
3. PLAN: Call Bedrock (Claude Sonnet 5) with:
   → The user's question
   → The capability catalog from all servers (generated from YAML manifests)
   → Model returns a multi-step plan: which server, which tool, what arguments, why
    │
    ▼
4. EXECUTE: For each planned step:
   → Route to the correct server via Gateway Client
   → Gateway routes to the Lambda target (IAM auth)
   → Lambda spawns the MCP server, sends the tool call, returns result
   → Decision log records the rationale and observation
    │
    ▼
5. CORRELATE: Group evidence from all servers
   → Label each observation with its source server and tool
   → The plan is static: later steps do not use earlier results
    │
    ▼
6. SYNTHESIZE: Call Bedrock again with all evidence
   → Produce a final answer with citations
   → Record the "decide" step in the decision log
```

## How Tool Routing Works

The Gateway presents a unified MCP endpoint. Tools are prefixed with their target name:

```
cloudwatch-mcp___get_active_alarms
cloudwatch-mcp___get_metric_data
cloudtrail-mcp___lookup_events
iam-mcp___list_users
pricing-mcp___get_pricing
documentation-mcp___search_documentation
```

The Gateway requires SigV4-signed requests (`AWS_IAM` authorization). Unsigned requests are rejected.

The Gateway Client maps the planner's `(server, tool)` pair to the full prefixed name:
- `("cloudwatch-mcp", "get_active_alarms")` → `"cloudwatch-mcp___get_active_alarms"`
- `("aws-mcp-server", "search_documentation")` → `"aws___search_documentation"`. This one does **not** go through the Gateway; the client calls the managed AWS MCP Server directly over a session-based connection.

## How Lambda Targets Work

Each Lambda function:
1. Receives the tool arguments directly from the Gateway (no JSON-RPC wrapper)
2. Reads the selected tool name from the AgentCore context metadata (`bedrockAgentCoreToolName`)
3. Rejects the call if the tool is not in that function's `MCP_ALLOWED_TOOLS` list
4. Spawns the awslabs MCP server as a subprocess
5. Sends `initialize`, waits for the response, then sends `notifications/initialized` and `tools/call`
6. Reads the JSON-RPC response from stdout (threaded reader with timeout)
7. Returns the tool result to the Gateway

```
Gateway → Lambda Event (just args)
                │
                ▼
         handler.py
                │
                ├── shutil.which("awslabs.cloudwatch-mcp-server")
                ├── subprocess.Popen(server)
                ├── stdin: initialize → (wait) → notifications/initialized + tools/call
                ├── stdout: read response (threaded)
                └── return result
```

## How the Planner Chooses Servers

The planner receives a capability catalog generated from the YAML manifests:

```
- cloudwatch-mcp: get_metric_data (reading metrics...), get_active_alarms (checking alarms...)
- cloudtrail-mcp: lookup_events (finding recent API changes...)
- iam-mcp: list_users (listing IAM users...), list_policies (listing policies...)
- pricing-mcp: get_pricing (getting pricing...), generate_cost_report (cost reports...)
- documentation-mcp: search_documentation (searching docs...), recommend (recommendations...)
```

The model decides based on:
- **Domain matching**: "cost question" → pricing-mcp, "security" → iam-mcp + cloudtrail-mcp
- **Capability matching**: "check alarms" → cloudwatch-mcp/get_active_alarms
- **Dependency ordering**: confirm the problem first, then hunt for the cause
- **Cross-server correlation**: spread steps across servers to build a complete picture

The manifests currently carry capability names and descriptions, not complete input schemas. Exact tool argument fields are defined in `PLAN_SYSTEM` in `orchestrator/planner.py`. When adding a server, update that prompt contract together with the Gateway schema and integration test; otherwise the model would have to guess the tool arguments.

## Decision Log Format

Every step is recorded:

```markdown
## Step 3: invoke_tool
- **Server:** cloudwatch-mcp
- **Tool:** get_active_alarms
- **Why:** Check for any currently firing alarms that may indicate active incidents.
- **Observed:** {"metric_alarms": [], "composite_alarms": [], "message": "No active alarms found"}
```

This is the **explainability differentiator** — you can audit exactly why each tool was called and what it returned.

## Configuration

All configuration is in `.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `AGENTCORE_GATEWAY_URL` | Gateway MCP endpoint | (required) |
| `AWS_REGION` | AWS region | `us-east-1` |
| `PLANNER_MODE` | `sop_first` or `authoritative` | `sop_first` in code; `.env.example` sets `authoritative` |
| `PLANNER_MODEL_ID` | Bedrock model for planning | `us.anthropic.claude-sonnet-5` |

## Two Planning Modes

| Mode | Behavior |
|------|----------|
| `authoritative` | Always build a custom plan over the registry. This is the tested mode. |
| `sop_first` | Experimental. Tries to check AWS MCP Server for a pre-built workflow first; if the check fails or finds nothing, builds a custom plan. Not covered by the integration test. |
