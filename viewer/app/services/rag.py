"""RAG (Retrieval-Augmented Generation) service for paper chatbot.

This module implements the RAG pipeline:
1. Chunking: Split markdown into manageable chunks
2. Retrieval: Keyword-based search to find relevant chunks
3. Context Assembly: Build LLM prompt with retrieved chunks
4. Generation: Stream LLM response
"""

import re
from pathlib import Path
from typing import List, AsyncGenerator
import os

from ..models.chat import ChatChunk, ChatMessage


def estimate_tokens(text: str) -> int:
    """Rough token estimate for English text.

    Args:
        text: Input text

    Returns:
        Estimated token count (~1 token per 4 characters)
    """
    return len(text) // 4


def chunk_markdown(
    md_path: Path,
    chunk_size: int = 500,
    overlap: int = 50
) -> List[ChatChunk]:
    """Split markdown file into overlapping chunks for RAG retrieval.

    Strategy:
    - Split at heading boundaries (##, ###) for semantic coherence
    - Target 500 tokens (~2000 chars) per chunk
    - 50-token overlap between chunks
    - Preserve code blocks and math equations

    Args:
        md_path: Path to markdown file
        chunk_size: Target chunk size in tokens (default: 500)
        overlap: Overlap size in tokens (default: 50)

    Returns:
        List of ChatChunk objects with content and metadata
    """
    content = md_path.read_text(encoding="utf-8")
    lines = content.split('\n')

    chunks = []
    current_chunk_lines = []
    current_heading = None
    current_tokens = 0
    start_line = 0

    def save_chunk():
        """Save current chunk and reset state."""
        if not current_chunk_lines:
            return

        chunk_content = '\n'.join(current_chunk_lines)
        chunks.append(ChatChunk(
            index=len(chunks),
            content=chunk_content,
            heading=current_heading,
            start_line=start_line,
            end_line=start_line + len(current_chunk_lines)
        ))

    in_code_block = False

    for i, line in enumerate(lines):
        # Track code blocks to avoid splitting them
        if line.strip().startswith('```'):
            in_code_block = not in_code_block

        # Detect heading (new section)
        if line.startswith('## ') or line.startswith('### '):
            # Save previous chunk if it's getting large
            if current_tokens > chunk_size:
                save_chunk()

                # Create overlap: keep last few lines
                overlap_lines = current_chunk_lines[-5:] if len(current_chunk_lines) >= 5 else current_chunk_lines
                current_chunk_lines = overlap_lines
                current_tokens = sum(estimate_tokens(l) for l in overlap_lines)
                start_line = i - len(overlap_lines)

            # Extract heading text
            current_heading = line.strip('#').strip()

        # Add line to current chunk
        current_chunk_lines.append(line)
        current_tokens += estimate_tokens(line)

        # Split if chunk is too large (but not in middle of code block)
        if current_tokens > chunk_size and not in_code_block:
            save_chunk()

            # Create overlap
            overlap_lines = current_chunk_lines[-5:] if len(current_chunk_lines) >= 5 else []
            current_chunk_lines = overlap_lines
            current_tokens = sum(estimate_tokens(l) for l in overlap_lines)
            start_line = i - len(overlap_lines) + 1

    # Save final chunk
    save_chunk()

    return chunks


def search_chunks(
    query: str,
    chunks: List[ChatChunk],
    top_k: int = 5
) -> tuple[List[ChatChunk], List[float]]:
    """Search for relevant chunks using keyword-based scoring (BM25-style).

    Scoring:
    - Count term frequency in chunk content
    - Bonus score for heading matches (10 points)
    - Sort by score descending
    - Return top K chunks with their scores

    Args:
        query: User's question
        chunks: List of all available chunks
        top_k: Number of top chunks to return (default: 5)

    Returns:
        Tuple of (relevant_chunks, scores) in descending score order
    """
    # Tokenize query (simple lowercase split)
    query_terms = query.lower().split()

    scored_chunks = []

    for chunk in chunks:
        score = 0
        chunk_text = chunk.content.lower()
        heading_text = (chunk.heading or '').lower()

        for term in query_terms:
            # Term frequency in chunk content
            tf = chunk_text.count(term)
            score += tf

            # Heading match bonus (semantic relevance)
            if term in heading_text:
                score += 10

        # Only include chunks with non-zero score
        if score > 0:
            scored_chunks.append((score, chunk))

    # Sort by score descending
    scored_chunks.sort(key=lambda x: x[0], reverse=True)

    # Return top K chunks with scores
    top = scored_chunks[:top_k]
    return ([chunk for _, chunk in top], [score for score, _ in top])


# ── Web Search Heuristic ─────────────────────────────────────────────────

# Patterns suggesting external information is needed (EN + KO)
_EXTERNAL_PATTERNS = [
    re.compile(r'\b(compar|versus|vs\.?|differ)', re.I),
    re.compile(r'\b(state.of.the.art|sota|recent|latest|current|version)', re.I),
    re.compile(r'\b(related\s+work|prior\s+work|other\s+(papers?|methods?|approaches?))', re.I),
    re.compile(r'\b(benchmark|dataset|leaderboard)', re.I),
    re.compile(r'\b(implement(ation)?|code|github|repository)', re.I),
    re.compile(r'\b(who\s+(invented|proposed|created)|when\s+was)', re.I),
    re.compile(r'\b(cite|citation|impact)', re.I),
    re.compile(r'(비교|차이점|다른\s*(방법|논문|모델|접근))', re.I),
    re.compile(r'(최신|최근|동향|트렌드|버전)', re.I),
    re.compile(r'(관련\s*연구|선행\s*연구|다른\s*연구)', re.I),
    re.compile(r'(코드|구현|깃허브|소스코드)', re.I),
    re.compile(r'(벤치마크|데이터셋|리더보드)', re.I),
]

# Patterns suggesting paper-internal questions (skip web search)
_INTERNAL_PATTERNS = [
    re.compile(r'\b(this\s+paper|the\s+paper|the\s+authors?|section\s+\d|table\s+\d|figure\s+\d|equation\s+\d)', re.I),
    re.compile(r'\b(proposed\s+method|their\s+(approach|method|model|result))', re.I),
    re.compile(r'\b(abstract|introduction|conclusion|appendix)', re.I),
    re.compile(r'(이\s*논문|본\s*논문|저자|제안\s*(된|하는|한)\s*방법|본\s*연구)', re.I),
    re.compile(r'(요약|초록|결론|서론)', re.I),
]

_SCORE_THRESHOLD = 3


def should_web_search(query: str, top_score: float, num_results: int) -> bool:
    """Decide whether to augment RAG with web search results.

    Returns True if:
    1. Query matches external-knowledge patterns, OR
    2. BM25 retrieval found zero or very low-scoring results

    Returns False if:
    1. Query clearly asks about paper internals
    """
    # Paper-internal questions: skip web search
    for pat in _INTERNAL_PATTERNS:
        if pat.search(query):
            return False

    # External-knowledge patterns: trigger web search
    for pat in _EXTERNAL_PATTERNS:
        if pat.search(query):
            return True

    # Poor retrieval quality: trigger web search
    if num_results == 0 or top_score < _SCORE_THRESHOLD:
        return True

    return False


def build_web_search_query(user_query: str, paper_title: str | None = None) -> str:
    """Build an effective web search query from user question + paper context.

    Args:
        user_query: The user's chat question
        paper_title: Optional paper title for domain context

    Returns:
        Search query string
    """
    q = user_query.strip()
    if len(q) > 80:
        q = q[:80].rsplit(' ', 1)[0]

    if paper_title:
        short_title = paper_title[:50].rsplit(' ', 1)[0] if len(paper_title) > 50 else paper_title
        q = f"{q} {short_title}"

    return q


def build_rag_context(
    query: str,
    chunks: List[ChatChunk],
    history: List[ChatMessage],
    max_chunks: int = 3,
    max_history: int = 2,
    web_results: list[dict] | None = None
) -> str:
    """Assemble RAG context for LLM prompt.

    Args:
        query: User's current question
        chunks: Retrieved relevant chunks
        history: Conversation history
        max_chunks: Maximum chunks to include (default: 5)
        max_history: Maximum previous conversation turns (default: 2)
        web_results: Optional web search results to supplement context

    Returns:
        Formatted context string for LLM
    """
    context_parts = []

    # 1. Paper content excerpts
    context_parts.append("# Paper Content (Relevant Excerpts)\n")

    for chunk in chunks[:max_chunks]:
        if chunk.heading:
            context_parts.append(f"\n## Section: {chunk.heading}\n")
        else:
            context_parts.append(f"\n## Section {chunk.index + 1}\n")

        context_parts.append(chunk.content)

    # 2. Web search results (supplementary)
    if web_results:
        context_parts.append("\n\n# Web Search Results (Supplementary)\n")
        for r in web_results[:3]:
            context_parts.append(f"\n## [{r.get('title', '')}]({r.get('url', '')})\n")
            context_parts.append(r.get('description', ''))

    # 3. Previous conversation (last N turns for context)
    if history and len(history) > 0:
        context_parts.append("\n\n# Previous Conversation\n")

        # Get last max_history*2 messages (user + assistant pairs)
        recent_messages = history[-(max_history * 2):] if len(history) > max_history * 2 else history

        for msg in recent_messages:
            role_label = "User" if msg.role == "user" else "Assistant"
            context_parts.append(f"{role_label}: {msg.content}\n")

    # 4. Current question
    context_parts.append(f"\n# Current Question\nUser: {query}\n")

    return '\n'.join(context_parts)


async def generate_response_stream(
    context: str,
    query: str,
    model: str,
    base_url: str,
    api_key: str,
    has_web_context: bool = False
) -> AsyncGenerator[dict, None]:
    """Stream LLM response using OpenAI-compatible API.

    Args:
        context: Assembled RAG context (paper excerpts + history + query)
        query: User's question
        model: LLM model name (e.g., "gpt-4o", "gemini-2.5-pro")
        base_url: API base URL
        api_key: API key
        has_web_context: Whether web search results are included in context

    Yields:
        Event dicts:
        - {"type": "token", "content": "..."}
        - {"type": "done"}
        - {"type": "error", "error": "..."}
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        yield {"type": "error", "error": "OpenAI library not installed"}
        return

    system_prompt = """You are a helpful research assistant helping a user understand an academic paper.

Your task:
- Be easy to understand and concise
- Prefer simple Korean explanations over academic wording
- If the question is about this paper, prioritize paper excerpts
- If the question is general/current-fact (e.g., versions, products, market examples), use web results when available
- If information is insufficient, say so briefly and ask one focused follow-up question

Default response style (important):
- Answer naturally in plain Korean without fixed headers/templates
- Keep it concise by default (about 2-5 sentences)
- Use bullets only when they improve clarity
- Expand only when the user explicitly asks for detail"""

    if has_web_context:
        system_prompt += """

Web search context:
- Web search results are provided under "# Web Search Results (Supplementary)"
- For paper-specific questions: prioritize paper content
- For general/current-fact questions: prioritize web results and answer directly
- When citing web sources, include the URL as a markdown link"""

    system_prompt += """

Guidelines:
- Do not force the answer into paper-only mode when user asks a general/current-fact question
- Keep wording plain and short
- Avoid long introductions, repetition, and over-explaining
- Use bullet points only when they improve clarity
- Never invent product names, versions, or specs. Only use facts explicitly present in context/web results
- For each concrete claim (product/model/version), include a source link from provided web results
- Render sources as clickable markdown hyperlinks: [출처](https://...)
- If sources are weak/ambiguous, say "확인된 출처가 불충분" and ask for narrower scope
- Do NOT claim tool/environment limitations such as "I can't browse" or "I cannot do real-time web search"
- If information is missing, ask only ONE short follow-up question
- Avoid stiff/meta phrases like "제공된 발췌", "웹 발췌 기준", "정보가 들어있지 않습니다"
- Prefer conversational Korean (친구에게 설명하듯) over formal report tone"""

    try:
        client = AsyncOpenAI(base_url=base_url, api_key=api_key)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context}
        ]

        # Stream response
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,  # Low temperature for factual responses
            max_tokens=900,
            stream=True
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield {
                    "type": "token",
                    "content": chunk.choices[0].delta.content
                }

        yield {"type": "done"}

    except Exception as e:
        yield {"type": "error", "error": str(e)}
