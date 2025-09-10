# Azure WhatsApp RAG Agent

A multilingual WhatsApp chatbot with RAG (Retrieval-Augmented Generation) capabilities for safety and hazard awareness, deployed on Azure Container Apps.

## Features

- **Multilingual Support**: English, Sinhala, and Tamil with intelligent language detection and switching
- **RAG System**: Query PDF documents for safety information with vector-based retrieval
- **Enhanced Web Search**: SerpAPI integration with DuckDuckGo fallback for reliable web search
- **Smart Language Switching**: Automatic language detection and user-friendly manual switching commands
- **Conversation Memory**: Redis-based session management with persistent user preferences
- **Azure Deployment**: Container Apps with auto-scaling and zero-downtime deployments
- **Production-Ready**: Comprehensive error handling, monitoring, and security features

## Project Structure

```
azure-whatsapp-rag-agent/
├─ app.py                    # FastAPI main application
├─ config.py                 # Configuration management
├─ agent/
│  ├─ orchestrator.py        # Main message processing logic
│  ├─ rag.py                 # RAG system implementation
│  ├─ tools.py               # Web search tools
│  ├─ i18n.py                # Internationalization
│  └─ memory.py              # Conversation memory
├─ training-files/
│  └─ general-hazard-awareness/   # Put your PDFs here
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml        # For local testing
├─ .env.example              # Environment variables template
└─ .github/workflows/deploy.yml   # CI/CD pipeline
```

## Prerequisites

- Azure subscription + Azure CLI (`az version`)
- Docker (for local development and building images)
- WhatsApp Cloud API app (get: WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN)
- OpenAI API key for LLM and embeddings
- SerpAPI key (for enhanced web search capabilities)

## Setup Instructions

### 1. Clone and Setup

```bash
git clone <your-repo-url>
cd azure-whatsapp-rag-agent
```

### 2. Add Training Documents

Place your PDF files in the `training-files/general-hazard-awareness/` directory.

### 3. Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your actual values:

- **WhatsApp API credentials** (from Meta WhatsApp Cloud API)
  - `WHATSAPP_VERIFY_TOKEN`: Your webhook verification token
  - `WHATSAPP_TOKEN`: Your app's access token  
  - `WHATSAPP_PHONE_NUMBER_ID`: Your WhatsApp Business phone number ID

- **API Keys**
  - `OPENAI_API_KEY`: Your OpenAI API key
  - `SERPAPI_KEY`: Your SerpAPI key (for enhanced web search)

- **Other configuration** as needed

### 4. Local Development (Optional)

```bash
# Start with Docker Compose
docker-compose up --build

# Or run locally with Python
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

### 5. Azure Deployment

Set your variables:

```bash
RG=rg-whatsapp-agent
LOC=eastus
ACR=acrwhatsapprag32324  # Use your actual ACR name
ENV=cae-whatsapp-agent
APP=whatsapp-agent
```

Create Azure resources:

```bash
# Login and create resource group
az login
az group create -n $RG -l $LOC

# Create Container Registry (if not exists)
az acr create -n $ACR -g $RG --sku Basic
ACR_LOGIN=$(az acr show -n $ACR -g $RG --query "loginServer" -o tsv)

# Create Container Apps environment
az extension add -n containerapp --upgrade
az provider register --namespace Microsoft.App
az containerapp env create -g $RG -n $ENV -l $LOC

# Create Redis instance
REDIS=redis-whatsapp-$RANDOM
az redis create -n $REDIS -g $RG --location $LOC --sku Basic --vm-size c0
REDIS_HOST=$(az redis show -n $REDIS -g $RG --query "hostName" -o tsv)
REDIS_KEY=$(az redis list-keys -n $REDIS -g $RG --query "primaryKey" -o tsv)
REDIS_URL="redis://:${REDIS_KEY}@${REDIS_HOST}:6379/0"

# Build and push image (AMD64 for Azure compatibility)
docker buildx build --platform linux/amd64 -t $APP:latest .
docker tag $APP:latest $ACR_LOGIN/$APP:latest
az acr login --name $ACR
docker push $ACR_LOGIN/$APP:latest

# Create Container App with ACR integration
az containerapp create -g $RG -n $APP \
  --environment $ENV \
  --image $ACR_LOGIN/$APP:latest \
  --ingress external --target-port 8000 \
  --registry-server $ACR_LOGIN \
  --registry-identity system

# Set secrets and environment variables
WHATSAPP_VERIFY_TOKEN=your_verify_token
WHATSAPP_TOKEN=your_meta_sysuser_token
WHATSAPP_PHONE_NUMBER_ID=your_number_id
OPENAI_API_KEY=your_openai_key
SERPAPI_KEY=your_serpapi_key

az containerapp secret set -g $RG -n $APP \
  --secrets \
    whatsapp-verify-token=$WHATSAPP_VERIFY_TOKEN \
    whatsapp-token=$WHATSAPP_TOKEN \
    openai-key=$OPENAI_API_KEY \
    serpapi-key=$SERPAPI_KEY

az containerapp update -g $RG -n $APP \
  --set-env-vars \
    WHATSAPP_VERIFY_TOKEN=secretref:whatsapp-verify-token \
    WHATSAPP_TOKEN=secretref:whatsapp-token \
    WHATSAPP_PHONE_NUMBER_ID=$WHATSAPP_PHONE_NUMBER_ID \
    OPENAI_API_KEY=secretref:openai-key \
    SERPAPI_KEY=secretref:serpapi-key \
    MODEL_PROVIDER=openai \
    MODEL_NAME=gpt-4o-mini \
    EMBEDDING_MODEL=text-embedding-3-large \
    RAG_VECTOR_DIR=/app/vectorstore \
    TRAINING_ROOT=/app/training-files/general-hazard-awareness \
    REDIS_URL="$REDIS_URL" \
    DEPLOYMENT_TIMESTAMP=$(date -u +"%Y%m%d%H%M%S")

# Get your public URL
FQDN=$(az containerapp show -g $RG -n $APP --query "properties.configuration.ingress.fqdn" -o tsv)
echo "Webhook URL: https://$FQDN/webhook"
```

### 6. Configure WhatsApp Webhook

In Meta → WhatsApp → Configuration:
- **Webhook URL**: `https://<FQDN>/webhook`
- **Verify token**: Your `WHATSAPP_VERIFY_TOKEN` value
- **Subscribe to**: `messages`

### 7. Test the Bot

Send a message to your WhatsApp Business number:

1. You'll receive a language selection menu
2. Reply with 1 (Sinhala), 2 (English), or 3 (Tamil)
3. Ask questions about safety or hazards
4. The bot will search your PDFs first, then web search if needed

## Language Switching

The bot supports intelligent language switching with multiple methods:

### Automatic Detection
- The bot automatically detects Sinhala, Tamil, and English text
- Switches language context based on the script used in messages
- Maintains user language preference in Redis session

### Manual Language Change Commands

Users can change language anytime by typing:

**English:**
- "language"
- "change language" 
- "I want to change the language"
- "menu"
- "switch language"

**Sinhala:**
- "භාෂාව"
- "භාෂාව වෙනස් කරන්න"
- "ලැයිස්තුව"

**Tamil:**
- "மொழி"
- "மொழியை மாற்று"
- "பட்டியல்"

The bot will then display a numbered menu for language selection.

## Updating the Application

### For Code Changes

```bash
# Build new image with version tag
docker buildx build --platform linux/amd64 -t whatsapp-agent:v6 .
docker tag whatsapp-agent:v6 acrwhatsapprag32324.azurecr.io/whatsapp-agent:v6
docker push acrwhatsapprag32324.azurecr.io/whatsapp-agent:v6

# Update container app
az containerapp update --name whatsapp-agent --resource-group rg-whatsapp-agent \
  --image acrwhatsapprag32324.azurecr.io/whatsapp-agent:v6

# Check deployment status
az containerapp show --name whatsapp-agent --resource-group rg-whatsapp-agent \
  --query "properties.runningStatus"
```

### For Training Data Updates

1. Add/remove PDF files in `training-files/general-hazard-awareness/`
2. Rebuild and redeploy the container (RAG index rebuilds automatically on startup)
3. No additional configuration needed

## CI/CD Setup

To enable automatic deployments:

1. Create GitHub repository secrets:
   - `AZURE_CREDENTIALS`: Service principal JSON
   - `ACR_NAME`: Your ACR name
   - `ACR_LOGIN_SERVER`: Your ACR login server
   - `AZ_RG`: Your resource group
   - `APP_NAME`: Your container app name

2. Push to `main` branch to trigger deployment

## Updating Training Data

1. Add/remove PDF files in `training-files/general-hazard-awareness/`
2. Commit and push changes
3. The RAG system will rebuild the vector index on container startup

## Architecture

- **FastAPI**: Web framework for webhook handling
- **LangChain**: RAG implementation with FAISS vector store
- **OpenAI**: LLM and embeddings
- **Redis**: Session and conversation memory
- **Azure Container Apps**: Serverless container hosting
- **Azure Container Registry**: Container image storage

## Monitoring

Check logs with:

```bash
az containerapp logs show -g $RG -n $APP --follow
```

## Cost Optimization

- Container Apps auto-scales to zero when not in use
- Redis Basic tier for development (consider Standard for production)
- Monitor OpenAI API usage

## Security Notes

- All secrets are stored in Azure Container Apps secrets
- No sensitive data in environment variables
- Redis connection secured with authentication

## Troubleshooting

### Common Issues and Solutions

1. **Webhook verification fails**
   - Check `WHATSAPP_VERIFY_TOKEN` matches in both Azure and Meta
   - Verify webhook URL is accessible: `curl https://your-fqdn/webhook`

2. **No responses from bot**
   - Check OpenAI API key is valid and has sufficient credits
   - Verify Redis connection: Check Azure Redis status
   - Check container logs: `az containerapp logs show -g $RG -n $APP --follow`

3. **RAG not finding relevant information**
   - Ensure PDFs are in `training-files/general-hazard-awareness/` directory
   - Verify PDFs are text-searchable (not scanned images)
   - Check container logs for vector index build errors

4. **Language switching not working**
   - Try exact commands: "language", "භාෂාව", or "மொழி"
   - Check if Redis session is persisting user language preference
   - Verify language detection by testing with clear Sinhala/Tamil text

5. **Web search not working**
   - Check if SerpAPI key is set correctly
   - Verify SerpAPI account has sufficient credits
   - DuckDuckGo fallback should work if SerpAPI fails

6. **Docker build fails for ARM64/AMD64**
   ```bash
   # Use buildx for cross-platform builds
   docker buildx build --platform linux/amd64 -t app:latest .
   ```

7. **Container app deployment fails**
   - Check image architecture: Must be `linux/amd64` for Azure
   - Verify ACR credentials are properly configured
   - Check resource quotas in your Azure subscription

### Monitoring Commands

```bash
# Check container app status
az containerapp show -g rg-whatsapp-agent -n whatsapp-agent --query "properties.runningStatus"

# View real-time logs
az containerapp logs show -g rg-whatsapp-agent -n whatsapp-agent --follow

# Check active revision
az containerapp revision list -g rg-whatsapp-agent -n whatsapp-agent --query "[?properties.active].{name:name,createdTime:properties.createdTime}"

# Check environment variables
az containerapp show -g rg-whatsapp-agent -n whatsapp-agent --query "properties.template.containers[0].env"

# Check Redis connection
az redis show -g rg-whatsapp-agent -n <redis-name> --query "properties.provisioningState"
```

### Performance Optimization

- **Redis**: Use Standard tier for production workloads
- **Container Apps**: Configure appropriate CPU/memory limits
- **SerpAPI**: Monitor usage to avoid quota limits
- **OpenAI**: Use batch processing for multiple PDF processing

## License

MIT License

## Environment Variables Reference

Create a `.env` file with the following variables:

```bash
# WhatsApp API Configuration
WHATSAPP_VERIFY_TOKEN=your_verify_token_here
WHATSAPP_TOKEN=your_access_token_here
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id_here

# AI/ML Configuration
OPENAI_API_KEY=your_openai_api_key_here
MODEL_PROVIDER=openai
MODEL_NAME=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-large

# Search Configuration
SERPAPI_KEY=your_serpapi_key_here

# Storage Configuration
REDIS_URL=redis://localhost:6379/0
RAG_VECTOR_DIR=/app/vectorstore
TRAINING_ROOT=/app/training-files/general-hazard-awareness

# Deployment Configuration
DEPLOYMENT_TIMESTAMP=20250910170000
```

### Getting API Keys and Tokens

1. **WhatsApp Cloud API**:
   - Go to [Meta for Developers](https://developers.facebook.com/)
   - Create a WhatsApp Cloud API app
   - Get your access token, phone number ID, and set a verify token

2. **OpenAI API**:
   - Sign up at [OpenAI](https://platform.openai.com/)
   - Generate an API key in your account settings
   - Ensure billing is set up for API usage

3. **SerpAPI**:
   - Sign up at [SerpAPI](https://serpapi.com/)
   - Get your API key from the dashboard
   - Free tier includes 100 searches/month

## Quick Start

For users who want to get the bot running quickly:

```bash
# 1. Clone and setup
git clone <your-repo-url>
cd azure-whatsapp-rag-agent
cp .env.example .env
# Edit .env with your API keys

# 2. Add your PDF training files
# Place PDFs in training-files/general-hazard-awareness/

# 3. Deploy to Azure (requires Azure CLI)
./deploy.sh  # Use the deployment script below

# 4. Configure WhatsApp webhook with your Azure app URL
# Webhook URL: https://your-app.azurecontainerapps.io/webhook
```

### One-Click Deployment Script

Create `deploy.sh`:

```bash
#!/bin/bash
set -e

# Load environment variables
source .env

# Set Azure variables
RG=rg-whatsapp-agent
ACR=acrwhatsapprag32324
APP=whatsapp-agent

# Build and deploy
echo "Building AMD64 image..."
docker buildx build --platform linux/amd64 -t $APP:latest .

echo "Tagging and pushing to ACR..."
docker tag $APP:latest $ACR.azurecr.io/$APP:latest
az acr login --name $ACR
docker push $ACR.azurecr.io/$APP:latest

echo "Updating container app..."
az containerapp update --name $APP --resource-group $RG \
  --image $ACR.azurecr.io/$APP:latest

echo "Deployment complete!"
az containerapp show --name $APP --resource-group $RG \
  --query "properties.configuration.ingress.fqdn" -o tsv
```

Make it executable: `chmod +x deploy.sh`

---

## 📋 Summary for New Developers

This WhatsApp RAG Agent is a production-ready multilingual chatbot that:

### ✅ **What It Does**
- Responds to WhatsApp messages in English, Sinhala, and Tamil
- Searches your PDF documents first for safety-related questions
- Falls back to web search (SerpAPI + DuckDuckGo) for other queries
- Remembers user language preferences and conversation context
- Automatically detects and switches languages based on user input

### 🛠️ **What You Need to Get Started**
1. **Azure subscription** (for hosting)
2. **WhatsApp Cloud API app** (for messaging)
3. **OpenAI API key** (for AI responses)
4. **SerpAPI key** (for web search - optional but recommended)
5. **Docker** (for building and deployment)

### ⚡ **Quick Deployment**
```bash
# 1. Clone, configure, and deploy
git clone <repo-url> && cd azure-whatsapp-rag-agent
cp .env.example .env  # Edit with your API keys
./deploy.sh           # One-command deployment

# 2. Add your webhook URL to WhatsApp
# URL: https://your-app.azurecontainerapps.io/webhook
```

### 📁 **Key Files to Know**
- `app.py` - Main FastAPI application (webhook handler)
- `agent/orchestrator.py` - Core message processing logic
- `agent/i18n.py` - Language detection and multilingual responses
- `agent/tools.py` - Web search with SerpAPI integration
- `training-files/` - Put your PDF documents here
- `deploy.sh` - One-click deployment script
- `.env.example` - Template for environment variables

### 🔧 **Customization Points**
- **Languages**: Add new languages in `agent/i18n.py`
- **Training Data**: Add PDFs to `training-files/general-hazard-awareness/`
- **AI Models**: Change models in `.env` (MODEL_NAME, EMBEDDING_MODEL)
- **Search Sources**: Modify `agent/tools.py` for different search APIs
- **Response Logic**: Update `agent/orchestrator.py` for custom flows

### 🚨 **Important Notes**
- Always use `linux/amd64` platform when building for Azure
- PDFs must be text-searchable (not scanned images)
- Redis stores conversation memory and language preferences
- Container rebuilds vector index automatically on startup
- Use `az containerapp logs show` for debugging

The application is designed to be easily extensible and maintainable. All major components are modular and well-documented.

## How the Deployment Works

### Architecture Overview

The WhatsApp RAG Agent uses a modern cloud-native architecture:

```
[WhatsApp Cloud API] ↔ [Azure Container Apps] ↔ [Azure Redis] 
                            ↓
                    [Azure Container Registry]
                            ↓
                    [Docker Container with:]
                    - FastAPI app (webhook handler)
                    - RAG system (PDF processing)
                    - LangChain + FAISS (vector search)
                    - Language detection & switching
                    - Web search integration
```

### Deployment Process Explained

#### 1. **Container Building**
```bash
docker buildx build --platform linux/amd64 -t app:latest .
```
- Builds a Linux AMD64 container (required for Azure Container Apps)
- Installs Python dependencies from `requirements.txt`
- Copies application code and training files
- Sets up the vector database directory structure

#### 2. **Container Registry**
```bash
docker push acrwhatsapprag32324.azurecr.io/whatsapp-agent:latest
```
- Pushes the container image to Azure Container Registry (ACR)
- ACR serves as the secure image repository
- Container Apps pulls images from here during deployment

#### 3. **Redis Cache Setup**
```bash
az redis create -n $REDIS -g $RG --location $LOC --sku Basic --vm-size c0
```
- Creates Azure Redis Cache for session management
- Stores user language preferences and conversation history
- Provides fast access to user context across container restarts

#### 4. **Container App Deployment**
```bash
az containerapp create -g $RG -n $APP \
  --environment $ENV \
  --image $ACR_LOGIN/$APP:latest \
  --ingress external --target-port 8000 \
  --registry-server $ACR_LOGIN \
  --registry-identity system
```
- Creates the Container App with auto-scaling capabilities
- Sets up external ingress for WhatsApp webhook calls
- Configures environment variables and secrets
- Enables system-assigned managed identity for ACR access

#### 5. **Runtime Initialization**
When the container starts:
1. **PDF Processing**: Scans `training-files/` directory for PDFs
2. **Vector Index Building**: Creates FAISS embeddings using OpenAI
3. **Redis Connection**: Establishes connection for session storage
4. **FastAPI Startup**: Initializes webhook endpoint at `/webhook`
5. **Health Check**: Container reports ready status to Azure

### Container Lifecycle

```
Container Start → PDF Scan → Vector Index Build → Redis Connect → API Ready
     ↓
WhatsApp Message → FastAPI Handler → Orchestrator → RAG/Search → Response
     ↓
Auto-scale: 0 instances (idle) ↔ N instances (load)
```

### Secrets Management

Azure Container Apps securely manages sensitive data:

```bash
az containerapp secret set -g $RG -n $APP --secrets \
  whatsapp-token=$WHATSAPP_TOKEN \
  openai-key=$OPENAI_API_KEY \
  serpapi-key=$SERPAPI_KEY
```

- **Secrets**: Encrypted at rest and in transit
- **Environment Variables**: Reference secrets using `secretref:` syntax
- **Managed Identity**: Container Apps authenticates to ACR automatically
- **No secrets in code**: All sensitive data handled by Azure platform

### Auto-Scaling Behavior

Container Apps automatically scales based on:
- **HTTP requests**: More WhatsApp messages = more instances
- **Scale to zero**: No messages = 0 running containers (cost savings)
- **Resource limits**: Each instance gets 0.5 CPU, 1GB memory
- **Concurrent requests**: Multiple users handled by single instance

### Monitoring and Logging

```bash
# Real-time logs
az containerapp logs show -g $RG -n $APP --follow

# Check scaling metrics
az monitor metrics list --resource $APP_RESOURCE_ID --metric "Requests"
```

---

## 💰 Cost Analysis & Resource Planning

Understanding the costs associated with running this WhatsApp RAG Agent is crucial for budgeting and optimization.

### Azure Resources Cost Breakdown

#### 1. **Azure Container Apps** (Primary Compute)
```
Consumption Plan (Pay-per-use):
- vCPU-s: $0.000024 per second per vCPU (0.5 vCPU = $0.000012/s)
- Memory: $0.000002667 per second per GB (1GB = $0.000002667/s)

Monthly estimate (moderate usage):
- Running 2 hours/day: ~$1.50/month
- Running 8 hours/day: ~$6.00/month
- Running 24/7: ~$18.00/month

Scale-to-zero benefit: $0 when not processing messages
```

#### 2. **Azure Container Registry** (Image Storage)
```
Basic SKU: $5.00/month
- 10GB storage included
- Unlimited image pulls
- 2,000 registry operations/month included

Additional costs:
- Extra storage: $0.10/GB/month
- Operations beyond limit: $0.10/10,000 operations
```

#### 3. **Azure Redis Cache** (Session Storage)
```
Basic SKU:
- C0 (250MB): $16.32/month
- C1 (1GB): $30.95/month
- C2 (2.5GB): $61.90/month

Standard SKU (Recommended for production):
- C1 (1GB): $61.90/month (includes high availability)
- C2 (2.5GB): $123.80/month
```

#### 4. **Azure Resource Group** (Management)
```
Cost: $0 (Free)
- Logical container for resources
- No additional charges
```

### External API Costs

#### 1. **OpenAI API** (AI Processing)
```
GPT-4o-mini:
- Input: $0.15 per 1M tokens
- Output: $0.60 per 1M tokens

Text Embeddings 3 Large:
- $0.13 per 1M tokens

Monthly estimates (1000 messages):
- Simple responses: ~$5-10/month
- Complex RAG queries: ~$15-25/month
- PDF processing (one-time): ~$2-5 per 100 pages
```

#### 2. **SerpAPI** (Web Search)
```
Free Plan: 100 searches/month
Starter Plan: $25/month for 5,000 searches
Pro Plan: $75/month for 15,000 searches

Alternative: DuckDuckGo (free fallback included)
```

#### 3. **WhatsApp Cloud API** (Messaging)
```
Free Tier: 1,000 conversations/month
Pay-as-you-go: $0.005-0.009 per conversation
(Conversation = 24-hour session with a user)

Business-initiated messages: $0.0055-0.0135 each
```

### Total Monthly Cost Estimates

#### **Development/Testing Environment**
```
Azure Container Apps (2 hrs/day):     $1.50
Azure Container Registry (Basic):     $5.00
Azure Redis (Basic C0):              $16.32
OpenAI API (light usage):            $5.00
SerpAPI (free tier):                 $0.00
WhatsApp (free tier):                $0.00
────────────────────────────────────────────
Total: ~$28/month
```

#### **Small Production (100 users, 500 messages/month)**
```
Azure Container Apps (8 hrs/day):     $6.00
Azure Container Registry (Basic):     $5.00
Azure Redis (Standard C1):           $61.90
OpenAI API (moderate usage):         $15.00
SerpAPI (Starter plan):              $25.00
WhatsApp (within free tier):         $0.00
────────────────────────────────────────────
Total: ~$113/month
```

#### **Medium Production (500 users, 2500 messages/month)**
```
Azure Container Apps (16 hrs/day):   $12.00
Azure Container Registry (Basic):     $5.00
Azure Redis (Standard C2):          $123.80
OpenAI API (heavy usage):            $50.00
SerpAPI (Pro plan):                  $75.00
WhatsApp (paid conversations):       $15.00
────────────────────────────────────────────
Total: ~$281/month
```

#### **Large Production (2000+ users, 10000+ messages/month)**
```
Azure Container Apps (24/7):         $18.00
Azure Container Registry (Basic):     $5.00
Azure Redis (Premium P1):           $381.30
OpenAI API (enterprise usage):      $200.00
SerpAPI (Custom plan):              $150.00
WhatsApp (business messaging):       $50.00
────────────────────────────────────────────
Total: ~$804/month
```

### Cost Optimization Strategies

#### 1. **Auto-Scaling Optimization**
```bash
# Configure minimal scaling
az containerapp update -g $RG -n $APP \
  --min-replicas 0 \
  --max-replicas 5
```

#### 2. **Smart Caching**
- Use Redis to cache frequent queries
- Implement response caching for common questions
- Cache vector embeddings to reduce OpenAI calls

#### 3. **Alternative AI Models**
```bash
# Use cheaper models for simple queries
MODEL_NAME=gpt-3.5-turbo  # vs gpt-4o-mini
EMBEDDING_MODEL=text-embedding-ada-002  # vs text-embedding-3-large
```

#### 4. **Search Strategy**
- Use free DuckDuckGo search when possible
- Implement smart routing to SerpAPI only for complex queries
- Cache search results to avoid duplicate API calls

#### 5. **WhatsApp Optimization**
- Use template messages for common responses
- Implement message threading to reduce conversation count
- Use business-initiated messages sparingly

### Monitoring Costs

#### Azure Cost Management
```bash
# Set up budget alerts
az consumption budget create \
  --resource-group $RG \
  --budget-name "whatsapp-bot-budget" \
  --amount 100 \
  --time-grain Monthly

# Monitor spending
az consumption usage list \
  --top 10 \
  --include-additional-properties \
  --include-meter-details
```

#### API Usage Monitoring
```bash
# OpenAI usage tracking
curl https://api.openai.com/v1/usage \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# SerpAPI usage check
curl "https://serpapi.com/account?api_key=$SERPAPI_KEY"
```

### Production Readiness Checklist

#### Cost Controls
- [ ] Set up Azure budget alerts
- [ ] Configure auto-scaling limits
- [ ] Monitor API usage dashboards
- [ ] Implement response caching
- [ ] Set up cost anomaly detection

#### Performance vs Cost
- [ ] Choose appropriate Redis tier
- [ ] Optimize container resource allocation
- [ ] Implement smart API routing
- [ ] Use content delivery for static responses
- [ ] Consider regional deployment for latency

The total cost can range from $28/month for development to $800+/month for enterprise usage. The pay-per-use model of Azure Container Apps makes it very cost-effective for variable workloads.

---

## Deployment Best Practices

#### Security Considerations
```bash
# Use managed identity for ACR access
az containerapp identity assign -g $RG -n $APP --system-assigned

# Rotate secrets regularly
az containerapp secret set -g $RG -n $APP \
  --secrets openai-key=$NEW_OPENAI_KEY

# Enable HTTPS only
az containerapp ingress update -g $RG -n $APP \
  --transport https
```

#### High Availability Setup
```bash
# Deploy across multiple regions
az containerapp create -g $RG-east -n $APP --location eastus
az containerapp create -g $RG-west -n $APP --location westus

# Use Azure Front Door for load balancing
az network front-door create \
  --resource-group $RG \
  --name whatsapp-bot-fd
```

#### Backup and Disaster Recovery
```bash
# Backup Redis data
az redis export -g $RG -n $REDIS \
  --container $STORAGE_CONTAINER \
  --prefix backup-$(date +%Y%m%d)

# Export container app configuration
az containerapp show -g $RG -n $APP > app-config-backup.json
```

#### CI/CD Pipeline Integration
```yaml
# .github/workflows/deploy.yml
name: Deploy WhatsApp Agent
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build and Deploy
        run: |
          docker buildx build --platform linux/amd64 -t ${{ secrets.ACR_LOGIN_SERVER }}/whatsapp-agent:${{ github.sha }} .
          docker push ${{ secrets.ACR_LOGIN_SERVER }}/whatsapp-agent:${{ github.sha }}
          az containerapp update --image ${{ secrets.ACR_LOGIN_SERVER }}/whatsapp-agent:${{ github.sha }}
```
