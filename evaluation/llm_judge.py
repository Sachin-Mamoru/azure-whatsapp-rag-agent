"""
LLM-as-judge scoring for RAG answer quality.

Uses a separate, larger model (gpt-4o) than the production system's
gpt-4o-mini to reduce same-model self-evaluation bias, falling back to
gpt-4o-mini automatically if gpt-4o is unavailable on the configured API key.
This is a disclosed, imperfect substitute for human/domain-expert judgement
(see PERFORMANCE_EVALUATION.md limitations) but is standard practice
(RAGAS/G-Eval-style) for bounding answer faithfulness/relevance at scale.
"""
import asyncio
import json
from typing import Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import Config

_JUDGE_SYSTEM_PROMPT = """You are an impartial evaluator scoring an AI safety-advisory \
assistant's answer to a citizen's disaster-preparedness question.

Score the answer on two 0-5 integer scales:
  faithfulness: Is every factual claim in the answer supported by the provided \
CONTEXT (if any context is given), or, if no context is given, is the answer free \
of fabricated specifics (invented statistics, invented place names, invented \
regulations)? 5 = fully supported/no fabrication, 0 = contains clearly invented \
or contradicted facts.
  relevance: Does the answer directly address the user's question? 5 = fully \
relevant and complete, 0 = off-topic or non-answer.

Also set hallucination_flag=true if the answer states any specific fact (a number, \
a named law/manual/organisation, a technical claim) that is NOT present in the \
provided CONTEXT and is not common-sense safety advice.

Return ONLY a JSON object: {"faithfulness": int, "relevance": int, \
"hallucination_flag": bool, "rationale": "one short sentence"}"""


class LLMJudge:
    def __init__(self, preferred_model: str = "gpt-4o"):
        self.model_used = preferred_model
        try:
            self.llm = ChatOpenAI(
                model=preferred_model, openai_api_key=Config.OPENAI_API_KEY, temperature=0.0,
                request_timeout=20, max_retries=1,
            )
        except Exception:
            self.model_used = "gpt-4o-mini"
            self.llm = ChatOpenAI(
                model="gpt-4o-mini", openai_api_key=Config.OPENAI_API_KEY, temperature=0.0,
                request_timeout=20, max_retries=1,
            )

    async def score(self, question: str, answer: str, context: str = "") -> Dict:
        user_content = f"CONTEXT:\n{context or '(none provided)'}\n\nQUESTION:\n{question}\n\nANSWER:\n{answer}"
        try:
            result = await self.llm.ainvoke([
                SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ])
            raw = result.content.strip()
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else parts[0]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw.strip())
            parsed["judge_model"] = self.model_used
            return parsed
        except Exception as exc:
            # On rate-limit/model-access failure, retry once with gpt-4o-mini
            if self.model_used != "gpt-4o-mini":
                self.model_used = "gpt-4o-mini"
                self.llm = ChatOpenAI(
                    model="gpt-4o-mini", openai_api_key=Config.OPENAI_API_KEY, temperature=0.0,
                    request_timeout=20, max_retries=1,
                )
                return await self.score(question, answer, context)
            print(f"[llm_judge] scoring error: {exc}")
            return {"faithfulness": None, "relevance": None, "hallucination_flag": None,
                    "rationale": f"judge_error: {exc}", "judge_model": self.model_used}
