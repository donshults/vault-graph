# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**Vault Graph** is an interactive graph visualization web app for Context Vault memories and documents. It provides an Obsidian-style knowledge graph view plus a JSON API for agent platforms.

**Key Features:**
- Interactive graph visualization with Sigma.js (WebGL)
- Semantic and tag-based edge computation
- Full-text semantic search
- Document download via R2 presigned URLs
- Split-pane layout with reading view

**Architecture:**
- Backend: FastAPI (Python)
- Frontend: React + Vite + TypeScript + Sigma.js
- Database: Neon Postgres (same as Context Vault - read-only access)
- Graph Schema: `vault_graph` schema (app-owned)
- Storage: Cloudflare R2 (for presigned download URLs)

## Relationship to Context Vault

Vault Graph is a **read-only companion service** to Context Vault:

1. **Shares the same Neon database** - reads from `memories`, `documents`, `workspaces` tables
2. **Owns its own schema** - writes only to `vault_graph.*` tables (edges, node_cache, builds)
3. **Uses same authentication** - same `VAULT_API_KEY` as Context Vault
4. **Uses same R2 bucket** - generates presigned URLs for document downloads

**Critical: Never write to Context Vault tables.** All writes are to `vault_graph.*` only.

## Key Commands

### Local Development

```bash
# Backend (from project root)
cd api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (from project root)
cd frontend
npm install
npm run dev  # Runs on port 3000, proxies /api to 8000
```

### Building

```bash
# Build frontend
cd frontend && npm run build

# Docker build
docker build -t vault-graph .
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Health check with schema status |
| `/api/graph` | GET | Graph topology (nodes + edges) |
| `/api/node/{id}` | GET | Node details + content + related |
| `/api/search` | GET | Semantic search |
| `/api/workspaces` | GET | List workspaces with counts |
| `/api/rebuild` | POST | Trigger edge recomputation |
| `/api/rebuild/{id}/status` | GET | Build job status |

## Database Schema

### App-Owned (`vault_graph.*`)

```sql
-- Build job tracking
vault_graph.graph_builds (id, status, started_at, completed_at, nodes_processed, edges_created)

-- Precomputed edges
vault_graph.graph_edges (source_id, source_type, target_id, target_type, edge_type, weight, workspace_id)

-- Cached node metadata
vault_graph.node_cache (node_id, node_type, workspace_id, workspace_slug, label, tags, etc.)
```

### Read-Only Access (Context Vault)

- `workspaces` - Workspace metadata
- `memories` - Memory content and embeddings
- `documents` - Document metadata and R2 keys
- `document_chunks` - Chunk content and embeddings

## Edge Types

| Type | Computation | Threshold |
|------|-------------|-----------|
| `semantic` | pgvector kNN (cosine) | 0.7 similarity |
| `tag` | Jaccard similarity | 0.3 overlap |
| `document_memory` | Foreign key link | 1.0 (direct) |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VAULT_GRAPH_DATABASE_URL` | Yes | Neon connection string |
| `VAULT_GRAPH_OPENAI_API_KEY` | Yes | For search embeddings |
| `VAULT_GRAPH_API_KEY` | No | API authentication |
| `VAULT_GRAPH_S3_*` | For R2 | R2 credentials for presigned URLs |

## File Structure

```
vault-graph/
├── api/
│   ├── main.py          # FastAPI app and routes
│   ├── config.py        # Settings with VAULT_GRAPH_ prefix
│   ├── database.py      # SQLAlchemy models (CV read-only + vault_graph)
│   ├── schemas.py       # Pydantic models
│   ├── services.py      # Business logic (GraphService, SearchService, NodeService)
│   ├── storage.py       # R2 presigned URL generation
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Main app component
│   │   ├── components/      # UI components
│   │   ├── hooks/           # React hooks
│   │   ├── types/           # TypeScript types
│   │   └── api/             # API client
│   ├── package.json
│   └── vite.config.ts
├── Dockerfile
└── .github/workflows/
```

## Development Notes

### Graph Rebuild Process

1. Creates `graph_builds` record with status `pending`
2. Clears old edges and cache for target workspaces
3. Populates `node_cache` from memories and documents
4. Computes tag edges (Jaccard similarity)
5. Computes semantic edges (pgvector kNN)
6. Computes document-memory edges (foreign key links)
7. Updates build status to `completed`

### Frontend Graph Rendering

- Uses Sigma.js with WebGL for performance at scale
- ForceAtlas2 layout runs for 5 seconds on load
- Node selection highlights related nodes via edge traversal
- Search results highlight matching nodes in gold

### Authentication

Supports both:
- `Authorization: Bearer <token>` (Claude.ai style)
- `X-API-Key: <token>` (Context Vault style)

## Deployment

### Railway Setup

1. Create new Railway project: `vault-graph`
2. Add service pointing to this repo
3. Configure environment variables (same DB, R2, OpenAI as Context Vault)
4. Configure environments: `staging` and `production`

### GitHub Secrets

- `RAILWAY_TOKEN` - Railway deploy token
- `N8N_WEBHOOK_URL` - Slack notification webhook

## Testing

```bash
# Backend tests
cd api
pytest -v

# Frontend type checking
cd frontend
npm run build  # Includes TypeScript check
```

## Related Projects

- **Context Vault** - Parent project providing the memory/document data
- **Context Vault API** - REST API that Vault Graph reads from
