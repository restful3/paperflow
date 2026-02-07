"""Chat-related data models for per-paper chatbot functionality."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional


class ChatMessage(BaseModel):
    """Single chat message in a conversation.

    Attributes:
        role: Message sender - "user" or "assistant"
        content: Message text content
        timestamp: When the message was created (ISO 8601 format)
        sources: Optional list of paper sections cited in assistant responses
    """
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    sources: Optional[List[dict]] = None
    web_sources: Optional[List[dict]] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ChatHistory(BaseModel):
    """Complete chat history for a single paper.

    Attributes:
        paper_name: Unique identifier for the paper (folder name)
        messages: List of all messages in chronological order
        created_at: When the first message was sent
        updated_at: When the last message was sent
    """
    paper_name: str
    messages: List[ChatMessage] = []
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ChatRequest(BaseModel):
    """Request payload for sending a chat message.

    Attributes:
        message: User's question/message
        paper_name: Unique identifier for the paper being discussed
    """
    message: str
    paper_name: str


class ChatChunk(BaseModel):
    """A chunk of markdown content from a paper for RAG retrieval.

    Attributes:
        index: Sequential chunk number (0-indexed)
        content: The actual text content of this chunk
        heading: Section heading if this chunk starts a new section
        start_line: Starting line number in the original markdown file
        end_line: Ending line number in the original markdown file
    """
    index: int
    content: str
    heading: Optional[str] = None
    start_line: int
    end_line: int
