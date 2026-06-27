"""
Vault Graph Database Models and Connection

This module defines:
1. Read-only access to Context Vault tables (memories, documents, workspaces)
2. App-owned vault_graph schema tables (edges, builds, node_cache)
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from decimal import Decimal
import json

from sqlalchemy import (
    Column, String, Text, Boolean, Integer, DateTime,
    ForeignKey, Index, text, ARRAY, Float, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector
import enum

from config import get_settings

settings = get_settings()

# Create async engine (read-only for CV tables, read-write for vault_graph schema)
engine = create_async_engine(
    settings.database_url_async,
    echo=False,
    pool_pre_ping=True
)

# Session factory
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# =============================================================================
# Context Vault Tables (Read-Only Access)
# These mirror the CV schema but are only used for SELECT queries
# =============================================================================

class Workspace(Base):
    """Read-only view of Context Vault workspaces."""
    __tablename__ = "workspaces"

    id = Column(PGUUID, primary_key=True)
    owner = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    workspace_type = Column(String(50), nullable=False)
    description = Column(Text)
    meta_data = Column(JSONB, default={})
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class Memory(Base):
    """Read-only view of Context Vault memories."""
    __tablename__ = "memories"

    id = Column(PGUUID, primary_key=True)
    workspace_id = Column(PGUUID, ForeignKey("workspaces.id"), nullable=False)
    project_id = Column(PGUUID)
    document_id = Column(PGUUID)

    content = Column(Text, nullable=False)
    summary = Column(Text)
    embedding = Column(Vector(1536))

    memory_type = Column(String(50), default="general")
    importance = Column(Integer, default=5)
    tags = Column(ARRAY(Text), default=[])

    source_tool = Column(String(50))
    source_machine = Column(String(100))

    is_active = Column(Boolean, default=True)
    meta_data = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class Document(Base):
    """Read-only view of Context Vault documents."""
    __tablename__ = "documents"

    id = Column(PGUUID, primary_key=True)
    workspace_id = Column(PGUUID, ForeignKey("workspaces.id"), nullable=False)
    project_id = Column(PGUUID)

    title = Column(String(500), nullable=False)
    source_type = Column(String(50))
    original_file_path = Column(Text)
    original_url = Column(Text)
    r2_key = Column(String(500))
    content_hash = Column(String(64))
    total_chunks = Column(Integer, default=0)

    tags = Column(ARRAY(Text), default=[])
    meta_data = Column(JSONB, default={})
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class DocumentChunk(Base):
    """Read-only view of Context Vault document chunks."""
    __tablename__ = "document_chunks"

    id = Column(PGUUID, primary_key=True)
    document_id = Column(PGUUID, ForeignKey("documents.id"), nullable=False)

    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536))

    chunk_index = Column(Integer, nullable=False)
    start_char = Column(Integer)
    end_char = Column(Integer)

    is_active = Column(Boolean, default=True)
    meta_data = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True))


# =============================================================================
# Vault Graph Schema (App-Owned)
# These tables are created and managed by this application
# =============================================================================

class EdgeType(enum.Enum):
    """Types of edges in the graph."""
    SEMANTIC = "semantic"  # Based on embedding similarity
    TAG = "tag"  # Based on shared tags (Jaccard)
    DOCUMENT_MEMORY = "document_memory"  # Memory linked to document
    PROJECT = "project"  # Same project relationship


class BuildStatus(enum.Enum):
    """Status of a graph build job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GraphBuild(Base):
    """Tracks graph rebuild jobs."""
    __tablename__ = "graph_builds"
    __table_args__ = {"schema": "vault_graph"}

    id = Column(PGUUID, primary_key=True, server_default=text("gen_random_uuid()"))

    status = Column(String(20), nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Statistics
    nodes_processed = Column(Integer, default=0)
    edges_created = Column(Integer, default=0)

    # Workspace filter (null = all workspaces)
    workspace_id = Column(PGUUID)

    # Error info
    error_message = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))


class GraphEdge(Base):
    """Precomputed edges between nodes."""
    __tablename__ = "graph_edges"
    __table_args__ = (
        Index('ix_graph_edges_source', 'source_id'),
        Index('ix_graph_edges_target', 'target_id'),
        Index('ix_graph_edges_edge_type', 'edge_type'),
        Index('ix_graph_edges_workspace', 'workspace_id'),
        {"schema": "vault_graph"}
    )

    id = Column(PGUUID, primary_key=True, server_default=text("gen_random_uuid()"))

    # Source node
    source_id = Column(PGUUID, nullable=False)
    source_type = Column(String(20), nullable=False)  # 'memory' or 'document'

    # Target node
    target_id = Column(PGUUID, nullable=False)
    target_type = Column(String(20), nullable=False)

    # Edge metadata
    edge_type = Column(String(30), nullable=False)  # semantic, tag, document_memory, project
    weight = Column(Float, nullable=False)  # 0.0 to 1.0

    # Workspace for filtering
    workspace_id = Column(PGUUID, nullable=False)

    # Build reference
    build_id = Column(PGUUID, ForeignKey("vault_graph.graph_builds.id", ondelete="CASCADE"))

    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))


class NodeCache(Base):
    """Cached node metadata for fast graph loading."""
    __tablename__ = "node_cache"
    __table_args__ = (
        Index('ix_node_cache_node_id', 'node_id'),
        Index('ix_node_cache_workspace', 'workspace_id'),
        Index('ix_node_cache_node_type', 'node_type'),
        {"schema": "vault_graph"}
    )

    id = Column(PGUUID, primary_key=True, server_default=text("gen_random_uuid()"))

    # Node reference
    node_id = Column(PGUUID, nullable=False, unique=True)
    node_type = Column(String(20), nullable=False)  # 'memory' or 'document'

    # Cached metadata
    workspace_id = Column(PGUUID, nullable=False)
    workspace_slug = Column(String(100), nullable=False)

    label = Column(String(200), nullable=False)  # Display label
    content_preview = Column(String(500))  # First ~500 chars

    tags = Column(ARRAY(Text), default=[])
    importance = Column(Integer)  # For memories
    memory_type = Column(String(50))  # For memories

    # Document-specific
    document_title = Column(String(500))
    has_file = Column(Boolean, default=False)

    # Metadata
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), server_default=text("NOW()"))


# Dependency for FastAPI
async def get_db():
    """Get database session dependency for FastAPI."""
    async with async_session() as session:
        yield session
