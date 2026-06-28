// Active-filter chip row: makes it explicit what the graph is currently scoped
// to (workspace + tag + any non-default node/importance filters). Chips for
// clearable filters show an x; the workspace chip is informational.

import type { GraphFilters, WorkspaceSummary } from '../types';

interface ActiveFiltersProps {
  filters: GraphFilters;
  workspaces: WorkspaceSummary[];
  onChange: (partial: Partial<GraphFilters>) => void;
}

const ALL_NODE_TYPES = 2; // memory + document

function Chip({
  label,
  value,
  tone = 'gray',
  onClear,
}: {
  label: string;
  value: string;
  tone?: 'gray' | 'blue' | 'amber';
  onClear?: () => void;
}) {
  const toneClasses =
    tone === 'blue'
      ? 'bg-blue-600/25 border-blue-500/40 text-blue-200'
      : tone === 'amber'
      ? 'bg-amber-600/25 border-amber-500/40 text-amber-200'
      : 'bg-gray-800 border-gray-700 text-gray-300';
  return (
    <span
      className={`inline-flex items-center gap-1.5 border rounded-full pl-2.5 pr-1.5 py-1 text-xs ${toneClasses}`}
    >
      <span className="text-gray-400">{label}:</span>
      <span className="font-medium truncate max-w-[16rem]">{value}</span>
      {onClear && (
        <button
          onClick={onClear}
          title={`Clear ${label.toLowerCase()}`}
          className="ml-0.5 hover:bg-white/10 rounded-full w-4 h-4 flex items-center justify-center flex-shrink-0"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </span>
  );
}

export function ActiveFilters({ filters, workspaces, onChange }: ActiveFiltersProps) {
  // Workspace label (resolve slug -> name).
  let workspaceValue: string;
  if (filters.workspaces.length === 0) {
    workspaceValue = 'All Workspaces';
  } else if (filters.workspaces.length === 1) {
    const ws = workspaces.find((w) => w.slug === filters.workspaces[0]);
    workspaceValue = ws?.name ?? filters.workspaces[0];
  } else {
    workspaceValue = `${filters.workspaces.length} workspaces`;
  }

  const typesFiltered =
    filters.nodeTypes.length > 0 && filters.nodeTypes.length < ALL_NODE_TYPES;
  const importanceFiltered = filters.minImportance !== undefined;

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Workspace is informational (changed via the Filters panel) */}
      <Chip label="Workspace" value={workspaceValue} />

      {/* Active tags — clearable */}
      {filters.tags.map((tag) => (
        <Chip
          key={tag}
          label="Tag"
          value={tag}
          tone="blue"
          onClear={() => onChange({ tags: filters.tags.filter((t) => t !== tag) })}
        />
      ))}

      {/* Non-default node-type filter — clearable (reset to all) */}
      {typesFiltered && (
        <Chip
          label="Type"
          value={filters.nodeTypes.join(', ')}
          tone="amber"
          onClear={() => onChange({ nodeTypes: ['memory', 'document'] })}
        />
      )}

      {/* Min importance filter — clearable */}
      {importanceFiltered && (
        <Chip
          label="Min importance"
          value={String(filters.minImportance)}
          tone="amber"
          onClear={() => onChange({ minImportance: undefined })}
        />
      )}
    </div>
  );
}
