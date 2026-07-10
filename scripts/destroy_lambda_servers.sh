#!/usr/bin/env bash
#
# Destroy all resources created by deploy_lambda_servers.sh.
#
# This removes:
#   - AgentCore Gateway and all targets
#   - Lambda functions
#   - ECR repositories (and all images)
#   - IAM roles and policies
#
# Usage:
#   ./scripts/destroy_lambda_servers.sh
#   ./scripts/destroy_lambda_servers.sh --region us-west-2
#   ./scripts/destroy_lambda_servers.sh --dry-run
#   ./scripts/destroy_lambda_servers.sh --keep-roles
#
set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

REGION="${AWS_REGION:-us-east-1}"
GATEWAY_NAME="mcp-workflow-orchestrator"
LAMBDA_ROLE_NAME="mcp-orchestrator-lambda-role"
GATEWAY_ROLE_NAME="mcp-orchestrator-agentcore-role"
DRY_RUN=false
KEEP_ROLES=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
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
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Lambda function names
LAMBDA_FUNCTIONS=(
    "mcp-cloudwatch"
    "mcp-cloudtrail"
    "mcp-iam"
    "mcp-pricing"
    "mcp-documentation"
)

# ECR repository names
ECR_REPOS=(
    "mcp-server-cloudwatch"
    "mcp-server-cloudtrail"
    "mcp-server-iam"
    "mcp-server-pricing"
    "mcp-server-documentation"
)

# ─── Helper Functions ────────────────────────────────────────────────────────

log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err() { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; }
success() { echo -e "\033[1;32m[OK]\033[0m $*"; }
dry() { echo -e "\033[1;35m[DRY RUN]\033[0m Would: $*"; }

run_or_dry() {
    if [[ "$DRY_RUN" == "true" ]]; then
        dry "$*"
    else
        eval "$@"
    fi
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo ""
        echo "════════════════════════════════════════════════════════════════"
        echo "  DRY RUN MODE — no resources will be deleted"
        echo "════════════════════════════════════════════════════════════════"
        echo ""
    fi

    log "Region: ${REGION}"
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    log "Account: ${ACCOUNT_ID}"

    # ─── Step 1: Delete Gateway & Targets ─────────────────────────────────
    echo ""
    log "═══ Step 1: Delete AgentCore Gateway ═══"
    delete_gateway

    # ─── Step 2: Delete Lambda Functions ──────────────────────────────────
    echo ""
    log "═══ Step 2: Delete Lambda Functions ═══"
    delete_lambdas

    # ─── Step 3: Delete ECR Repositories ──────────────────────────────────
    echo ""
    log "═══ Step 3: Delete ECR Repositories ═══"
    delete_ecr_repos

    # ─── Step 4: Delete IAM Roles ─────────────────────────────────────────
    echo ""
    if [[ "$KEEP_ROLES" == "true" ]]; then
        log "═══ Step 4: Keeping IAM Roles (--keep-roles) ═══"
    else
        log "═══ Step 4: Delete IAM Roles ═══"
        delete_role "$LAMBDA_ROLE_NAME"
        delete_role "$GATEWAY_ROLE_NAME"
    fi

    # ─── Done ─────────────────────────────────────────────────────────────
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    if [[ "$DRY_RUN" == "true" ]]; then
        success "DRY RUN COMPLETE — no resources were modified"
    else
        success "TEARDOWN COMPLETE — all resources removed"
    fi
    echo "════════════════════════════════════════════════════════════════"
    echo ""
}

# ─── Gateway ─────────────────────────────────────────────────────────────────

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

    # Delete all targets first
    log "Deleting gateway targets..."
    local targets
    targets=$(aws bedrock-agentcore-control list-gateway-targets \
        --gateway-identifier "$gateway_id" \
        --region "$REGION" \
        --query 'items[].{id:targetId,name:name}' \
        --output json 2>/dev/null || echo "[]")

    echo "$targets" | jq -r '.[] | "\(.id) \(.name)"' 2>/dev/null | while read -r target_id target_name; do
        if [[ -n "$target_id" ]]; then
            if [[ "$DRY_RUN" == "true" ]]; then
                dry "delete target: ${target_name} (${target_id})"
            else
                log "  Deleting target: ${target_name} (${target_id})"
                aws bedrock-agentcore-control delete-gateway-target \
                    --gateway-identifier "$gateway_id" \
                    --target-id "$target_id" \
                    --region "$REGION" 2>/dev/null || warn "Could not delete target ${target_id}"
            fi
        fi
    done

    # Wait a bit for targets to be removed
    if [[ "$DRY_RUN" != "true" ]]; then
        sleep 3
    fi

    # Delete the gateway
    if [[ "$DRY_RUN" == "true" ]]; then
        dry "delete gateway: ${gateway_id}"
    else
        log "Deleting gateway: ${gateway_id}"
        aws bedrock-agentcore-control delete-gateway \
            --gateway-identifier "$gateway_id" \
            --region "$REGION" 2>/dev/null || warn "Could not delete gateway"
        success "Gateway deleted."
    fi
}

# ─── Lambda ──────────────────────────────────────────────────────────────────

delete_lambdas() {
    for fn_name in "${LAMBDA_FUNCTIONS[@]}"; do
        if aws lambda get-function --function-name "$fn_name" \
            --region "$REGION" >/dev/null 2>&1; then
            if [[ "$DRY_RUN" == "true" ]]; then
                dry "delete Lambda function: ${fn_name}"
            else
                log "Deleting: ${fn_name}"
                aws lambda delete-function \
                    --function-name "$fn_name" \
                    --region "$REGION"
                success "Deleted: ${fn_name}"
            fi
        else
            log "${fn_name} not found, skipping."
        fi
    done
}

# ─── ECR ─────────────────────────────────────────────────────────────────────

delete_ecr_repos() {
    for repo_name in "${ECR_REPOS[@]}"; do
        if aws ecr describe-repositories --repository-names "$repo_name" \
            --region "$REGION" >/dev/null 2>&1; then
            if [[ "$DRY_RUN" == "true" ]]; then
                dry "delete ECR repository: ${repo_name} (force, including all images)"
            else
                log "Deleting ECR repository: ${repo_name} (including all images)..."
                aws ecr delete-repository \
                    --repository-name "$repo_name" \
                    --region "$REGION" \
                    --force >/dev/null
                success "Deleted: ${repo_name}"
            fi
        else
            log "${repo_name} not found, skipping."
        fi
    done
}

# ─── IAM Roles ───────────────────────────────────────────────────────────────

delete_role() {
    local role_name="$1"

    if ! aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
        log "Role ${role_name} not found, skipping."
        return
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        dry "delete IAM role: ${role_name}"
        return
    fi

    log "Deleting role: ${role_name}"

    # Detach all managed policies
    local policies
    policies=$(aws iam list-attached-role-policies --role-name "$role_name" \
        --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null || echo "")

    for policy_arn in $policies; do
        if [[ -n "$policy_arn" ]]; then
            aws iam detach-role-policy --role-name "$role_name" --policy-arn "$policy_arn"
        fi
    done

    # Delete inline policies
    local inline
    inline=$(aws iam list-role-policies --role-name "$role_name" \
        --query 'PolicyNames[]' --output text 2>/dev/null || echo "")

    for policy_name in $inline; do
        if [[ -n "$policy_name" ]]; then
            aws iam delete-role-policy --role-name "$role_name" --policy-name "$policy_name"
        fi
    done

    # Delete the role
    aws iam delete-role --role-name "$role_name"
    success "Deleted role: ${role_name}"
}

# ─── Run ─────────────────────────────────────────────────────────────────────

main "$@"
