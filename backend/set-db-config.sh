#!/bin/bash

# XO Platform - Set DATABASE_URL and JWT_SECRET on all Lambdas
# Usage: ./set-db-config.sh <DATABASE_URL> <JWT_SECRET>
#
# Example:
#   ./set-db-config.sh "postgresql://xo_admin:PASS@xo-quickstart-db.xxxxx.us-west-1.rds.amazonaws.com:5432/xo_quickstart" "my-jwt-secret-256bit"

set -e

REGION="eu-west-2"
BUCKET_NAME="xo-client-data-mv"

DATABASE_URL="${1}"
JWT_SECRET="${2}"
AES_ENCRYPTION_KEY="${3}"

if [ -z "$DATABASE_URL" ] || [ -z "$JWT_SECRET" ] || [ -z "$AES_ENCRYPTION_KEY" ]; then
    echo "Usage: ./set-db-config.sh <DATABASE_URL> <JWT_SECRET> <AES_ENCRYPTION_KEY>"
    echo ""
    echo "Example:"
    echo '  ./set-db-config.sh "postgresql://xo_admin:PASS@HOST:5432/xo_quickstart" "my-secret" "my-encryption-key"'
    exit 1
fi

LAMBDAS=("xo-clients" "xo-upload" "xo-enrich" "xo-results" "xo-auth" "xo-buttons" "xo-gdrive-import" "xo-rapid-prototype")

echo "🔧 Setting DATABASE_URL and JWT_SECRET on all Lambdas..."
echo "   Region: $REGION"
echo ""

for LAMBDA in "${LAMBDAS[@]}"; do
    echo "   Setting env vars on $LAMBDA..."

    # Get existing env vars to preserve them
    EXISTING=$(aws lambda get-function-configuration \
        --function-name $LAMBDA \
        --region $REGION \
        --query 'Environment.Variables' \
        --output json 2>/dev/null || echo '{}')
echo $EXISTING
    # Merge new vars with existing
    MERGED=$(echo "$EXISTING" | python3 -c "
import sys, json
existing = json.load(sys.stdin)
existing['DATABASE_URL'] = '$DATABASE_URL'
existing['JWT_SECRET'] = '$JWT_SECRET'
existing['AES_ENCRYPTION_KEY'] = '$AES_ENCRYPTION_KEY'
existing['AES_MASTER_KEY'] = '$AES_ENCRYPTION_KEY'
existing['BUCKET_NAME'] = '$BUCKET_NAME'
print(json.dumps(existing))
")
echo $MERGED
    aws lambda update-function-configuration \
        --function-name $LAMBDA \
        --environment "Variables={BUCKET_NAME=$BUCKET_NAME,DATABASE_URL=$DATABASE_URL,JWT_SECRET=$JWT_SECRET,AES_ENCRYPTION_KEY=$AES_ENCRYPTION_KEY,AES_MASTER_KEY=$AES_ENCRYPTION_KEY}" \
        --region $REGION \
        --output text > /dev/null

    echo "   ✅ $LAMBDA configured"
done

echo ""
echo "✨ All Lambdas configured with DATABASE_URL, JWT_SECRET and AES_ENCRYPTION_KEY"
