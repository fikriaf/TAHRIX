"use client";

import { motion } from "framer-motion";
import {
  ChartLineUp,
  MagnifyingGlass,
  ShieldCheck,
  FileSearchIcon,
  ClockCounterClockwise,
  ShareNetwork,
} from "@phosphor-icons/react";

const features = [
  {
    icon: MagnifyingGlass,
    title: "Agentic Investigation",
    description:
      "Autonomous AI formulates hypotheses, queries on-chain data, and traces multi-hop transactions across Ethereum, Solana, Bitcoin, and beyond.",
  },
  {
    icon: ChartLineUp,
    title: "Graph Neural Network",
    description:
      "ONNX-based GAT model scores wallet risk by learning topological patterns in transaction graphs — illicit probability in milliseconds.",
  },
  {
    icon: ShieldCheck,
    title: "Sanctions Screening",
    description:
      "Real-time OFAC, UN, and EU sanctions list checks. Automatic flagging with severity scoring and audit trail generation.",
  },
  {
    icon: FileSearchIcon,
    title: "OSINT Intelligence",
    description:
      "Deep web, social media, and dark web monitoring. Entity resolution linking blockchain addresses to real-world identities.",
  },
  {
    icon: ClockCounterClockwise,
    title: "Temporal Analysis",
    description:
      "Chronological transaction reconstruction with anomaly detection. Identify layering, mixing, and rapid movement patterns.",
  },
  {
    icon: ShareNetwork,
    title: "Cross-Chain Tracing",
    description:
      "Bridge event detection across Wormhole, LayerZero, and CCTP. Follow funds as they hop between L1s, L2s, and alt-L1s.",
  },
];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.1 },
  },
};

const itemVariants = {
  hidden: { y: 32, opacity: 0 },
  visible: {
    y: 0,
    opacity: 1,
    transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] },
  },
};

export default function Features() {
  return (
    <section id="features" className="relative py-28 md:py-36">
      <div className="max-w-[1400px] mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] }}
          className="max-w-2xl mb-20"
        >
          <div className="text-xs font-medium text-accent uppercase tracking-[0.2em] mb-4">
            Capabilities
          </div>
          <h2 className="text-3xl md:text-4xl lg:text-5xl font-semibold tracking-tight text-text-primary mb-5">
            Intelligence at Every Layer
          </h2>
          <p className="text-base md:text-lg text-text-secondary leading-relaxed max-w-[60ch]">
            From on-chain tracing to open-source intelligence, TAHRIX stitches
            disparate signals into a unified forensic picture.
          </p>
        </motion.div>

        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"
        >
          {features.map((f, i) => (
            <motion.div
              key={i}
              variants={itemVariants}
              className="group relative p-7 rounded-xl border border-border bg-surface/60 hover:bg-surface-raised/80 transition-all duration-500"
            >
              <div className="absolute inset-0 rounded-xl border border-transparent group-hover:border-accent/10 transition-colors duration-500" />

              <div className="relative">
                <div className="w-11 h-11 rounded-lg bg-accent/8 border border-accent/15 flex items-center justify-center mb-5 group-hover:bg-accent/12 transition-colors duration-300">
                  <span className="w-5 h-5 text-accent flex items-center justify-center">
                    <f.icon weight="duotone" />
                  </span>
                </div>

                <h3 className="text-base font-semibold text-text-primary mb-2.5 tracking-tight">
                  {f.title}
                </h3>
                <p className="text-sm leading-relaxed text-text-secondary max-w-[36ch]">
                  {f.description}
                </p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
