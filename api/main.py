"""
Vault Graph API - Main Application

Interactive graph visualization and JSON API for Context Vault memories and documents.
This is a READ-ONLY service that connects to Context Vault's Neon database.
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
import logging

from fastapi import FastAPI, HTTPException, Depends, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from contextlib import asynccontextmanager
import os

from config import get_settings
from database import (
    get_db, Workspace, Memory, Document, DocumentChunk,
    GraphBuild, GraphEdge, NodeCache
)
from schemas import (
    HealthResponse, GraphResponse, GraphNode, GraphFilters,
    NodeDetailResponse, RelatedNode,
    SearchResponse, SearchResult,
    RebuildRequest, RebuildResponse, RebuildStatusResponse,
    WorkspaceListResponse, WorkspaceSummary
)
from services import GraphService, SearchService, NodeService
from storage import get_storage


settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Vault Graph API starting up...")
    # Ensure vault_graph schema exists
    from database import engine
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS vault_graph"))
        # Create tables if they don't exist
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS vault_graph.graph_builds (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                nodes_processed INTEGER DEFAULT 0,
                edges_created INTEGER DEFAULT 0,
                workspace_id UUID,
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS vault_graph.graph_edges (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                source_id UUID NOT NULL,
                source_type VARCHAR(20) NOT NULL,
                target_id UUID NOT NULL,
                target_type VARCHAR(20) NOT NULL,
                edge_type VARCHAR(30) NOT NULL,
                weight FLOAT NOT NULL,
                workspace_id UUID NOT NULL,
                build_id UUID REFERENCES vault_graph.graph_builds(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS vault_graph.node_cache (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                node_id UUID NOT NULL UNIQUE,
                node_type VARCHAR(20) NOT NULL,
                workspace_id UUID NOT NULL,
                workspace_slug VARCHAR(100) NOT NULL,
                label VARCHAR(200) NOT NULL,
                content_preview VARCHAR(500),
                tags TEXT[],
                importance INTEGER,
                memory_type VARCHAR(50),
                document_title VARCHAR(500),
                has_file BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        # Create indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_graph_edges_source ON vault_graph.graph_edges(source_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_graph_edges_target ON vault_graph.graph_edges(target_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_graph_edges_workspace ON vault_graph.graph_edges(workspace_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_node_cache_node_id ON vault_graph.node_cache(node_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_node_cache_workspace ON vault_graph.node_cache(workspace_id)
        """))
    logger.info("Database schema initialized")
    yield
    logger.info("Vault Graph API shutting down...")


# Create FastAPI app
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="Interactive graph visualization for Context Vault memories and documents",
    lifespan=lifespan
)

# CORS Configuration
allowed_origins = settings.allowed_origins.split(",") if settings.allowed_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Authentication
# =============================================================================

def get_valid_api_keys() -> List[str]:
    """Get list of valid API keys."""
    if not settings.api_key:
        return []
    return [key.strip() for key in settings.api_key.split(",") if key.strip()]


async def verify_api_key(
    authorization: str = Header(None),
    x_api_key: str = Header(None)
):
    """Verify Bearer token or X-API-Key header."""
    if not settings.api_key:
        return True  # No auth required if not configured

    valid_keys = get_valid_api_keys()
    if not valid_keys:
        return True

    # Check Bearer token first
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
            if token in valid_keys:
                return True

    # Fall back to X-API-Key
    if x_api_key and x_api_key in valid_keys:
        return True

    logger.warning("Invalid API key attempt")
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def get_owner(x_owner: str = Header(default=None)) -> str:
    """Get owner from header or use default."""
    return x_owner or settings.default_owner


# =============================================================================
# Health & System
# =============================================================================

@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check with database and schema verification."""
    try:
        # Check database connection
        result = await db.execute(text("SELECT 1"))
        db_status = "connected" if result else "error"

        # Check vault_graph schema
        schema_check = await db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'vault_graph'
            )
        """))
        schema_exists = schema_check.scalar()

        # Get counts
        node_count = None
        edge_count = None
        if schema_exists:
            node_result = await db.execute(text("SELECT COUNT(*) FROM vault_graph.node_cache"))
            node_count = node_result.scalar()
            edge_result = await db.execute(text("SELECT COUNT(*) FROM vault_graph.graph_edges"))
            edge_count = edge_result.scalar()

        return HealthResponse(
            status="healthy",
            database=db_status,
            graph_schema="ready" if schema_exists else "missing",
            version=settings.api_version,
            node_count=node_count,
            edge_count=edge_count
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            database="error",
            graph_schema="unknown",
            version=settings.api_version
        )


# =============================================================================
# Graph API
# =============================================================================

@app.get("/api/graph", response_model=GraphResponse, tags=["Graph"])
async def get_graph(
    workspaces: Optional[str] = Query(None, description="Comma-separated workspace slugs"),
    node_types: Optional[str] = Query(None, description="Comma-separated node types"),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    min_importance: Optional[int] = Query(None, ge=1, le=10),
    edge_types: Optional[str] = Query(None, description="Comma-separated edge types"),
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
    _auth: bool = Depends(verify_api_key)
):
    """Get the graph topology with optional filtering."""
    # Parse comma-separated params
    workspace_list = workspaces.split(",") if workspaces else None
    node_type_list = node_types.split(",") if node_types else None
    tag_list = tags.split(",") if tags else None
    edge_type_list = edge_types.split(",") if edge_types else None

    graph_service = GraphService(db, owner)
    return await graph_service.get_graph(
        workspaces=workspace_list,
        node_types=node_type_list,
        tags=tag_list,
        min_importance=min_importance,
        edge_types=edge_type_list
    )


# =============================================================================
# Node API
# =============================================================================

@app.get("/api/node/{node_id}", response_model=NodeDetailResponse, tags=["Node"])
async def get_node(
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
    _auth: bool = Depends(verify_api_key)
):
    """Get full node details including content and related nodes."""
    node_service = NodeService(db, owner)
    result = await node_service.get_node_detail(node_id)
    if not result:
        raise HTTPException(status_code=404, detail="Node not found")
    return result


# =============================================================================
# Search API
# =============================================================================

@app.get("/api/search", response_model=SearchResponse, tags=["Search"])
async def search(
    query: str = Query(..., min_length=1, description="Search query"),
    workspaces: Optional[str] = Query(None, description="Comma-separated workspace slugs"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
    _auth: bool = Depends(verify_api_key)
):
    """Semantic search across memories and documents."""
    workspace_list = workspaces.split(",") if workspaces else None

    search_service = SearchService(db, owner)
    return await search_service.search(
        query=query,
        workspaces=workspace_list,
        limit=limit
    )


# =============================================================================
# Rebuild API
# =============================================================================

@app.post("/api/rebuild", response_model=RebuildResponse, tags=["Build"])
async def trigger_rebuild(
    request: RebuildRequest = None,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
    _auth: bool = Depends(verify_api_key)
):
    """Trigger a graph rebuild."""
    graph_service = GraphService(db, owner)
    build_id = await graph_service.trigger_rebuild(
        workspace_slugs=request.workspace_slugs if request else None
    )
    return RebuildResponse(
        build_id=str(build_id),
        status="pending",
        message="Graph rebuild job created"
    )


@app.get("/api/rebuild/{build_id}/status", response_model=RebuildStatusResponse, tags=["Build"])
async def get_rebuild_status(
    build_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_api_key)
):
    """Get the status of a rebuild job."""
    result = await db.execute(
        select(GraphBuild).where(GraphBuild.id == build_id)
    )
    build = result.scalar_one_or_none()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    return RebuildStatusResponse(
        build_id=str(build.id),
        status=build.status,
        started_at=build.started_at,
        completed_at=build.completed_at,
        nodes_processed=build.nodes_processed or 0,
        edges_created=build.edges_created or 0,
        error_message=build.error_message
    )


# =============================================================================
# Workspace API
# =============================================================================

@app.get("/api/workspaces", response_model=WorkspaceListResponse, tags=["Workspace"])
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
    _auth: bool = Depends(verify_api_key)
):
    """List all workspaces with counts."""
    # Get workspaces
    result = await db.execute(
        select(Workspace).where(
            Workspace.owner == owner,
            Workspace.is_active == True
        )
    )
    workspaces = result.scalars().all()

    summaries = []
    for ws in workspaces:
        # Count memories
        mem_result = await db.execute(
            select(func.count(Memory.id)).where(
                Memory.workspace_id == ws.id,
                Memory.is_active == True
            )
        )
        memory_count = mem_result.scalar() or 0

        # Count documents
        doc_result = await db.execute(
            select(func.count(Document.id)).where(
                Document.workspace_id == ws.id,
                Document.is_active == True
            )
        )
        document_count = doc_result.scalar() or 0

        summaries.append(WorkspaceSummary(
            id=str(ws.id),
            slug=ws.slug,
            name=ws.name,
            workspace_type=ws.workspace_type,
            memory_count=memory_count,
            document_count=document_count
        ))

    return WorkspaceListResponse(
        workspaces=summaries,
        total=len(summaries)
    )


# =============================================================================
# Static Files (Frontend)
# =============================================================================

# Mount static files for frontend if dist exists
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/", response_class=FileResponse)
    async def serve_frontend():
        """Serve the frontend SPA."""
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    @app.get("/{path:path}")
    async def serve_frontend_routes(path: str):
        """Catch-all for SPA routing."""
        # Check if it's an API route
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        # Check if file exists in dist
        file_path = os.path.join(frontend_dist, path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)

        # Default to index.html for SPA routing
        return FileResponse(os.path.join(frontend_dist, "index.html"))
