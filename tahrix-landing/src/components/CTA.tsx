"use client";

import { motion } from "framer-motion";
import { ArrowRight, ShieldCheck } from "@phosphor-icons/react";

export default function CTA() {
  return (
    <section id="access" className="relative py-28 md:py-36">
      <div className="max-w-[1400px] mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 32 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] }}
          className="relative rounded-2xl overflow-hidden"
        >
          {/* Background layers */}
          <div className="absolute inset-0 bg-surface border border-border rounded-2xl" />
          <div className="absolute inset-0 bg-gradient-to-br from-accent/5 via-transparent to-transparent rounded-2xl" />
          <div className="absolute top-0 right-0 w-[500px] h-[500px] rounded-full bg-accent/4 blur-[120px] pointer-events-none" />

          {/* Grid overlay */}
          <div className="absolute inset-0 bg-grid opacity-30 rounded-2xl" />

          <div className="relative px-8 py-20 md:px-16 md:py-24 text-center">
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              whileInView={{ scale: 1, opacity: 1 }}
              viewport={{ once: true }}
              transition={{ delay: 0.2, duration: 0.6 }}
              className="w-14 h-14 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center mx-auto mb-8"
            >
              <span className="w-7 h-7 text-accent flex items-center justify-center">
                <ShieldCheck weight="fill" />
              </span>
            </motion.div>

            <h2 className="text-3xl md:text-4xl lg:text-5xl font-semibold tracking-tight text-text-primary mb-5 max-w-2xl mx-auto">
              Ready to Investigate?
            </h2>
            <p className="text-base md:text-lg text-text-secondary leading-relaxed max-w-xl mx-auto mb-10">
              Deploy autonomous blockchain forensics in minutes. No manual
              tracing. No blind spots.
            </p>

            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <a
                href="https://tahrix.serveousercontent.com"
                target="_blank"
                rel="noopener noreferrer"
                className="group inline-flex items-center justify-center gap-2.5 px-8 py-4 rounded-xl bg-accent text-white font-medium text-sm hover:bg-accent/90 active:scale-[0.98] active:-translate-y-[1px] transition-all duration-200 glow-pulse"
              >
                Access Platform
                <span className="w-4 h-4 group-hover:translate-x-0.5 transition-transform flex items-center justify-center">
                  <ArrowRight />
                </span>
              </a>
              <a
                href="https://github.com/fikriaf/TAHRIX"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl border border-border bg-surface text-text-primary font-medium text-sm hover:bg-surface-raised active:scale-[0.98] transition-all duration-200"
              >
                View on GitHub
              </a>
            </div>

            <p className="text-xs text-text-tertiary mt-8">
              Self-hosted. Open source. MIT licensed.
            </p>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
