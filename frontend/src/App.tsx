// Main App component

import { useState, useCallback, useMemo } from 'react';
import { useGraph } from './hooks/useGraph';
import { GraphView } from './components/GraphView';
import { DetailPanel } from './components/DetailPanel';
import { SearchBar } from './components/SearchBar';
import { FilterPanel } from './components/FilterPanel';
import { StatsBar } from './components/StatsBar';
import { Legend } from './components/Legend';
import { WorkspaceIndicator } from './components/WorkspaceIndicator';
import { FolderSidebar } from './components/FolderSidebar';
import { AuthModal } from './components/AuthModal';
import { hasApiKey, triggerRebuild } from './api/client';

function App() {
  // Auth state
  const [isAuthenticated, setIsAuthenticated] = useState(hasApiKey());

  // Graph state
  const {
    graph,
    loading,
    error,
    filters,
    setFilters,
    workspaces,
    refetch,
    stats,
  } = useGraph();

  // UI state
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [rebuildStatus, setRebuildStatus] = useState<string | null>(null);

  // Handlers
  const handleNodeClick = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  const handleSearchResults = useCallback((nodeIds: string[]) => {
    setHighlightedNodeIds(nodeIds);
  }, []);

  // Click a folder tag -> filter the graph by it; click the active tag -> clear.
  const handleSelectTag = useCallback(
    (tag: string) => {
      const isActive = filters.tags.length === 1 && filters.tags[0] === tag;
      setFilters({ tags: isActive ? [] : [tag] });
    },
    [filters.tags, setFilters]
  );

  const handleRebuild = useCallback(async () => {
    console.log('Rebuild triggered, workspaces:', filters.workspaces);
    try {
      setRebuildStatus('Starting rebuild...');
      const response = await triggerRebuild(
        filters.workspaces.length > 0 ? filters.workspaces : undefined
      );
      console.log('Rebuild response:', response);
      setRebuildStatus(`Rebuild started: ${response.build_id.slice(0, 8)}...`);

      // Poll for completion, but give up after a bounded number of attempts so a
      // build that dies without reporting 'completed'/'failed' (e.g. its in-process
      // task was killed by a restart) doesn't leave the banner spinning forever.
      const POLL_INTERVAL_MS = 2000;
      const MAX_POLL_ATTEMPTS = 150; // ~5 minutes at 2s
      let attempts = 0;
      const pollInterval = setInterval(async () => {
        attempts += 1;
        try {
          const { getRebuildStatus } = await import('./api/client');
          const status = await getRebuildStatus(response.build_id);
          console.log('Rebuild status:', status);

          if (status.status === 'running') {
            setRebuildStatus(
              `Building: ${status.nodes_processed} nodes, ${status.edges_created} edges`
            );
          } else {
            setRebuildStatus(`${status.status}`);
          }

          if (status.status === 'completed' || status.status === 'failed') {
            clearInterval(pollInterval);
            if (status.status === 'completed') {
              setRebuildStatus('Complete! Refreshing...');
              setTimeout(() => {
                setRebuildStatus(null);
                refetch();
              }, 1500);
            } else {
              setRebuildStatus(`Failed: ${status.error_message || 'Unknown error'}`);
              setTimeout(() => setRebuildStatus(null), 5000);
            }
          } else if (attempts >= MAX_POLL_ATTEMPTS) {
            // Timed out waiting; stop polling so the banner clears.
            clearInterval(pollInterval);
            setRebuildStatus('Rebuild timed out — stopped tracking. Try refreshing.');
            setTimeout(() => setRebuildStatus(null), 5000);
          }
        } catch (pollErr) {
          console.error('Poll error:', pollErr);
          clearInterval(pollInterval);
          setRebuildStatus(null);
        }
      }, POLL_INTERVAL_MS);
    } catch (err) {
      console.error('Rebuild error:', err);
      setRebuildStatus(`Error: ${err instanceof Error ? err.message : 'Unknown'}`);
      setTimeout(() => setRebuildStatus(null), 5000);
    }
  }, [filters.workspaces, refetch]);

  // Convert highlighted IDs to Set for efficient lookup
  const highlightedNodes = useMemo(
    () => new Set(highlightedNodeIds),
    [highlightedNodeIds]
  );

  // Show auth modal if not authenticated
  if (!isAuthenticated) {
    return (
      <AuthModal
        onAuthenticated={() => {
          setIsAuthenticated(true);
          refetch();
        }}
      />
    );
  }

  return (
    <div className="flex w-full h-full">
      {/* Folder sidebar (Obsidian-style tag tree) */}
      <FolderSidebar
        workspaces={filters.workspaces}
        activeTags={filters.tags}
        onSelectTag={handleSelectTag}
        onSelectNode={handleNodeClick}
      />

      {/* Main graph area (graph fills the space above a fixed footer) */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Graph + floating overlays */}
        <div className="flex-1 relative min-h-0">
          {/* Search */}
          <SearchBar
            onResultClick={handleNodeClick}
            onSearchResults={handleSearchResults}
          />

          {/* Active workspace indicator */}
          <WorkspaceIndicator
            selected={filters.workspaces}
            workspaces={workspaces}
          />

          {/* Filters */}
          <FilterPanel
            filters={filters}
            onFiltersChange={setFilters}
            workspaces={workspaces}
            onRebuild={handleRebuild}
          />

          {/* Rebuild status */}
          {rebuildStatus && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 bg-violet-900/90 text-violet-100 px-4 py-2 rounded-lg text-sm flex items-center gap-2">
              <div className="loading-spinner !w-4 !h-4 !border-2 !border-violet-400 !border-t-transparent" />
              {rebuildStatus}
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 bg-red-900/90 text-red-100 px-4 py-2 rounded-lg text-sm">
              {error}
            </div>
          )}

          {/* Graph */}
          <GraphView
            graph={graph}
            selectedNodeId={selectedNodeId}
            onNodeClick={handleNodeClick}
            highlightedNodes={highlightedNodes}
          />
        </div>

        {/* Footer: stats on the left, collapsible legend on the right */}
        <footer className="flex items-center justify-between gap-4 px-4 py-2 border-t border-gray-800 bg-gray-900 text-gray-300">
          <StatsBar stats={stats} loading={loading} />
          <Legend />
        </footer>
      </div>

      {/* Detail panel */}
      <DetailPanel
        nodeId={selectedNodeId}
        onClose={handleCloseDetail}
        onNodeClick={handleNodeClick}
      />
    </div>
  );
}

export default App;
