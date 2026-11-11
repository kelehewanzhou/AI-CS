'use client';

import { useEffect, useRef } from 'react';
import type { EdgeView, GraphNode } from '@/lib/types';

export default function GraphVisualization({ nodes, edges }: { nodes: GraphNode[]; edges: EdgeView[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    let graph: import('cytoscape').Core | undefined;

    if (!containerRef.current) return undefined;
    import('cytoscape').then((module) => {
      if (disposed || !containerRef.current) return;
      const cytoscape = module.default;
      graph = cytoscape({
        container: containerRef.current,
        elements: [
          ...nodes.map((node) => ({ data: { id: node.node_id, label: node.title, course: node.course_code } })),
          ...edges.map((edge) => ({ data: { id: edge.edge_id, source: edge.source_id, target: edge.target_id, label: edge.display_label } })),
        ],
        style: [
          { selector: 'node', style: { label: 'data(label)', 'background-color': '#2563eb', color: '#172033', 'font-size': '12px', 'text-valign': 'bottom', 'text-margin-y': 8, width: '30px', height: '30px' } },
          { selector: 'edge', style: { label: 'data(label)', 'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'line-color': '#a7b5c9', 'target-arrow-color': '#a7b5c9', color: '#52627a', 'font-size': '9px', 'text-background-color': '#ffffff', 'text-background-opacity': 1, 'text-background-padding': '2px' } },
        ],
        layout: { name: 'cose', animate: false, padding: 40 },
      });
      graph.on('tap', 'node', (event) => {
        window.location.href = `/node/?id=${encodeURIComponent(event.target.id())}`;
      });
    });

    return () => {
      disposed = true;
      graph?.destroy();
    };
  }, [nodes, edges]);

  return <div className="graph-canvas" ref={containerRef} aria-label="知识图谱可视化" />;
}
