"""
Component Benchmark 1 — RAG Retrieval Layer (FAISS + OpenAI embeddings)

Measures:
  - Query embedding + FAISS similarity_search latency (retrieval-only, no LLM)
  - Keyword-based Recall@k (automatic proxy metric — see limitations in report)
  - Sensitivity of retrieval latency to k (nearest-neighbour count)

Run with the real, already-built vectorstore in ./vectorstore (916 chunks
from the 3 training PDFs). Requires OPENAI_API_KEY (embeddings only, no
chat-completion calls, so this benchmark is inexpensive).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from evaluation.common import load_dataset, save_json, summarize, timer
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings


def relevant(doc_content: str, keywords) -> bool:
    text = doc_content.lower()
    return any(kw.lower() in text for kw in keywords)


def main():
    dataset = load_dataset("qa_testset.json")

    embeddings = OpenAIEmbeddings(model=Config.EMBEDDING_MODEL, openai_api_key=Config.OPENAI_API_KEY)
    with timer() as load_t:
        vectorstore = FAISS.load_local(Config.RAG_VECTOR_DIR, embeddings, allow_dangerous_deserialization=True)
    print(f"vectorstore load: {load_t['elapsed_s']:.3f}s, n_vectors={vectorstore.index.ntotal}")

    k_values = [1, 2, 4, 8]
    per_k_results = {}

    for k in k_values:
        latencies = []
        recall_hits = 0
        per_query = []
        for item in dataset:
            q = item["question"]
            t0 = time.perf_counter()
            docs = vectorstore.similarity_search(q, k=k)
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)
            hit = any(relevant(d.page_content, item["keywords"]) for d in docs)
            recall_hits += int(hit)
            per_query.append({
                "id": item["id"], "language": item["language"], "k": k,
                "latency_s": elapsed, "hit": hit,
            })
        per_k_results[k] = {
            "latency": summarize(latencies),
            "recall_at_k": recall_hits / len(dataset),
            "per_query": per_query,
        }
        print(f"k={k}: recall@k={per_k_results[k]['recall_at_k']:.3f} "
              f"mean_latency={per_k_results[k]['latency']['mean']*1000:.1f}ms")

    save_json("01_rag_retrieval.json", {
        "n_vectors": vectorstore.index.ntotal,
        "vectorstore_load_s": load_t["elapsed_s"],
        "embedding_model": Config.EMBEDDING_MODEL,
        "n_queries": len(dataset),
        "by_k": per_k_results,
    })


if __name__ == "__main__":
    main()
