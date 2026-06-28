"""
Vault Graph API Schemas

Pydantic models for request/response validation.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


# =============================================================================
# Health & System
# =============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    database: str
    graph_schema: str
    version: str
    node_count: Optional[int] = None
    edge_count: Optional[int] = None


# =============================================================================
# Graph API
# =============================================================================

class GraphNode(BaseModel):
    """A node in the graph."""
    id: str
    node_type: str  # 'memory' or 'document'
    label: str
    workspace_id: str
    workspace_slug: str
    tags: List[str] = []
    importance: Optional[int] = None
    memory_type: Optional[str] = None
    document_title: Optional[str] = None
    has_file: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GraphEdge(BaseModel):
    """An edge connecting two nodes."""
    source: str
    target: str
    edge_type: str  # semantic, tag, document_memory, project
    weight: float

    class Config:
        from_attributes = True


class GraphResponse(BaseModel):
    """Full graph topology response."""
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    workspace_filter: Optional[List[str]] = None
    total_nodes: int
    total_edges: int
    cached_at: Optional[datetime] = None


class GraphFilters(BaseModel):
    """Query parameters for graph filtering."""
    workspaces: Optional[List[str]] = Field(
        default=None,
        description="Filter by workspace slugs"
    )
    node_types: Optional[List[str]] = Field(
        default=None,
        description="Filter by node types (memory, document)"
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Filter by tags (any match)"
    )
    min_importance: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Minimum importance for memories"
    )
    edge_types: Optional[List[str]] = Field(
        default=None,
        description="Filter by edge types"
    )


# =============================================================================
# Node API
# =============================================================================

class RelatedNode(BaseModel):
    """A related node with edge info."""
    node: GraphNode
    edge_type: str
    weight: float


class NodeDetailResponse(BaseModel):
    """Full node details including content."""
    id: str
    node_type: str
    label: str
    workspace_id: str
    workspace_slug: str

    # Full content
    content: str
    content_preview: str

    # Metadata
    tags: List[str] = []
    importance: Optional[int] = None
    memory_type: Optional[str] = None
    source_tool: Optional[str] = None
    source_machine: Optional[str] = None

    # Document-specific
    document_title: Optional[str] = None
    has_file: bool = False
    download_url: Optional[str] = None
    total_chunks: Optional[int] = None

    # Related nodes
    related: List[RelatedNode] = []

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# =============================================================================
# Search API
# =============================================================================

class SearchResult(BaseModel):
    """A search result."""
    id: str
    node_type: str
    label: str
    content_preview: str
    workspace_slug: str
    tags: List[str] = []
    similarity: float

    # For documents
    document_title: Optional[str] = None
    chunk_index: Optional[int] = None


class SearchResponse(BaseModel):
    """Search results response."""
    query: str
    results: List[SearchResult]
    total: int
    workspace_filter: Optional[List[str]] = None


# =============================================================================
# Rebuild API
# =============================================================================

class RebuildRequest(BaseModel):
    """Request to rebuild the graph."""
    workspace_slugs: Optional[List[str]] = Field(
        default=None,
        description="Limit rebuild to specific workspaces"
    )
    jaccard_threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum Jaccard similarity for tag edges (default 0.5)"
    )
    similarity_threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity for semantic edges (default 0.7)"
    )
    max_edges_per_node: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description="Maximum edges per node (default 5)"
    )
    skip_semantic_edges: Optional[bool] = Field(
        default=False,
        description="Skip slow semantic edge computation"
    )


class RebuildResponse(BaseModel):
    """Response for rebuild job creation."""
    build_id: str
    status: str
    message: str


class RebuildStatusResponse(BaseModel):
    """Status of a rebuild job."""
    build_id: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    nodes_processed: int = 0
    edges_created: int = 0
    error_message: Optional[str] = None


# =============================================================================
# Workspace List
# =============================================================================

class WorkspaceSummary(BaseModel):
    """Summary of a workspace."""
    id: str
    slug: str
    name: str
    workspace_type: str
    memory_count: int = 0
    document_count: int = 0


class WorkspaceListResponse(BaseModel):
    """List of workspaces."""
    workspaces: List[WorkspaceSummary]
    total: int
