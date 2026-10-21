#!/usr/bin/env bash
# Stop the MarisAI EC2 instance and wait until it is stopped.
set -euo pipefail
INSTANCE_ID="${MARIS_INSTANCE_ID:-i-0c7686f701d6b0af1}"
aws ec2 stop-instances --instance-ids "$INSTANCE_ID" --output text >/dev/null
aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"
echo "$INSTANCE_ID stopped."
