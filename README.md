# Azure WhatsApp RAG Agent

A multilingual WhatsApp chatbot with RAG (Retrieval-Augmented Generation) capabilities for safety and hazard awareness, deployed on Azure Container Apps.

## Features

- **Multilingual Support**: English, Sinhala, and Tamil
- **RAG System**: Query PDF documents for safety information
- **Web Search Fallback**: DuckDuckGo search when RAG doesn't have answers
- **Conversation Memory**: Redis-based session management
- **Azure Deployment**: Container Apps with auto-scaling

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
- Docker (for local development)
- WhatsApp Cloud API app (get: WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN)
- OpenAI API key

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
- WhatsApp API credentials
- OpenAI API key
- Other configuration as needed

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
ACR=acrwhatsapprag$RANDOM
ENV=cae-whatsapp-agent
APP=whatsapp-agent
```

Create Azure resources:

```bash
# Login and create resource group
az login
az group create -n $RG -l $LOC

# Create Container Registry
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

# Build and push image
az acr build -r $ACR -g $RG -t $ACR_LOGIN/$APP:latest .

# Create Container App
az containerapp create -g $RG -n $APP \
  --environment $ENV \
  --image $ACR_LOGIN/$APP:latest \
  --ingress external --target-port 8000 \
  --registry-server $ACR_LOGIN

# Set secrets and environment variables
WHATSAPP_VERIFY_TOKEN=your_verify_token
WHATSAPP_TOKEN=your_meta_sysuser_token
WHATSAPP_PHONE_NUMBER_ID=your_number_id
OPENAI_API_KEY=your_openai_key

az containerapp secret set -g $RG -n $APP \
  --secrets whatsapp-verify-token=$WHATSAPP_VERIFY_TOKEN whatsapp-token=$WHATSAPP_TOKEN openai-key=$OPENAI_API_KEY

az containerapp update -g $RG -n $APP \
  --set-env-vars \
    WHATSAPP_VERIFY_TOKEN=secretref:whatsapp-verify-token \
    WHATSAPP_TOKEN=secretref:whatsapp-token \
    WHATSAPP_PHONE_NUMBER_ID=$WHATSAPP_PHONE_NUMBER_ID \
    OPENAI_API_KEY=secretref:openai-key \
    MODEL_PROVIDER=openai \
    MODEL_NAME=gpt-4o-mini \
    EMBEDDING_MODEL=text-embedding-3-large \
    RAG_VECTOR_DIR=/app/vectorstore \
    TRAINING_ROOT=/app/training-files/general-hazard-awareness \
    REDIS_URL="$REDIS_URL"

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

1. **Webhook verification fails**: Check WHATSAPP_VERIFY_TOKEN
2. **No responses**: Check OpenAI API key and Redis connection
3. **RAG not working**: Ensure PDFs are in correct directory
4. **Build fails**: Check Dockerfile and requirements.txt

## License

MIT License
