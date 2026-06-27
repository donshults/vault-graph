"""
Vault Graph Services

Business logic for graph operations, search, and node retrieval.
"""
from typing import List, Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone
import logging
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, and_, or_

from database import (
    Workspace, Memory, Document, DocumentChunk,
    GraphBuild, GraphEdge, NodeCache
)
from schemas import (
    GraphResponse, GraphNode, GraphEdge as GraphEdgeSchema,
    NodeDetailResponse, RelatedNode,
    SearchResponse, SearchResult
)
from config import get_settings
from storage import get_storage

settings = get_settings()
logger = logging.getLogger(__name__)


# =============================================================================
# Embeddings
# =============================================================================

async def get_embedding(text: str) -> Optional[List[float]]:
    """Get embedding vector for text using OpenAI."""
    if not settings.openai_api_key:
        logger.warning("OpenAI API key not configured")
        return None

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to get embedding: {e}")
        return None


# =============================================================================
# Graph Service
# =============================================================================

class GraphService:
    """Service for graph operations."""

    def __init__(self, db: AsyncSession, owner: str):
        self.db = db
        self.owner = owner

    async def get_graph(
        self,
        workspaces: Optional[List[str]] = None,
        node_types: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        min_importance: Optional[int] = None,
        edge_types: Optional[List[str]] = None
    ) -> GraphResponse:
        """Get graph topology with optional filtering."""
        # Get workspace IDs for filtering
        workspace_ids = []
        if workspaces:
            result = await self.db.execute(
                select(Workspace.id, Workspace.slug).where(
                    Workspace.owner == self.owner,
                    Workspace.slug.in_(workspaces),
                    Workspace.is_active == True
                )
            )
            workspace_ids = [row.id for row in result.fetchall()]
        else:
            # Get all owner's workspaces
            result = await self.db.execute(
                select(Workspace.id).where(
                    Workspace.owner == self.owner,
                    Workspace.is_active == True
                )
            )
            workspace_ids = [row.id for row in result.fetchall()]

        if not workspace_ids:
            return GraphResponse(
                nodes=[],
                edges=[],
                workspace_filter=workspaces,
                total_nodes=0,
                total_edges=0
            )

        # Build node query
        node_query = select(NodeCache).where(
            NodeCache.workspace_id.in_(workspace_ids)
        )

        if node_types:
            node_query = node_query.where(NodeCache.node_type.in_(node_types))

        if tags:
            # Any tag matches
            node_query = node_query.where(NodeCache.tags.overlap(tags))

        if min_importance is not None:
            # Only filter memories by importance
            node_query = node_query.where(
                or_(
                    NodeCache.node_type != 'memory',
                    NodeCache.importance >= min_importance
                )
            )

        result = await self.db.execute(node_query)
        node_rows = result.scalars().all()

        # Convert to response format
        nodes = []
        node_ids = set()
        for row in node_rows:
            node_ids.add(row.node_id)
            nodes.append(GraphNode(
                id=str(row.node_id),
                node_type=row.node_type,
                label=row.label,
                workspace_id=str(row.workspace_id),
                workspace_slug=row.workspace_slug,
                tags=row.tags or [],
                importance=row.importance,
                memory_type=row.memory_type,
                document_title=row.document_title,
                has_file=row.has_file or False,
                created_at=row.created_at
            ))

        # Get edges between these nodes
        edge_query = select(GraphEdge).where(
            GraphEdge.source_id.in_(node_ids),
            GraphEdge.target_id.in_(node_ids)
        )

        if edge_types:
            edge_query = edge_query.where(GraphEdge.edge_type.in_(edge_types))

        result = await self.db.execute(edge_query)
        edge_rows = result.scalars().all()

        edges = [
            GraphEdgeSchema(
                source=str(row.source_id),
                target=str(row.target_id),
                edge_type=row.edge_type,
                weight=row.weight
            )
            for row in edge_rows
        ]

        return GraphResponse(
            nodes=nodes,
            edges=edges,
            workspace_filter=workspaces,
            total_nodes=len(nodes),
            total_edges=len(edges)
        )

    async def trigger_rebuild(
        self,
        workspace_slugs: Optional[List[str]] = None
    ) -> UUID:
        """Trigger a graph rebuild job."""
        # Create build record
        workspace_id = None
        if workspace_slugs and len(workspace_slugs) == 1:
            result = await self.db.execute(
                select(Workspace.id).where(
                    Workspace.owner == self.owner,
                    Workspace.slug == workspace_slugs[0]
                )
            )
            row = result.first()
            if row:
                workspace_id = row.id

        # Insert build job
        build_result = await self.db.execute(
            text("""
                INSERT INTO vault_graph.graph_builds (status, workspace_id)
                VALUES ('pending', :workspace_id)
                RETURNING id
            """),
            {"workspace_id": workspace_id}
        )
        build_id = build_result.scalar()
        await self.db.commit()

        # Run rebuild in background
        asyncio.create_task(self._run_rebuild(build_id, workspace_slugs))

        return build_id

    async def _run_rebuild(
        self,
        build_id: UUID,
        workspace_slugs: Optional[List[str]] = None
    ):
        """Run the actual rebuild process."""
        from database import async_session

        async with async_session() as db:
            try:
                # Update status to running
                await db.execute(
                    text("""
                        UPDATE vault_graph.graph_builds
                        SET status = 'running', started_at = NOW()
                        WHERE id = :build_id
                    """),
                    {"build_id": build_id}
                )
                await db.commit()

                # Get workspace IDs
                if workspace_slugs:
                    result = await db.execute(
                        select(Workspace).where(
                            Workspace.owner == self.owner,
                            Workspace.slug.in_(workspace_slugs),
                            Workspace.is_active == True
                        )
                    )
                else:
                    result = await db.execute(
                        select(Workspace).where(
                            Workspace.owner == self.owner,
                            Workspace.is_active == True
                        )
                    )
                workspaces = result.scalars().all()
                workspace_map = {ws.id: ws.slug for ws in workspaces}
                workspace_ids = list(workspace_map.keys())

                # Clear old edges and cache for these workspaces
                await db.execute(
                    text("""
                        DELETE FROM vault_graph.graph_edges
                        WHERE workspace_id = ANY(:workspace_ids)
                    """),
                    {"workspace_ids": workspace_ids}
                )
                await db.execute(
                    text("""
                        DELETE FROM vault_graph.node_cache
                        WHERE workspace_id = ANY(:workspace_ids)
                    """),
                    {"workspace_ids": workspace_ids}
                )
                await db.commit()

                nodes_processed = 0
                edges_created = 0

                # Process memories
                result = await db.execute(
                    select(Memory).where(
                        Memory.workspace_id.in_(workspace_ids),
                        Memory.is_active == True
                    )
                )
                memories = result.scalars().all()

                for memory in memories:
                    # Cache node
                    label = (memory.content[:100] + "...") if len(memory.content) > 100 else memory.content
                    await db.execute(
                        text("""
                            INSERT INTO vault_graph.node_cache
                            (node_id, node_type, workspace_id, workspace_slug, label,
                             content_preview, tags, importance, memory_type, created_at)
                            VALUES (:node_id, 'memory', :workspace_id, :workspace_slug, :label,
                                    :preview, :tags, :importance, :memory_type, :created_at)
                            ON CONFLICT (node_id) DO UPDATE SET
                                label = EXCLUDED.label,
                                content_preview = EXCLUDED.content_preview,
                                tags = EXCLUDED.tags,
                                importance = EXCLUDED.importance,
                                updated_at = NOW()
                        """),
                        {
                            "node_id": memory.id,
                            "workspace_id": memory.workspace_id,
                            "workspace_slug": workspace_map.get(memory.workspace_id, "unknown"),
                            "label": label,
                            "preview": memory.content[:500],
                            "tags": memory.tags or [],
                            "importance": memory.importance,
                            "memory_type": memory.memory_type,
                            "created_at": memory.created_at
                        }
                    )
                    nodes_processed += 1

                # Process documents
                result = await db.execute(
                    select(Document).where(
                        Document.workspace_id.in_(workspace_ids),
                        Document.is_active == True
                    )
                )
                documents = result.scalars().all()

                for doc in documents:
                    # Get first chunk for preview
                    chunk_result = await db.execute(
                        select(DocumentChunk.content).where(
                            DocumentChunk.document_id == doc.id,
                            DocumentChunk.is_active == True
                        ).order_by(DocumentChunk.chunk_index).limit(1)
                    )
                    first_chunk = chunk_result.scalar()
                    preview = first_chunk[:500] if first_chunk else ""

                    await db.execute(
                        text("""
                            INSERT INTO vault_graph.node_cache
                            (node_id, node_type, workspace_id, workspace_slug, label,
                             content_preview, tags, document_title, has_file, created_at)
                            VALUES (:node_id, 'document', :workspace_id, :workspace_slug, :label,
                                    :preview, :tags, :doc_title, :has_file, :created_at)
                            ON CONFLICT (node_id) DO UPDATE SET
                                label = EXCLUDED.label,
                                content_preview = EXCLUDED.content_preview,
                                tags = EXCLUDED.tags,
                                document_title = EXCLUDED.document_title,
                                has_file = EXCLUDED.has_file,
                                updated_at = NOW()
                        """),
                        {
                            "node_id": doc.id,
                            "workspace_id": doc.workspace_id,
                            "workspace_slug": workspace_map.get(doc.workspace_id, "unknown"),
                            "label": doc.title[:100] if len(doc.title) > 100 else doc.title,
                            "preview": preview,
                            "tags": doc.tags or [],
                            "doc_title": doc.title,
                            "has_file": bool(doc.r2_key),
                            "created_at": doc.created_at
                        }
                    )
                    nodes_processed += 1

                await db.commit()

                # Compute tag-based edges (Jaccard similarity)
                edges_created += await self._compute_tag_edges(db, workspace_ids, build_id)

                # Compute semantic edges (kNN)
                edges_created += await self._compute_semantic_edges(db, workspace_ids, build_id)

                # Compute document-memory edges
                edges_created += await self._compute_doc_memory_edges(db, workspace_ids, build_id)

                # Update build status
                await db.execute(
                    text("""
                        UPDATE vault_graph.graph_builds
                        SET status = 'completed',
                            completed_at = NOW(),
                            nodes_processed = :nodes,
                            edges_created = :edges
                        WHERE id = :build_id
                    """),
                    {
                        "build_id": build_id,
                        "nodes": nodes_processed,
                        "edges": edges_created
                    }
                )
                await db.commit()

                logger.info(f"Build {build_id} completed: {nodes_processed} nodes, {edges_created} edges")

            except Exception as e:
                logger.error(f"Build {build_id} failed: {e}")
                await db.execute(
                    text("""
                        UPDATE vault_graph.graph_builds
                        SET status = 'failed',
                            completed_at = NOW(),
                            error_message = :error
                        WHERE id = :build_id
                    """),
                    {"build_id": build_id, "error": str(e)}
                )
                await db.commit()

    async def _compute_tag_edges(
        self,
        db: AsyncSession,
        workspace_ids: List[UUID],
        build_id: UUID
    ) -> int:
        """Compute edges based on tag Jaccard similarity."""
        # Get all nodes with tags
        result = await db.execute(
            text("""
                SELECT node_id, node_type, workspace_id, tags
                FROM vault_graph.node_cache
                WHERE workspace_id = ANY(:workspace_ids)
                  AND tags IS NOT NULL
                  AND array_length(tags, 1) > 0
            """),
            {"workspace_ids": workspace_ids}
        )
        nodes = result.fetchall()

        edges_created = 0
        threshold = settings.edge_jaccard_threshold

        for i, node1 in enumerate(nodes):
            tags1 = set(node1.tags or [])
            if not tags1:
                continue

            for node2 in nodes[i + 1:]:
                # Only create edges within same workspace
                if node1.workspace_id != node2.workspace_id:
                    continue

                tags2 = set(node2.tags or [])
                if not tags2:
                    continue

                # Jaccard similarity
                intersection = len(tags1 & tags2)
                union = len(tags1 | tags2)
                if union == 0:
                    continue

                similarity = intersection / union
                if similarity >= threshold:
                    await db.execute(
                        text("""
                            INSERT INTO vault_graph.graph_edges
                            (source_id, source_type, target_id, target_type,
                             edge_type, weight, workspace_id, build_id)
                            VALUES (:source_id, :source_type, :target_id, :target_type,
                                    'tag', :weight, :workspace_id, :build_id)
                        """),
                        {
                            "source_id": node1.node_id,
                            "source_type": node1.node_type,
                            "target_id": node2.node_id,
                            "target_type": node2.node_type,
                            "weight": similarity,
                            "workspace_id": node1.workspace_id,
                            "build_id": build_id
                        }
                    )
                    edges_created += 1

        await db.commit()
        return edges_created

    async def _compute_semantic_edges(
        self,
        db: AsyncSession,
        workspace_ids: List[UUID],
        build_id: UUID
    ) -> int:
        """Compute edges based on embedding similarity (kNN)."""
        threshold = settings.edge_similarity_threshold
        max_neighbors = settings.max_knn_edges

        # Use pgvector kNN query for memories
        result = await db.execute(
            text("""
                WITH memory_pairs AS (
                    SELECT DISTINCT ON (m1.id, neighbor_rank)
                        m1.id as source_id,
                        m1.workspace_id,
                        m2.id as target_id,
                        1 - (m1.embedding <=> m2.embedding) as similarity,
                        ROW_NUMBER() OVER (PARTITION BY m1.id ORDER BY m1.embedding <=> m2.embedding) as neighbor_rank
                    FROM memories m1
                    JOIN memories m2 ON m1.id != m2.id
                        AND m1.workspace_id = m2.workspace_id
                        AND m1.workspace_id = ANY(:workspace_ids)
                        AND m1.is_active = true
                        AND m2.is_active = true
                        AND m1.embedding IS NOT NULL
                        AND m2.embedding IS NOT NULL
                )
                SELECT source_id, workspace_id, target_id, similarity
                FROM memory_pairs
                WHERE neighbor_rank <= :max_neighbors
                  AND similarity >= :threshold
            """),
            {
                "workspace_ids": workspace_ids,
                "max_neighbors": max_neighbors,
                "threshold": threshold
            }
        )
        pairs = result.fetchall()

        edges_created = 0
        for pair in pairs:
            await db.execute(
                text("""
                    INSERT INTO vault_graph.graph_edges
                    (source_id, source_type, target_id, target_type,
                     edge_type, weight, workspace_id, build_id)
                    VALUES (:source_id, 'memory', :target_id, 'memory',
                            'semantic', :weight, :workspace_id, :build_id)
                """),
                {
                    "source_id": pair.source_id,
                    "target_id": pair.target_id,
                    "weight": pair.similarity,
                    "workspace_id": pair.workspace_id,
                    "build_id": build_id
                }
            )
            edges_created += 1

        # Similar query for document chunks (connect documents)
        result = await db.execute(
            text("""
                WITH chunk_pairs AS (
                    SELECT DISTINCT ON (d1.id, d2.id)
                        d1.id as source_id,
                        d1.workspace_id,
                        d2.id as target_id,
                        MAX(1 - (dc1.embedding <=> dc2.embedding)) as max_similarity
                    FROM documents d1
                    JOIN document_chunks dc1 ON dc1.document_id = d1.id
                    JOIN documents d2 ON d1.id != d2.id AND d1.workspace_id = d2.workspace_id
                    JOIN document_chunks dc2 ON dc2.document_id = d2.id
                    WHERE d1.workspace_id = ANY(:workspace_ids)
                      AND d1.is_active = true
                      AND d2.is_active = true
                      AND dc1.is_active = true
                      AND dc2.is_active = true
                      AND dc1.embedding IS NOT NULL
                      AND dc2.embedding IS NOT NULL
                    GROUP BY d1.id, d1.workspace_id, d2.id
                    HAVING MAX(1 - (dc1.embedding <=> dc2.embedding)) >= :threshold
                )
                SELECT source_id, workspace_id, target_id, max_similarity as similarity
                FROM chunk_pairs
            """),
            {
                "workspace_ids": workspace_ids,
                "threshold": threshold
            }
        )
        doc_pairs = result.fetchall()

        for pair in doc_pairs:
            await db.execute(
                text("""
                    INSERT INTO vault_graph.graph_edges
                    (source_id, source_type, target_id, target_type,
                     edge_type, weight, workspace_id, build_id)
                    VALUES (:source_id, 'document', :target_id, 'document',
                            'semantic', :weight, :workspace_id, :build_id)
                """),
                {
                    "source_id": pair.source_id,
                    "target_id": pair.target_id,
                    "weight": pair.similarity,
                    "workspace_id": pair.workspace_id,
                    "build_id": build_id
                }
            )
            edges_created += 1

        await db.commit()
        return edges_created

    async def _compute_doc_memory_edges(
        self,
        db: AsyncSession,
        workspace_ids: List[UUID],
        build_id: UUID
    ) -> int:
        """Compute edges between memories and their source documents."""
        result = await db.execute(
            text("""
                SELECT m.id as memory_id, m.document_id, m.workspace_id
                FROM memories m
                WHERE m.document_id IS NOT NULL
                  AND m.workspace_id = ANY(:workspace_ids)
                  AND m.is_active = true
            """),
            {"workspace_ids": workspace_ids}
        )
        links = result.fetchall()

        edges_created = 0
        for link in links:
            await db.execute(
                text("""
                    INSERT INTO vault_graph.graph_edges
                    (source_id, source_type, target_id, target_type,
                     edge_type, weight, workspace_id, build_id)
                    VALUES (:memory_id, 'memory', :document_id, 'document',
                            'document_memory', 1.0, :workspace_id, :build_id)
                """),
                {
                    "memory_id": link.memory_id,
                    "document_id": link.document_id,
                    "workspace_id": link.workspace_id,
                    "build_id": build_id
                }
            )
            edges_created += 1

        await db.commit()
        return edges_created


# =============================================================================
# Node Service
# =============================================================================

class NodeService:
    """Service for retrieving node details."""

    def __init__(self, db: AsyncSession, owner: str):
        self.db = db
        self.owner = owner

    async def get_node_detail(self, node_id: UUID) -> Optional[NodeDetailResponse]:
        """Get full node details including content and related nodes."""
        # Try to find as memory first
        result = await self.db.execute(
            select(Memory, Workspace).join(
                Workspace, Memory.workspace_id == Workspace.id
            ).where(
                Memory.id == node_id,
                Memory.is_active == True,
                Workspace.owner == self.owner
            )
        )
        row = result.first()

        if row:
            memory, workspace = row
            related = await self._get_related_nodes(node_id)

            return NodeDetailResponse(
                id=str(memory.id),
                node_type="memory",
                label=(memory.content[:100] + "...") if len(memory.content) > 100 else memory.content,
                workspace_id=str(workspace.id),
                workspace_slug=workspace.slug,
                content=memory.content,
                content_preview=memory.content[:500],
                tags=memory.tags or [],
                importance=memory.importance,
                memory_type=memory.memory_type,
                source_tool=memory.source_tool,
                source_machine=memory.source_machine,
                related=related,
                created_at=memory.created_at,
                updated_at=memory.updated_at
            )

        # Try to find as document
        result = await self.db.execute(
            select(Document, Workspace).join(
                Workspace, Document.workspace_id == Workspace.id
            ).where(
                Document.id == node_id,
                Document.is_active == True,
                Workspace.owner == self.owner
            )
        )
        row = result.first()

        if row:
            doc, workspace = row

            # Get first chunk content
            chunk_result = await self.db.execute(
                select(DocumentChunk.content).where(
                    DocumentChunk.document_id == doc.id,
                    DocumentChunk.is_active == True
                ).order_by(DocumentChunk.chunk_index).limit(1)
            )
            first_chunk = chunk_result.scalar() or ""

            # Get presigned download URL if file exists
            download_url = None
            if doc.r2_key:
                storage = get_storage()
                if storage and storage.is_configured:
                    download_url = storage.generate_presigned_url(doc.r2_key)

            related = await self._get_related_nodes(node_id)

            return NodeDetailResponse(
                id=str(doc.id),
                node_type="document",
                label=doc.title[:100] if len(doc.title) > 100 else doc.title,
                workspace_id=str(workspace.id),
                workspace_slug=workspace.slug,
                content=first_chunk,
                content_preview=first_chunk[:500],
                tags=doc.tags or [],
                document_title=doc.title,
                has_file=bool(doc.r2_key),
                download_url=download_url,
                total_chunks=doc.total_chunks,
                related=related,
                created_at=doc.created_at,
                updated_at=doc.updated_at
            )

        return None

    async def _get_related_nodes(self, node_id: UUID) -> List[RelatedNode]:
        """Get nodes related to this node via edges."""
        # Get edges where this node is source or target
        result = await self.db.execute(
            text("""
                SELECT e.target_id as related_id, e.edge_type, e.weight
                FROM vault_graph.graph_edges e
                WHERE e.source_id = :node_id
                UNION
                SELECT e.source_id as related_id, e.edge_type, e.weight
                FROM vault_graph.graph_edges e
                WHERE e.target_id = :node_id
            """),
            {"node_id": node_id}
        )
        edges = result.fetchall()

        related = []
        for edge in edges:
            # Get node info from cache
            cache_result = await self.db.execute(
                select(NodeCache).where(NodeCache.node_id == edge.related_id)
            )
            cached = cache_result.scalar_one_or_none()

            if cached:
                related.append(RelatedNode(
                    node=GraphNode(
                        id=str(cached.node_id),
                        node_type=cached.node_type,
                        label=cached.label,
                        workspace_id=str(cached.workspace_id),
                        workspace_slug=cached.workspace_slug,
                        tags=cached.tags or [],
                        importance=cached.importance,
                        memory_type=cached.memory_type,
                        document_title=cached.document_title,
                        has_file=cached.has_file or False,
                        created_at=cached.created_at
                    ),
                    edge_type=edge.edge_type,
                    weight=edge.weight
                ))

        # Sort by weight descending
        related.sort(key=lambda x: x.weight, reverse=True)
        return related[:10]  # Limit to top 10


# =============================================================================
# Search Service
# =============================================================================

class SearchService:
    """Service for semantic search."""

    def __init__(self, db: AsyncSession, owner: str):
        self.db = db
        self.owner = owner

    async def search(
        self,
        query: str,
        workspaces: Optional[List[str]] = None,
        limit: int = 10
    ) -> SearchResponse:
        """Search memories and documents by semantic similarity."""
        # Get workspace IDs
        if workspaces:
            ws_result = await self.db.execute(
                select(Workspace.id, Workspace.slug).where(
                    Workspace.owner == self.owner,
                    Workspace.slug.in_(workspaces),
                    Workspace.is_active == True
                )
            )
        else:
            ws_result = await self.db.execute(
                select(Workspace.id, Workspace.slug).where(
                    Workspace.owner == self.owner,
                    Workspace.is_active == True
                )
            )
        ws_rows = ws_result.fetchall()
        workspace_ids = [row.id for row in ws_rows]
        workspace_map = {row.id: row.slug for row in ws_rows}

        if not workspace_ids:
            return SearchResponse(
                query=query,
                results=[],
                total=0,
                workspace_filter=workspaces
            )

        # Get query embedding
        query_embedding = await get_embedding(query)
        if not query_embedding:
            logger.error("Failed to get embedding for search query")
            return SearchResponse(
                query=query,
                results=[],
                total=0,
                workspace_filter=workspaces
            )

        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        min_similarity = settings.similarity_threshold

        results = []

        # Search memories
        mem_result = await self.db.execute(
            text("""
                SELECT
                    m.id,
                    m.content,
                    m.workspace_id,
                    m.tags,
                    1 - (m.embedding <=> CAST(:embedding AS vector)) as similarity
                FROM memories m
                WHERE m.workspace_id = ANY(:workspace_ids)
                  AND m.is_active = true
                  AND m.embedding IS NOT NULL
                  AND 1 - (m.embedding <=> CAST(:embedding AS vector)) >= :min_similarity
                ORDER BY m.embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
            """),
            {
                "embedding": embedding_str,
                "workspace_ids": workspace_ids,
                "min_similarity": min_similarity,
                "limit": limit
            }
        )

        for row in mem_result.fetchall():
            label = (row.content[:100] + "...") if len(row.content) > 100 else row.content
            results.append(SearchResult(
                id=str(row.id),
                node_type="memory",
                label=label,
                content_preview=row.content[:300],
                workspace_slug=workspace_map.get(row.workspace_id, "unknown"),
                tags=row.tags or [],
                similarity=row.similarity
            ))

        # Search document chunks
        doc_result = await self.db.execute(
            text("""
                SELECT
                    d.id,
                    d.title,
                    dc.content,
                    dc.chunk_index,
                    d.workspace_id,
                    d.tags,
                    1 - (dc.embedding <=> CAST(:embedding AS vector)) as similarity
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE d.workspace_id = ANY(:workspace_ids)
                  AND d.is_active = true
                  AND dc.is_active = true
                  AND dc.embedding IS NOT NULL
                  AND 1 - (dc.embedding <=> CAST(:embedding AS vector)) >= :min_similarity
                ORDER BY dc.embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
            """),
            {
                "embedding": embedding_str,
                "workspace_ids": workspace_ids,
                "min_similarity": min_similarity,
                "limit": limit
            }
        )

        for row in doc_result.fetchall():
            results.append(SearchResult(
                id=str(row.id),
                node_type="document",
                label=row.title[:100] if len(row.title) > 100 else row.title,
                content_preview=row.content[:300],
                workspace_slug=workspace_map.get(row.workspace_id, "unknown"),
                tags=row.tags or [],
                similarity=row.similarity,
                document_title=row.title,
                chunk_index=row.chunk_index
            ))

        # Sort all results by similarity
        results.sort(key=lambda x: x.similarity, reverse=True)
        results = results[:limit]

        return SearchResponse(
            query=query,
            results=results,
            total=len(results),
            workspace_filter=workspaces
        )
