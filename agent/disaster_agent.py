"""
Disaster Assistant Agent
------------------------
A LangChain tool-calling agent that decides which tool to invoke for each
incoming WhatsApp message.  The LLM reads the tool descriptions and selects
the appropriate tool autonomously — this is the agent-based routing layer
that replaces the manual if/elif routing chain.

Architecture for MPhil research:
  - 4 tools: query_knowledge_base, search_web, submit_community_report,
             get_community_observations
  - LLM (GPT-4o-mini with function calling) selects tools autonomously
  - Every tool selection is logged → evaluatable routing dataset
  - Hard pre-checks (language, registration, STOP) stay in the orchestrator
    because they are not research-interesting routing decisions

The authoritative knowledge base and community reports remain in separate
stores; the agent cannot cross-contaminate them — it calls the tools
that enforce that boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from agent.agent_tools import build_tools
from config import Config

if TYPE_CHECKING:
    from agent.rag import RAGSystem
    from agent.reporter import CommunityReporter
    from agent.tools import WebSearchTool


_LANG_NAMES = {"si": "Sinhala", "ta": "Tamil", "en": "English"}


def _system_prompt(lang_name: str) -> str:
    return (
        f"You are a safety and disaster awareness assistant for Sri Lanka, "
        f"communicating via WhatsApp.\n\n"
        f"LANGUAGE RULE: You MUST reply ONLY in {lang_name}.  "
        f"Even if a tool returns English text, translate your final reply to {lang_name}.\n\n"
        f"You have four tools:\n"
        f"  • query_knowledge_base — for safety questions, hazard guidance, preparedness advice, "
        f"emergency procedures.  Use for questions.\n"
        f"  • search_web — for current weather, live news, active alerts, anything time-sensitive.\n"
        f"  • submit_community_report — when the user DESCRIBES observing a hazard, flood, "
        f"landslide, cracked slope, blocked drain, road damage, or any safety concern they are "
        f"witnessing right now.  Use for reports, NOT questions.\n"
        f"  • get_community_observations — when the user asks what others are reporting or what "
        f"conditions are like nearby.\n\n"
        f"Rules:\n"
        f"1. Always call at least one tool before giving your final answer.\n"
        f"2. Never answer from general knowledge alone without calling a tool first.\n"
        f"3. If the user is reporting AND asking a question, call submit_community_report first, "
        f"then query_knowledge_base.\n"
        f"4. Keep replies concise and plain-text suitable for WhatsApp (no markdown headers).\n"
        f"5. If a community observation is referenced, label it 'community report (unverified)'."
    )


class DisasterAgent:
    """
    Wraps a LangChain tool-calling agent with the four disaster domain tools.

    The same DisasterAgent instance is reused across messages; a fresh
    AgentExecutor is built per invocation so the system prompt and tool
    closures always carry the correct per-message language and user context.
    """

    def __init__(
        self,
        rag_system: "RAGSystem",
        reporter: "CommunityReporter",
        web_search: "WebSearchTool",
    ) -> None:
        self.rag_system = rag_system
        self.reporter = reporter
        self.web_search = web_search
        self.llm = ChatOpenAI(
            model=Config.MODEL_NAME,
            openai_api_key=Config.OPENAI_API_KEY,
            temperature=0.1,
        )

    async def ainvoke(
        self,
        message: str,
        language: str,
        phone_number: str,
        conversation_history: Optional[List[Dict]] = None,
    ) -> str:
        """
        Run the agent for a single message and return the final text response.

        Parameters
        ----------
        message:              The user's WhatsApp message text.
        language:             Detected language code (si / en / ta).
        phone_number:         Raw phone number — passed through to tools for
                              logging; never stored in plaintext by tools.
        conversation_history: Last N turns from ConversationMemory.
        """
        lang_name = _LANG_NAMES.get(language, "English")

        prompt = ChatPromptTemplate.from_messages([
            ("system", _system_prompt(lang_name)),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])

        tools = build_tools(
            self.rag_system, self.reporter, self.web_search, language, phone_number
        )

        agent = create_tool_calling_agent(self.llm, tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=tools,
            max_iterations=4,
            handle_parsing_errors=True,
            return_intermediate_steps=False,
        )

        # Convert stored conversation history to LangChain message objects
        chat_history: List = []
        for msg in (conversation_history or [])[-6:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                chat_history.append(HumanMessage(content=content))
            elif role == "assistant":
                chat_history.append(AIMessage(content=content))

        try:
            result = await executor.ainvoke({
                "input": message,
                "chat_history": chat_history,
            })
            return result.get("output", "")
        except Exception as exc:
            print(f"[disaster_agent] Agent execution error: {exc}")
            return ""
