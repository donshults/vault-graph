// Detail panel for showing node content and related nodes

import { useState, useEffect } from 'react';
import { getNode } from '../api/client';
import type { NodeDetail, RelatedNode } from '../types';

interface DetailPanelProps {
  nodeId: string | null;
  onClose: () => void;
  onNodeClick: (nodeId: string) => void;
}

export function DetailPanel({ nodeId, onClose, onNodeClick }: DetailPanelProps) {
  const [node, setNode] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!nodeId) {
      setNode(null);
      return;
    }

    setLoading(true);
    setError(null);

    getNode(nodeId)
      .then(setNode)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [nodeId]);

  if (!nodeId) return null;

  return (
    <div className="detail-panel">
      {/* Header */}
      <div className="detail-panel-header">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block w-3 h-3 rounded-full ${
                node?.node_type === 'memory' ? 'bg-blue-500' : 'bg-emerald-500'
              }`}
            />
            <span className="text-sm font-medium text-gray-400">
              {node?.node_type === 'memory' ? 'Memory' : 'Document'}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white p-1"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {node && (
          <h2 className="text-lg font-semibold mt-2 text-white">
            {node.document_title || node.label}
          </h2>
        )}
      </div>

      {/* Content */}
      <div className="detail-panel-content">
        {loading && (
          <div className="flex justify-center py-8">
            <div className="loading-spinner" />
          </div>
        )}

        {error && (
          <div className="bg-red-900/50 text-red-200 p-4 rounded-lg">
            {error}
          </div>
        )}

        {node && !loading && (
          <>
            {/* Metadata */}
            <div className="space-y-4 mb-6">
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <span className="font-medium">Workspace:</span>
                <span className="text-white">{node.workspace_slug}</span>
              </div>

              {node.memory_type && (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <span className="font-medium">Type:</span>
                  <span className="text-white capitalize">{node.memory_type}</span>
                </div>
              )}

              {node.importance && (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <span className="font-medium">Importance:</span>
                  <div className="flex gap-0.5">
                    {[...Array(10)].map((_, i) => (
                      <div
                        key={i}
                        className={`w-2 h-2 rounded-full ${
                          i < node.importance!
                            ? 'bg-blue-500'
                            : 'bg-gray-700'
                        }`}
                      />
                    ))}
                  </div>
                </div>
              )}

              {node.source_tool && (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <span className="font-medium">Source:</span>
                  <span className="text-white">
                    {node.source_tool}
                    {node.source_machine && ` / ${node.source_machine}`}
                  </span>
                </div>
              )}

              {node.created_at && (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <span className="font-medium">Created:</span>
                  <span className="text-white">
                    {new Date(node.created_at).toLocaleDateString()}
                  </span>
                </div>
              )}
            </div>

            {/* Tags */}
            {node.tags.length > 0 && (
              <div className="mb-6">
                <h3 className="text-sm font-medium text-gray-400 mb-2">Tags</h3>
                <div className="flex flex-wrap gap-2">
                  {node.tags.map((tag) => (
                    <span key={tag} className="tag-badge tag-badge-blue">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Content */}
            <div className="mb-6">
              <h3 className="text-sm font-medium text-gray-400 mb-2">Content</h3>
              <div className="bg-gray-800 rounded-lg p-4 text-sm text-gray-300 whitespace-pre-wrap max-h-96 overflow-y-auto">
                {node.content}
              </div>
            </div>

            {/* Download button for documents */}
            {node.has_file && node.download_url && (
              <div className="mb-6">
                <a
                  href={node.download_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download File
                </a>
              </div>
            )}

            {/* Related nodes */}
            {node.related.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-2">
                  Related ({node.related.length})
                </h3>
                <div className="space-y-2">
                  {node.related.map((rel) => (
                    <button
                      key={rel.node.id}
                      onClick={() => onNodeClick(rel.node.id)}
                      className="w-full text-left bg-gray-800 hover:bg-gray-700 rounded-lg p-3 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            rel.node.node_type === 'memory'
                              ? 'bg-blue-500'
                              : 'bg-emerald-500'
                          }`}
                        />
                        <span className="text-sm font-medium text-white truncate flex-1">
                          {rel.node.document_title || rel.node.label}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                        <span className="capitalize">{rel.edge_type}</span>
                        <span>|</span>
                        <span>{(rel.weight * 100).toFixed(0)}% match</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
