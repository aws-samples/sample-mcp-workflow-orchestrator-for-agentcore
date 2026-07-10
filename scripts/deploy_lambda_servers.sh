#!/usr/bin/env bash
#
# Deploy 5 MCP servers as Lambda functions behind AgentCore Gateway.
#
# Usage:
#   ./scripts/deploy_lambda_servers.sh [--region us-east-1]
#
# Prerequisites: AWS CLI v2, finch (or docker), jq
#
set -eo pipefail

REGION="${AWS_REGION:-us-east-1}"
GATEWAY_NAME="mcp-workflow-orchestrator"
LAMBDA_ROLE_NAME="mcp-orchestrator-lambda-role"
GATEWAY_ROLE_NAME="mcp-orchestrator-agentcore-role"
LAMBDA_MEMORY=512
LAMBDA_TIMEOUT=120
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDA_DIR="${PROJECT_DIR}/lambda"

while [[ $# -gt 0 ]]; do
    case $1 in
        --region) REGION="$2"; shift 2 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

# Container tool (finch or docker)
if command -v finch >/dev/null 2>&1; then
    CTR=finch
elif command -v docker >/dev/null 2>&1; then
    CTR=docker
else
    echo "ERROR: finch or docker required"; exit 1
fi

log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
ok() { echo -e "\033[1;32m[OK]\033[0m $*"; }

# Server definitions
SERVERS="cloudwatch cloudtrail iam pricing documentation"

get_ecr_repo() { echo "mcp-server-$1"; }
get_lambda_name() { echo "mcp-$1"; }
get_dockerfile() { echo "Dockerfile.$1"; }

# ─── Main ────────────────────────────────────────────────────────────────────

log "Detecting AWS account..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
log "Account: ${ACCOUNT_ID}, Region: ${REGION}, Container tool: ${CTR}"

# ─── Step 1: IAM Roles ───────────────────────────────────────────────────────
echo ""
log "═══ Step 1: IAM Roles ═══"

if aws iam get-role --role-name "$LAMBDA_ROLE_NAME" >/dev/null 2>&1; then
    LAMBDA_ROLE_ARN=$(aws iam get-role --role-name "$LAMBDA_ROLE_NAME" --query 'Role.Arn' --output text)
    log "Lambda role exists: ${LAMBDA_ROLE_ARN}"
else
    log "Creating Lambda role..."
    LAMBDA_ROLE_ARN=$(aws iam create-role --role-name "$LAMBDA_ROLE_NAME" \
        --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
        --query 'Role.Arn' --output text)
    aws iam attach-role-policy --role-name "$LAMBDA_ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    # NOTE: ReadOnlyAccess is used for the demo. For production, create a custom policy
    # limiting access to only the specific APIs each Lambda needs (CloudWatch, CloudTrail, IAM, Pricing).
    aws iam attach-role-policy --role-name "$LAMBDA_ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/ReadOnlyAccess"
    aws iam attach-role-policy --role-name "$LAMBDA_ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
    ok "Created: ${LAMBDA_ROLE_ARN}"
    log "Waiting for IAM propagation (10s)..."
    sleep 10
fi

if aws iam get-role --role-name "$GATEWAY_ROLE_NAME" >/dev/null 2>&1; then
    GATEWAY_ROLE_ARN=$(aws iam get-role --role-name "$GATEWAY_ROLE_NAME" --query 'Role.Arn' --output text)
    log "Gateway role exists: ${GATEWAY_ROLE_ARN}"
else
    log "Creating Gateway role..."
    GATEWAY_ROLE_ARN=$(aws iam create-role --role-name "$GATEWAY_ROLE_NAME" \
        --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock-agentcore.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
        --query 'Role.Arn' --output text)
    aws iam attach-role-policy --role-name "$GATEWAY_ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaRole"
    ok "Created: ${GATEWAY_ROLE_ARN}"
    sleep 10
fi

# ─── Step 2: ECR Repositories ────────────────────────────────────────────────
echo ""
log "═══ Step 2: ECR Repositories ═══"

for server in $SERVERS; do
    repo=$(get_ecr_repo "$server")
    if aws ecr describe-repositories --repository-names "$repo" --region "$REGION" >/dev/null 2>&1; then
        log "ECR exists: ${repo}"
    else
        aws ecr create-repository --repository-name "$repo" --region "$REGION" --image-scanning-configuration scanOnPush=true >/dev/null
        ok "Created: ${repo}"
    fi
done

# ─── Step 3: Build & Push ────────────────────────────────────────────────────
echo ""
log "═══ Step 3: Build & Push Docker Images ═══"

aws ecr get-login-password --region "$REGION" | $CTR login --username AWS --password-stdin "$ECR_REGISTRY"

for server in $SERVERS; do
    repo=$(get_ecr_repo "$server")
    dockerfile=$(get_dockerfile "$server")
    image="${ECR_REGISTRY}/${repo}:latest"

    log "Building ${server}..."
    $CTR build --platform linux/amd64 -t "$image" -f "${LAMBDA_DIR}/${dockerfile}" "${LAMBDA_DIR}" 2>&1 | tail -1
    log "Pushing ${server}..."
    $CTR push "$image" 2>&1 | tail -1
    ok "Pushed: ${image}"
done

# ─── Step 4: Lambda Functions ────────────────────────────────────────────────
echo ""
log "═══ Step 4: Lambda Functions ═══"

for server in $SERVERS; do
    fn_name=$(get_lambda_name "$server")
    repo=$(get_ecr_repo "$server")
    image="${ECR_REGISTRY}/${repo}:latest"

    if aws lambda get-function --function-name "$fn_name" --region "$REGION" >/dev/null 2>&1; then
        log "Updating ${fn_name}..."
        aws lambda update-function-code --function-name "$fn_name" --image-uri "$image" --region "$REGION" >/dev/null
    else
        log "Creating ${fn_name}..."
        aws lambda create-function \
            --function-name "$fn_name" \
            --package-type Image \
            --code "ImageUri=${image}" \
            --role "$LAMBDA_ROLE_ARN" \
            --memory-size "$LAMBDA_MEMORY" \
            --timeout "$LAMBDA_TIMEOUT" \
            --environment "Variables={FASTMCP_LOG_LEVEL=ERROR,LOG_LEVEL=INFO,MCP_TIMEOUT=90}" \
            --region "$REGION" >/dev/null
        aws lambda wait function-active-v2 --function-name "$fn_name" --region "$REGION" 2>/dev/null || true
        aws lambda add-permission --function-name "$fn_name" --statement-id AllowAgentCoreGateway \
            --action lambda:InvokeFunction --principal bedrock-agentcore.amazonaws.com \
            --region "$REGION" >/dev/null 2>&1 || true
    fi
    ok "${fn_name}"
done

# ─── Step 5: AgentCore Gateway ───────────────────────────────────────────────
echo ""
log "═══ Step 5: AgentCore Gateway ═══"

GATEWAY_ID=$(aws bedrock-agentcore-control list-gateways --region "$REGION" \
    --query "items[?name=='${GATEWAY_NAME}'].gatewayId | [0]" --output text 2>/dev/null || echo "None")

if [[ "$GATEWAY_ID" == "None" || -z "$GATEWAY_ID" ]]; then
    log "Creating gateway..."
    # NOTE: NONE authorizer used because inbound access is controlled via SigV4 signing
    # from the orchestrator. For production with multiple clients, use AWS_IAM or CUSTOM_JWT.
    GATEWAY_ID=$(aws bedrock-agentcore-control create-gateway \
        --name "$GATEWAY_NAME" \
        --description "MCP Workflow Orchestrator" \
        --role-arn "$GATEWAY_ROLE_ARN" \
        --protocol-type MCP \
        --authorizer-type NONE \
        --region "$REGION" \
        --query gatewayId --output text)
    log "Waiting for gateway..."
    sleep 15
fi
ok "Gateway: ${GATEWAY_ID}"

# ─── Step 6: Add Targets ─────────────────────────────────────────────────────
echo ""
log "═══ Step 6: Add Targets ═══"

# Add AWS MCP Server (remote managed)
EXISTING=$(aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GATEWAY_ID" --region "$REGION" \
    --query "items[?name=='aws-mcp-server'].targetId | [0]" --output text 2>/dev/null || echo "None")
if [[ "$EXISTING" == "None" || -z "$EXISTING" ]]; then
    log "Adding aws-mcp-server target..."
    aws bedrock-agentcore-control create-gateway-target \
        --gateway-identifier "$GATEWAY_ID" --name aws-mcp-server --description "AWS MCP Server (managed)" \
        --target-configuration '{"mcp":{"mcpServer":{"endpoint":"https://aws-mcp.us-east-1.api.aws/mcp"}}}' \
        --region "$REGION" >/dev/null 2>&1 || true
    ok "aws-mcp-server"
else
    log "aws-mcp-server exists"
fi

# Add Lambda targets with correct tool schemas
add_target() {
    local name="$1" arn="$2" schema="$3"
    local target_name="${name}-mcp"
    local existing
    existing=$(aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GATEWAY_ID" --region "$REGION" \
        --query "items[?name=='${target_name}'].targetId | [0]" --output text 2>/dev/null || echo "None")
    if [[ "$existing" != "None" && -n "$existing" ]]; then
        log "${target_name} exists"
        return
    fi
    log "Adding ${target_name}..."
    aws bedrock-agentcore-control create-gateway-target \
        --gateway-identifier "$GATEWAY_ID" --name "$target_name" --description "MCP server: ${name}" \
        --target-configuration "$schema" \
        --credential-provider-configurations '[{"credentialProviderType":"GATEWAY_IAM_ROLE"}]' \
        --region "$REGION" >/dev/null 2>&1 || warn "Failed: ${target_name}"
    ok "${target_name}"
}

CW_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-cloudwatch"
CT_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-cloudtrail"
IAM_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-iam"
PR_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-pricing"
DOC_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:mcp-documentation"

add_target "cloudwatch" "$CW_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$CW_ARN"'","toolSchema":{"inlinePayload":[{"name":"get_active_alarms","description":"Get active CloudWatch alarms","inputSchema":{"type":"object","properties":{"state_value":{"type":"string"}}}},{"name":"get_metric_data","description":"Get metric data","inputSchema":{"type":"object","properties":{"namespace":{"type":"string"},"metric_name":{"type":"string"}},"required":["namespace","metric_name"]}},{"name":"execute_log_insights_query","description":"Run Logs Insights query","inputSchema":{"type":"object","properties":{"log_group_names":{"type":"array","items":{"type":"string"}},"query_string":{"type":"string"},"start_time":{"type":"string"},"end_time":{"type":"string"}},"required":["log_group_names","query_string","start_time","end_time"]}}]}}}}'

add_target "cloudtrail" "$CT_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$CT_ARN"'","toolSchema":{"inlinePayload":[{"name":"lookup_events","description":"Look up CloudTrail events","inputSchema":{"type":"object","properties":{"start_time":{"type":"string"},"end_time":{"type":"string"},"lookup_attributes":{"type":"array"}}}}]}}}}'

add_target "iam" "$IAM_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$IAM_ARN"'","toolSchema":{"inlinePayload":[{"name":"list_users","description":"List IAM users","inputSchema":{"type":"object","properties":{"path_prefix":{"type":"string"},"max_items":{"type":"integer"}}}},{"name":"list_policies","description":"List IAM policies","inputSchema":{"type":"object","properties":{"scope":{"type":"string"}}}},{"name":"get_managed_policy_document","description":"Get policy document","inputSchema":{"type":"object","properties":{"policy_arn":{"type":"string"},"version_id":{"type":"string"}},"required":["policy_arn"]}}]}}}}'

add_target "pricing" "$PR_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$PR_ARN"'","toolSchema":{"inlinePayload":[{"name":"get_pricing","description":"Get AWS service pricing","inputSchema":{"type":"object","properties":{"service_code":{"type":"string"},"region":{"type":"string"},"filters":{"type":"array"},"max_results":{"type":"integer"}},"required":["service_code"]}},{"name":"generate_cost_report","description":"Generate cost report","inputSchema":{"type":"object","properties":{"service_code":{"type":"string"}},"required":["service_code"]}}]}}}}'

add_target "documentation" "$DOC_ARN" '{"mcp":{"lambda":{"lambdaArn":"'"$DOC_ARN"'","toolSchema":{"inlinePayload":[{"name":"search_documentation","description":"Search AWS docs","inputSchema":{"type":"object","properties":{"search_phrase":{"type":"string"}},"required":["search_phrase"]}},{"name":"read_documentation","description":"Read AWS doc page","inputSchema":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}},{"name":"recommend","description":"Get AWS recommendations","inputSchema":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}]}}}}'

# ─── Done ────────────────────────────────────────────────────────────────────
echo ""
GATEWAY_URL="https://${GATEWAY_ID}.gateway.bedrock-agentcore.${REGION}.amazonaws.com/mcp"
echo "════════════════════════════════════════════════════════════════"
ok "DEPLOYMENT COMPLETE"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Gateway: ${GATEWAY_URL}"
echo ""
echo "  .env:"
echo "    AGENTCORE_GATEWAY_URL=${GATEWAY_URL}"
echo "    AWS_REGION=${REGION}"
echo "    PLANNER_MODE=sop_first"
echo "    PLANNER_MODEL_ID=us.anthropic.claude-sonnet-5"
echo ""
