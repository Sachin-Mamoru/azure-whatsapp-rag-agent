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

# Check if Azure CLI is logged in
if ! az account show &> /dev/null; then
    echo "❌ Error: Not logged into Azure CLI. Please run 'az login' first."
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo "❌ Error: Docker is not running. Please start Docker first."
    exit 1
fi

echo "📦 Building AMD64 image for Azure compatibility..."
docker buildx build --platform linux/amd64 -t $APP:$(date +%Y%m%d%H%M%S) .
docker tag $APP:$(date +%Y%m%d%H%M%S) $ACR.azurecr.io/$APP:latest

echo "🔐 Logging into Azure Container Registry..."
az acr login --name $ACR

echo "⬆️  Pushing image to ACR..."
docker push $ACR.azurecr.io/$APP:latest

echo "🔄 Updating container app..."
az containerapp update --name $APP --resource-group $RG \
  --image $ACR.azurecr.io/$APP:latest

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
