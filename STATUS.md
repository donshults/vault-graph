# Vault Graph - Implementation Status

**Last Updated:** 2026-06-28
**Repository:** /home/callteksupport/projects/vault-graph
**Production URL:** https://vault-graph-production.up.railway.app
**Railway Project:** vault-graph

## Overview

Vault Graph is an Obsidian-style interactive graph visualization for Context Vault memories and documents. It provides a WebGL-rendered graph UI plus a JSON API for agent platforms.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Railway Platform                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    Vault Graph                        │   │
│  │  ┌────────────────┐    ┌─────────────────────────┐   │   │
│  │  │ FastAPI Backend│    │ React + Sigma.js Frontend│  │   │
│  │  │    (api/)      │    │     (frontend/)          │   │   │
│  │  └───────┬────────┘    └───────────┬─────────────┘   │   │
│  └──────────┼─────────────────────────┼─────────────────┘   │
│             │                         │                      │
│             ▼                         │                      │
│     ┌───────────────┐                 │                      │
│     │ Neon Postgres │                 │                      │
│     │ (vault_graph  │                 │                      │
│     │   schema)     │                 │                      │
│     └───────────────┘                 │                      │
│             │                         │                      │
│             ▼                         ▼                      │
│     ┌───────────────┐         ┌──────────────┐              │
│     │ Context Vault │         │ Cloudflare R2│              │
│     │   Tables      │         │ (presigned)  │              │
│     │ (read-only)   │         └──────────────┘              │
│     └───────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
```

## Current State: FUNCTIONAL

### What's Working

1. **Graph Visualization** (frontend/)
   - Sigma.js WebGL rendering
   - ForceAtlas2 layout (3 second stabilization)
   - Node hover highlighting
   - Node selection with detail panel
   - Search with result highlighting
   - Workspace filtering (single-select)
   - Node limit slider (50-1000, default 300)
   - Node type filtering (memory/document)
   - Edge type filtering (semantic/tag/doc-memory)
   - Importance filtering

2. **API Endpoints** (api/)
   - `GET /api/health` - Health check with node/edge counts
   - `GET /api/graph` - Graph topology with filtering + limit
   - `GET /api/node/{id}` - Full node details + related nodes
   - `GET /api/search` - Semantic search
   - `POST /api/rebuild` - Trigger graph rebuild with params
   - `GET /api/rebuild/{id}/status` - Build job status
   - `GET /api/workspaces` - List workspaces with counts

3. **Graph Builder** (api/services.py)
   - Node caching (memories + documents)
   - Tag-based edges (Jaccard similarity)
   - Semantic edges (pgvector kNN) - optional
   - Document-memory edges
   - Edge-per-node limiting (default 5)
   - Batch operations for performance

### Rebuild API Parameters

```json
POST /api/rebuild
{
  "workspace_slugs": ["personal_trading"],  // Optional: limit to workspaces
  "jaccard_threshold": 0.5,                 // Min tag overlap (0.0-1.0)
  "similarity_threshold": 0.7,              // Min semantic similarity (0.0-1.0)
  "max_edges_per_node": 5,                  // Edge limit per node (1-50)
  "skip_semantic_edges": true               // Skip slow O(n²) computation
}
```

### Current Graph Stats

- **9,293 nodes** (4,166 memories + 5,127 documents)
- **38,788 edges** (tag-based, ~4 per node average)
- Default display: 300 nodes (adjustable via slider)

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI (Python 3.11) |
| Frontend | React + Vite + TypeScript |
| Graph Rendering | Sigma.js + Graphology |
| Layout | ForceAtlas2 (web worker) |
| Database | Neon Postgres (same as Context Vault) |
| Storage | Cloudflare R2 (presigned URLs for docs) |
| Auth | Bearer token (X-API-Key header) |
| Deployment | Railway |

## Key Files

### Backend (api/)
- `main.py` - FastAPI app, routes, lifespan
- `services.py` - GraphService, NodeService, SearchService
- `schemas.py` - Pydantic models
- `config.py` - Settings with VAULT_GRAPH_ prefix
- `database.py` - SQLAlchemy models
- `storage.py` - R2 presigned URL generation

### Frontend (frontend/src/)
- `App.tsx` - Main app with state management
- `components/GraphView.tsx` - Sigma.js wrapper
- `components/FilterPanel.tsx` - Filter controls + rebuild
- `components/DetailPanel.tsx` - Node detail sidebar
- `components/SearchBar.tsx` - Semantic search
- `hooks/useGraph.ts` - Graph data fetching + state
- `api/client.ts` - API client functions
- `types/index.ts` - TypeScript types

### Infrastructure
- `Dockerfile` - Multi-stage build (frontend + backend)
- `.github/workflows/deploy-staging.yml` - Auto-deploy on push
- `.github/workflows/deploy-production.yml` - Manual deploy

## Database Schema (vault_graph)

```sql
-- App-owned tables in vault_graph schema
graph_builds        -- Build jobs: id, status, timing, counts, error
graph_edges         -- Edges: source, target, type, weight, workspace
node_cache          -- Cached node metadata for fast graph loads

-- Read-only access to Context Vault tables
memories, documents, document_chunks, workspaces
```

## Environment Variables (Railway)

```
VAULT_GRAPH_DATABASE_URL     # Neon connection string
VAULT_GRAPH_OPENAI_API_KEY   # For embeddings
VAULT_GRAPH_API_KEY          # API authentication
VAULT_GRAPH_S3_*             # R2 storage config
VAULT_GRAPH_DEFAULT_OWNER    # Default: don
```

## Performance Optimizations Implemented

1. **Node limiting** - Default 300 nodes (was 9000+)
2. **Edge-per-node limiting** - Max 5 edges per node (was 312 avg)
3. **Batch inserts** - 500 nodes/edges at a time
4. **Single query for chunks** - Window function vs N+1
5. **Sigma refs** - Prevent recreation on hover/select
6. **ForceAtlas2 timeout** - 3 seconds (was 5)
7. **Ordered by importance** - Most important nodes first

## Recent Commits (2026-06-28)

```
6bc3215 fix: Smaller nodes, workspace filter, rebuild button
d8831ce fix: Prevent Sigma recreation on hover/select state changes
0cfe719 fix: Add node limit to prevent performance issues
9646026 feat: Add configurable thresholds to rebuild API
2fcc06e perf: Batch node cache inserts and use single query for document chunks
d264f0c fix: Limit tag edges to top N per node to prevent graph explosion
```

## Known Issues / Future Work

1. **Semantic edges slow** - O(n²) computation, currently skipped by default
2. **No clustering** - Large graphs could benefit from node grouping
3. **No edge labels** - Could show similarity scores
4. **No export** - Could add PNG/SVG export
5. **No keyboard navigation** - Arrow keys for node selection

## Quick Commands

```bash
# Local development
cd /home/callteksupport/projects/vault-graph
cd frontend && npm run dev  # Frontend on :5173
cd api && uvicorn main:app --reload  # Backend on :8000

# Build frontend
cd frontend && npm run build

# Deploy to production
railway up --service vault-graph --environment production --detach

# Trigger rebuild via API
curl -X POST "https://vault-graph-production.up.railway.app/api/rebuild" \
  -H "Authorization: Bearer $VAULT_GRAPH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"skip_semantic_edges": true, "max_edges_per_node": 10}'

# Check health
curl "https://vault-graph-production.up.railway.app/api/health"
```

## Authentication

API key stored in Railway: `VAULT_GRAPH_API_KEY`

To get it:
```bash
cd /home/callteksupport/projects/vault-graph
railway link --project vault-graph --service vault-graph --environment production
railway variables | grep API_KEY
```
