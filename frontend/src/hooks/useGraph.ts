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
};

export function useGraph(): UseGraphResult {
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<GraphFilters>(DEFAULT_FILTERS);

  const setFilters = useCallback((newFilters: Partial<GraphFilters>) => {
    setFiltersState((prev) => ({ ...prev, ...newFilters }));
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch workspaces first (for filter options)
      const wsResponse = await getWorkspaces();
      setWorkspaces(wsResponse.workspaces);

      // Fetch graph with current filters
      const graphResponse = await getGraph({
        workspaces: filters.workspaces.length > 0 ? filters.workspaces : undefined,
        nodeTypes: filters.nodeTypes.length > 0 ? filters.nodeTypes : undefined,
        tags: filters.tags.length > 0 ? filters.tags : undefined,
        minImportance: filters.minImportance,
        edgeTypes: filters.edgeTypes.length > 0 ? filters.edgeTypes : undefined,
      });

      setGraphData(graphResponse);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load graph';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Convert API response to Graphology graph
  const graph = useMemo(() => {
    if (!graphData) return null;

    const g = new Graph({ type: 'undirected', multi: false });

    // Add nodes
    for (const node of graphData.nodes) {
      const nodeSize = node.node_type === 'memory'
        ? 5 + (node.importance || 5)
        : 10;

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
