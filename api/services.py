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
    SearchResponse, SearchResult,
    FolderNode, FolderTreeResponse, FolderLeavesResponse
)
from config import get_settings
from storage import get_storage

settings = get_settings()
logger = logging.getLogger(__name__)

# Strong references to in-flight rebuild tasks. asyncio only keeps a *weak*
# reference to tasks created with create_task(), so a fire-and-forget task can be
# garbage-collected mid-run — which silently kills the rebuild (build stuck in
# 'running' at 0 nodes, no exception). Holding the task here until it finishes
# prevents that. See https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_rebuild_tasks: set = set()


async def _fail_build_if_unfinished(build_id, reason: str) -> None:
    """Mark a build failed if it's still pending/running (i.e. its task died
    without finishing). No-op for builds that already reached a terminal state."""
    from database import async_session
    try:
        async with async_session() as db:
            await db.execute(
                text("""
                    UPDATE vault_graph.graph_builds
                    SET status = 'failed',
                        completed_at = NOW(),
                        error_message = COALESCE(error_message, :reason)
                    WHERE id = :build_id AND status IN ('pending', 'running')
                """),
                {"build_id": build_id, "reason": f"Rebuild task ended abnormally: {reason}"[:500]}
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to mark build {build_id} failed: {e}")


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
        edge_types: Optional[List[str]] = None,
        limit: int = 500
    ) -> GraphResponse:
        """Get graph topology with optional filtering and node limit."""
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
            # Any tag matches. NodeCache.tags is a generic ARRAY(Text) which has
            # no .overlap(); use the Postgres array-overlap operator '&&' against
            # the provided tag list cast to text[].
            node_query = node_query.where(
                text("node_cache.tags && CAST(:tag_list AS text[])").bindparams(tag_list=list(tags))
            )

        if min_importance is not None:
            # Only filter memories by importance
            node_query = node_query.where(
                or_(
                    NodeCache.node_type != 'memory',
                    NodeCache.importance >= min_importance
                )
            )

        # Order by importance/recency and apply limit
        node_query = node_query.order_by(
            NodeCache.importance.desc().nullslast(),
            NodeCache.created_at.desc().nullslast()
        ).limit(limit)

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
        workspace_slugs: Optional[List[str]] = None,
        jaccard_threshold: Optional[float] = None,
        similarity_threshold: Optional[float] = None,
        max_edges_per_node: Optional[int] = None,
        skip_semantic_edges: bool = False
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

        # Capture owner for the background task
        owner = self.owner

        # Use provided thresholds or fall back to settings
        jt = jaccard_threshold if jaccard_threshold is not None else settings.edge_jaccard_threshold
        st = similarity_threshold if similarity_threshold is not None else settings.edge_similarity_threshold
        me = max_edges_per_node if max_edges_per_node is not None else settings.max_knn_edges

        # Run rebuild in background. Keep a strong reference until the task
        # finishes, otherwise asyncio may garbage-collect it mid-run (see
        # _rebuild_tasks above). On completion, fail the build if the task ended
        # without reaching a terminal state (e.g. killed/cancelled mid-run).
        task = asyncio.create_task(self._run_rebuild(
            build_id, workspace_slugs, owner,
            jaccard_threshold=jt,
            similarity_threshold=st,
            max_edges_per_node=me,
            skip_semantic_edges=skip_semantic_edges
        ))
        _rebuild_tasks.add(task)

        def _on_done(t: "asyncio.Task") -> None:
            _rebuild_tasks.discard(t)
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                exc = RuntimeError("rebuild task was cancelled")
            if exc is not None:
                logger.error(f"Rebuild task {build_id} ended abnormally: {exc!r}")
                asyncio.create_task(_fail_build_if_unfinished(build_id, str(exc)))

        task.add_done_callback(_on_done)

        return build_id

    async def _run_rebuild(
        self,
        build_id: UUID,
        workspace_slugs: Optional[List[str]],
        owner: str,
        jaccard_threshold: float = 0.5,
        similarity_threshold: float = 0.7,
        max_edges_per_node: int = 5,
        skip_semantic_edges: bool = False
    ):
        """Run the actual rebuild process."""
        from database import async_session

        logger.info(f"Starting rebuild {build_id} for owner {owner} "
                   f"(jaccard={jaccard_threshold}, similarity={similarity_threshold}, "
                   f"max_edges={max_edges_per_node}, skip_semantic={skip_semantic_edges})")

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
                            Workspace.owner == owner,
                            Workspace.slug.in_(workspace_slugs),
                            Workspace.is_active == True
                        )
                    )
                else:
                    result = await db.execute(
                        select(Workspace).where(
                            Workspace.owner == owner,
                            Workspace.is_active == True
                        )
                    )
                workspaces = result.scalars().all()
                workspace_map = {ws.id: ws.slug for ws in workspaces}
                workspace_ids = list(workspace_map.keys())

                logger.info(f"Build {build_id}: Processing {len(workspace_ids)} workspaces")

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

                # Process memories with batch inserts
                result = await db.execute(
                    select(Memory).where(
                        Memory.workspace_id.in_(workspace_ids),
                        Memory.is_active == True
                    )
                )
                memories = result.scalars().all()
                logger.info(f"Build {build_id}: Processing {len(memories)} memories")

                memory_batch = []
                for memory in memories:
                    label = (memory.content[:100] + "...") if len(memory.content) > 100 else memory.content
                    memory_batch.append({
                        "node_id": memory.id,
                        "workspace_id": memory.workspace_id,
                        "workspace_slug": workspace_map.get(memory.workspace_id, "unknown"),
                        "label": label,
                        "preview": memory.content[:500],
                        "tags": memory.tags or [],
                        "importance": memory.importance,
                        "memory_type": memory.memory_type,
                        "created_at": memory.created_at
                    })
                    nodes_processed += 1

                    # Batch insert every 500 memories
                    if len(memory_batch) >= 500:
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
                            memory_batch
                        )
                        memory_batch = []

                # Insert remaining memories
                if memory_batch:
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
                        memory_batch
                    )

                # Process documents - fetch all first chunks in one query for efficiency
                result = await db.execute(
                    select(Document).where(
                        Document.workspace_id.in_(workspace_ids),
                        Document.is_active == True
                    )
                )
                documents = result.scalars().all()
                logger.info(f"Build {build_id}: Processing {len(documents)} documents")

                # Get all first chunks in a single query using window function
                first_chunks_result = await db.execute(
                    text("""
                        WITH ranked_chunks AS (
                            SELECT
                                document_id,
                                content,
                                ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY chunk_index) as rn
                            FROM document_chunks
                            WHERE document_id = ANY(:doc_ids)
                              AND is_active = true
                        )
                        SELECT document_id, content
                        FROM ranked_chunks
                        WHERE rn = 1
                    """),
                    {"doc_ids": [doc.id for doc in documents]}
                )
                first_chunks = {row.document_id: row.content for row in first_chunks_result.fetchall()}

                # Batch insert documents
                doc_batch = []
                for doc in documents:
                    first_chunk = first_chunks.get(doc.id, "")
                    preview = first_chunk[:500] if first_chunk else ""

                    doc_batch.append({
                        "node_id": doc.id,
                        "workspace_id": doc.workspace_id,
                        "workspace_slug": workspace_map.get(doc.workspace_id, "unknown"),
                        "label": doc.title[:100] if len(doc.title) > 100 else doc.title,
                        "preview": preview,
                        "tags": doc.tags or [],
                        "doc_title": doc.title,
                        "has_file": bool(doc.r2_key),
                        "created_at": doc.created_at
                    })
                    nodes_processed += 1

                    # Batch insert every 500 documents
                    if len(doc_batch) >= 500:
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
                            doc_batch
                        )
                        doc_batch = []

                # Insert remaining documents
                if doc_batch:
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
                        doc_batch
                    )

                await db.commit()
                logger.info(f"Build {build_id}: Cached {nodes_processed} nodes, computing edges...")

                # Compute tag-based edges (Jaccard similarity)
                edges_created += await self._compute_tag_edges(
                    db, workspace_ids, build_id,
                    threshold=jaccard_threshold,
                    max_edges_per_node=max_edges_per_node
                )

                # Compute semantic edges (kNN) - optional
                if not skip_semantic_edges:
                    edges_created += await self._compute_semantic_edges(
                        db, workspace_ids, build_id,
                        threshold=similarity_threshold,
                        max_neighbors=max_edges_per_node
                    )
                else:
                    logger.info(f"Build {build_id}: Skipping semantic edges (skip_semantic_edges=True)")

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
                logger.error(f"Build {build_id} failed: {e}", exc_info=True)
                try:
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
                except Exception as db_err:
                    logger.error(f"Failed to update build status: {db_err}")

    async def _compute_tag_edges(
        self,
        db: AsyncSession,
        workspace_ids: List[UUID],
        build_id: UUID,
        threshold: float = 0.5,
        max_edges_per_node: int = 5
    ) -> int:
        """Compute edges based on tag Jaccard similarity.

        Optimized using inverted index - only compares nodes that share tags.
        Limits edges per node to max_edges_per_node to prevent graph explosion.
        """
        from collections import defaultdict
        import heapq

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

        if not nodes:
            return 0

        logger.info(f"Computing tag edges for {len(nodes)} nodes with tags (max {max_edges_per_node} per node)")

        # Build node lookup and tag sets
        node_data = {}  # node_id -> (node_type, workspace_id, tags_set)
        for node in nodes:
            node_data[node.node_id] = (
                node.node_type,
                node.workspace_id,
                set(node.tags or [])
            )

        # Build inverted index: tag -> set of node_ids (per workspace)
        # Key: (workspace_id, tag) -> set of node_ids
        tag_index = defaultdict(set)
        for node in nodes:
            workspace_id = node.workspace_id
            for tag in (node.tags or []):
                tag_index[(workspace_id, tag)].add(node.node_id)

        # Find candidate pairs (nodes that share at least one tag)
        candidate_pairs = set()
        for (workspace_id, tag), node_ids in tag_index.items():
            node_list = list(node_ids)
            for i, id1 in enumerate(node_list):
                for id2 in node_list[i + 1:]:
                    # Use sorted tuple to avoid duplicates
                    pair = (min(id1, id2), max(id1, id2))
                    candidate_pairs.add(pair)

        logger.info(f"Found {len(candidate_pairs)} candidate pairs to evaluate (threshold={threshold})")

        # Collect all valid edges with similarity scores
        # node_edges[node_id] = list of (similarity, edge_data)
        node_edges = defaultdict(list)

        for id1, id2 in candidate_pairs:
            type1, ws1, tags1 = node_data[id1]
            type2, ws2, tags2 = node_data[id2]

            # Should already be same workspace, but verify
            if ws1 != ws2:
                continue

            # Jaccard similarity
            intersection = len(tags1 & tags2)
            union = len(tags1 | tags2)
            if union == 0:
                continue

            similarity = intersection / union
            if similarity >= threshold:
                edge_data = {
                    "source_id": id1,
                    "source_type": type1,
                    "target_id": id2,
                    "target_type": type2,
                    "weight": similarity,
                    "workspace_id": ws1,
                    "build_id": build_id
                }
                # Track for both nodes (undirected edge)
                node_edges[id1].append((similarity, id2, edge_data))
                node_edges[id2].append((similarity, id1, edge_data))

        logger.info(f"Found {sum(len(e) for e in node_edges.values()) // 2} edges above threshold, pruning to top {max_edges_per_node} per node")

        # Keep only top N edges per node
        final_edges = set()  # Use frozenset of (id1, id2) to dedupe
        for node_id, edges in node_edges.items():
            # Sort by similarity descending, take top N
            top_edges = heapq.nlargest(max_edges_per_node, edges, key=lambda x: x[0])
            for similarity, other_id, edge_data in top_edges:
                # Create canonical pair key for deduplication
                pair_key = (min(edge_data["source_id"], edge_data["target_id"]),
                           max(edge_data["source_id"], edge_data["target_id"]))
                if pair_key not in final_edges:
                    final_edges.add(pair_key)

        # Build final edge list from deduplicated pairs
        edge_batch = []
        for id1, id2 in final_edges:
            type1, ws1, tags1 = node_data[id1]
            type2, ws2, tags2 = node_data[id2]
            intersection = len(tags1 & tags2)
            union = len(tags1 | tags2)
            similarity = intersection / union

            edge_batch.append({
                "source_id": id1,
                "source_type": type1,
                "target_id": id2,
                "target_type": type2,
                "weight": similarity,
                "workspace_id": ws1,
                "build_id": build_id
            })

        # Batch insert
        edges_created = len(edge_batch)
        batch_size = 1000
        for i in range(0, len(edge_batch), batch_size):
            await self._insert_edge_batch(db, edge_batch[i:i + batch_size])

        await db.commit()
        logger.info(f"Created {edges_created} tag-based edges (pruned from {sum(len(e) for e in node_edges.values()) // 2})")
        return edges_created

    async def _insert_edge_batch(self, db: AsyncSession, edges: List[dict]):
        """Batch insert edges for better performance."""
        if not edges:
            return

        # Use executemany for batch insert
        await db.execute(
            text("""
                INSERT INTO vault_graph.graph_edges
                (source_id, source_type, target_id, target_type,
                 edge_type, weight, workspace_id, build_id)
                VALUES (:source_id, :source_type, :target_id, :target_type,
                        'tag', :weight, :workspace_id, :build_id)
            """),
            edges
        )

    async def _compute_semantic_edges(
        self,
        db: AsyncSession,
        workspace_ids: List[UUID],
        build_id: UUID,
        threshold: float = 0.7,
        max_neighbors: int = 5
    ) -> int:
        """Compute edges based on embedding similarity (kNN)."""

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
# Folder Service (tag-derived, Obsidian-style)
# =============================================================================

class FolderService:
    """Builds an Obsidian-style folder tree from node tags.

    The data has no real folder hierarchy, so 'folders' are derived from tags:
    a tag like 'project:diamond-money-press' becomes folder 'project' > tag
    'diamond-money-press'. Flat tags (no ':') and tags whose prefix is numeric
    (e.g. '12:30' timestamps) are grouped under a single '# Tags' folder.
    """

    FLAT_FOLDER = "# Tags"  # bucket for tags with no usable namespace prefix

    def __init__(self, db: AsyncSession, owner: str):
        self.db = db
        self.owner = owner

    async def _resolve_workspace_ids(self, workspaces: Optional[List[str]]) -> List[UUID]:
        """Resolve owner-scoped workspace IDs (all if none specified)."""
        if workspaces:
            result = await self.db.execute(
                select(Workspace.id).where(
                    Workspace.owner == self.owner,
                    Workspace.slug.in_(workspaces),
                    Workspace.is_active == True
                )
            )
        else:
            result = await self.db.execute(
                select(Workspace.id).where(
                    Workspace.owner == self.owner,
                    Workspace.is_active == True
                )
            )
        return [row.id for row in result.fetchall()]

    @staticmethod
    def _split_tag(tag: str) -> Tuple[str, str]:
        """Return (folder, leaf_label) for a tag.

        Namespaced only when the tag contains ':' and the prefix is non-numeric;
        otherwise it goes under FLAT_FOLDER with its full name as the label.
        """
        if ":" in tag:
            prefix, rest = tag.split(":", 1)
            if prefix and not prefix.isdigit() and rest:
                return prefix, rest
        return FolderService.FLAT_FOLDER, tag

    # Cap child tags shown per folder. The flat '# Tags' bucket can hold
    # thousands of long-tail tags (most appearing once); showing them all is
    # unusable. Top-N by count keeps the meaningful ones; the rest stay
    # reachable via the sidebar search. The UI shows a "+N more" hint from
    # truncated_children. When a search query is supplied, the cap is bypassed
    # so a matching tag is never hidden regardless of its rank.
    MAX_CHILDREN_PER_FOLDER = 200

    async def get_folder_tree(
        self,
        workspaces: Optional[List[str]] = None,
        query: Optional[str] = None,
    ) -> FolderTreeResponse:
        """Build the tag-folder tree for the given workspaces.

        If `query` is given, only tags whose full name contains it
        (case-insensitive) are included, and the per-folder cap is bypassed so
        every match is shown — this is how a buried tag like 'strategy-guide'
        becomes findable.
        """
        workspace_ids = await self._resolve_workspace_ids(workspaces)
        if not workspace_ids:
            return FolderTreeResponse(
                workspace_filter=workspaces, folders=[], total_tags=0
            )

        # Count nodes per distinct tag, scoped to the workspaces.
        result = await self.db.execute(
            text("""
                SELECT tag, COUNT(*) AS n
                FROM vault_graph.node_cache, unnest(tags) AS tag
                WHERE workspace_id = ANY(:workspace_ids)
                GROUP BY tag
            """),
            {"workspace_ids": workspace_ids}
        )
        tag_counts = result.fetchall()

        q = query.strip().lower() if query else None
        searching = bool(q)

        # Group tags into folders (filtering by the query when searching).
        folders: dict = {}  # folder name -> {count, children: {full_tag: (label, count)}}
        matched_tags = 0
        for row in tag_counts:
            if q and q not in row.tag.lower():
                continue
            matched_tags += 1
            folder, leaf_label = self._split_tag(row.tag)
            bucket = folders.setdefault(folder, {"count": 0, "children": {}})
            bucket["count"] += row.n
            bucket["children"][row.tag] = (leaf_label, row.n)

        # When searching, bypass the cap so no match is hidden.
        cap = len(tag_counts) + 1 if searching else self.MAX_CHILDREN_PER_FOLDER

        # Build response: folders sorted by count desc, flat bucket last;
        # children sorted by count desc.
        folder_nodes: List[FolderNode] = []
        for folder_name, data in folders.items():
            sorted_children = sorted(
                data["children"].items(), key=lambda kv: kv[1][1], reverse=True
            )
            capped = sorted_children[:cap]
            children = [
                FolderNode(name=label, full_tag=full_tag, node_count=cnt, children=[])
                for full_tag, (label, cnt) in capped
            ]
            folder_nodes.append(FolderNode(
                name=folder_name,
                full_tag=None,
                node_count=data["count"],
                children=children,
                truncated_children=max(0, len(sorted_children) - len(capped)),
            ))

        folder_nodes.sort(
            key=lambda f: (f.name == self.FLAT_FOLDER, -f.node_count)
        )

        return FolderTreeResponse(
            workspace_filter=workspaces,
            folders=folder_nodes,
            total_tags=matched_tags if searching else len(tag_counts),
        )

    async def get_folder_leaves(
        self,
        tag: str,
        workspaces: Optional[List[str]] = None,
        limit: int = 200,
    ) -> FolderLeavesResponse:
        """List nodes carrying a given tag (lazy-loaded tree leaves)."""
        workspace_ids = await self._resolve_workspace_ids(workspaces)
        if not workspace_ids:
            return FolderLeavesResponse(tag=tag, nodes=[])

        # NodeCache.tags is a generic ARRAY(Text), which has no .overlap(); use a
        # plain `= ANY(tags)` membership test (works on any text array column).
        node_query = (
            select(NodeCache)
            .where(
                NodeCache.workspace_id.in_(workspace_ids),
                text("CAST(:tag AS text) = ANY(node_cache.tags)").bindparams(tag=tag),
            )
            .order_by(
                NodeCache.importance.desc().nullslast(),
                NodeCache.created_at.desc().nullslast(),
            )
            .limit(limit)
        )
        result = await self.db.execute(node_query)
        rows = result.scalars().all()

        nodes = [
            GraphNode(
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
                created_at=row.created_at,
            )
            for row in rows
        ]
        return FolderLeavesResponse(tag=tag, nodes=nodes)


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
