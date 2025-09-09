import os
import glob
from typing import List, Dict, Any, Optional
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
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
        self.qa_chain = None
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
                self.setup_qa_chain()
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
        """Setup the QA chain with custom prompt"""
        if not self.vectorstore:
            return
        
        # Custom prompt template for multilingual support
        prompt_template = """You are a helpful safety and hazard awareness assistant. Use the following context to answer the question accurately and concisely.

Context: {context}

Question: {question}

Instructions:
- Answer in the same language as the question
- If the context doesn't contain relevant information, say "I don't have specific information about that in my knowledge base"
- Keep answers clear and actionable
- Focus on safety and hazard awareness

Answer:"""

        PROMPT = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"]
        )
        
        self.qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=self.vectorstore.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 4}
            ),
            chain_type_kwargs={"prompt": PROMPT}
        )
    
    async def query(self, question: str, language: str = "en") -> Optional[Dict[str, Any]]:
        """Query the RAG system"""
        try:
            if not self.qa_chain:
                return None
            
            # Add language context to question if not English
            if language != "en":
                lang_names = {"si": "Sinhala", "ta": "Tamil"}
                lang_instruction = f"Please respond in {lang_names.get(language, 'English')}. "
                question = lang_instruction + question
            
            result = self.qa_chain.invoke({"query": question})
            answer = result["result"]
            
            # Simple confidence scoring based on answer content
            confidence = self.calculate_confidence(answer)
            
            return {
                "answer": answer,
                "confidence": confidence,
                "source": "rag"
            }
            
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
    
    def refresh_vectorstore(self):
        """Refresh the vectorstore with new documents"""
        print("Refreshing vectorstore...")
        if os.path.exists(Config.RAG_VECTOR_DIR):
            import shutil
            shutil.rmtree(Config.RAG_VECTOR_DIR)
        
        self.build_vectorstore()
        if self.vectorstore:
            self.setup_qa_chain()
            print("Vectorstore refreshed successfully")
