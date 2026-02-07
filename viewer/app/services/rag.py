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
) -> List[ChatChunk]:
    """Search for relevant chunks using keyword-based scoring (BM25-style).

    Scoring:
    - Count term frequency in chunk content
    - Bonus score for heading matches (10 points)
    - Sort by score descending
    - Return top K chunks

    Args:
        query: User's question
        chunks: List of all available chunks
        top_k: Number of top chunks to return (default: 5)

    Returns:
        List of most relevant chunks (up to top_k)
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

    # Return top K chunks
    return [chunk for score, chunk in scored_chunks[:top_k]]


def build_rag_context(
    query: str,
    chunks: List[ChatChunk],
    history: List[ChatMessage],
    max_chunks: int = 5,
    max_history: int = 2
) -> str:
    """Assemble RAG context for LLM prompt.

    Format:
    ```
    # Paper Content (Relevant Excerpts)

    ## Section: {heading}
    {chunk_content}

    # Previous Conversation
    User: {previous question}
    Assistant: {previous answer}

    # Current Question
    User: {current query}
    ```

    Args:
        query: User's current question
        chunks: Retrieved relevant chunks
        history: Conversation history
        max_chunks: Maximum chunks to include (default: 5)
        max_history: Maximum previous conversation turns (default: 2)

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

    # 2. Previous conversation (last N turns for context)
    if history and len(history) > 0:
        context_parts.append("\n\n# Previous Conversation\n")

        # Get last max_history*2 messages (user + assistant pairs)
        recent_messages = history[-(max_history * 2):] if len(history) > max_history * 2 else history

        for msg in recent_messages:
            role_label = "User" if msg.role == "user" else "Assistant"
            context_parts.append(f"{role_label}: {msg.content}\n")

    # 3. Current question
    context_parts.append(f"\n# Current Question\nUser: {query}\n")

    return '\n'.join(context_parts)


async def generate_response_stream(
    context: str,
    query: str,
    model: str,
    base_url: str,
    api_key: str
) -> AsyncGenerator[dict, None]:
    """Stream LLM response using OpenAI-compatible API.

    System prompt instructs LLM to:
    - Act as research assistant for academic papers
    - Answer based on provided excerpts
    - Be concise and cite sections
    - Acknowledge if excerpts lack info

    Args:
        context: Assembled RAG context (paper excerpts + history + query)
        query: User's question
        model: LLM model name (e.g., "gpt-4o", "gemini-2.5-pro")
        base_url: API base URL
        api_key: API key

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
- Answer questions based on the provided paper excerpts and conversation history
- Be concise, accurate, and cite specific sections when possible
- Use clear, accessible language while maintaining technical accuracy
- If the provided excerpts don't contain enough information to answer fully, acknowledge this and suggest what additional context might help

Guidelines:
- Focus on the paper's content, not general knowledge
- Quote or paraphrase from the excerpts when relevant
- Maintain conversation context from previous exchanges
- Be helpful and educational"""

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
            max_tokens=2048,
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
