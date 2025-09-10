import asyncio
import os
from typing import Optional
from serpapi import GoogleSearch
from duckduckgo_search import DDGS
from langchain_openai import ChatOpenAI
from config import Config

class WebSearchTool:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=Config.MODEL_NAME,
            openai_api_key=Config.OPENAI_API_KEY,
            temperature=0.1
        )
        self.serpapi_key = os.getenv('SERPAPI_KEY')
        self.has_serpapi = bool(self.serpapi_key)
    
    async def search(self, query: str, language: str = "en") -> Optional[str]:
        """Perform web search and summarize results"""
        try:
            # Try SerpAPI first if available, otherwise use DuckDuckGo
            if self.has_serpapi:
                search_results = await self.serpapi_search(query, language)
            else:
                search_results = await self.web_search(query, language)
            
            if not search_results:
                return None
            
            # Summarize results using LLM
            summary = await self.summarize_results(search_results, query, language)
            return summary
            
        except Exception as e:
            print(f"Error in web search: {e}")
            return None
    
    async def serpapi_search(self, query: str, language: str) -> list:
        """Perform search using SerpAPI (Google Search)"""
        try:
            params = {
                'q': query,
                'api_key': self.serpapi_key,
                'engine': 'google',
                'num': 5,
                'hl': language if language == 'en' else 'en',
                'safe': 'active'
            }
            
            # Use asyncio to run the synchronous SerpAPI search
            loop = asyncio.get_event_loop()
            search = GoogleSearch(params)
            results = await loop.run_in_executor(None, search.get_dict)
            
            # Convert SerpAPI results to DuckDuckGo format for compatibility
            organic_results = results.get('organic_results', [])
            formatted_results = []
            
            for result in organic_results:
                formatted_results.append({
                    'title': result.get('title', ''),
                    'body': result.get('snippet', ''),
                    'href': result.get('link', '')
                })
            
            return formatted_results
            
        except Exception as e:
            print(f"Error in SerpAPI search: {e}")
            # Fallback to DuckDuckGo
            return await self.web_search(query, language)

    async def web_search(self, query: str, language: str) -> list:
        """Perform DuckDuckGo search (fallback)"""
        try:
            # Add language context to search
            lang_prefixes = {
                "si": "සිංහල",
                "ta": "தமிழ்",
                "en": ""
            }
            
            search_query = query
            if language in lang_prefixes and lang_prefixes[language]:
                search_query = f"{lang_prefixes[language]} {query}"
            
            # Use asyncio to run the synchronous search
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: list(DDGS().text(search_query, max_results=5))
            )
            
            return results
            
        except Exception as e:
            print(f"Error in DuckDuckGo search: {e}")
            # Check if it's a rate limit error
            if "ratelimit" in str(e).lower() or "202" in str(e):
                print("DuckDuckGo rate limit detected")
            return []
    
    async def summarize_results(self, results: list, query: str, language: str) -> str:
        """Summarize search results using LLM"""
        try:
            # Prepare context from search results
            context = "\n\n".join([
                f"Title: {result.get('title', '')}\nContent: {result.get('body', '')}"
                for result in results[:3]  # Use top 3 results
            ])
            
            # Language-specific prompts
            lang_instructions = {
                "si": "කරුණාකර සිංහලෙන් පිළිතුරු දෙන්න.",
                "ta": "தயவுசெய்து தமிழில் பதிலளிக்கவும்.",
                "en": "Please respond in English."
            }
            
            prompt = f"""Based on the following web search results, provide a helpful and accurate answer to the user's question.

Search Results:
{context}

User Question: {query}

Instructions:
- {lang_instructions.get(language, lang_instructions['en'])}
- Provide a concise and helpful answer
- If the results don't contain relevant information, say so
- Focus on factual information

Answer:"""

            response = self.llm.invoke(prompt)
            return response.content
            
        except Exception as e:
            print(f"Error summarizing results: {e}")
            return "Sorry, I couldn't process the search results."
