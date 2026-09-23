"""
Component Benchmark 0 — Offline Indexing Pipeline (PDF ingestion -> FAISS build)

Measures the one-time (per-deployment) cost of building the FAISS vectorstore
from the 3 training PDFs: PDF parsing, recursive chunking, and OpenAI
text-embedding-3-large embedding generation for all chunks.
Builds into a throwaway directory so the production ./vectorstore used by
the other benchmarks is left untouched.
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP_VECTOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "_bench_vectorstore_tmp")
os.environ["RAG_VECTOR_DIR"] = TMP_VECTOR_DIR
if os.path.exists(TMP_VECTOR_DIR):
    shutil.rmtree(TMP_VECTOR_DIR)

from evaluation.common import save_json
from agent.rag import RAGSystem
from config import Config


def main():
    Config.RAG_VECTOR_DIR = TMP_VECTOR_DIR  # class attr already bound; override explicitly

    t0 = time.perf_counter()
    rag = RAGSystem()
    total_s = time.perf_counter() - t0

    n_chunks = rag.vectorstore.index.ntotal if rag.vectorstore else 0
    n_pdfs = 3

    result = {
        "n_pdfs": n_pdfs,
        "n_chunks": n_chunks,
        "chunk_size_chars": 1000,
        "chunk_overlap_chars": 200,
        "embedding_model": Config.EMBEDDING_MODEL,
        "total_build_time_s": total_s,
        "chunks_per_second": n_chunks / total_s if total_s > 0 else 0,
    }
    print(result)
    save_json("00_indexing_pipeline.json", result)

    shutil.rmtree(TMP_VECTOR_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
