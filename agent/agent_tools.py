"""
Agent Tool Definitions
----------------------
Defines the four tools exposed to the LLM agent.  The LLM reads the
docstrings and decides which tool to call — that decision is the core
research contribution of the agent-based architecture.

Tool call metadata is logged to the community_reports database so every
routing decision can be analysed in the MPhil evaluation.

build_tools() is called once per message so each tool closure captures
the correct per-request language and phone-number context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from langchain_core.tools import tool

if TYPE_CHECKING:
    from agent.rag import RAGSystem
    from agent.reporter import CommunityReporter
    from agent.tools import WebSearchTool


def build_tools(
    rag_system: "RAGSystem",
    reporter: "CommunityReporter",
    web_search: "WebSearchTool",
    language: str,
    phone_number: str,
) -> List:
    """
    Return the four LangChain tool objects for one agent invocation.

    All tools capture *language* and *phone_number* via closure so the agent
    does not need to pass them explicitly — keeping tool descriptions clean
    and reducing prompt complexity.
    """

    @tool
    async def query_knowledge_base(question: str) -> str:
        """Search the authoritative knowledge base for information about disaster
        preparedness, hazard awareness, landslide and flood risk, safety
        procedures, emergency response, and community resilience in Sri Lanka.

        Use this tool when the user asks a question, seeks advice, wants to
        understand a safety topic, or asks how to prepare for or respond to
        a natural hazard.  Do NOT use this for reports of ongoing incidents.
        """
        reporter.log_tool_call(phone_number, "query_knowledge_base", {"question": question})
        community_ctx = reporter.get_recent_reports_context()
        result = await rag_system.query(
            question, language, community_context=community_ctx
        )
        if result and result.get("answer"):
            return result["answer"]
        return "No relevant information found in the knowledge base."

    @tool
    async def search_web(query: str) -> str:
        """Search the web for current news, weather conditions, active alerts,
        or any time-sensitive information not available in the knowledge base.

        Use this when the user asks about current weather, today's situation,
        recent events, live flood levels, or anything that requires up-to-date
        external information.
        """
        reporter.log_tool_call(phone_number, "search_web", {"query": query})
        result = await web_search.search(query, language)
        return result or "No web search results available."

    @tool
    async def submit_community_report(report_text: str) -> str:
        """Submit a community hazard or safety report on behalf of the user.

        Use this tool when the user is REPORTING something they currently
        observe or have witnessed — such as: a crack on a slope, rising flood
        water, a blocked drain, a landslide, road damage, unsafe construction,
        or any environmental safety concern.

        Do NOT use this for questions or requests for advice.  The input should
        be the user's own description of what they are observing.
        """
        reporter.log_tool_call(
            phone_number, "submit_community_report", {"text": report_text[:200]}
        )
        result = await reporter.process_report(phone_number, report_text, language)
        return result["response"]

    @tool
    def get_community_observations(area: str = "") -> str:
        """Retrieve recent unverified hazard observations submitted by other
        community members.

        Use this when the user asks what others are reporting, whether there
        are recent reports nearby, or what the current community-reported
        conditions are.  Optionally provide an area name to indicate the
        geographic context (used for logging only in Phase 1).
        """
        reporter.log_tool_call(
            phone_number, "get_community_observations", {"area": area}
        )
        ctx = reporter.get_recent_reports_context()
        return ctx if ctx else "No recent community observations available."

    return [
        query_knowledge_base,
        search_web,
        submit_community_report,
        get_community_observations,
    ]
