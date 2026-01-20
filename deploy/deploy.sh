#!/bin/bash
set -e

# ============================================
# Accessibility MCP Server - EC2 Deployment Script
# ============================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Accessibility MCP Server Deployment ===${NC}"

# Configuration
STACK_NAME="${STACK_NAME:-accessibility-mcp-server}"
REGION="${AWS_REGION:-us-east-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-c6i.2xlarge}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Check for required environment variables
if [ -z "$GEMINI_API_KEY" ]; then
    echo -e "${YELLOW}GEMINI_API_KEY not set. Reading from .env file...${NC}"
    if [ -f "$PROJECT_DIR/.env" ]; then
        export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
    fi

    if [ -z "$GEMINI_API_KEY" ]; then
        echo -e "${RED}Error: GEMINI_API_KEY is required${NC}"
        echo "Set it with: export GEMINI_API_KEY=your_api_key"
        exit 1
    fi
fi

# Check AWS CLI
echo -e "${YELLOW}Checking AWS CLI...${NC}"
if ! command -v aws &> /dev/null; then
    echo -e "${RED}AWS CLI not found. Please install it first.${NC}"
    exit 1
fi

# Verify AWS credentials
echo -e "${YELLOW}Verifying AWS credentials...${NC}"
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
    echo -e "${RED}AWS credentials not configured properly${NC}"
    exit 1
}
echo -e "${GREEN}Using AWS Account: $AWS_ACCOUNT${NC}"

# Check if stack exists
STACK_STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_EXISTS")

if [ "$STACK_STATUS" != "NOT_EXISTS" ]; then
    echo -e "${YELLOW}Stack '$STACK_NAME' already exists with status: $STACK_STATUS${NC}"
    read -p "Do you want to update it? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 0
    fi
    OPERATION="update-stack"
else
    OPERATION="create-stack"
fi

# Deploy CloudFormation stack
echo -e "${GREEN}Deploying CloudFormation stack...${NC}"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  Instance Type: $INSTANCE_TYPE"

aws cloudformation $OPERATION \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --template-body "file://$SCRIPT_DIR/cloudformation.yaml" \
    --parameters \
        ParameterKey=InstanceType,ParameterValue="$INSTANCE_TYPE" \
        ParameterKey=GeminiApiKey,ParameterValue="$GEMINI_API_KEY" \
    --capabilities CAPABILITY_NAMED_IAM \
    --on-failure DO_NOTHING \
    2>/dev/null || {
        # Check if it's a "no updates" error
        if [ "$OPERATION" == "update-stack" ]; then
            echo -e "${YELLOW}No updates to perform${NC}"
        else
            echo -e "${RED}Stack deployment failed${NC}"
            exit 1
        fi
    }

# Wait for stack completion
echo -e "${YELLOW}Waiting for stack to complete (this may take 5-10 minutes)...${NC}"
if [ "$OPERATION" == "create-stack" ]; then
    aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$REGION"
else
    aws cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$REGION" 2>/dev/null || true
fi

# Get outputs
echo -e "${GREEN}Stack deployment complete!${NC}"
echo ""
echo "=== Stack Outputs ==="

SERVER_IP=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`ServerPublicIP`].OutputValue' \
    --output text)

INSTANCE_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' \
    --output text)

echo -e "Server IP:     ${GREEN}$SERVER_IP${NC}"
echo -e "API Endpoint:  ${GREEN}http://$SERVER_IP:8000${NC}"
echo -e "Health Check:  ${GREEN}http://$SERVER_IP:8000/health${NC}"
echo -e "Tools List:    ${GREEN}http://$SERVER_IP:8000/tools${NC}"
echo -e "Instance ID:   $INSTANCE_ID"
echo ""

# Wait for instance to be ready
echo -e "${YELLOW}Waiting for instance to be ready...${NC}"
aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID" --region "$REGION"

# Deploy application code
echo -e "${GREEN}Deploying application code...${NC}"

# Create deployment package
DEPLOY_PACKAGE="/tmp/accessibility-mcp-deploy.tar.gz"
cd "$PROJECT_DIR"
tar -czf "$DEPLOY_PACKAGE" \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='*.pyc' \
    --exclude='deploy/*.tar.gz' \
    .

# Upload via SSM
echo -e "${YELLOW}Uploading code to EC2 instance...${NC}"

# First, upload the tarball to S3 (temporary)
BUCKET_NAME="accessibility-mcp-deploy-$AWS_ACCOUNT"
aws s3 mb "s3://$BUCKET_NAME" --region "$REGION" 2>/dev/null || true
aws s3 cp "$DEPLOY_PACKAGE" "s3://$BUCKET_NAME/deploy.tar.gz"

# Run deployment commands via SSM
aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters commands="[
        \"cd /home/mcpuser\",
        \"aws s3 cp s3://$BUCKET_NAME/deploy.tar.gz /tmp/deploy.tar.gz\",
        \"rm -rf app.bak && mv app app.bak 2>/dev/null || true\",
        \"mkdir -p app && cd app\",
        \"tar -xzf /tmp/deploy.tar.gz\",
        \"chown -R mcpuser:mcpuser /home/mcpuser/app\",
        \"cd /home/mcpuser/app && source venv/bin/activate 2>/dev/null || python3.11 -m venv venv && source venv/bin/activate\",
        \"pip install -r requirements.txt\",
        \"pip install fastapi uvicorn python-multipart\",
        \"systemctl restart accessibility-mcp\"
    ]" \
    --output text \
    --query 'Command.CommandId'

echo -e "${YELLOW}Waiting for deployment to complete...${NC}"
sleep 30

# Test the endpoint
echo -e "${YELLOW}Testing API endpoint...${NC}"
for i in {1..10}; do
    if curl -s "http://$SERVER_IP:8000/health" | grep -q "healthy"; then
        echo -e "${GREEN}API is healthy!${NC}"
        break
    fi
    echo "Waiting for API to be ready... ($i/10)"
    sleep 10
done

# Final output
echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "API Endpoint: http://$SERVER_IP:8000"
echo ""
echo "Quick test commands:"
echo "  curl http://$SERVER_IP:8000/health"
echo "  curl http://$SERVER_IP:8000/tools"
echo ""
echo "Connect to instance:"
echo "  aws ssm start-session --target $INSTANCE_ID --region $REGION"
echo ""
echo "View logs:"
echo "  aws ssm start-session --target $INSTANCE_ID --region $REGION"
echo "  sudo journalctl -u accessibility-mcp -f"
echo ""

# Cleanup
rm -f "$DEPLOY_PACKAGE"
aws s3 rm "s3://$BUCKET_NAME/deploy.tar.gz" 2>/dev/null || true
