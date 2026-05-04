import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TAHRIX — Agentic Blockchain Intelligence",
  description: "Autonomous AI-driven blockchain investigation platform. Detect, trace, and analyze cryptocurrency crime with graph neural networks and multi-chain forensics.",
  keywords: ["blockchain", "forensics", "AI", "cryptocurrency", "investigation", "GNN", "OSINT"],
  openGraph: {
    title: "TAHRIX — Agentic Blockchain Intelligence",
    description: "Autonomous AI-driven blockchain investigation platform.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark antialiased bg-noise`}
    >
      <body className="min-h-[100dvh] flex flex-col bg-background text-foreground">
        {children}
      </body>
    </html>
  );
}
