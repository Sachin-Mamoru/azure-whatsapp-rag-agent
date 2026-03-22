import os
import glob
from typing import List, Dict, Any, Optional
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from config import Config

class RAGSystem:
    def __init__(self):
        self.embeddings = OpenAIEmbeddings(
            model=Config.EMBEDDING_MODEL,
            openai_api_key=Config.OPENAI_API_KEY
        )
        self.llm = ChatOpenAI(
            model=Config.MODEL_NAME,
            openai_api_key=Config.OPENAI_API_KEY,
            temperature=0.1
        )
        self.vectorstore = None
        self.initialize_rag()
    
    def initialize_rag(self):
        """Initialize or load the RAG system"""
        try:
            # Check if vectorstore exists
            if os.path.exists(Config.RAG_VECTOR_DIR):
                print("Loading existing vectorstore...")
                self.vectorstore = FAISS.load_local(
                    Config.RAG_VECTOR_DIR, 
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
            else:
                print("Creating new vectorstore...")
                self.build_vectorstore()
            
            if self.vectorstore:
                print("RAG system initialized successfully")
            
        except Exception as e:
            print(f"Error initializing RAG system: {e}")
    
    def build_vectorstore(self):
        """Build vectorstore from PDF documents"""
        try:
            documents = self.load_documents()
            if not documents:
                print("No documents found for indexing")
                return
            
            # Split documents into chunks
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200,
                length_function=len
            )
            splits = text_splitter.split_documents(documents)
            
            # Create vectorstore
            self.vectorstore = FAISS.from_documents(splits, self.embeddings)
            
            # Save vectorstore
            os.makedirs(Config.RAG_VECTOR_DIR, exist_ok=True)
            self.vectorstore.save_local(Config.RAG_VECTOR_DIR)
            
            print(f"Vectorstore created with {len(splits)} document chunks")
            
        except Exception as e:
            print(f"Error building vectorstore: {e}")
    
    def load_documents(self) -> List:
        """Load PDF documents from training directory"""
        documents = []
        
        if not os.path.exists(Config.TRAINING_ROOT):
            print(f"Training directory not found: {Config.TRAINING_ROOT}")
            return documents
        
        pdf_files = glob.glob(os.path.join(Config.TRAINING_ROOT, "*.pdf"))
        
        for pdf_file in pdf_files:
            try:
                loader = PyPDFLoader(pdf_file)
                docs = loader.load()
                documents.extend(docs)
                print(f"Loaded {len(docs)} pages from {os.path.basename(pdf_file)}")
            except Exception as e:
                print(f"Error loading {pdf_file}: {e}")
        
        return documents
    
    def setup_qa_chain(self):
        """No-op — we now query directly via the vectorstore + LLM."""
        pass

    async def query(self, question: str, language: str = "en",
                    conversation_history: Optional[List[Dict]] = None) -> Optional[Dict[str, Any]]:
        """Query the RAG system with full conversation history for context."""
        try:
            if not self.vectorstore:
                return None

            # Retrieve relevant documents
            docs = self.vectorstore.similarity_search(question, k=4)
            context = "\n\n".join([doc.page_content for doc in docs])

            lang_names = {"si": "Sinhala", "ta": "Tamil", "en": "English"}
            lang_name = lang_names.get(language, "English")

            system_prompt = (
                f"You are a helpful safety and hazard awareness assistant for Sri Lanka.\n"
                f"Use the knowledge base context below to answer questions accurately and concisely.\n"
                f"ALWAYS respond in {lang_name} — even if the user wrote in another language.\n\n"
                f"Knowledge Base Context:\n{context}\n\n"
                f"Instructions:\n"
                f"- Reply ONLY in {lang_name}.\n"
                f"- If the context does not contain relevant information, say so briefly in {lang_name}.\n"
                f"- Keep answers clear and actionable.\n"
                f"- Focus on safety and hazard awareness.\n"
                f"- You remember the conversation history and can refer back to it."
            )

            messages: List = [SystemMessage(content=system_prompt)]

            # Inject last 6 turns of conversation history for context
            if conversation_history:
                for msg in conversation_history[-6:]:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=content))

            # Add current user question
            messages.append(HumanMessage(content=question))

            result = await self.llm.ainvoke(messages)
            answer = result.content

            confidence = self.calculate_confidence(answer)
            return {"answer": answer, "confidence": confidence, "source": "rag"}

        except Exception as e:
            print(f"Error querying RAG system: {e}")
            return None
    
    def calculate_confidence(self, answer: str) -> float:
        """Calculate confidence score for the answer"""
        if "I don't have specific information" in answer:
            return 0.1
        elif "knowledge base" in answer.lower():
            return 0.3
        elif len(answer) < 50:
            return 0.5
        else:
            return 0.8
    
    async def chat_with_history(self, message: str, language: str,
                                conversation_history: Optional[List[Dict]] = None) -> str:
        """Answer conversational / meta questions using only LLM + conversation history."""
        lang_names = {"si": "Sinhala", "ta": "Tamil", "en": "English"}
        lang_name = lang_names.get(language, "English")

        system_prompt = (
            f"You are a friendly safety and hazard awareness assistant for Sri Lanka.\n"
            f"ALWAYS respond in {lang_name}.\n"
            f"You have full memory of the conversation below. "
            f"Use it to answer questions about what was previously discussed, "
            f"previous questions asked, or any follow-up queries."
        )

        messages: List = [SystemMessage(content=system_prompt)]
        if conversation_history:
            for msg in conversation_history[-10:]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=message))

        try:
            result = await self.llm.ainvoke(messages)
            return result.content
        except Exception as e:
            print(f"[rag] chat_with_history error: {e}")
            return ""

    def refresh_vectorstore(self):
        """Refresh the vectorstore with new documents"""
        print("Refreshing vectorstore...")
        if os.path.exists(Config.RAG_VECTOR_DIR):
            import shutil
            shutil.rmtree(Config.RAG_VECTOR_DIR)
        
        self.build_vectorstore()
        if self.vectorstore:
            print("Vectorstore refreshed successfully")
