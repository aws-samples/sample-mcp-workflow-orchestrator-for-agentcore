#!/usr/bin/env bash
#
# Destroy resources created by deploy_lambda_servers.sh in a declared sandbox account.
#
# This removes:
#   - AgentCore Gateway and all targets
#   - Lambda functions
#   - ECR repositories (including all images)
#   - IAM roles and policies
#
# Usage:
#   ./scripts/destroy_lambda_servers.sh --sandbox-account-id 123456789012 --dry-run
#   ./scripts/destroy_lambda_servers.sh --sandbox-account-id 123456789012
#   ./scripts/destroy_lambda_servers.sh --sandbox-account-id 123456789012 --keep-roles
#
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
SANDBOX_ACCOUNT_ID="${MCP_SANDBOX_ACCOUNT_ID:-}"
GATEWAY_NAME="mcp-workflow-orchestrator"
LAMBDA_ROLE_NAME="mcp-orchestrator-lambda-role"
GATEWAY_ROLE_NAME="mcp-orchestrator-agentcore-role"
DRY_RUN=false
KEEP_ROLES=false

usage() {
    cat <<'EOF'
Usage: ./scripts/destroy_lambda_servers.sh --sandbox-account-id ACCOUNT_ID [options]

Required:
  --sandbox-account-id ACCOUNT_ID  Twelve-digit disposable sandbox account ID.

Options:
  --region REGION                  AWS Region (default: AWS_REGION or us-east-1).
  --dry-run                        Preview deletions without modifying resources.
  --keep-roles                     Keep the two sample IAM roles.
  --help                           Show this message.

This script deletes resources with the sample's fixed names, including all images
in the matching ECR repositories. Run --dry-run first and never use a production
or shared account.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sandbox-account-id)
            SANDBOX_ACCOUNT_ID="$2"
            shift 2
            ;;
        --region)
            REGION="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --keep-roles)
            KEEP_ROLES=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! "$SANDBOX_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
    echo "ERROR: --sandbox-account-id must be a 12-digit sandbox account ID." >&2
    exit 2
fi

LAMBDA_FUNCTIONS=(
    "mcp-cloudwatch"
    "mcp-cloudtrail"
    "mcp-iam"
    "mcp-pricing"
    "mcp-documentation"
)

ECR_REPOS=(
    "mcp-server-cloudwatch"
    "mcp-server-cloudtrail"
    "mcp-server-iam"
    "mcp-server-pricing"
    "mcp-server-documentation"
)

log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; }
success() { echo -e "\033[1;32m[OK]\033[0m $*"; }
dry() { echo -e "\033[1;35m[DRY RUN]\033[0m Would: $*"; }

verify_account() {
    local actual_account
    actual_account=$(aws sts get-caller-identity --query Account --output text)
    if [[ "$actual_account" != "$SANDBOX_ACCOUNT_ID" ]]; then
        error "Authenticated account ${actual_account} does not match declared sandbox ${SANDBOX_ACCOUNT_ID}."
        exit 1
    fi
    log "Verified sandbox account: ${actual_account}"
}

delete_gateway() {
    local gateway_id
    gateway_id=$(aws bedrock-agentcore-control list-gateways \
        --region "$REGION" \
        --query "items[?name=='${GATEWAY_NAME}'].gatewayId | [0]" \
        --output text 2>/dev/null || echo "None")

    if [[ "$gateway_id" == "None" || -z "$gateway_id" ]]; then
        log "Gateway '${GATEWAY_NAME}' not found, skipping."
        return
    fi

    log "Found gateway: ${gateway_id}"
    local targets
    targets=$(aws bedrock-agentcore-control list-gateway-targets \
        --gateway-identifier "$gateway_id" \
        --region "$REGION" \
        --query 'items[].{id:targetId,name:name}' \
        --output json 2>/dev/null || echo "[]")

    echo "$targets" | jq -r '.[] | "\(.id) \(.name)"' 2>/dev/null | while read -r target_id target_name; do
        [[ -z "$target_id" ]] && continue
        if [[ "$DRY_RUN" == "true" ]]; then
            dry "delete target: ${target_name} (${target_id})"
        else
            log "Deleting target: ${target_name} (${target_id})"
            aws bedrock-agentcore-control delete-gateway-target \
                --gateway-identifier "$gateway_id" \
                --target-id "$target_id" \
                --region "$REGION" >/dev/null
        fi
    done

    if [[ "$DRY_RUN" == "true" ]]; then
        dry "delete gateway: ${gateway_id}"
        return
    fi

    # Target deletion is asynchronous. Wait until the Gateway has no targets.
    for _ in {1..30}; do
        local remaining
        remaining=$(aws bedrock-agentcore-control list-gateway-targets \
            --gateway-identifier "$gateway_id" \
            --region "$REGION" \
            --query 'length(items)' --output text 2>/dev/null || echo "0")
        [[ "$remaining" == "0" ]] && break
        sleep 2
    done

    log "Deleting gateway: ${gateway_id}"
    aws bedrock-agentcore-control delete-gateway \
        --gateway-identifier "$gateway_id" \
        --region "$REGION" >/dev/null
    success "Gateway deletion started."
}

delete_lambdas() {
    for function_name in "${LAMBDA_FUNCTIONS[@]}"; do
        if ! aws lambda get-function --function-name "$function_name" \
            --region "$REGION" >/dev/null 2>&1; then
            log "${function_name} not found, skipping."
            continue
        fi
        if [[ "$DRY_RUN" == "true" ]]; then
            dry "delete Lambda function: ${function_name}"
        else
            aws lambda delete-function --function-name "$function_name" --region "$REGION"
            success "Deleted Lambda function: ${function_name}"
        fi
    done
}

delete_ecr_repos() {
    for repository_name in "${ECR_REPOS[@]}"; do
        if ! aws ecr describe-repositories --repository-names "$repository_name" \
            --region "$REGION" >/dev/null 2>&1; then
            log "${repository_name} not found, skipping."
            continue
        fi
        if [[ "$DRY_RUN" == "true" ]]; then
            dry "delete ECR repository: ${repository_name} (force, including all images)"
        else
            aws ecr delete-repository --repository-name "$repository_name" \
                --region "$REGION" --force >/dev/null
            success "Deleted ECR repository: ${repository_name}"
        fi
    done
}

delete_role() {
    local role_name="$1"
    if ! aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
        log "Role ${role_name} not found, skipping."
        return
    fi
    if [[ "$DRY_RUN" == "true" ]]; then
        dry "delete IAM role: ${role_name} after removing its policies"
        return
    fi

    local policies
    policies=$(aws iam list-attached-role-policies --role-name "$role_name" \
        --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null || echo "")
    for policy_arn in $policies; do
        [[ -n "$policy_arn" ]] && aws iam detach-role-policy \
            --role-name "$role_name" --policy-arn "$policy_arn"
    done

    local inline_policies
    inline_policies=$(aws iam list-role-policies --role-name "$role_name" \
        --query 'PolicyNames[]' --output text 2>/dev/null || echo "")
    for policy_name in $inline_policies; do
        [[ -n "$policy_name" ]] && aws iam delete-role-policy \
            --role-name "$role_name" --policy-name "$policy_name"
    done

    aws iam delete-role --role-name "$role_name"
    success "Deleted IAM role: ${role_name}"
}

main() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "DRY RUN MODE — no resources will be deleted"
    fi
    log "Region: ${REGION}"
    verify_account

    delete_gateway
    delete_lambdas
    delete_ecr_repos

    if [[ "$KEEP_ROLES" == "true" ]]; then
        log "Keeping IAM roles (--keep-roles)."
    else
        delete_role "$LAMBDA_ROLE_NAME"
        delete_role "$GATEWAY_ROLE_NAME"
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        success "DRY RUN COMPLETE — no resources were modified"
    else
        success "TEARDOWN COMPLETE — sample resources removed"
    fi
}

main "$@"
