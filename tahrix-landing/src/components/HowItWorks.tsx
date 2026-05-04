"use client";

import { motion } from "framer-motion";
import {
  MagnifyingGlass,
  Brain,
  ShieldWarning,
  FileText,
} from "@phosphor-icons/react";

const steps = [
  {
    number: "01",
    icon: MagnifyingGlass,
    title: "Input",
    description:
      "Submit a blockchain address, ENS name, or transaction hash. TAHRIX normalizes and resolves the target across all supported chains.",
  },
  {
    number: "02",
    icon: Brain,
    title: "Autonomous Investigation",
    description:
      "The AI agent spawns sub-tasks: trace fund flows, query sanctions databases, fetch on-chain metadata, and probe OSINT channels — all in parallel.",
  },
  {
    number: "03",
    icon: ShieldWarning,
    title: "Risk Scoring",
    description:
      "GNN inference, anomaly detection, and centrality analysis converge into a composite risk score with transparent component breakdown.",
  },
  {
    number: "04",
    icon: FileText,
    title: "Forensic Report",
    description:
      "A structured PDF report is generated with evidence chain, risk visualization, and audit trail — ready for compliance submission.",
  },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="relative py-28 md:py-36 bg-surface/40">
      <div className="max-w-[1400px] mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] }}
          className="max-w-2xl mb-20"
        >
          <div className="text-xs font-medium text-accent uppercase tracking-[0.2em] mb-4">
            Process
          </div>
          <h2 className="text-3xl md:text-4xl lg:text-5xl font-semibold tracking-tight text-text-primary mb-5">
            From Suspicion to Evidence
          </h2>
          <p className="text-base md:text-lg text-text-secondary leading-relaxed max-w-[60ch]">
            TAHRIX compresses hours of manual blockchain analysis into minutes
            of autonomous investigation.
          </p>
        </motion.div>

        <div className="relative">
          {/* Connecting line */}
          <div className="absolute left-[27px] md:left-[35px] top-0 bottom-0 w-px bg-gradient-to-b from-accent/40 via-accent/20 to-transparent hidden md:block" />

          <div className="space-y-12 md:space-y-16">
            {steps.map((step, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: i % 2 === 0 ? -40 : 40 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{
                  duration: 0.7,
                  delay: i * 0.1,
                  ease: [0.22, 1, 0.36, 1] as [number, number, number, number],
                }}
                className="relative flex gap-6 md:gap-10 items-start"
              >
                {/* Step indicator */}
                <div className="relative z-10 flex-shrink-0 w-14 h-14 md:w-[72px] md:h-[72px] rounded-xl bg-surface border border-border flex flex-col items-center justify-center">
                  <span className="text-[10px] font-mono text-accent leading-none">
                    {step.number}
                  </span>
                  <span className="w-5 h-5 md:w-6 md:h-6 text-text-primary mt-1 flex items-center justify-center">
                    <step.icon weight="duotone" />
                  </span>
                </div>

                {/* Content */}
                <div className="pt-1 md:pt-2">
                  <h3 className="text-lg md:text-xl font-semibold text-text-primary mb-2 tracking-tight">
                    {step.title}
                  </h3>
                  <p className="text-sm md:text-base text-text-secondary leading-relaxed max-w-[52ch]">
                    {step.description}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
