"use client";

import { motion } from "framer-motion";
import { ArrowRight, Fingerprint, Brain, Globe } from "@phosphor-icons/react";
import NetworkVisual from "./NetworkVisual";

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1, delayChildren: 0.2 },
  },
};

const itemVariants = {
  hidden: { y: 24, opacity: 0 },
  visible: {
    y: 0,
    opacity: 1,
    transition: { duration: 0.7, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] },
  },
};

export default function Hero() {
  return (
    <section className="relative min-h-[100dvh] flex items-center overflow-hidden bg-grid">
      {/* Ambient glow */}
      <div className="absolute top-[-10%] right-[-5%] w-[600px] h-[600px] rounded-full bg-accent/5 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[400px] h-[400px] rounded-full bg-accent/3 blur-[100px] pointer-events-none" />

      <div className="max-w-[1400px] mx-auto px-6 py-32 w-full grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-8 items-center">
        {/* Left: Content */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="relative z-10 order-2 lg:order-1"
        >
          <motion.div
            variants={itemVariants}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-accent/20 bg-accent/5 text-xs font-medium text-accent mb-8"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
            Now with GNN-powered risk prediction
          </motion.div>

          <motion.h1
            variants={itemVariants}
            className="text-4xl md:text-5xl lg:text-6xl font-semibold tracking-tighter leading-[1.05] text-text-primary mb-6"
          >
            Trace the Untraceable.
            <br />
            <span className="text-text-tertiary">Expose the Invisible.</span>
          </motion.h1>

          <motion.p
            variants={itemVariants}
            className="text-base md:text-lg text-text-secondary leading-relaxed max-w-[54ch] mb-10"
          >
            TAHRIX deploys autonomous AI agents across blockchain networks to
            investigate wallets, trace transactions, and generate forensic
            intelligence in real time.
          </motion.p>

          <motion.div
            variants={itemVariants}
            className="flex flex-col sm:flex-row gap-4 mb-16"
          >
            <a
              href="#access"
              className="group inline-flex items-center justify-center gap-2.5 px-7 py-3.5 rounded-xl bg-accent text-white font-medium text-sm hover:bg-accent/90 active:scale-[0.98] active:-translate-y-[1px] transition-all duration-200 glow-pulse"
            >
              Start Investigation
              <span className="w-4 h-4 group-hover:translate-x-0.5 transition-transform flex items-center justify-center">
                <ArrowRight />
              </span>
            </a>
            <a
              href="#how-it-works"
              className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl border border-border bg-surface text-text-primary font-medium text-sm hover:bg-surface-raised active:scale-[0.98] transition-all duration-200"
            >
              See How It Works
            </a>
          </motion.div>

          <motion.div
            variants={containerVariants}
            className="flex flex-wrap gap-8"
          >
            {[
              { icon: Fingerprint, label: "Multi-Chain", value: "ETH, SOL, BTC" },
              { icon: Brain, label: "AI Agent", value: "Autonomous" },
              { icon: Globe, label: "OSINT", value: "Real-Time" },
            ].map((stat) => (
              <motion.div key={stat.label} variants={itemVariants} className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-surface border border-border flex items-center justify-center">
                  <span className="w-4 h-4 text-accent flex items-center justify-center"><stat.icon /></span>
                </div>
                <div>
                  <div className="text-xs text-text-tertiary">{stat.label}</div>
                  <div className="text-sm font-medium text-text-primary">{stat.value}</div>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </motion.div>

        {/* Right: Visual */}
        <motion.div
          initial={{ opacity: 0, scale: 0.92 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 1, delay: 0.4, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] }}
          className="relative order-1 lg:order-2 h-[420px] md:h-[520px]"
        >
          <div className="absolute inset-0 rounded-2xl border border-border bg-surface/40 overflow-hidden">
            <NetworkVisual />
          </div>

          {/* Corner accents */}
          <div className="absolute top-0 left-0 w-16 h-px bg-gradient-to-r from-accent to-transparent" />
          <div className="absolute top-0 left-0 w-px h-16 bg-gradient-to-b from-accent to-transparent" />
          <div className="absolute bottom-0 right-0 w-16 h-px bg-gradient-to-l from-accent to-transparent" />
          <div className="absolute bottom-0 right-0 w-px h-16 bg-gradient-to-t from-accent to-transparent" />
        </motion.div>
      </div>
    </section>
  );
}
