"use client";

import { motion } from "framer-motion";
import { useMemo } from "react";

interface Node {
  id: number;
  x: number;
  y: number;
  size: number;
}

interface Edge {
  from: number;
  to: number;
}

function generateNetwork(count: number): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = Array.from({ length: count }, (_, i) => ({
    id: i,
    x: 20 + Math.random() * 60,
    y: 15 + Math.random() * 70,
    size: 2 + Math.random() * 4,
  }));

  const edges: Edge[] = [];
  for (let i = 0; i < count; i++) {
    const connections = 1 + Math.floor(Math.random() * 3);
    for (let j = 0; j < connections; j++) {
      const target = Math.floor(Math.random() * count);
      if (target !== i) edges.push({ from: i, to: target });
    }
  }
  return { nodes, edges };
}

export default function NetworkVisual() {
  const { nodes, edges } = useMemo(() => generateNetwork(28), []);

  return (
    <div className="relative w-full h-full min-h-[400px]">
      <svg
        viewBox="0 0 100 100"
        className="w-full h-full"
        style={{ filter: "drop-shadow(0 0 12px rgba(225,29,72,0.15))" }}
      >
        <defs>
          <linearGradient id="edgeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="rgba(225,29,72,0.3)" />
            <stop offset="100%" stopColor="rgba(225,29,72,0.05)" />
          </linearGradient>
        </defs>

        {edges.map((e, i) => {
          const n1 = nodes[e.from];
          const n2 = nodes[e.to];
          return (
            <motion.line
              key={`edge-${i}`}
              x1={n1.x}
              y1={n1.y}
              x2={n2.x}
              y2={n2.y}
              stroke="url(#edgeGrad)"
              strokeWidth={0.15}
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{
                duration: 1.2,
                delay: i * 0.02,
                ease: "easeInOut",
              }}
            />
          );
        })}

        {nodes.map((n, i) => (
          <motion.g key={n.id}>
            <motion.circle
              cx={n.x}
              cy={n.y}
              r={n.size}
              fill={i < 3 ? "#e11d48" : "#27272a"}
              stroke={i < 3 ? "rgba(225,29,72,0.4)" : "rgba(255,255,255,0.06)"}
              strokeWidth={0.3}
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{
                duration: 0.6,
                delay: i * 0.04,
                type: "spring",
                stiffness: 200,
                damping: 15,
              }}
            />
            {i < 3 && (
              <motion.circle
                cx={n.x}
                cy={n.y}
                r={n.size + 2}
                fill="none"
                stroke="rgba(225,29,72,0.15)"
                strokeWidth={0.2}
                initial={{ scale: 0, opacity: 0 }}
                animate={{ scale: [1, 1.8, 1], opacity: [0.3, 0, 0.3] }}
                transition={{
                  duration: 3,
                  repeat: Infinity,
                  delay: i * 0.8,
                }}
              />
            )}
          </motion.g>
        ))}
      </svg>

      {/* Floating stats cards */}
      <motion.div
        className="absolute top-[15%] right-[10%] glass rounded-lg px-3 py-2"
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 1.2, duration: 0.6 }}
      >
        <div className="text-[10px] text-text-tertiary uppercase tracking-wider">Risk Score</div>
        <div className="text-sm font-mono font-semibold text-accent">94.2%</div>
      </motion.div>

      <motion.div
        className="absolute bottom-[20%] left-[5%] glass rounded-lg px-3 py-2"
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 1.5, duration: 0.6 }}
      >
        <div className="text-[10px] text-text-tertiary uppercase tracking-wider">Nodes Traced</div>
        <div className="text-sm font-mono font-semibold text-text-primary">12,847</div>
      </motion.div>

      <motion.div
        className="absolute top-[55%] right-[5%] glass rounded-lg px-3 py-2"
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 1.8, duration: 0.6 }}
      >
        <div className="text-[10px] text-text-tertiary uppercase tracking-wider">Sanctions Hit</div>
        <div className="text-sm font-mono font-semibold text-accent">OFAC Match</div>
      </motion.div>
    </div>
  );
}
