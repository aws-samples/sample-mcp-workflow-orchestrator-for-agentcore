# Security

## Reporting a Vulnerability

If you discover a potential security issue in this project, we ask that you notify AWS Security via our
[vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/). Please do **not**
create a public GitHub issue.

## Disclaimer

This project is provided as **sample/educational code** and is NOT intended for production use without
additional security hardening. The default deployment uses broad IAM policies and minimal gateway
authentication suitable for demonstration and development purposes only.

## AWS Services Used

| Service | Purpose | Security Consideration |
|---------|---------|----------------------|
| AWS Lambda | Hosts MCP server containers | Execution role has ReadOnlyAccess (demo only) |
| Amazon ECR | Stores container images | Scan-on-push enabled |
| Amazon Bedrock AgentCore Gateway | Unified MCP endpoint | NONE authorizer (demo only) |
| Amazon Bedrock (Claude) | AI planner reasoning | Model access controlled by IAM |
| IAM | Roles for Lambda and Gateway | ReadOnlyAccess + CloudWatchLogsFullAccess (demo only) |

## Known Security Considerations

1. **Lambda IAM Role (ReadOnlyAccess)**: The demo uses `arn:aws:iam::aws:policy/ReadOnlyAccess` for
   simplicity. This grants read access to ALL AWS services in the account.

2. **Gateway Authorizer (NONE)**: The demo Gateway is created with `--authorizer-type NONE`. Any entity
   that can reach the Gateway endpoint can invoke tools.

3. **Subprocess Execution**: The Lambda handler spawns MCP server processes. Command input is validated
   against an allowlist (`awslabs.*`, `python`) to prevent injection.

4. **Network Exposure**: Lambda functions are not placed in a VPC. They communicate with AWS APIs via
   public endpoints only.

## Production Hardening Recommendations

Before deploying in a production environment:

### Authentication & Authorization
- [ ] Change Gateway authorizer from `NONE` to `AWS_IAM` or `CUSTOM_JWT`
- [ ] Replace `ReadOnlyAccess` with per-Lambda custom policies scoped to specific APIs:
  - `mcp-cloudwatch`: Only `cloudwatch:GetMetricData`, `cloudwatch:DescribeAlarms`, `logs:*`
  - `mcp-cloudtrail`: Only `cloudtrail:LookupEvents`
  - `mcp-iam`: Only `iam:List*`, `iam:Get*`, `iam:SimulatePrincipalPolicy`
  - `mcp-pricing`: Only `pricing:GetProducts`
  - `mcp-documentation`: No AWS API access needed (uses external endpoints)
- [ ] Add resource-based policies to restrict Lambda invocation to the Gateway role only

### Network Security
- [ ] Consider placing Lambda functions in a VPC with VPC endpoints if accessing private resources
- [ ] Enable AWS WAF on the Gateway if exposed to untrusted clients
- [ ] Review and restrict Security Group rules if using VPC

### Monitoring & Audit
- [ ] Enable CloudTrail logging for all AgentCore API calls
- [ ] Set up CloudWatch Alarms for Lambda errors and throttling
- [ ] Enable AWS Config rules for IAM policy drift detection
- [ ] Add Amazon Bedrock Guardrails to the planner's Converse calls

### Supply Chain
- [ ] Pin all Python dependencies to exact versions in `pyproject.toml`
- [ ] Pin GitHub Actions to commit SHAs (not mutable tags)
- [ ] Regularly update container base images and run vulnerability scans
- [ ] Enable Amazon Inspector for continuous Lambda vulnerability assessment

## Resource Cleanup

To remove all deployed resources and avoid ongoing charges:

```bash
./scripts/destroy_lambda_servers.sh --region us-east-1
```

This removes: Gateway, Lambda functions, ECR repositories (including images), and IAM roles.
