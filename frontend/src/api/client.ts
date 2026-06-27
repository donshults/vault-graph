// API Client for Vault Graph

import type {
  GraphResponse,
  NodeDetail,
  SearchResponse,
  WorkspaceListResponse,
  HealthResponse,
  RebuildResponse,
  RebuildStatusResponse,
} from '../types';

const API_BASE = '/api';

// Get API key from localStorage or environment
function getApiKey(): string | null {
  return localStorage.getItem('vault_graph_api_key');
}

async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const apiKey = getApiKey();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (apiKey) {
    headers['Authorization'] = `Bearer ${apiKey}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// Health check
export async function getHealth(): Promise<HealthResponse> {
  return fetchApi<HealthResponse>('/health');
}

// Graph API
export async function getGraph(params?: {
  workspaces?: string[];
  nodeTypes?: string[];
  tags?: string[];
  minImportance?: number;
  edgeTypes?: string[];
}): Promise<GraphResponse> {
  const searchParams = new URLSearchParams();

  if (params?.workspaces?.length) {
    searchParams.set('workspaces', params.workspaces.join(','));
  }
  if (params?.nodeTypes?.length) {
    searchParams.set('node_types', params.nodeTypes.join(','));
  }
  if (params?.tags?.length) {
    searchParams.set('tags', params.tags.join(','));
  }
  if (params?.minImportance !== undefined) {
    searchParams.set('min_importance', params.minImportance.toString());
  }
  if (params?.edgeTypes?.length) {
    searchParams.set('edge_types', params.edgeTypes.join(','));
  }

  const query = searchParams.toString();
  return fetchApi<GraphResponse>(`/graph${query ? `?${query}` : ''}`);
}

// Node API
export async function getNode(nodeId: string): Promise<NodeDetail> {
  return fetchApi<NodeDetail>(`/node/${nodeId}`);
}

// Search API
export async function search(
  query: string,
  workspaces?: string[],
  limit?: number
): Promise<SearchResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set('query', query);

  if (workspaces?.length) {
    searchParams.set('workspaces', workspaces.join(','));
  }
  if (limit !== undefined) {
    searchParams.set('limit', limit.toString());
  }

  return fetchApi<SearchResponse>(`/search?${searchParams.toString()}`);
}

// Workspace API
export async function getWorkspaces(): Promise<WorkspaceListResponse> {
  return fetchApi<WorkspaceListResponse>('/workspaces');
}

// Rebuild API
export async function triggerRebuild(
  workspaceSlugs?: string[]
): Promise<RebuildResponse> {
  return fetchApi<RebuildResponse>('/rebuild', {
    method: 'POST',
    body: JSON.stringify({ workspace_slugs: workspaceSlugs }),
  });
}

export async function getRebuildStatus(
  buildId: string
): Promise<RebuildStatusResponse> {
  return fetchApi<RebuildStatusResponse>(`/rebuild/${buildId}/status`);
}

// Auth helpers
export function setApiKey(key: string): void {
  localStorage.setItem('vault_graph_api_key', key);
}

export function clearApiKey(): void {
  localStorage.removeItem('vault_graph_api_key');
}

export function hasApiKey(): boolean {
  return !!getApiKey();
}
