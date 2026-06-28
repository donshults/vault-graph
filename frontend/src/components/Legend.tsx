// Collapsible legend for the footer. Collapsed to a button by default;
// clicking opens a popover (upward, since it lives at the bottom of the window).

import { useState } from 'react';

const NODE_ITEMS = [
  { color: 'bg-blue-500', label: 'Memory' },
  { color: 'bg-emerald-500', label: 'Document' },
];

const EDGE_ITEMS = [
  { color: 'bg-violet-500', label: 'Semantic' },
  { color: 'bg-amber-500', label: 'Tag' },
  { color: 'bg-indigo-500', label: 'Doc-Memory' },
];

export function Legend() {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      {/* Popover (opens upward) */}
      {open && (
        <div className="absolute bottom-full right-0 mb-2 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 shadow-lg z-30 w-44">
          <div className="space-y-1">
            {NODE_ITEMS.map((it) => (
              <div key={it.label} className="flex items-center gap-2 text-xs">
                <span className={`w-3 h-3 rounded-full ${it.color}`} />
                <span className="text-gray-300">{it.label}</span>
              </div>
            ))}
            <div className="h-px bg-gray-700 my-2" />
            {EDGE_ITEMS.map((it) => (
              <div key={it.label} className="flex items-center gap-2 text-xs">
                <span className={`w-3 h-0.5 ${it.color}`} />
                <span className="text-gray-300">{it.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Toggle button */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-200"
        title={open ? 'Hide legend' : 'Show legend'}
        aria-expanded={open}
      >
        {/* small color swatches preview so it reads as the legend even collapsed */}
        <span className="flex items-center gap-0.5">
          <span className="w-2 h-2 rounded-full bg-blue-500" />
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
        </span>
        <span>Legend</span>
        <svg
          className={`w-3 h-3 transition-transform ${open ? '' : 'rotate-180'}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          {/* chevron: points up when open, down (rotated) when closed */}
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
        </svg>
      </button>
    </div>
  );
}
