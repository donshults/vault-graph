// Always-visible indicator of which workspace the graph is currently showing.

import type { WorkspaceSummary } from '../types';

interface WorkspaceIndicatorProps {
  /** Currently selected workspace slugs (empty = all workspaces). */
  selected: string[];
  /** Full workspace list, used to resolve slugs to display names. */
  workspaces: WorkspaceSummary[];
}

export function WorkspaceIndicator({ selected, workspaces }: WorkspaceIndicatorProps) {
  let label: string;
  if (selected.length === 0) {
    label = 'All Workspaces';
  } else if (selected.length === 1) {
    const ws = workspaces.find((w) => w.slug === selected[0]);
    label = ws?.name ?? selected[0];
  } else {
    label = `${selected.length} workspaces`;
  }

  const isAll = selected.length === 0;

  return (
    <div
      className="absolute top-20 left-4 z-10 flex items-center gap-2 bg-gray-800/90
                 backdrop-blur-sm border border-gray-700 rounded-lg px-3 py-1.5
                 text-sm max-w-[24rem]"
      title={`Workspace: ${label}`}
    >
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${isAll ? 'bg-gray-400' : 'bg-blue-500'}`} />
      <span className="text-gray-400 flex-shrink-0">Workspace:</span>
      <span className="text-white font-medium truncate">{label}</span>
    </div>
  );
}
