#!/bin/bash

# Azure WhatsApp RAG Agent - Cost Verification Script
# This script helps you verify your actual Azure costs and resource configurations

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔍 Azure WhatsApp RAG Agent - Cost Verification${NC}"
echo "================================================="

# Check if user is logged into Azure
if ! az account show &> /dev/null; then
    echo -e "${RED}❌ Please login to Azure first: az login${NC}"
    exit 1
fi

# Get subscription info
SUBSCRIPTION=$(az account show --query name -o tsv)
echo -e "${GREEN}✅ Connected to subscription: ${SUBSCRIPTION}${NC}"
echo

# Find the resource group
echo -e "${BLUE}📋 Finding WhatsApp RAG resources...${NC}"
RESOURCE_GROUPS=$(az group list --query "[?contains(name, 'whatsapp') || contains(name, 'rag')].name" -o tsv)

if [ -z "$RESOURCE_GROUPS" ]; then
    echo -e "${YELLOW}⚠️  No resource groups found with 'whatsapp' or 'rag' in the name.${NC}"
    echo "Available resource groups:"
    az group list --output table
    echo
    read -p "Enter your resource group name: " RG
else
    echo "Found resource groups:"
    echo "$RESOURCE_GROUPS"
    
    if [ $(echo "$RESOURCE_GROUPS" | wc -l) -eq 1 ]; then
        RG="$RESOURCE_GROUPS"
        echo -e "${GREEN}✅ Using resource group: ${RG}${NC}"
    else
        echo "Multiple resource groups found. Please select:"
        select RG in $RESOURCE_GROUPS; do
            if [ -n "$RG" ]; then
                echo -e "${GREEN}✅ Selected: ${RG}${NC}"
                break
            fi
        done
    fi
fi

echo

# Check resources
echo -e "${BLUE}💰 Checking actual resource costs...${NC}"
echo "================================================="

# Container Registry
echo -e "${YELLOW}Azure Container Registry:${NC}"
ACR_NAME=$(az acr list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)
if [ -n "$ACR_NAME" ]; then
    ACR_SKU=$(az acr show -n "$ACR_NAME" -g "$RG" --query "sku.name" -o tsv)
    case "$ACR_SKU" in
        "Basic") echo "  📦 $ACR_NAME (Basic): ~$5.00/month" ;;
        "Standard") echo "  📦 $ACR_NAME (Standard): ~$20.00/month" ;;
        "Premium") echo "  📦 $ACR_NAME (Premium): ~$40.00/month" ;;
        *) echo "  📦 $ACR_NAME ($ACR_SKU): Check Azure pricing" ;;
    esac
else
    echo "  ❌ No Container Registry found"
fi

# Redis Cache
echo -e "${YELLOW}Redis Cache:${NC}"
REDIS_NAME=$(az redis list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)
if [ -n "$REDIS_NAME" ]; then
    REDIS_INFO=$(az redis show -n "$REDIS_NAME" -g "$RG" --query "{sku:sku.name, capacity:sku.capacity}" -o json)
    REDIS_SKU=$(echo "$REDIS_INFO" | jq -r '.sku')
    REDIS_CAPACITY=$(echo "$REDIS_INFO" | jq -r '.capacity')
    
    case "${REDIS_SKU}${REDIS_CAPACITY}" in
        "BasicC0") echo "  🗄️  $REDIS_NAME (Basic C0): ~$16.32/month" ;;
        "BasicC1") echo "  🗄️  $REDIS_NAME (Basic C1): ~$30.95/month" ;;
        "BasicC2") echo "  🗄️  $REDIS_NAME (Basic C2): ~$61.90/month" ;;
        "StandardC1") echo "  🗄️  $REDIS_NAME (Standard C1): ~$61.90/month" ;;
        "StandardC2") echo "  🗄️  $REDIS_NAME (Standard C2): ~$123.80/month" ;;
        *) echo "  🗄️  $REDIS_NAME ($REDIS_SKU $REDIS_CAPACITY): Check Azure pricing" ;;
    esac
else
    echo "  ❌ No Redis Cache found"
fi

# Container Apps
echo -e "${YELLOW}Container Apps:${NC}"
CONTAINERAPP_NAME=$(az containerapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)
if [ -n "$CONTAINERAPP_NAME" ]; then
    STATUS=$(az containerapp show -n "$CONTAINERAPP_NAME" -g "$RG" --query "properties.provisioningState" -o tsv)
    echo "  🐳 $CONTAINERAPP_NAME ($STATUS): Consumption plan"
    echo "     📊 Scales to zero when idle = $0.00/hour"
    echo "     📊 Only pay when processing messages"
    echo "     💡 Estimated: $0-25/month depending on usage"
else
    echo "  ❌ No Container Apps found"
fi

# Log Analytics
echo -e "${YELLOW}Log Analytics:${NC}"
WORKSPACE_NAME=$(az monitor log-analytics workspace list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)
if [ -n "$WORKSPACE_NAME" ]; then
    echo "  📊 $WORKSPACE_NAME: ~$2-5/month (depends on log volume)"
else
    echo "  ❌ No Log Analytics workspace found"
fi

echo
echo -e "${BLUE}💡 Cost Summary:${NC}"
echo "================================================="
echo -e "${GREEN}✅ Minimum monthly cost (when idle): ~$23.63${NC}"
echo "   • Container Registry: $5.00"
echo "   • Redis Cache: $16.32" 
echo "   • Log Analytics: $2.31"
echo ""
echo -e "${YELLOW}📈 Variable costs (usage-based):${NC}"
echo "   • Container Apps: $0-25/month (scales with messages)"
echo "   • OpenAI API: $3-50/month (depends on message complexity)"
echo "   • SerpAPI: $0-75/month (free tier available)"
echo "   • WhatsApp: $0-50/month (free tier: 1000 conversations)"
echo ""
echo -e "${BLUE}🎯 Total expected range: $26-200/month${NC}"

# Optional: Check actual consumption
echo
echo -e "${BLUE}📊 Recent Usage (optional):${NC}"
read -p "Check actual spending for last 7 days? (y/N): " CHECK_SPENDING

if [[ $CHECK_SPENDING =~ ^[Yy]$ ]]; then
    echo "Fetching usage data..."
    START_DATE=$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d '7 days ago' +%Y-%m-%d)
    END_DATE=$(date +%Y-%m-%d)
    
    az consumption usage list \
        --start-date "$START_DATE" \
        --end-date "$END_DATE" \
        --resource-group "$RG" \
        --query "[].{Resource:instanceName, Cost:pretaxCost, Currency:currency}" \
        --output table 2>/dev/null || echo "Cost data not available (may need billing permissions)"
fi

echo
echo -e "${GREEN}✅ Cost verification complete!${NC}"
echo -e "${BLUE}💡 To minimize costs during POC:${NC}"
echo "   1. Use the poc-cost-optimize.sh script when not testing"
echo "   2. Container Apps auto-scale to 0 (no ongoing compute costs)"
echo "   3. Use free tiers for OpenAI, SerpAPI, and WhatsApp when possible"
echo "   4. Monitor usage in Azure Cost Management portal"
