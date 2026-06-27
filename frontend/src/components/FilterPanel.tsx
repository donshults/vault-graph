// Filter panel for graph filtering

import { useState } from 'react';
import type { GraphFilters, WorkspaceSummary } from '../types';

interface FilterPanelProps {
  filters: GraphFilters;
  onFiltersChange: (filters: Partial<GraphFilters>) => void;
  workspaces: WorkspaceSummary[];
  onRebuild: () => void;
}

export function FilterPanel({
  filters,
  onFiltersChange,
  workspaces,
  onRebuild,
}: FilterPanelProps) {
  const [isOpen, setIsOpen] = useState(false);

  const toggleWorkspace = (slug: string) => {
    const current = filters.workspaces;
    const updated = current.includes(slug)
      ? current.filter((w) => w !== slug)
      : [...current, slug];
    onFiltersChange({ workspaces: updated });
  };

  const toggleNodeType = (type: 'memory' | 'document') => {
    const current = filters.nodeTypes;
    const updated = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type];
    onFiltersChange({ nodeTypes: updated });
  };

  const toggleEdgeType = (type: 'semantic' | 'tag' | 'document_memory' | 'project') => {
    const current = filters.edgeTypes;
    const updated = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type];
    onFiltersChange({ edgeTypes: updated });
  };

  return (
    <div className="absolute top-4 right-4 z-10">
      {/* Toggle button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="control-button flex items-center gap-2"
      >
        <svg
          className="w-5 h-5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"
          />
        </svg>
        Filters
      </button>

      {/* Filter panel */}
      {isOpen && (
        <div className="filter-panel mt-2">
          {/* Workspaces */}
          <div className="mb-4">
            <h4 className="text-sm font-medium text-gray-400 mb-2">Workspaces</h4>
            <div className="space-y-1">
              {workspaces.map((ws) => (
                <label
                  key={ws.slug}
                  className="flex items-center gap-2 text-sm cursor-pointer hover:bg-gray-700 rounded px-2 py-1"
                >
                  <input
                    type="checkbox"
                    checked={
                      filters.workspaces.length === 0 ||
                      filters.workspaces.includes(ws.slug)
                    }
                    onChange={() => toggleWorkspace(ws.slug)}
                    className="rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">{ws.name}</span>
                  <span className="text-gray-500 text-xs">
                    ({ws.memory_count + ws.document_count})
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* Node Types */}
          <div className="mb-4">
            <h4 className="text-sm font-medium text-gray-400 mb-2">Node Types</h4>
            <div className="flex gap-2">
              <button
                onClick={() => toggleNodeType('memory')}
                className={`px-3 py-1 rounded-full text-sm ${
                  filters.nodeTypes.includes('memory')
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-400'
                }`}
              >
                Memories
              </button>
              <button
                onClick={() => toggleNodeType('document')}
                className={`px-3 py-1 rounded-full text-sm ${
                  filters.nodeTypes.includes('document')
                    ? 'bg-emerald-600 text-white'
                    : 'bg-gray-700 text-gray-400'
                }`}
              >
                Documents
              </button>
            </div>
          </div>

          {/* Edge Types */}
          <div className="mb-4">
            <h4 className="text-sm font-medium text-gray-400 mb-2">Edge Types</h4>
            <div className="flex flex-wrap gap-2">
              {[
                { key: 'semantic', label: 'Semantic', color: 'violet' },
                { key: 'tag', label: 'Tag', color: 'amber' },
                { key: 'document_memory', label: 'Doc-Mem', color: 'indigo' },
              ].map(({ key, label, color }) => (
                <button
                  key={key}
                  onClick={() =>
                    toggleEdgeType(key as 'semantic' | 'tag' | 'document_memory')
                  }
                  className={`px-3 py-1 rounded-full text-sm ${
                    filters.edgeTypes.includes(
                      key as 'semantic' | 'tag' | 'document_memory'
                    )
                      ? `bg-${color}-600 text-white`
                      : 'bg-gray-700 text-gray-400'
                  }`}
                  style={{
                    backgroundColor: filters.edgeTypes.includes(
                      key as 'semantic' | 'tag' | 'document_memory'
                    )
                      ? color === 'violet'
                        ? '#7C3AED'
                        : color === 'amber'
                        ? '#D97706'
                        : '#4F46E5'
                      : undefined,
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Importance filter for memories */}
          <div className="mb-4">
            <h4 className="text-sm font-medium text-gray-400 mb-2">
              Min Importance
            </h4>
            <input
              type="range"
              min="1"
              max="10"
              value={filters.minImportance || 1}
              onChange={(e) =>
                onFiltersChange({
                  minImportance:
                    e.target.value === '1'
                      ? undefined
                      : parseInt(e.target.value),
                })
              }
              className="w-full"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>Any</span>
              <span>{filters.minImportance || 'All'}</span>
              <span>10</span>
            </div>
          </div>

          {/* Rebuild button */}
          <button
            onClick={onRebuild}
            className="w-full bg-violet-600 hover:bg-violet-700 text-white px-4 py-2 rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            Rebuild Graph
          </button>
        </div>
      )}
    </div>
  );
}
