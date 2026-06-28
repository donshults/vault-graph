# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Vault Graph** is an Obsidian-style interactive knowledge-graph visualization for Context Vault memories and documents, plus a JSON API for agent platforms. It is a **read-only companion service** to Context Vault: it shares the same Neon Postgres database and reads from CV's tables (`memories`, `documents`, `document_chunks`, `workspaces`), but only ever *writes* to its own `vault_graph.*` schema (edges, node cache, build jobs).

- Backend: FastAPI (async, Python 3.11) in [api/](api/)
- Frontend: React + Vite + TypeScript + Sigma.js (WebGL) in [frontend/](frontend/)
- Deployed as a single container on Railway (backend serves the built frontend)

**Critical invariant: never write to Context Vault tables.** All writes go to `vault_graph.*` only. The SQLAlchemy models for `workspaces`/`memories`/`documents`/`document_chunks` in [api/database.py](api/database.py) exist solely for `SELECT`s.

## Key Commands

```bash
# Backend (from api/)
cd api && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (from frontend/) — dev server runs on :3000 and proxies /api -> :8000
cd frontend && npm install && npm run dev

# Frontend build (runs tsc typecheck first, then vite build)
cd frontend && npm run build

# Frontend lint (zero-warning policy)
cd frontend && npm run lint

# Full container build (frontend + backend)
docker build -t vault-graph .
```

There is currently **no backend test suite** in the repo (no `pytest` test files exist). Backend "checks" are effectively running the server and hitting `/api/health`. Frontend correctness is enforced by `tsc` (via `npm run build`) and `eslint`.

## Architecture: the non-obvious parts

Read these before changing graph-building or graph-loading behavior — the design has several deliberate choices that look like bugs but aren't.

### Two database "halves" share one connection
[api/database.py](api/database.py) defines one async engine over the CV Neon DB. CV tables are read-only mirrors; `vault_graph.*` tables are app-owned. `Settings.database_url_async` ([api/config.py](api/config.py)) rewrites `postgresql://` → `postgresql+asyncpg://` and `sslmode=` → `ssl=` so a standard Neon connection string works with asyncpg unchanged.

### No migrations — schema is created at startup
The `vault_graph` schema, its three tables, and their indexes are created with raw `CREATE ... IF NOT EXISTS` SQL in the FastAPI `lifespan` handler in [api/main.py](api/main.py). There is no Alembic. To change the `vault_graph` schema you edit both the `lifespan` DDL **and** the SQLAlchemy models in [api/database.py](api/database.py) (they must stay in sync), and existing deployments won't auto-migrate column changes.

### Rebuild runs in-process, not in a worker
`POST /api/rebuild` inserts a `graph_builds` row, then kicks off `asyncio.create_task(self._run_rebuild(...))` ([api/services.py](api/services.py)). There is **no Celery/queue/separate worker** — the rebuild runs inside the same web process on its own DB session (`async_session()`), and the HTTP request returns immediately with a `build_id`. Poll `GET /api/rebuild/{id}/status`. Implications: a rebuild competes for the web process's resources, and it dies if the process restarts mid-build. Build state (`pending`/`running`/`completed`/`failed`) lives in `graph_builds`.

**Orphan reaping (two layers).** Because a killed task can leave a build stuck in `running` forever (the frontend then polls it indefinitely), there are two guards: (1) on startup, the `lifespan` handler in [api/main.py](api/main.py) marks any leftover `pending`/`running` build as `failed`; (2) `GET /api/rebuild/{id}/status` marks a build `failed` if it has been running longer than `VAULT_GRAPH_BUILD_STALE_SECONDS` (default 600). The frontend poller ([App.tsx](frontend/src/App.tsx)) also caps itself at ~5 minutes of polling.

### Rebuild pipeline (in `GraphService._run_rebuild`)
1. Mark build `running`.
2. Resolve target workspaces (all of the owner's, or the slugs passed in).
3. **Delete** existing edges + node_cache rows for those workspaces (full rebuild per workspace, not incremental).
4. Cache nodes from `memories` + `documents` into `node_cache` (batched 500 at a time; document previews come from the first chunk, fetched for all docs in **one** windowed query to avoid N+1).
5. Compute **tag edges** (always).
6. Compute **semantic edges** (only if `skip_semantic_edges` is false).
7. Compute **document↔memory edges** (foreign-key links, weight 1.0).
8. Mark `completed` with node/edge counts (or `failed` + `error_message`).

### Edge computation specifics
- **Tag edges** (`_compute_tag_edges`): not a naive O(n²) Jaccard. It builds an inverted index `(workspace, tag) -> node_ids`, only evaluates candidate pairs that share ≥1 tag, computes Jaccard, keeps pairs above `jaccard_threshold`, then **prunes to the top `max_edges_per_node` per node** (via heap) before a final dedupe. This pruning is what keeps the graph from exploding — don't remove it.
- **Semantic edges** (`_compute_semantic_edges`): pgvector kNN (`<=>` cosine) over `memories.embedding` and over `document_chunks.embedding` (doc-to-doc uses the max chunk similarity). This is expensive (effectively O(n²) joins) and is the reason rebuilds default to skipping it. **Heads-up discrepancy:** the API request model defaults `skip_semantic_edges` to **False**, so a bare `POST /api/rebuild` with no body *will* attempt semantic edges. Pass `{"skip_semantic_edges": true}` to skip.
- **Edge types** stored: `tag`, `semantic`, `document_memory`. (`project` exists in the `EdgeType` enum and frontend filters but is not computed by any builder.)

### Graph loading is node-limited, then edge-filtered
`GraphService.get_graph` selects nodes first — ordered by `importance DESC, created_at DESC` — and applies `limit`. It then returns **only edges whose source AND target are both in that limited node set**. So raising/lowering `limit` changes edge density, and low-importance nodes simply don't appear. The API default limit is **500**; the frontend hook ([frontend/src/hooks/useGraph.ts](frontend/src/hooks/useGraph.ts)) overrides it to **300** for performance.

### Startup workspace focus
By default the graph loads **all** of the owner's workspaces, which is unreadable at scale. To focus on one workspace at startup, set it via the `?workspace=<name-or-slug>` URL param (matched case-insensitively against workspace name or slug; `?workspace=all` forces show-all) or the build-time `VITE_DEFAULT_WORKSPACE` env var. The URL param wins. Resolution lives in `resolveDefaultWorkspaceSlug` in [frontend/src/hooks/useGraph.ts](frontend/src/hooks/useGraph.ts); it only applies on first load and never overrides a user's later filter choice.

### Tenancy is by `owner`, not by API key
Every CV-table query is scoped by `Workspace.owner == owner`. `owner` comes from the optional `X-Owner` header, defaulting to `settings.default_owner` (`"don"`). The API key only gates access; it does not select the data set.

### Auth is optional and multi-key
`verify_api_key` ([api/main.py](api/main.py)) returns `True` (no auth) when `VAULT_GRAPH_API_KEY` is unset. When set, it may be a **comma-separated list** of valid keys, and accepts either `Authorization: Bearer <key>` or `X-API-Key: <key>`.

### Single-container serving
The same FastAPI app serves the API and the built SPA. At startup [api/main.py](api/main.py) looks for `frontend/dist` in two locations (Docker `/app/frontend/dist` vs dev `../frontend/dist`); if found, it mounts `/assets` and adds a catch-all route that serves `index.html` for non-`api/` paths (SPA routing). The [Dockerfile](Dockerfile) is a two-stage build (node:20 builds the frontend → python:3.11 runs the backend with the dist copied in) and respects Railway's `$PORT`.

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | DB + `vault_graph` schema status, node/edge counts |
| `/api/graph` | GET | Graph topology (filtered, node-limited) |
| `/api/node/{id}` | GET | Node detail + content + top-10 related (incl. R2 presigned URL for docs) |
| `/api/search` | GET | Semantic search over memories + document chunks |
| `/api/workspaces` | GET | Workspaces with memory/document counts |
| `/api/rebuild` | POST | Trigger an in-process rebuild |
| `/api/rebuild/{id}/status` | GET | Build job status |

`POST /api/rebuild` body (all optional): `workspace_slugs[]`, `jaccard_threshold`, `similarity_threshold`, `max_edges_per_node`, `skip_semantic_edges`. Unset numeric thresholds fall back to `Settings` defaults (`edge_jaccard_threshold=0.5`, `edge_similarity_threshold=0.7`, `max_knn_edges=5`).

## Configuration

All settings use the `VAULT_GRAPH_` env prefix ([api/config.py](api/config.py)). Key ones:

| Variable | Required | Notes |
|----------|----------|-------|
| `VAULT_GRAPH_DATABASE_URL` | Yes | Neon connection string (shared with Context Vault) |
| `VAULT_GRAPH_OPENAI_API_KEY` | For search | `text-embedding-3-small`, 1536 dims (must match CV's embeddings) |
| `VAULT_GRAPH_API_KEY` | No | Omit to disable auth; comma-separate for multiple keys |
| `VAULT_GRAPH_DEFAULT_OWNER` | No | Defaults to `don` |
| `VAULT_GRAPH_BUILD_STALE_SECONDS` | No | Mark a still-`running` build failed after this many seconds (default 600) |
| `VAULT_GRAPH_S3_*` | For doc downloads | R2 creds for presigned URLs ([api/storage.py](api/storage.py)) |

The frontend also reads a build-time `VITE_DEFAULT_WORKSPACE` (see "Startup workspace focus" above).

## Deployment

- **Production auto-deploy:** push to `main` deploys production via [.github/workflows/deploy.yml](.github/workflows/deploy.yml) (`railway up --environment production`). The Railway project has **only a `production` environment** (no staging) — there is no staging deploy.
- **Manual fallback:** [.github/workflows/deploy-production.yml](.github/workflows/deploy-production.yml) is a manual `workflow_dispatch` (type "deploy" to confirm) for on-demand re-deploys of a specific commit.
- Both workflows post deploy start/success/failure notifications to an n8n webhook (`N8N_WEBHOOK_URL` secret); `RAILWAY_TOKEN` does the deploy.
- Production: `https://vault-graph-production.up.railway.app`.

```bash
# Manual production deploy
railway up --service vault-graph --environment production --detach

# Trigger a rebuild against production (tag edges only)
curl -X POST "https://vault-graph-production.up.railway.app/api/rebuild" \
  -H "Authorization: Bearer $VAULT_GRAPH_API_KEY" -H "Content-Type: application/json" \
  -d '{"skip_semantic_edges": true, "max_edges_per_node": 10}'
```

## File Map

```
api/
  main.py        FastAPI app, routes, lifespan schema-init, auth, static SPA serving
  services.py    GraphService (build + load), NodeService, SearchService, get_embedding()
  database.py    Async engine + SQLAlchemy models (CV read-only + vault_graph)
  schemas.py     Pydantic request/response models
  config.py      VAULT_GRAPH_-prefixed Settings + database_url_async rewriter
  storage.py     R2 presigned URL generation
frontend/src/
  hooks/useGraph.ts     Graph fetch + Graphology conversion + DEFAULT_FILTERS (limit 300)
  components/GraphView.tsx    Sigma.js wrapper (ForceAtlas2 layout, hover/select)
  components/FilterPanel.tsx  Filters + rebuild trigger
  components/DetailPanel.tsx  Node detail sidebar
  api/client.ts / types/index.ts   API client + shared types (NODE_COLORS, EDGE_COLORS)
```

See [STATUS.md](STATUS.md) for current graph stats, known issues, and recent perf work.

## Context Vault (project memory)

This project uses Context Vault for persistent memory. Recall context at session start and persist decisions at session end. Use the project's configured workspace from `.mcp.json` — never hardcode a workspace name. (Note: `.mcp.json` is not currently committed; confirm the configured `VAULT_DEFAULT_WORKSPACE` and bot identity before relying on cross-session memory.)
