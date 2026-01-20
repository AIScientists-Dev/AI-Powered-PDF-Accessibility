#!/bin/bash
# Update EC2 server from GitHub
# Usage: ./deploy/update-ec2.sh

set -e

INSTANCE_ID="i-0e875c3fc07d73dca"
REGION="us-east-1"

echo "=== Deploying latest code from GitHub to EC2 ==="

# Send update command
COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd /home/mcpuser/app",
        "GIT_SSH_COMMAND=\"ssh -i /root/.ssh/github_deploy_key -o StrictHostKeyChecking=no\" git pull origin main",
        "source venv/bin/activate",
        "pip install -r requirements.txt -q",
        "systemctl restart accessibility-mcp",
        "sleep 3",
        "curl -s http://localhost:8080/health"
    ]' \
    --query 'Command.CommandId' \
    --output text)

echo "Command ID: $COMMAND_ID"
echo "Waiting for deployment..."

# Wait for completion
sleep 20

# Get result
aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query '[Status, StandardOutputContent]' \
    --output text

echo ""
echo "=== Deployment complete ==="
echo "Test: curl http://172.31.15.119:8080/health"
