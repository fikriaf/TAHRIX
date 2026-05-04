"use client";

import { motion } from "framer-motion";
import { ShieldCheck, GithubLogo, XLogo, Envelope } from "@phosphor-icons/react";

export default function Footer() {
  return (
    <motion.footer
      initial={{ opacity: 0 }}
      whileInView={{ opacity: 1 }}
      viewport={{ once: true }}
      transition={{ duration: 0.6 }}
      className="border-t border-border bg-surface/40"
    >
      <div className="max-w-[1400px] mx-auto px-6 py-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-12">
          {/* Brand */}
          <div className="md:col-span-1">
            <a href="#" className="flex items-center gap-2.5 mb-4">
              <div className="w-8 h-8 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center">
                <span className="w-4 h-4 text-accent flex items-center justify-center">
                  <ShieldCheck weight="fill" />
                </span>
              </div>
              <span className="text-base font-semibold tracking-tight text-text-primary">
                TAHRIX
              </span>
            </a>
            <p className="text-sm text-text-secondary leading-relaxed max-w-[36ch]">
              Autonomous blockchain forensics platform powered by agentic AI and
              graph neural networks.
            </p>
          </div>

          {/* Links */}
          <div>
            <h4 className="text-xs font-medium text-text-primary uppercase tracking-[0.15em] mb-5">
              Platform
            </h4>
            <ul className="space-y-3">
              {[
                { label: "Features", href: "#features" },
                { label: "How It Works", href: "#how-it-works" },
                { label: "GitHub", href: "https://github.com/fikriaf/TAHRIX" },
              ].map((link) => (
                <li key={link.label}>
                  <a
                    href={link.href}
                    className="text-sm text-text-secondary hover:text-text-primary transition-colors duration-300"
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {/* Connect */}
          <div>
            <h4 className="text-xs font-medium text-text-primary uppercase tracking-[0.15em] mb-5">
              Connect
            </h4>
            <div className="flex gap-3">
              <a
                href="https://github.com/fikriaf/TAHRIX"
                target="_blank"
                rel="noopener noreferrer"
                className="w-9 h-9 rounded-lg border border-border bg-surface flex items-center justify-center text-text-secondary hover:text-text-primary hover:border-accent/30 transition-all duration-300"
              >
                <span className="w-4 h-4 flex items-center justify-center">
                  <GithubLogo />
                </span>
              </a>
              <a
                href="#"
                className="w-9 h-9 rounded-lg border border-border bg-surface flex items-center justify-center text-text-secondary hover:text-text-primary hover:border-accent/30 transition-all duration-300"
              >
                <span className="w-4 h-4 flex items-center justify-center">
                  <XLogo />
                </span>
              </a>
              <a
                href="mailto:contact@tahrix.io"
                className="w-9 h-9 rounded-lg border border-border bg-surface flex items-center justify-center text-text-secondary hover:text-text-primary hover:border-accent/30 transition-all duration-300"
              >
                <span className="w-4 h-4 flex items-center justify-center">
                  <Envelope />
                </span>
              </a>
            </div>
          </div>
        </div>

        <div className="mt-16 pt-8 border-t border-border flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-xs text-text-tertiary">
            MIT License. Built by Fikri Armia Fahmi.
          </p>
          <p className="text-xs text-text-tertiary">
            Blockchain Fundamentals — Universitas Pembangunan Jaya
          </p>
        </div>
      </div>
    </motion.footer>
  );
}
