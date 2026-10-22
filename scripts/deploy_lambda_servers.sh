#!/usr/bin/env bash
#
# Deploy five read-only MCP servers behind an AWS_IAM-protected AgentCore Gateway.
# Run only in a dedicated sandbox account.
#
# Usage:
#   AWS_PROFILE=mcp-sandbox ./scripts/deploy_lambda_servers.sh \
#     --sandbox-account-id 123456789012 --region us-east-1
#
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
SANDBOX_ACCOUNT_ID="${MCP_SANDBOX_ACCOUNT_ID:-}"
GATEWAY_NAME="mcp-workflow-orchestrator"
LAMBDA_ROLE_NAME="mcp-orchestrator-lambda-role"
GATEWAY_ROLE_NAME="mcp-orchestrator-agentcore-role"
LAMBDA_MEMORY=512
LAMBDA_TIMEOUT=120
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDA_DIR="${PROJECT_DIR}/lambda"

usage() {
    cat <<'EOF'
Usage: ./scripts/deploy_lambda_servers.sh --sandbox-account-id ACCOUNT_ID [--region REGION]

This deployment creates ECR repositories, Lambda functions, IAM roles, and an
AWS_IAM-protected AgentCore Gateway. Use only a dedicated disposable account.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sandbox-account-id) SANDBOX_ACCOUNT_ID="$2"; shift 2 ;;
        --region) REGION="$2"; shift 2 ;;
        --help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ ! "$SANDBOX_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
    echo "ERROR: --sandbox-account-id must be a 12-digit sandbox account ID." >&2
    exit 2
fi

if command -v finch >/dev/null 2>&1; then
    CTR=finch
elif command -v docker >/dev/null 2>&1; then
    CTR=docker
else
    echo "ERROR: Finch or Docker is required." >&2
    exit 2
fi

log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
ok() { echo -e "\033[1;32m[OK]\033[0m $*"; }
fail() { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; exit 1; }

SERVERS="cloudwatch cloudtrail iam pricing documentation"
get_ecr_repo() { echo "mcp-server-$1"; }
get_lambda_name() { echo "mcp-$1"; }
get_dockerfile() { echo "Dockerfile.$1"; }
allowed_tools() {
    case "$1" in
        cloudwatch) echo "get_active_alarms|get_metric_data|execute_log_insights_query" ;;
        cloudtrail) echo "lookup_events" ;;
        iam) echo "list_users|list_policies|get_managed_policy_document" ;;
        pricing) echo "get_pricing|generate_cost_report" ;;
        documentation) echo "search_documentation|read_documentation|recommend" ;;
        *) fail "Unknown server: $1" ;;
    esac
}

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
[[ "$ACCOUNT_ID" == "$SANDBOX_ACCOUNT_ID" ]] || fail \
    "Authenticated account ${ACCOUNT_ID} does not match declared sandbox ${SANDBOX_ACCOUNT_ID}."
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
log "Verified sandbox account ${ACCOUNT_ID} in ${REGION}; container tool: ${CTR}."

# Do not silently modify pre-existing sample resources in a shared account.
for server in $SERVERS; do
    aws lambda get-function --function-name "$(get_lambda_name "$server")" --region "$REGION" >/dev/null 2>&1 \
        && fail "Lambda $(get_lambda_name "$server") already exists; inspect it before deploying."
    aws ecr describe-repositories --repository-names "$(get_ecr_repo "$server")" --region "$REGION" >/dev/null 2>&1 \
        && fail "ECR repository $(get_ecr_repo "$server") already exists; inspect it before deploying."
done
aws iam get-role --role-name "$LAMBDA_ROLE_NAME" >/dev/null 2>&1 \
    && fail "IAM role ${LAMBDA_ROLE_NAME} already exists; inspect it before deploying."
aws iam get-role --role-name "$GATEWAY_ROLE_NAME" >/dev/null 2>&1 \
    && fail "IAM role ${GATEWAY_ROLE_NAME} already exists; inspect it before deploying."
EXISTING_GATEWAY=$(aws bedrock-agentcore-control list-gateways --region "$REGION" \
    --query "items[?name=='${GATEWAY_NAME}'].gatewayId | [0]" --output text 2>/dev/null || true)
[[ -z "$EXISTING_GATEWAY" || "$EXISTING_GATEWAY" == "None" ]] || fail \
    "Gateway ${GATEWAY_NAME} already exists; inspect it before deploying."

log "Creating action-scoped Lambda execution role."
LAMBDA_TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
LAMBDA_ROLE_ARN=$(aws iam create-role --role-name "$LAMBDA_ROLE_NAME" \
    --assume-role-policy-document "$LAMBDA_TRUST" --query 'Role.Arn' --output text)
aws iam attach-role-policy --role-name "$LAMBDA_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name "$LAMBDA_ROLE_NAME" --policy-name McpReadOnlyToolAccess \
    --policy-document '{
      "Version":"2012-10-17",
      "Statement":[
        {"Effect":"Allow","Action":["cloudwatch:DescribeAlarms","cloudwatch:GetMetricData","cloudwatch:ListMetrics"],"Resource":"*"},
        {"Effect":"Allow","Action":["logs:DescribeLogGroups","logs:GetQueryResults","logs:StartQuery","logs:StopQuery"],"Resource":"*"},
        {"Effect":"Allow","Action":["cloudtrail:LookupEvents"],"Resource":"*"},
        {"Effect":"Allow","Action":["iam:GetPolicy","iam:GetPolicyVersion","iam:ListPolicies","iam:ListUsers"],"Resource":"*"},
        {"Effect":"Allow","Action":["pricing:GetProducts"],"Resource":"*"}
      ]
    }'
ok "Created scoped Lambda role ${LAMBDA_ROLE_ARN}."

log "Creating ECR repositories with scan-on-push enabled."
for server in $SERVERS; do
    aws ecr create-repository --repository-name "$(get_ecr_repo "$server")" --region "$REGION" \
        --image-scanning-configuration scanOnPush=true >/dev/null
    ok "Created $(get_ecr_repo "$server")."
done

log "Building and pushing container images."
aws ecr get-login-password --region "$REGION" | "$CTR" login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null
for server in $SERVERS; do
    image="${ECR_REGISTRY}/$(get_ecr_repo "$server"):latest"
    "$CTR" build --platform linux/amd64 -t "$image" \
        -f "${LAMBDA_DIR}/$(get_dockerfile "$server")" "$LAMBDA_DIR" >/dev/null
    "$CTR" push "$image" >/dev/null
    ok "Pushed ${server} image."
done

log "Creating Lambda functions with explicit tool allowlists."
for server in $SERVERS; do
    function_name=$(get_lambda_name "$server")
    image="${ECR_REGISTRY}/$(get_ecr_repo "$server"):latest"
    aws lambda create-function --function-name "$function_name" --package-type Image \
        --code "ImageUri=${image}" --role "$LAMBDA_ROLE_ARN" --memory-size "$LAMBDA_MEMORY" \
        --timeout "$LAMBDA_TIMEOUT" \
        --environment "Variables={FASTMCP_LOG_LEVEL=ERROR,LOG_LEVEL=WARNING,MCP_TIMEOUT=90,MCP_ALLOWED_TOOLS=$(allowed_tools "$server")}" \
        --region "$REGION" >/dev/null
    aws lambda wait function-active-v2 --function-name "$function_name" --region "$REGION"
    ok "Created ${function_name}."
done

CW_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-cloudwatch"
CT_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-cloudtrail"
IAM_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-iam"
PR_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-pricing"
DOC_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-documentation"

log "Creating Gateway execution role scoped to the five sample Lambda targets."
GATEWAY_TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock-agentcore.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
GATEWAY_ROLE_ARN=$(aws iam create-role --role-name "$GATEWAY_ROLE_NAME" \
    --assume-role-policy-document "$GATEWAY_TRUST" --query 'Role.Arn' --output text)
aws iam put-role-policy --role-name "$GATEWAY_ROLE_NAME" --policy-name InvokeSampleMcpTargets \
    --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"lambda:InvokeFunction\",\"Resource\":[\"${CW_ARN}\",\"${CT_ARN}\",\"${IAM_ARN}\",\"${PR_ARN}\",\"${DOC_ARN}\"]}]}"

log "Creating AWS_IAM-protected AgentCore Gateway."
GATEWAY_CREATE=$(aws bedrock-agentcore-control create-gateway --name "$GATEWAY_NAME" \
    --description "MCP Workflow Orchestrator sandbox" --role-arn "$GATEWAY_ROLE_ARN" \
    --protocol-type MCP --authorizer-type AWS_IAM --region "$REGION" \
    --query '{id:gatewayId,arn:gatewayArn,url:gatewayUrl}' --output json)
GATEWAY_ID=$(python -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<< "$GATEWAY_CREATE")
GATEWAY_ARN=$(python -c 'import json,sys; print(json.load(sys.stdin)["arn"])' <<< "$GATEWAY_CREATE")
GATEWAY_URL=$(python -c 'import json,sys; print(json.load(sys.stdin)["url"])' <<< "$GATEWAY_CREATE")

for _ in {1..60}; do
    STATUS=$(aws bedrock-agentcore-control get-gateway --gateway-identifier "$GATEWAY_ID" \
        --region "$REGION" --query status --output text)
    [[ "$STATUS" == "READY" ]] && break
    [[ "$STATUS" == "FAILED" || "$STATUS" == "UPDATE_UNSUCCESSFUL" ]] && fail "Gateway entered ${STATUS}."
    sleep 5
done
[[ "$STATUS" == "READY" ]] || fail "Timed out waiting for Gateway readiness."

# Tighten the service-role trust after the exact Gateway ARN exists.
aws iam update-assume-role-policy --role-name "$GATEWAY_ROLE_NAME" --policy-document \
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"bedrock-agentcore.amazonaws.com\"},\"Action\":\"sts:AssumeRole\",\"Condition\":{\"StringEquals\":{\"aws:SourceAccount\":\"${ACCOUNT_ID}\"},\"ArnLike\":{\"aws:SourceArn\":\"${GATEWAY_ARN}\"}}}]}"

# Verify the inbound authorization gate before adding targets that can return account metadata.
UNSIGNED_STATUS=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --max-time 15 --request POST --header 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","method":"tools/list","id":1}' "$GATEWAY_URL" || true)
[[ "$UNSIGNED_STATUS" == "401" || "$UNSIGNED_STATUS" == "403" ]] || fail \
    "Expected unsigned Gateway denial (401/403), got HTTP ${UNSIGNED_STATUS:-no-response}."
ok "Verified unsigned Gateway access is denied (${UNSIGNED_STATUS})."

add_target() {
    local name="$1" arn="$2" schema="$3"
    aws bedrock-agentcore-control create-gateway-target --gateway-identifier "$GATEWAY_ID" \
        --name "${name}-mcp" --description "MCP server: ${name}" \
        --target-configuration "$schema" \
        --credential-provider-configurations '[{"credentialProviderType":"GATEWAY_IAM_ROLE"}]' \
        --region "$REGION" >/dev/null
}

log "Adding Lambda targets."
add_target "cloudwatch" "$CW_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$CW_ARN"'","toolSchema":{"inlinePayload":[{"name":"get_active_alarms","description":"Get active CloudWatch alarms","inputSchema":{"type":"object","properties":{"state_value":{"type":"string"}}}},{"name":"get_metric_data","description":"Get metric data","inputSchema":{"type":"object","properties":{"namespace":{"type":"string"},"metric_name":{"type":"string"}},"required":["namespace","metric_name"]}},{"name":"execute_log_insights_query","description":"Run Logs Insights query","inputSchema":{"type":"object","properties":{"log_group_names":{"type":"array","items":{"type":"string"}},"query_string":{"type":"string"},"start_time":{"type":"string"},"end_time":{"type":"string"}},"required":["log_group_names","query_string","start_time","end_time"]}}]}}}}'
add_target "cloudtrail" "$CT_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$CT_ARN"'","toolSchema":{"inlinePayload":[{"name":"lookup_events","description":"Look up CloudTrail events","inputSchema":{"type":"object","properties":{"start_time":{"type":"string"},"end_time":{"type":"string"},"lookup_attributes":{"type":"array"}}}}]}}}}'
add_target "iam" "$IAM_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$IAM_ARN"'","toolSchema":{"inlinePayload":[{"name":"list_users","description":"List IAM users","inputSchema":{"type":"object","properties":{"path_prefix":{"type":"string"},"max_items":{"type":"integer"}}}},{"name":"list_policies","description":"List IAM policies","inputSchema":{"type":"object","properties":{"scope":{"type":"string"}}}},{"name":"get_managed_policy_document","description":"Get policy document","inputSchema":{"type":"object","properties":{"policy_arn":{"type":"string"},"version_id":{"type":"string"}},"required":["policy_arn"]}}]}}}}'
add_target "pricing" "$PR_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$PR_ARN"'","toolSchema":{"inlinePayload":[{"name":"get_pricing","description":"Get AWS service pricing","inputSchema":{"type":"object","properties":{"service_code":{"type":"string"},"region":{"type":"string"},"filters":{"type":"array"},"max_results":{"type":"integer"}},"required":["service_code"]}},{"name":"generate_cost_report","description":"Generate a pricing report from supplied pricing data","inputSchema":{"type":"object","properties":{"pricing_data":{"type":"object"},"service_name":{"type":"string"}},"required":["pricing_data","service_name"]}}]}}}}'
add_target "documentation" "$DOC_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$DOC_ARN"'","toolSchema":{"inlinePayload":[{"name":"search_documentation","description":"Search AWS docs","inputSchema":{"type":"object","properties":{"search_phrase":{"type":"string"}},"required":["search_phrase"]}},{"name":"read_documentation","description":"Read AWS doc page","inputSchema":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}},{"name":"recommend","description":"Get AWS recommendations","inputSchema":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}]}}}}'

cat <<EOF

DEPLOYMENT COMPLETE
Gateway: ${GATEWAY_URL}
Gateway ARN: ${GATEWAY_ARN}

Use this environment for the live orchestrator test:
  AGENTCORE_GATEWAY_URL=${GATEWAY_URL}
  AWS_REGION=${REGION}
  PLANNER_MODE=authoritative
  PLANNER_MODEL_ID=us.anthropic.claude-sonnet-5

The caller identity needs bedrock-agentcore:InvokeGateway on:
  ${GATEWAY_ARN}
EOF
