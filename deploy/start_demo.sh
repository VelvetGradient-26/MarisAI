#!/usr/bin/env bash
# Start the MarisAI EC2 instance, open SSH for this machine's current IPv4,
# print the site URL, then wait until every surface is ready.
#
#   deploy/start_demo.sh [--ask]      (--ask also checks one assistant answer)
#
# The instance has no fixed address: its public IP changes on every start,
# which is why this prints it. Needs the AWS CLI configured for ap-south-1.
set -euo pipefail

INSTANCE_ID="${MARIS_INSTANCE_ID:-i-0c7686f701d6b0af1}"
SECURITY_GROUP="${MARIS_SECURITY_GROUP:-sg-0c2bd5f32efbdd067}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "Starting $INSTANCE_ID ..."
aws ec2 start-instances --instance-ids "$INSTANCE_ID" --output text >/dev/null
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

# SSH is open only to the machine running this script. Its address is
# dynamic, so replace whatever /32 was authorized last time.
MY_IP=$(curl -s -4 --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]')
if [ -n "$MY_IP" ]; then
  for old in $(aws ec2 describe-security-groups --group-ids "$SECURITY_GROUP" \
      --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp' --output text); do
    [ "$old" = "$MY_IP/32" ] && continue
    aws ec2 revoke-security-group-ingress --group-id "$SECURITY_GROUP" \
      --protocol tcp --port 22 --cidr "$old" >/dev/null
  done
  aws ec2 authorize-security-group-ingress --group-id "$SECURITY_GROUP" \
    --protocol tcp --port 22 --cidr "$MY_IP/32" >/dev/null 2>&1 || true
fi

echo
echo "  Site:  http://$IP/"
echo "  SSH:   ssh -i ~/Downloads/my-web-server-key.pem ec2-user@$IP"
echo
exec "$HERE/demo_ready.sh" "http://$IP" "$@"
