// Stats bar showing graph statistics

interface StatsBarProps {
  stats: {
    nodeCount: number;
    edgeCount: number;
    memoryCount: number;
    documentCount: number;
  };
  loading: boolean;
}

export function StatsBar({ stats, loading }: StatsBarProps) {
  return (
    <div className="absolute bottom-4 left-4 z-10 flex gap-4">
      <div className="bg-gray-800/90 backdrop-blur-sm border border-gray-700 rounded-lg px-4 py-2 flex items-center gap-6 text-sm">
        {loading ? (
          <div className="flex items-center gap-2 text-gray-400">
            <div className="loading-spinner !w-4 !h-4 !border-2" />
            Loading graph...
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="text-gray-400">Nodes:</span>
              <span className="text-white font-medium">{stats.nodeCount}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-gray-400">Edges:</span>
              <span className="text-white font-medium">{stats.edgeCount}</span>
            </div>
            <div className="h-4 w-px bg-gray-700" />
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500" />
              <span className="text-gray-400">Memories:</span>
              <span className="text-white font-medium">{stats.memoryCount}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-gray-400">Documents:</span>
              <span className="text-white font-medium">{stats.documentCount}</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
