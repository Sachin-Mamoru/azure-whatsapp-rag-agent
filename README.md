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

This WhatsApp RAG Agent is a production-ready multilingual AI agent that:

### ✅ **What It Does**
- **Intelligent Responses**: Uses autonomous AI agent with multiple tools (RAG, Web Search, Memory, i18n)
- **Multilingual**: Responds in English, Sinhala, and Tamil with auto-detection
- **Knowledge Integration**: Searches your PDF documents first, then web search for broader queries
- **Conversation Memory**: Remembers user language preferences and conversation context
- **Cost-Effective**: Auto-scales to zero when idle (~$24/month minimum cost)

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

## 🤖 AI Agent Architecture Deep Dive

This WhatsApp RAG Agent is a sophisticated multi-tool AI agent with autonomous decision-making capabilities. Here's how it works under the hood:

### Agent Components Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                    WhatsApp Orchestrator                    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────┐│
│  │ RAG System  │  │ Web Search  │  │ Memory Mgmt │  │ i18n ││
│  │   Tools     │  │    Tools    │  │    Tools    │  │Tools ││
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────┘│
├─────────────────────────────────────────────────────────────┤
│           OpenAI API (LLM + Embeddings)                    │
├─────────────────────────────────────────────────────────────┤
│     FAISS Vector DB    │    Redis Memory    │   External APIs│
└─────────────────────────────────────────────────────────────┘
```

### 1. Message Processing Pipeline

#### Core Orchestrator (`agent/orchestrator.py`)

```python
class WhatsAppOrchestrator:
    def __init__(self):
        self.redis_client = redis.from_url(Config.REDIS_URL)
        self.memory = ConversationMemory(self.redis_client)     # Session management
        self.rag_system = RAGSystem()                           # PDF knowledge base
        self.web_search = WebSearchTool()                       # Web search capabilities
        self.lang_detector = LanguageDetector()                 # Language intelligence
```

**Message Flow:**

```text
WhatsApp Message → Language Detection → Command Analysis → Tool Selection → Response Generation
```

#### Step-by-Step Processing:

1. **Session Retrieval**
```python
session = self.memory.get_session(phone_number)  # Get user context from Redis
```

2. **Language Command Detection**
```python
language_commands = [
    "change language", "language", "menu", "भाषाव", "மொழி"
]
if any(cmd in message_lower for cmd in language_commands):
    return get_menu_text()  # Show language selection menu
```

3. **Language Selection Processing**
```python
if message.strip() in ["1", "2", "3"]:
    language_map = {"1": "si", "2": "en", "3": "ta"}
    session["language"] = language_map[message.strip()]
    self.memory.update_session(phone_number, session)
```

4. **Intelligent Language Detection**
```python
detected_lang = self.lang_detector.detect_language(message)
if detected_lang != user_language and len(message) > 10:
    session["language"] = detected_lang  # Auto-switch language
```

5. **Tool Selection Logic**
```python
# Primary: RAG System (PDF knowledge)
rag_response = await self.rag_system.query(message, user_language)

if rag_response and rag_response.get("confidence", 0) > 0.7:
    response = rag_response["answer"]  # Use PDF knowledge
else:
    # Secondary: Web Search
    web_response = await self.web_search.search(message, user_language)
    if web_response:
        response = web_response
    else:
        response = get_response_text("no_answer", user_language)
```

### 2. RAG System Tool (`agent/rag.py`)

#### Vector Database Management

```python
class RAGSystem:
    def __init__(self):
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
        self.vectorstore = None  # FAISS vector database
```

#### PDF Processing Pipeline:

1. **Document Loading**
```python
def load_documents(self):
    pdf_files = glob.glob(os.path.join(Config.TRAINING_ROOT, "*.pdf"))
    for pdf_file in pdf_files:
        loader = PyPDFLoader(pdf_file)
        docs = loader.load()  # Extract text from PDFs
```

2. **Text Chunking**
```python
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,      # Each chunk ~1000 characters
    chunk_overlap=200,    # 200 char overlap for context continuity
    length_function=len
)
splits = text_splitter.split_documents(documents)
```

3. **Vector Embedding Creation**
```python
# Convert text chunks to vectors using OpenAI embeddings
self.vectorstore = FAISS.from_documents(splits, self.embeddings)
self.vectorstore.save_local(Config.RAG_VECTOR_DIR)  # Persist to disk
```

#### Query Processing:

```python
async def query(self, question: str, language: str) -> Dict[str, Any]:
    # 1. Convert question to vector
    query_embedding = self.embeddings.embed_query(question)
    
    # 2. Find similar document chunks
    docs = self.vectorstore.similarity_search_with_score(question, k=4)
    
    # 3. Generate answer using retrieved context
    prompt = f"""Based on this context: {retrieved_docs}
    Answer the question: {question}
    Language: {language}"""
    
    response = self.llm.invoke(prompt)
    return {"answer": response.content, "confidence": confidence_score}
```

### 3. Web Search Tool (`agent/tools.py`)

#### Dual Search Strategy

```python
class WebSearchTool:
    def __init__(self):
        self.llm = ChatOpenAI(model=Config.MODEL_NAME, temperature=0.1)
        self.serpapi_key = os.getenv('SERPAPI_KEY')
        self.has_serpapi = bool(self.serpapi_key)
```

#### Search Execution Logic:

1. **Primary: SerpAPI (Paid)**
```python
async def serpapi_search(self, query: str, language: str):
    params = {
        'q': query,
        'api_key': self.serpapi_key,
        'engine': 'google',
        'num': 5,
        'hl': language if language == 'en' else 'en'
    }
    search = GoogleSearch(params)
    results = await loop.run_in_executor(None, search.get_dict)
```

2. **Fallback: DuckDuckGo (Free)**
```python
async def web_search(self, query: str, language: str):
    # Add language context
    lang_prefixes = {"si": "සිංහල", "ta": "தமிழ்", "en": ""}
    search_query = f"{lang_prefixes[language]} {query}" if language != "en" else query
    
    results = await loop.run_in_executor(None, 
        lambda: list(DDGS().text(search_query, max_results=5)))
```

#### Result Summarization:

```python
async def summarize_results(self, results: list, query: str, language: str):
    context = "\n\n".join([
        f"Title: {result['title']}\nContent: {result['body']}"
        for result in results[:3]
    ])
    
    lang_instructions = {
        "si": "කරුණාකර සිංහලෙන් පිළිතුරු දෙන්න.",
        "ta": "தயவுசெய்து தமிழில் பதிலளிக்கவும்.",
        "en": "Please respond in English."
    }
    
    prompt = f"""Based on these search results: {context}
    Answer: {query}
    {lang_instructions[language]}"""
    
    return self.llm.invoke(prompt).content
```

### 4. Memory Management Tool (`agent/memory.py`)

#### Session Storage System

```python
class ConversationMemory:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.session_prefix = "session:"      # User sessions
        self.conversation_prefix = "conv:"    # Message history
        self.session_timeout = 3600 * 24     # 24-hour expiry
```

#### User Context Management:

```python
def get_session(self, phone_number: str) -> Dict[str, Any]:
    session_key = f"session:{phone_number}"
    session_data = self.redis.get(session_key)
    
    if session_data:
        return json.loads(session_data)  # Existing user
    else:
        # New user - create session
        new_session = {
            "phone_number": phone_number,
            "language": None,                    # Will be set on first interaction
            "created_at": datetime.now().isoformat(),
            "message_count": 0
        }
        return new_session
```

#### Conversation History:

```python
def add_message(self, phone_number: str, role: str, content: str):
    conv_key = f"conv:{phone_number}"
    message = {
        "role": role,           # "user" or "assistant"
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    
    # Store in Redis list (FIFO queue)
    self.redis.lpush(conv_key, json.dumps(message))
    self.redis.expire(conv_key, self.session_timeout)
```

### 5. Language Intelligence Tool (`agent/i18n.py`)

#### Automatic Language Detection

```python
class LanguageDetector:
    def detect_language(self, text: str) -> str:
        # Unicode script detection
        if self._contains_sinhala_script(text):
            return "si"
        elif self._contains_tamil_script(text):
            return "ta"
        else:
            return "en"  # Default to English
    
    def _contains_sinhala_script(self, text: str) -> bool:
        sinhala_range = range(0x0D80, 0x0DFF + 1)  # Unicode range for Sinhala
        return any(ord(char) in sinhala_range for char in text)
```

#### Dynamic Response Generation

```python
RESPONSES = {
    "language_selected": {
        "en": "Great! I'll respond in English. How can I help you?",
        "si": "හොඳයි! මම සිංහලෙන් පිළිතුරු දෙන්නම්. මම ඔබට කෙසේ උදව් කළ හැකිද?",
        "ta": "சிறப்பு! நான் தமிழில் பதிலளிப்பேன். நான் உங்களுக்கு எப்படி உதவ முடியும்?"
    }
}

def get_response_text(key: str, language: str) -> str:
    return RESPONSES.get(key, {}).get(language, RESPONSES[key]["en"])
```

### 6. Agent Decision-Making Logic

#### Tool Selection Algorithm

```python
# Decision tree for tool selection
if is_language_command(message):
    return language_menu()
elif is_language_selection(message):
    return set_user_language(message)
else:
    # Content query - choose best tool
    if pdf_knowledge_available():
        rag_result = rag_system.query(message)
        if rag_result.confidence > 0.7:
            return rag_result.answer
    
    # RAG insufficient - try web search
    if web_search_needed(message):
        web_result = web_search.search(message)
        if web_result:
            return web_result
    
    # No good results
    return fallback_response()
```

#### Confidence Scoring

```python
# RAG confidence based on document similarity
def calculate_confidence(similarity_scores):
    if not similarity_scores:
        return 0.0
    
    # Use highest similarity score as base confidence
    max_score = max(similarity_scores)
    
    # Apply thresholds
    if max_score > 0.8:
        return 0.9      # High confidence
    elif max_score > 0.6:
        return 0.7      # Medium confidence
    else:
        return 0.4      # Low confidence - trigger web search
```

### 7. Real-World Example Flow

#### User Query: "මෙම රසායනික ද්‍රව්‍යයක් වැගිරුණොත් මොකද කරන්න ඕනේ?" (Sinhala: "What to do if this chemical spills?")

**Step 1: Language Detection**
```python
detected_lang = lang_detector.detect_language("මෙම රසායනික...")  # Returns "si"
session["language"] = "si"  # Set Sinhala as user language
```

**Step 2: RAG System Query**
```python
# Convert Sinhala query to vector embedding
query_vector = embeddings.embed_query("මෙම රසායනික ද්‍රව්‍යයක් වැගිරුණොත්...")

# Search FAISS index for similar content
docs = vectorstore.similarity_search_with_score("chemical spill procedure", k=4)
# Returns: [
#   ("Chemical spills must be contained immediately...", 0.85),
#   ("Emergency procedures include evacuation...", 0.82),
#   ("PPE requirements: chemical-resistant gloves...", 0.78)
# ]
```

**Step 3: Response Generation**
```python
retrieved_context = """
Chemical spills must be contained immediately. Use absorbent materials...
Emergency procedures include evacuation of personnel from affected area...
PPE requirements: chemical-resistant gloves, eye protection, respirator...
"""

prompt = f"""Based on this safety information: {retrieved_context}
Answer in Sinhala: {user_question}
Provide clear, actionable safety steps."""

response = llm.invoke(prompt)
# Returns detailed Sinhala response with safety procedures
```

**Step 4: Memory Storage**
```python
memory.add_message(phone_number, "user", "මෙම රසායනික ද්‍රව්‍යයක් වැගිරුණොත්...")
memory.add_message(phone_number, "assistant", generated_response)
```

### 8. Agent Autonomy Features

#### Autonomous Language Switching
```python
# Agent detects language change and adapts automatically
if detected_lang != current_lang and len(message) > 10:
    session["language"] = detected_lang
    # Continue in new language without explicit user command
```

#### Smart Tool Routing
```python
# Agent chooses tools based on content analysis
web_keywords = ["weather", "news", "current", "today", "price"]
if any(keyword in message.lower() for keyword in web_keywords):
    # Route to web search for current information
    return await web_search.search(message, language)
else:
    # Route to RAG for safety/knowledge queries
    return await rag_system.query(message, language)
```

#### Proactive Error Handling
```python
# Agent handles API failures gracefully
try:
    serpapi_results = await self.serpapi_search(query, language)
except RateLimitError:
    # Automatically fallback to free alternative
    print("SerpAPI rate limit - falling back to DuckDuckGo")
    return await self.web_search(query, language)
```

### 9. Performance Optimizations

#### Async Tool Execution
```python
# All tool operations are asynchronous for better performance
async def process_message(self, phone_number: str, message: str):
    # Non-blocking operations
    rag_response = await self.rag_system.query(message, language)
    web_response = await self.web_search.search(message, language)
```

#### Caching Strategy
```python
# Vector embeddings cached in FAISS
# User sessions cached in Redis with 24h TTL
# Search results could be cached (implementation dependent)
```

### 10. Agent vs Traditional Chatbot

| Feature | Traditional Chatbot | This AI Agent |
|---------|-------------------|---------------|
| **Responses** | Pre-scripted responses | Dynamic generation with context |
| **Knowledge** | Static FAQ database | RAG + Real-time web search |
| **Tools** | Single response system | Multiple tools (RAG, Web, Memory, i18n) |
| **Decision Making** | Rule-based if/else | LLM-powered intelligent routing |
| **Memory** | Session-less | Persistent conversation memory |
| **Language** | Fixed language | Auto-detection + switching |
| **Autonomy** | Manual triggers | Self-directed tool selection |
| **Learning** | No adaptation | Context-aware improvements |

This agent represents a sophisticated implementation of tool-using AI that combines multiple specialized systems into a cohesive, intelligent assistant capable of handling complex, multilingual safety consultations with autonomous decision-making capabilities.
