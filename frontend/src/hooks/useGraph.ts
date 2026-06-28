// Hook for managing graph state

import { useState, useEffect, useCallback, useMemo } from 'react';
import Graph from 'graphology';
import { getGraph, getWorkspaces } from '../api/client';
import type { GraphResponse, WorkspaceSummary, GraphFilters } from '../types';
import { NODE_COLORS, EDGE_COLORS } from '../types';

export interface UseGraphResult {
  graph: Graph | null;
  loading: boolean;
  error: string | null;
  filters: GraphFilters;
  setFilters: (filters: Partial<GraphFilters>) => void;
  workspaces: WorkspaceSummary[];
  refetch: () => Promise<void>;
  stats: {
    nodeCount: number;
    edgeCount: number;
    memoryCount: number;
    documentCount: number;
  };
}

const DEFAULT_FILTERS: GraphFilters = {
  workspaces: [],
  nodeTypes: ['memory', 'document'],
  tags: [],
  minImportance: undefined,
  edgeTypes: ['semantic', 'tag', 'document_memory', 'project'],
  limit: 300, // Default to 300 nodes for good performance
};

// On first load, focus the graph on a single workspace so it's legible instead
// of showing every workspace's nodes mixed together. The target workspace can be
// supplied at runtime via the `?workspace=` URL param (name or slug, matched
// case-insensitively), or at build time via VITE_DEFAULT_WORKSPACE. If neither is
// set, no default is applied and all workspaces load.
//
//   ?workspace=DS9 Platform   focus by name
//   ?workspace=ds9_platform   focus by slug
//   ?workspace=all            explicitly show all workspaces
function getConfiguredDefaultWorkspace(): string | null {
  if (typeof window !== 'undefined') {
    const param = new URLSearchParams(window.location.search).get('workspace');
    if (param !== null && param.trim() !== '') return param.trim();
  }
  const envDefault = import.meta.env.VITE_DEFAULT_WORKSPACE as string | undefined;
  return envDefault && envDefault.trim() !== '' ? envDefault.trim() : null;
}

// Resolve the configured default to an actual workspace slug. Returns:
//   - a slug      -> focus that workspace on load
//   - '' (empty)  -> caller should show all workspaces (no filter)
//   - null        -> no default configured; leave default behavior to caller
function resolveDefaultWorkspaceSlug(
  workspaces: WorkspaceSummary[]
): string | '' | null {
  const configured = getConfiguredDefaultWorkspace();
  if (configured === null) return null;
  if (configured.toLowerCase() === 'all') return ''; // explicit "show everything"
  if (workspaces.length === 0) return null;

  const target = configured.toLowerCase();
  const match = workspaces.find(
    (ws) => ws.name.toLowerCase() === target || ws.slug.toLowerCase() === target
  );
  if (match) return match.slug;

  // Configured name didn't match anything — warn and fall back to no filter
  // rather than silently focusing an arbitrary workspace.
  console.warn(
    `[vault-graph] Configured default workspace "${configured}" not found; showing all workspaces.`
  );
  return '';
}

export function useGraph(): UseGraphResult {
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<GraphFilters>(DEFAULT_FILTERS);
  // Tracks whether we've already applied the startup default workspace, so
  // clearing the workspace filter later isn't immediately overridden.
  const [defaultApplied, setDefaultApplied] = useState(false);

  const setFilters = useCallback((newFilters: Partial<GraphFilters>) => {
    // Any explicit workspace change by the user counts as having seen the default.
    if (newFilters.workspaces !== undefined) {
      setDefaultApplied(true);
    }
    setFiltersState((prev) => ({ ...prev, ...newFilters }));
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch workspaces first (for filter options)
      const wsResponse = await getWorkspaces();
      setWorkspaces(wsResponse.workspaces);

      // On the very first load, if a default workspace is configured (via
      // ?workspace= or VITE_DEFAULT_WORKSPACE), focus the graph on it so it's
      // readable. Fetch the graph already scoped to it to avoid a wasted call.
      let effectiveWorkspaces = filters.workspaces;
      if (!defaultApplied && filters.workspaces.length === 0) {
        const defaultSlug = resolveDefaultWorkspaceSlug(wsResponse.workspaces);
        if (defaultSlug) {
          effectiveWorkspaces = [defaultSlug];
          setFiltersState((prev) => ({ ...prev, workspaces: effectiveWorkspaces }));
        }
        // defaultSlug === '' (show all) or null (not configured) -> no filter
        setDefaultApplied(true);
      }

      // Fetch graph with current filters
      const graphResponse = await getGraph({
        workspaces: effectiveWorkspaces.length > 0 ? effectiveWorkspaces : undefined,
        nodeTypes: filters.nodeTypes.length > 0 ? filters.nodeTypes : undefined,
        tags: filters.tags.length > 0 ? filters.tags : undefined,
        minImportance: filters.minImportance,
        edgeTypes: filters.edgeTypes.length > 0 ? filters.edgeTypes : undefined,
        limit: filters.limit,
      });

      setGraphData(graphResponse);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load graph';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [filters, defaultApplied]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Convert API response to Graphology graph
  const graph = useMemo(() => {
    if (!graphData) return null;

    const g = new Graph({ type: 'undirected', multi: false });

    // Add nodes (smaller sizes for better visibility)
    for (const node of graphData.nodes) {
      const nodeSize = node.node_type === 'memory'
        ? 2 + (node.importance || 5) * 0.3
        : 4;

      g.addNode(node.id, {
        label: node.label,
        x: Math.random() * 100,
        y: Math.random() * 100,
        size: nodeSize,
        color: NODE_COLORS[node.node_type],
        // Store metadata
        nodeType: node.node_type,
        workspaceSlug: node.workspace_slug,
        tags: node.tags,
        importance: node.importance,
        memoryType: node.memory_type,
        documentTitle: node.document_title,
        hasFile: node.has_file,
        createdAt: node.created_at,
      });
    }

    // Add edges
    for (const edge of graphData.edges) {
      // Skip if nodes don't exist
      if (!g.hasNode(edge.source) || !g.hasNode(edge.target)) continue;

      // Skip if edge already exists
      if (g.hasEdge(edge.source, edge.target)) continue;

      g.addEdge(edge.source, edge.target, {
        size: edge.weight * 2,
        color: EDGE_COLORS[edge.edge_type] || '#666',
        edgeType: edge.edge_type,
        weight: edge.weight,
      });
    }

    return g;
  }, [graphData]);

  // Compute stats
  const stats = useMemo(() => {
    if (!graphData) {
      return { nodeCount: 0, edgeCount: 0, memoryCount: 0, documentCount: 0 };
    }

    const memoryCount = graphData.nodes.filter((n) => n.node_type === 'memory').length;
    const documentCount = graphData.nodes.filter((n) => n.node_type === 'document').length;

    return {
      nodeCount: graphData.total_nodes,
      edgeCount: graphData.total_edges,
      memoryCount,
      documentCount,
    };
  }, [graphData]);

  return {
    graph,
    loading,
    error,
    filters,
    setFilters,
    workspaces,
    refetch: fetchData,
    stats,
  };
}
