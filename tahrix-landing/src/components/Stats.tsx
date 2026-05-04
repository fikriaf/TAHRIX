"use client";

import { motion, useMotionValue, useTransform, animate } from "framer-motion";
import { useEffect } from "react";
import { Wallet, Link, FileText, ShieldCheck } from "@phosphor-icons/react";

function AnimatedCounter({ target, suffix = "" }: { target: number; suffix?: string }) {
  const count = useMotionValue(0);
  const rounded = useTransform(count, (v) => Math.floor(v).toLocaleString() + suffix);

  useEffect(() => {
    const controls = animate(count, target, { duration: 2, ease: "easeOut" });
    return controls.stop;
  }, [count, target]);

  return <motion.span>{rounded}</motion.span>;
}

const stats = [
  {
    icon: Wallet,
    value: 2847,
    suffix: "",
    label: "Wallets Investigated",
  },
  {
    icon: Link,
    value: 156,
    suffix: "K",
    label: "Transactions Traced",
  },
  {
    icon: FileText,
    value: 428,
    suffix: "",
    label: "Reports Generated",
  },
  {
    icon: ShieldCheck,
    value: 96,
    suffix: "%",
    label: "Sanctions Detection",
  },
];

export default function Stats() {
  return (
    <section id="platform" className="relative py-28 md:py-36 overflow-hidden">
      {/* Ambient glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[400px] rounded-full bg-accent/3 blur-[140px] pointer-events-none" />

      <div className="max-w-[1400px] mx-auto px-6 relative">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] }}
          className="text-center max-w-xl mx-auto mb-20"
        >
          <div className="text-xs font-medium text-accent uppercase tracking-[0.2em] mb-4">
            Platform Metrics
          </div>
          <h2 className="text-3xl md:text-4xl lg:text-5xl font-semibold tracking-tight text-text-primary mb-5">
            Built for Scale
          </h2>
          <p className="text-base md:text-lg text-text-secondary leading-relaxed">
            Production-grade infrastructure handling high-throughput blockchain
            analysis across multiple networks.
          </p>
        </motion.div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
          {stats.map((stat, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 32 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-40px" }}
              transition={{
                duration: 0.6,
                delay: i * 0.1,
                ease: [0.22, 1, 0.36, 1] as [number, number, number, number],
              }}
              className="group relative p-7 rounded-xl border border-border bg-surface/40 text-center"
            >
              <div className="w-10 h-10 rounded-lg bg-accent/8 border border-accent/15 flex items-center justify-center mx-auto mb-5 group-hover:bg-accent/12 transition-colors duration-300">
                <span className="w-5 h-5 text-accent flex items-center justify-center">
                  <stat.icon weight="duotone" />
                </span>
              </div>
              <div className="text-3xl md:text-4xl font-semibold tracking-tight text-text-primary mb-1 font-mono">
                <AnimatedCounter target={stat.value} suffix={stat.suffix} />
              </div>
              <div className="text-xs md:text-sm text-text-secondary">{stat.label}</div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
