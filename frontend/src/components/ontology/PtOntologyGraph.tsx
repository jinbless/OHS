import React, { useEffect, useRef, useState } from 'react';
import { Network } from 'vis-network';
import { DataSet } from 'vis-data';
import type { GraphData } from '../../api/ontologyApi';

interface PtOntologyGraphProps {
  data: GraphData;
  onNodeClick?: (nodeId: string, group: string) => void;
  height?: string;
}

const GROUP_COLORS: Record<string, string> = {
  article: '#4FC3F7',
  norm: '#81C784',
  guide: '#FFB74D',
  unknown: '#BDBDBD',
};

const PtOntologyGraph: React.FC<PtOntologyGraphProps> = ({
  data,
  onNodeClick,
  height = '600px',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current || !data.nodes.length) return;

    const nodes = new DataSet(
      data.nodes.map((n) => ({
        id: n.id,
        label: n.label,
        group: n.group,
        shape: n.shape || 'dot',
        color: typeof n.color === 'string' ? n.color : GROUP_COLORS[n.group] || '#BDBDBD',
        font: { size: 11, color: '#333', multi: 'md' },
        value: n.value || 1,
        borderWidth: 2,
        shadow: true,
      }))
    );

    const edges = new DataSet(
      data.edges.map((e, i) => ({
        id: `e_${i}`,
        from: e.from,
        to: e.to,
        label: e.label || '',
        dashes: e.dashes || false,
        font: { size: 9, color: '#666', strokeWidth: 0, background: 'white' },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
        color: { color: '#999', opacity: 0.7 },
        smooth: { enabled: true, type: 'curvedCW', roundness: 0.2 },
      }))
    );

    const options = {
      physics: {
        enabled: true,
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -30,
          centralGravity: 0.005,
          springLength: 150,
          springConstant: 0.08,
          damping: 0.4,
        },
        stabilization: {
          iterations: 200,
          updateInterval: 25,
        },
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
        zoomView: true,
        dragView: true,
        navigationButtons: true,
      },
      nodes: {
        borderWidth: 2,
        shadow: true,
        font: { size: 11 },
      },
      edges: {
        width: 1,
        shadow: false,
      },
      groups: {
        article: {
          shape: 'box',
          color: { background: '#4FC3F7', border: '#0288D1' },
          font: { color: '#fff', size: 12, bold: { color: '#fff' } },
        },
        norm: {
          shape: 'ellipse',
          color: { background: '#81C784', border: '#388E3C' },
          font: { color: '#fff', size: 10 },
        },
        guide: {
          shape: 'diamond',
          color: { background: '#FFB74D', border: '#F57C00' },
          font: { color: '#333', size: 10 },
        },
      },
    };

    const network = new Network(containerRef.current, { nodes, edges }, options);
    networkRef.current = network;

    network.on('click', (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0] as string;
        const node = data.nodes.find((n) => n.id === nodeId);
        setSelectedNode(nodeId);
        if (onNodeClick && node) {
          onNodeClick(nodeId, node.group);
        }
      } else {
        setSelectedNode(null);
      }
    });

    return () => {
      network.destroy();
      networkRef.current = null;
    };
  }, [data]);

  const handleZoomFit = () => {
    networkRef.current?.fit({ animation: true });
  };

  return (
    <div className="relative">
      <div
        ref={containerRef}
        style={{ height, width: '100%' }}
        className="border rounded-lg bg-white"
      />
      {/* Legenda */}
      <div className="absolute top-3 left-3 bg-white/90 backdrop-blur rounded-lg p-3 shadow-sm text-xs">
        <div className="font-semibold mb-2 text-gray-700">Legenda</div>
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <span className="w-4 h-3 rounded-sm" style={{ background: '#4FC3F7' }} />
            <span>Artigo Legal</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-3 rounded-full" style={{ background: '#81C784' }} />
            <span>Proposição Normativa</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rotate-45" style={{ background: '#FFB74D' }} />
            <span>KOSHA GUIDE</span>
          </div>
        </div>
      </div>
      {/* Controles */}
      <div className="absolute top-3 right-3 flex flex-col gap-1">
        <button
          onClick={handleZoomFit}
          className="bg-white/90 backdrop-blur shadow-sm rounded-lg px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
        >
          Ver Tudo
        </button>
      </div>
      {/* Contagem de nós */}
      <div className="absolute bottom-3 left-3 bg-white/90 backdrop-blur rounded-lg px-3 py-1.5 shadow-sm text-xs text-gray-500">
        {data.nodes.length} nós / {data.edges.length} arestas
        {selectedNode && <span className="ml-2 text-blue-600 font-medium">{selectedNode}</span>}
      </div>
    </div>
  );
};

export default PtOntologyGraph;
