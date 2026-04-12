#!/bin/bash
set -e

# WhatsApp RAG Agent Deployment Script
# This script builds and deploys the application to Azure Container Apps

echo "🚀 Starting WhatsApp RAG Agent deployment..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found. Please copy .env.example to .env and configure it."
    exit 1
fi

# Load environment variables
source .env

# Set Azure variables
RG=rg-whatsapp-agent
ACR=acrwhatsapprag32324
APP=whatsapp-agent
IMG_TAG=$(date +%Y%m%d%H%M%S)

# Check if Azure CLI is logged in
if ! az account show &> /dev/null; then
    echo "❌ Error: Not logged into Azure CLI. Please run 'az login' first."
    exit 1
fi

# Check if Docker is running (only needed for local build — skip if using ACR Tasks)
USE_ACR_BUILD=true
if ! $USE_ACR_BUILD && ! docker info &> /dev/null; then
    echo "❌ Error: Docker is not running. Please start Docker first."
    exit 1
fi

echo "📦 Building image via Azure Container Registry Tasks (no local Docker needed)..."
az acr build --registry $ACR --image $APP:$IMG_TAG --platform linux/amd64 . 2>&1

echo "� Storing Google credentials as Azure secret..."
GOOGLE_CREDS_B64=$(base64 < credentials.json | tr -d '\n')
az containerapp secret set --name $APP --resource-group $RG \
  --secrets "google-credentials-json=$GOOGLE_CREDS_B64" 2>/dev/null || true

echo "� Storing Redis URL as Azure secret (prevents shell special-char truncation)..."
# Read REDIS_URL raw from .env to avoid shell expansion issues
REDIS_URL_RAW=$(grep '^REDIS_URL=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
az containerapp secret set --name $APP --resource-group $RG \
  --secrets "redis-url=${REDIS_URL_RAW}" 2>/dev/null || true

echo "🔄 Deploying container app..."
# Check if app already exists
if az containerapp show --name $APP --resource-group $RG &>/dev/null; then
  az containerapp update --name $APP --resource-group $RG \
    --image $ACR.azurecr.io/$APP:$IMG_TAG \
    --set-env-vars \
      GOOGLE_SHEETS_CREDENTIALS_JSON=secretref:google-credentials-json \
      REDIS_URL=secretref:redis-url \
      WHATSAPP_VERIFY_TOKEN="$WHATSAPP_VERIFY_TOKEN" \
      WHATSAPP_TOKEN="$WHATSAPP_TOKEN" \
      WHATSAPP_PHONE_NUMBER_ID="$WHATSAPP_PHONE_NUMBER_ID" \
      OPENAI_API_KEY="$OPENAI_API_KEY" \
      MODEL_NAME="$MODEL_NAME" \
      EMBEDDING_MODEL="$EMBEDDING_MODEL" \
      SERPER_API_KEY="$SERPER_API_KEY" \
      REGISTRATION_FORM_URL="$REGISTRATION_FORM_URL" \
      GOOGLE_SHEETS_SPREADSHEET_ID="$GOOGLE_SHEETS_SPREADSHEET_ID" \
      EARLY_WARNING_DATA_URL="$EARLY_WARNING_DATA_URL" \
      SHEETS_SYNC_INTERVAL_MINUTES="${SHEETS_SYNC_INTERVAL_MINUTES:-30}" \
      ALERT_CHECK_INTERVAL_MINUTES="${ALERT_CHECK_INTERVAL_MINUTES:-60}" \
      COMMUNITY_REPORTS_DB="${COMMUNITY_REPORTS_DB:-/data/community_reports.db}" \
      ADMIN_SECRET="$ADMIN_SECRET"
else
  az containerapp create --name $APP --resource-group $RG \
    --environment env-whatsapp-agent \
    --image $ACR.azurecr.io/$APP:$IMG_TAG \
    --registry-server $ACR.azurecr.io \
    --registry-username $(az acr credential show -n $ACR --query username -o tsv) \
    --registry-password $(az acr credential show -n $ACR --query "passwords[0].value" -o tsv) \
    --ingress external --target-port 8000 \
    --min-replicas 1 --max-replicas 3 \
    --cpu 0.5 --memory 1.0Gi \
    --secrets "google-credentials-json=$GOOGLE_CREDS_B64" "redis-url=${REDIS_URL_RAW}" \
    --env-vars \
      GOOGLE_SHEETS_CREDENTIALS_JSON=secretref:google-credentials-json \
      REDIS_URL=secretref:redis-url \
      WHATSAPP_VERIFY_TOKEN="$WHATSAPP_VERIFY_TOKEN" \
      WHATSAPP_TOKEN="$WHATSAPP_TOKEN" \
      WHATSAPP_PHONE_NUMBER_ID="$WHATSAPP_PHONE_NUMBER_ID" \
      OPENAI_API_KEY="$OPENAI_API_KEY" \
      MODEL_NAME="$MODEL_NAME" \
      EMBEDDING_MODEL="$EMBEDDING_MODEL" \
      SERPER_API_KEY="$SERPER_API_KEY" \
      REGISTRATION_FORM_URL="$REGISTRATION_FORM_URL" \
      GOOGLE_SHEETS_SPREADSHEET_ID="$GOOGLE_SHEETS_SPREADSHEET_ID" \
      EARLY_WARNING_DATA_URL="$EARLY_WARNING_DATA_URL" \
      SHEETS_SYNC_INTERVAL_MINUTES="${SHEETS_SYNC_INTERVAL_MINUTES:-30}" \
      ALERT_CHECK_INTERVAL_MINUTES="${ALERT_CHECK_INTERVAL_MINUTES:-60}" \
      COMMUNITY_REPORTS_DB="${COMMUNITY_REPORTS_DB:-/data/community_reports.db}" \
      ADMIN_SECRET="$ADMIN_SECRET"
fi


echo "✅ Deployment complete!"
echo ""
echo "📱 Your WhatsApp bot webhook URL:"
FQDN=$(az containerapp show --name $APP --resource-group $RG \
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo "https://$FQDN/webhook"
echo ""
echo "🔍 To view logs:"
echo "az containerapp logs show -g $RG -n $APP --follow"
echo ""
echo "✨ Bot is ready to receive messages!"
