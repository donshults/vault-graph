// Obsidian-style tag-folder sidebar.
//
// Tree is derived from tags (the data has no real folders): top-level namespace
// folders (from a tag's "prefix:" part) expand to their tags; expanding a tag
// lazily loads its document/memory leaves. Clicking a tag filters the graph by
// that tag; clicking a leaf selects that node.

import { useEffect, useState, useCallback } from 'react';
import { getFolders, getFolderLeaves } from '../api/client';
import type { FolderNode, GraphNode } from '../types';

interface FolderSidebarProps {
  /** Active workspace slugs — scopes the tree and triggers a refetch on change. */
  workspaces: string[];
  /** Currently graph-filtered tags, to highlight the active folder. */
  activeTags: string[];
  /** Click a tag folder -> filter the graph by that tag (toggle). */
  onSelectTag: (tag: string) => void;
  /** Click a leaf -> select that node (opens detail panel). */
  onSelectNode: (nodeId: string) => void;
}

const ChevronIcon = ({ open }: { open: boolean }) => (
  <svg
    className={`w-3 h-3 flex-shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
  >
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
  </svg>
);

export function FolderSidebar({
  workspaces,
  activeTags,
  onSelectTag,
  onSelectNode,
}: FolderSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [folders, setFolders] = useState<FolderNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Which namespace folders are expanded.
  const [openFolders, setOpenFolders] = useState<Set<string>>(new Set());
  // Lazy-loaded leaves per tag, plus loading state.
  const [leaves, setLeaves] = useState<Record<string, GraphNode[]>>({});
  const [loadingTags, setLoadingTags] = useState<Set<string>>(new Set());
  const [openTags, setOpenTags] = useState<Set<string>>(new Set());

  // Fetch the folder tree whenever the workspace scope changes.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getFolders(workspaces.length > 0 ? workspaces : undefined)
      .then((res) => {
        if (cancelled) return;
        setFolders(res.folders);
        // Reset expansion + leaf caches when the scope changes.
        setOpenFolders(new Set());
        setOpenTags(new Set());
        setLeaves({});
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load folders');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaces]);

  const toggleFolder = useCallback((name: string) => {
    setOpenFolders((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }, []);

  const toggleTag = useCallback(
    (fullTag: string) => {
      const isOpen = openTags.has(fullTag);
      setOpenTags((prev) => {
        const next = new Set(prev);
        next.has(fullTag) ? next.delete(fullTag) : next.add(fullTag);
        return next;
      });
      // Lazy-load leaves on first expand.
      if (!isOpen && leaves[fullTag] === undefined && !loadingTags.has(fullTag)) {
        setLoadingTags((prev) => new Set(prev).add(fullTag));
        getFolderLeaves(fullTag, workspaces.length > 0 ? workspaces : undefined)
          .then((res) => setLeaves((prev) => ({ ...prev, [fullTag]: res.nodes })))
          .catch(() => setLeaves((prev) => ({ ...prev, [fullTag]: [] })))
          .finally(() =>
            setLoadingTags((prev) => {
              const next = new Set(prev);
              next.delete(fullTag);
              return next;
            })
          );
      }
    },
    [openTags, leaves, loadingTags, workspaces]
  );

  if (collapsed) {
    // Thin in-flow rail with a show button, so the graph reclaims the space
    // without the toggle overlapping the search bar.
    return (
      <div className="folder-sidebar-collapsed">
        <button
          onClick={() => setCollapsed(false)}
          title="Show folders"
          className="text-gray-400 hover:text-white p-2"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <div className="folder-sidebar">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800 sticky top-0 bg-gray-900 z-10">
        <span className="text-sm font-medium text-gray-300">Folders</span>
        <button
          onClick={() => setCollapsed(true)}
          title="Hide folders"
          className="text-gray-500 hover:text-gray-300 p-1"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>
      </div>

      <div className="p-2">
        {loading && (
          <div className="flex items-center gap-2 text-gray-400 text-sm px-2 py-3">
            <div className="loading-spinner !w-4 !h-4 !border-2" />
            Loading folders...
          </div>
        )}
        {error && <div className="text-red-400 text-xs px-2 py-3">{error}</div>}
        {!loading && !error && folders.length === 0 && (
          <div className="text-gray-500 text-xs px-2 py-3">No tags in this workspace.</div>
        )}

        {!loading &&
          folders.map((folder) => {
            const open = openFolders.has(folder.name);
            return (
              <div key={folder.name} className="mb-0.5">
                {/* Namespace folder row */}
                <button
                  onClick={() => toggleFolder(folder.name)}
                  className="w-full flex items-center gap-1.5 px-2 py-1 rounded hover:bg-gray-800 text-left text-sm"
                >
                  <ChevronIcon open={open} />
                  <span className="text-gray-200 font-medium truncate flex-1">{folder.name}</span>
                  <span className="text-gray-500 text-xs flex-shrink-0">{folder.node_count}</span>
                </button>

                {/* Tags within the folder */}
                {open && (
                  <div className="ml-3 border-l border-gray-800 pl-1">
                    {folder.children.map((tag) => {
                      const fullTag = tag.full_tag as string;
                      const tagOpen = openTags.has(fullTag);
                      const isActive = activeTags.includes(fullTag);
                      const tagLeaves = leaves[fullTag];
                      return (
                        <div key={fullTag}>
                          {/* Tag row: chevron expands leaves; label filters graph */}
                          <div
                            className={`flex items-center gap-1 px-1 py-1 rounded text-sm ${
                              isActive ? 'bg-blue-600/30' : 'hover:bg-gray-800'
                            }`}
                          >
                            <button
                              onClick={() => toggleTag(fullTag)}
                              title="Expand"
                              className="p-0.5 text-gray-500 hover:text-gray-300 flex-shrink-0"
                            >
                              <ChevronIcon open={tagOpen} />
                            </button>
                            <button
                              onClick={() => onSelectTag(fullTag)}
                              title={`Filter graph by "${fullTag}"`}
                              className="flex items-center gap-1.5 flex-1 min-w-0 text-left"
                            >
                              <span className={`truncate ${isActive ? 'text-blue-300' : 'text-gray-300'}`}>
                                {tag.name}
                              </span>
                              <span className="text-gray-500 text-xs flex-shrink-0 ml-auto">
                                {tag.node_count}
                              </span>
                            </button>
                          </div>

                          {/* Leaves */}
                          {tagOpen && (
                            <div className="ml-4 border-l border-gray-800 pl-1">
                              {loadingTags.has(fullTag) && (
                                <div className="text-gray-500 text-xs px-2 py-1">Loading…</div>
                              )}
                              {tagLeaves?.map((node) => (
                                <button
                                  key={node.id}
                                  onClick={() => onSelectNode(node.id)}
                                  title={node.label}
                                  className="w-full flex items-center gap-1.5 px-2 py-1 rounded hover:bg-gray-800 text-left text-xs"
                                >
                                  <span
                                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                                      node.node_type === 'memory' ? 'bg-blue-500' : 'bg-emerald-500'
                                    }`}
                                  />
                                  <span className="text-gray-400 truncate">{node.label}</span>
                                </button>
                              ))}
                              {tagLeaves && tagLeaves.length === 0 && !loadingTags.has(fullTag) && (
                                <div className="text-gray-500 text-xs px-2 py-1">No items.</div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {folder.truncated_children > 0 && (
                      <div className="text-gray-600 text-xs px-2 py-1 italic">
                        +{folder.truncated_children} more tags (use search)
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}
