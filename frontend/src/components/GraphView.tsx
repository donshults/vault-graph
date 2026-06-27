// Main graph visualization component using Sigma.js

import { useEffect, useRef, useState } from 'react';
import Graph from 'graphology';
import Sigma from 'sigma';
import FA2Layout from 'graphology-layout-forceatlas2/worker';

interface GraphViewProps {
  graph: Graph | null;
  selectedNodeId: string | null;
  onNodeClick: (nodeId: string) => void;
  highlightedNodes?: Set<string>;
}

export function GraphView({
  graph,
  selectedNodeId,
  onNodeClick,
  highlightedNodes,
}: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const layoutRef = useRef<FA2Layout | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  // Initialize Sigma
  useEffect(() => {
    if (!containerRef.current || !graph) return;

    // Create Sigma instance
    const sigma = new Sigma(graph, containerRef.current, {
      renderLabels: true,
      labelSize: 12,
      labelColor: { color: '#fff' },
      labelFont: 'Inter, sans-serif',
      defaultEdgeColor: '#444',
      minCameraRatio: 0.1,
      maxCameraRatio: 10,
      // Node reducers for highlighting
      nodeReducer: (node, data) => {
        const res = { ...data };

        // Highlight selected node
        if (node === selectedNodeId) {
          res.highlighted = true;
          res.size = (data.size as number) * 1.5;
        }

        // Highlight search results
        if (highlightedNodes?.has(node)) {
          res.color = '#FFD700'; // Gold
        }

        // Dim non-neighbors when hovering
        if (hoveredNode && hoveredNode !== node) {
          const neighbors = graph.neighbors(hoveredNode);
          if (!neighbors.includes(node)) {
            res.color = '#333';
            res.label = '';
          }
        }

        return res;
      },
      edgeReducer: (edge, data) => {
        const res = { ...data };

        // Highlight edges connected to selected node
        if (selectedNodeId) {
          const [source, target] = graph.extremities(edge);
          if (source !== selectedNodeId && target !== selectedNodeId) {
            res.color = '#222';
          }
        }

        // Dim edges when hovering
        if (hoveredNode) {
          const [source, target] = graph.extremities(edge);
          if (source !== hoveredNode && target !== hoveredNode) {
            res.hidden = true;
          }
        }

        return res;
      },
    });

    // Event handlers
    sigma.on('clickNode', ({ node }) => {
      onNodeClick(node);
    });

    sigma.on('enterNode', ({ node }) => {
      setHoveredNode(node);
      containerRef.current!.style.cursor = 'pointer';
    });

    sigma.on('leaveNode', () => {
      setHoveredNode(null);
      containerRef.current!.style.cursor = 'default';
    });

    sigmaRef.current = sigma;

    // Start ForceAtlas2 layout
    const layout = new FA2Layout(graph, {
      settings: {
        gravity: 1,
        scalingRatio: 2,
        strongGravityMode: true,
        slowDown: 10,
        barnesHutOptimize: true,
        barnesHutTheta: 0.5,
      },
    });
    layout.start();
    layoutRef.current = layout;

    // Stop layout after 5 seconds
    const layoutTimeout = setTimeout(() => {
      layout.stop();
    }, 5000);

    return () => {
      clearTimeout(layoutTimeout);
      layout.stop();
      sigma.kill();
    };
  }, [graph, selectedNodeId, hoveredNode, highlightedNodes, onNodeClick]);

  // Refresh on state changes
  useEffect(() => {
    sigmaRef.current?.refresh();
  }, [selectedNodeId, hoveredNode, highlightedNodes]);

  return (
    <div ref={containerRef} className="sigma-container">
      {/* Hover tooltip */}
      {hoveredNode && graph && (
        <NodeTooltip
          graph={graph}
          nodeId={hoveredNode}
          container={containerRef.current}
          sigma={sigmaRef.current}
        />
      )}
    </div>
  );
}

// Node tooltip component
interface NodeTooltipProps {
  graph: Graph;
  nodeId: string;
  container: HTMLElement | null;
  sigma: Sigma | null;
}

function NodeTooltip({ graph, nodeId, container, sigma }: NodeTooltipProps) {
  const [position, setPosition] = useState({ x: 0, y: 0 });

  useEffect(() => {
    if (!sigma || !container) return;

    const updatePosition = () => {
      const nodeData = graph.getNodeAttributes(nodeId);
      const viewportPos = sigma.graphToViewport({
        x: nodeData.x,
        y: nodeData.y,
      });
      setPosition({ x: viewportPos.x + 20, y: viewportPos.y - 20 });
    };

    updatePosition();
    sigma.on('afterRender', updatePosition);

    return () => {
      sigma.off('afterRender', updatePosition);
    };
  }, [graph, nodeId, sigma, container]);

  const nodeData = graph.getNodeAttributes(nodeId);

  return (
    <div
      className="node-tooltip"
      style={{ left: position.x, top: position.y }}
    >
      <div className="text-sm font-medium truncate">
        {nodeData.label}
      </div>
      <div className="text-xs text-gray-400 mt-1">
        {nodeData.nodeType === 'memory' ? 'Memory' : 'Document'}
        {' | '}
        {nodeData.workspaceSlug}
      </div>
      {nodeData.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {nodeData.tags.slice(0, 3).map((tag: string) => (
            <span
              key={tag}
              className="tag-badge tag-badge-blue"
            >
              {tag}
            </span>
          ))}
          {nodeData.tags.length > 3 && (
            <span className="text-xs text-gray-500">
              +{nodeData.tags.length - 3} more
            </span>
          )}
        </div>
      )}
    </div>
  );
}
