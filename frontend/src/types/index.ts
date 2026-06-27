// Vault Graph Types

export interface GraphNode {
  id: string;
  node_type: 'memory' | 'document';
  label: string;
  workspace_id: string;
  workspace_slug: string;
  tags: string[];
  importance?: number;
  memory_type?: string;
  document_title?: string;
  has_file: boolean;
  created_at?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  edge_type: 'semantic' | 'tag' | 'document_memory' | 'project';
  weight: number;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  workspace_filter?: string[];
  total_nodes: number;
  total_edges: number;
  cached_at?: string;
}

export interface RelatedNode {
  node: GraphNode;
  edge_type: string;
  weight: number;
}

export interface NodeDetail {
  id: string;
  node_type: 'memory' | 'document';
  label: string;
  workspace_id: string;
  workspace_slug: string;
  content: string;
  content_preview: string;
  tags: string[];
  importance?: number;
  memory_type?: string;
  source_tool?: string;
  source_machine?: string;
  document_title?: string;
  has_file: boolean;
  download_url?: string;
  total_chunks?: number;
  related: RelatedNode[];
  created_at?: string;
  updated_at?: string;
}

export interface SearchResult {
  id: string;
  node_type: 'memory' | 'document';
  label: string;
  content_preview: string;
  workspace_slug: string;
  tags: string[];
  similarity: number;
  document_title?: string;
  chunk_index?: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  total: number;
  workspace_filter?: string[];
}

export interface WorkspaceSummary {
  id: string;
  slug: string;
  name: string;
  workspace_type: string;
  memory_count: number;
  document_count: number;
}

export interface WorkspaceListResponse {
  workspaces: WorkspaceSummary[];
  total: number;
}

export interface HealthResponse {
  status: string;
  database: string;
  graph_schema: string;
  version: string;
  node_count?: number;
  edge_count?: number;
}

export interface RebuildResponse {
  build_id: string;
  status: string;
  message: string;
}

export interface RebuildStatusResponse {
  build_id: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  nodes_processed: number;
  edges_created: number;
  error_message?: string;
}

// Graph filter state
export interface GraphFilters {
  workspaces: string[];
  nodeTypes: ('memory' | 'document')[];
  tags: string[];
  minImportance?: number;
  edgeTypes: ('semantic' | 'tag' | 'document_memory' | 'project')[];
}

// Color scheme
export const NODE_COLORS = {
  memory: '#3B82F6',      // blue-500
  document: '#10B981',    // emerald-500
} as const;

export const EDGE_COLORS = {
  semantic: '#8B5CF6',    // violet-500
  tag: '#F59E0B',         // amber-500
  document_memory: '#6366F1', // indigo-500
  project: '#EC4899',     // pink-500
} as const;
