"""
AI Query Memory Model - Stores user-approved question→SQL pairs for reuse.

When the LLM fails and ChatGPT proposes SQL, the user can approve it.
That question + SQL pair is stored here. Future similar questions reuse the stored query.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from ..database import Base


class AiQueryMemory(Base):
    """
    Stores user-approved question→SQL pairs for AI SQL generation.

    Flow:
    1. User asks question
    2. LLM fails to generate SQL
    3. ChatGPT (OpenAI) proposes SQL
    4. User approves
    5. Store (question_pattern, sql_query) here
    6. Next time similar question → reuse stored SQL
    """
    __tablename__ = "ai_query_memory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(Integer, nullable=False, index=True)

    # The question pattern that triggered this (normalized for matching)
    question_pattern = Column(String(500), nullable=False, index=True)
    # Original question as approved (for display)
    original_question = Column(Text, nullable=True)

    # The approved SQL query
    sql_query = Column(Text, nullable=False)
    # Tables used (for validation and hints)
    tables_used = Column(JSONB, nullable=True)  # e.g. ["VBRP", "VBRK", "MAKT"]

    # Source: "chatgpt" (OpenAI fallback), "user" (manually added)
    source = Column(String(50), default="chatgpt", nullable=False)
    # Model that generated it (e.g. gpt-4o)
    model_used = Column(String(100), nullable=True)

    # Usage tracking
    use_count = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_by_user_id = Column(Integer, nullable=False)

    def mark_used(self):
        self.use_count += 1
        self.last_used_at = datetime.utcnow()

    __table_args__ = (
        Index("idx_ai_query_memory_user_pattern", "user_id", "question_pattern"),
    )

    def mark_used(self):
        self.use_count += 1
        self.last_used_at = datetime.utcnow()
