"""Chat history management service for per-paper chatbot.

This module provides functions to load, save, and manage chat histories
stored as JSON files in paper directories.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from ..models.chat import ChatHistory, ChatMessage, ChatChunk
from ..config import settings
from .papers import _resolve_paper_dir


def load_chat_history(paper_name: str) -> ChatHistory:
    """Load chat history from paper directory.

    Args:
        paper_name: Unique paper identifier (folder name)

    Returns:
        ChatHistory object with messages, or empty history if file doesn't exist

    Raises:
        ValueError: If paper directory is not found
    """
    paper_dir = _resolve_paper_dir(paper_name)
    if not paper_dir:
        raise ValueError(f"Paper '{paper_name}' not found")

    chat_file = paper_dir / "chat_history.json"

    # Return empty history if file doesn't exist
    if not chat_file.exists():
        return ChatHistory(paper_name=paper_name)

    # Load existing history
    try:
        with open(chat_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return ChatHistory(**data)
    except (json.JSONDecodeError, Exception) as e:
        # Corrupted file - log and return empty history
        print(f"Warning: Failed to load chat history for '{paper_name}': {e}")
        return ChatHistory(paper_name=paper_name)


def save_chat_history(history: ChatHistory) -> None:
    """Save chat history to paper directory.

    Args:
        history: ChatHistory object to save

    Raises:
        ValueError: If paper directory is not found
    """
    paper_dir = _resolve_paper_dir(history.paper_name)
    if not paper_dir:
        raise ValueError(f"Paper '{history.paper_name}' not found")

    chat_file = paper_dir / "chat_history.json"

    # Update timestamp
    history.updated_at = datetime.now()

    # Limit history size to prevent unbounded growth
    MAX_MESSAGES = 100
    if len(history.messages) > MAX_MESSAGES:
        # Keep only the most recent messages
        history.messages = history.messages[-MAX_MESSAGES:]

    # Save to JSON
    try:
        with open(chat_file, "w", encoding="utf-8") as f:
            # Use model_dump() for Pydantic v2, dict() for v1
            try:
                data = history.model_dump()
            except AttributeError:
                data = history.dict()

            # Custom JSON encoder for datetime
            def default_encoder(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

            json.dump(data, f, indent=2, default=default_encoder, ensure_ascii=False)
    except Exception as e:
        print(f"Error: Failed to save chat history for '{history.paper_name}': {e}")
        raise


def clear_chat_history(paper_name: str) -> bool:
    """Delete all chat history for a paper.

    Args:
        paper_name: Unique paper identifier (folder name)

    Returns:
        True if history was deleted, False if file didn't exist or paper not found
    """
    paper_dir = _resolve_paper_dir(paper_name)
    if not paper_dir:
        return False

    chat_file = paper_dir / "chat_history.json"

    if chat_file.exists():
        try:
            chat_file.unlink()
            return True
        except Exception as e:
            print(f"Error: Failed to delete chat history for '{paper_name}': {e}")
            return False

    return False


def get_or_create_chunks(paper_name: str) -> List[ChatChunk]:
    """Load pre-chunked markdown or generate on-demand.

    Chunks are cached in chat_chunks.json for performance.
    Prefers Korean markdown (_ko.md) over English (.md).

    Args:
        paper_name: Unique paper identifier (folder name)

    Returns:
        List of ChatChunk objects

    Raises:
        ValueError: If paper not found or no markdown file exists
    """
    from .rag import chunk_markdown  # Import here to avoid circular dependency

    paper_dir = _resolve_paper_dir(paper_name)
    if not paper_dir:
        raise ValueError(f"Paper '{paper_name}' not found")

    # Check cache
    cache_file = paper_dir / "chat_chunks.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [ChatChunk(**chunk) for chunk in data]
        except Exception as e:
            # Cache invalid - regenerate
            print(f"Warning: Invalid chunk cache for '{paper_name}': {e}")

    # Find markdown file (prefer Korean)
    md_ko_file = None
    md_en_file = None

    for f in paper_dir.iterdir():
        if f.suffix == ".md":
            if f.name.endswith("_ko.md"):
                md_ko_file = f
            else:
                md_en_file = f

    md_file = md_ko_file or md_en_file

    if not md_file:
        raise ValueError(f"No markdown file found for paper '{paper_name}'")

    # Generate chunks
    print(f"Generating chunks for '{paper_name}' from {md_file.name}...")
    chunks = chunk_markdown(md_file)

    # Cache for next time
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            # Convert chunks to dicts
            try:
                chunk_dicts = [chunk.model_dump() for chunk in chunks]
            except AttributeError:
                chunk_dicts = [chunk.dict() for chunk in chunks]

            json.dump(chunk_dicts, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Failed to cache chunks for '{paper_name}': {e}")
        # Continue anyway - chunks were generated successfully

    return chunks
