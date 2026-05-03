# MVP Teknikal: Agentic AI Blockchain untuk Cyber Intelligence
**Versi:** 1.0  
**Penulis:** Fikri Armia Fahmi (2023071018)  
**Tanggal:** 30 April 2026  
**Mata Kuliah:** Blockchain Fundamentals — Universitas Pembangunan Jaya

---

## Daftar Isi
1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Scope MVP vs Roadmap Penuh](#2-scope-mvp-vs-roadmap-penuh)
3. [Arsitektur Sistem Lengkap](#3-arsitektur-sistem-lengkap)
4. [Katalog External API](#4-katalog-external-api)
5. [Data Model & Graph Schema](#5-data-model--graph-schema)
6. [Arsitektur Agentic AI (Cognitive Loop)](#6-arsitektur-agentic-ai-cognitive-loop)
7. [Alur Sistem End-to-End](#7-alur-sistem-end-to-end)
8. [Tech Stack Lengkap](#8-tech-stack-lengkap)
9. [Infrastruktur & Deployment](#9-infrastruktur--deployment)
10. [Keamanan & Compliance](#10-keamanan--compliance)
11. [Matriks Fitur: MVP vs Phase 2 vs Phase 3](#11-matriks-fitur-mvp-vs-phase-2-vs-phase-3)
12. [Risiko Teknikal & Mitigasi](#12-risiko-teknikal--mitigasi)
13. [Estimasi Biaya & Sumber Daya](#13-estimasi-biaya--sumber-daya)
14. [Roadmap Pengembangan](#14-roadmap-pengembangan)

---

## 1. Ringkasan Eksekutif

Sistem **Agentic AI Blockchain Cyber Intelligence (AABCI)** adalah platform investigasi kripto otonom yang menggabungkan tiga paradigma teknikal mutakhir:

1. **Agentic AI** — AI yang mampu merumuskan hipotesis, mengeksekusi investigasi, dan mereflek hasil secara mandiri tanpa prompt manusia di setiap langkah.
2. **Graph Neural Network (GNN)** — Model machine learning berbasis struktur graph untuk mendeteksi pola transaksi mencurigakan yang tidak dapat ditangkap oleh rule-based system.
3. **Blockchain Evidence Chain** — Penyimpanan bukti investigasi secara immutable dan terdesentralisasi untuk memenuhi standar audit dan forensik digital.

**Target pengguna utama (MVP):** Analis keamanan siber, tim compliance exchange kripto Indonesia, dan investigator keuangan digital yang membutuhkan alat investigasi on-chain yang dapat dioperasikan tanpa expertise mendalam terhadap blockchain.

**Proposi nilai utama:** Meningkatkan produktivitas investigasi 5–8× dibandingkan metode manual, dengan kemampuan cross-chain tracing lintas Ethereum, Solana, Base, Polygon, dan BNB Chain dalam satu antarmuka.

---

## 2. Scope MVP vs Roadmap Penuh

### 2.1 Definisi MVP (Minimum Viable Product)

MVP AABCI mencakup kemampuan inti yang membuktikan dua hipotesis fundamental:

> **Hipotesis 1:** Agentic AI dapat secara otonom melakukan investigasi transaksi blockchain dari wallet input hingga risk report tanpa instruksi manual setiap tahap.  
> **Hipotesis 2:** GNN dapat mendeteksi pola transaksi ilegal (mixer, layering, fan-out) dengan akurasi yang secara statistically significant melampaui rule-based baseline.

### 2.2 Batasan MVP

| Dimensi | Dalam Scope MVP | Di Luar Scope MVP |
|---|---|---|
| **Blockchain** | Ethereum, Solana | BSC, Polygon, Avalanche |
| **Cross-chain** | LayerZero + Wormhole (read-only) | Axelar, Stargate, Synapse |
| **Input** | Wallet address, TX hash | Email, phone, domain OSINT |
| **GNN** | Node classification (illicit/licit) | Link prediction, temporal GNN |
| **Evidence** | IPFS hash + metadata | On-chain smart contract write |
| **Alert** | Telegram Bot | WhatsApp, Email, Slack |
| **Visualisasi** | D3.js graph statik | Real-time streaming graph |
| **Compliance** | OFAC sanctions screening | PPATK, FinCEN format report |
| **Auth** | API Key + JWT | OAuth2, MetaMask login |

---

## 3. Arsitektur Sistem Lengkap

Sistem AABCI terdiri dari **enam layer** yang tersusun secara vertikal, dengan masing-masing layer memiliki tanggung jawab yang terisolasi dan berkomunikasi melalui interface yang terdefinisi.

### 3.1 Layer 1: Storage

#### Neo4j AuraDB (Graph Database)
Menyimpan seluruh entitas dan relasi dalam bentuk property graph. Neo4j dipilih karena kemampuan native graph traversal yang secara performa sangat superior dibandingkan relational database untuk query multi-hop.

**Tipe Node yang disimpan:**
- `Wallet` — alamat blockchain dengan properti chain, balance, first_seen, last_seen, risk_score
- `Transaction` — hash transaksi dengan properti value, timestamp, gas, status
- `Entity` — identitas yang ter-resolve (exchange, mixer, darknet)
- `BridgeEvent` — event cross-chain dengan properti source_chain, dest_chain, protocol
- `InvestigationCase` — metadata case dengan properti analyst, created_at, status

#### PostgreSQL (Relational — Case Management)
Menyimpan data operasional: user accounts, API keys, investigasi case metadata, audit log operasi.

#### Redis (In-Memory Cache)
Caching hasil query GNN dan risk score untuk wallet yang sering diakses. TTL default: 1 jam untuk risk score, 24 jam untuk entity labels.

#### IPFS (Decentralized Evidence Store)
Setiap laporan investigasi yang diselesaikan di-pin ke IPFS untuk memperoleh Content Identifier (CID) yang immutable.

### 3.2 Layer 2: Data Ingestion

#### Multi-chain Indexer
Komponen yang bertanggung jawab mengambil data transaksi dari berbagai blockchain melalui external API. Setiap chain memiliki adapter tersendiri.

#### Real-time Stream Processor
Stream processing dilakukan dengan polling interval 30 detik terhadap Helius Webhooks (Solana) dan Alchemy WebSocket (Ethereum).

### 3.3 Layer 3: Integration

#### API Gateway
- Rate limiting berbasis API Key
- Request validation dan schema enforcement
- Logging terstruktur setiap request untuk audit trail
- Circuit breaker pattern

#### Cross-chain Bridge Adapter
Layer abstraksi untuk protokol bridge (LayerZero/Wormhole).

### 3.4 Layer 4: AI Core

#### Agent Orchestrator
Mengimplementasikan Cognitive Reasoning Loop berbasis paradigma ReAct (Reasoning + Acting).

#### Trace Engine
Komponen yang mengeksekusi graph traversal pada Neo4j untuk melacak aliran dana:
- Forward tracing
- Backward tracing
- Fan-out detection
- Fan-in detection

#### GNN Engine
Graph Attention Network (GAT) dengan:
- 3 GAT layers dengan dimensi hidden [256, 128, 64]
- 8 parallel attention heads
- Output: probability score 0.0–1.0

#### Anomaly Detector
Rule-based layer mendeteksi 17 kategori pola spesifik.

### 3.5 Layer 5: Intelligence

#### Risk Scorer
Mengaggregasi sinyal dari GNN Engine, Anomaly Detector, dan OFAC Sanctions Screening menjadi Risk Score 0–100.

#### XAI Module (SHAP)
Setiap prediksi GNN disertai SHAP values.

#### Entity Resolution Engine
Menggunakan heuristik untuk menghubungkan data on-chain dengan identitas off-chain.

### 3.6 Layer 6: Output

#### Risk Dashboard
React.js dengan D3.js graph interaktif.

#### Compliance Report Generator
Menghasilkan laporan PDF terstruktur.

#### Evidence PDF + IPFS Pin
Setiap laporan di-hash SHA-256, upload ke IPFS, simpan CID di PostgreSQL.

---

## 4. Katalog External API

### 4.1 Alchemy — Ethereum & EVM Transaction Data
- Primary data source untuk Ethereum Mainnet, Base, Polygon
- Endpoint: `alchemy_getAssetTransfers`, `trace_transaction`, `eth_getTransactionByHash`

### 4.2 Helius — Solana Transaction Data & Webhooks
- Primary data source untuk Solana Mainnet
- Endpoint: `getTransactionsForAddress`, `getAssetsByOwner`, Webhooks

### 4.3 Etherscan API V2
- Supplementary data source untuk labeling entity
- Endpoint: `account/txlist`, `contract/getabi`, `token/tokeninfo`

### 4.4 Chainalysis Free Sanctions API
- Sanctions screening untuk OFAC SDN
- Endpoint: `GET /v1/sanctions/entities/{address}`

### 4.5 LayerZero API
- Cross-chain message tracking
- Endpoint: `https://scan.layerzero-api.com/v1/messages/tx/{txHash}`

### 4.6 Wormhole
- Cross-chain VAA Tracking
- Endpoint: WormholeScan API

### 4.7 Neo4j AuraDB
- Graph database untuk Transaction Graph, Entity Graph

### 4.8 PyTorch Geometric (PyG)
- GNN Framework untuk training dan inferensi

### 4.9 IPFS via Infura Gateway
- Decentralized evidence storage

### 4.10 Telegram Bot API
- Real-time alert ke analyst

---

## 5. Data Model & Graph Schema

### 5.1 Node Types
```
(:Wallet)
  - address: String (UNIQUE)
  - chain: Enum [ETH, SOL, BASE, POLYGON]
  - balance_usd: Float
  - risk_score: Float (0.0–1.0)
  - gnn_label: Enum [UNKNOWN, LICIT, ILLICIT]
  - entity_label: String

(:Transaction)
  - hash: String (UNIQUE)
  - value_usd: Float
  - timestamp: DateTime
  - anomaly_flags: List<String>

(:BridgeEvent)
  - protocol: Enum [LAYERZERO, WORMHOLE]
  - source_chain, dest_chain: Enum

(:Entity)
  - name: String
  - type: Enum [EXCHANGE, MIXER, DARKNET, DEFI]

(:InvestigationCase)
  - case_id: String
  - status: Enum
  - ipfs_cid: String
```

### 5.2 Relationship Types
```
(:Wallet)-[:SENT_TO]->(:Wallet)
(:Wallet)-[:BRIDGE_OUT]->(:BridgeEvent)->[:BRIDGE_IN]->(:Wallet)
(:Wallet)-[:LABELED_AS]->(:Entity)
(:InvestigationCase)-[:INVESTIGATES]->(:Wallet)
```

---

## 6. Arsitektur Agentic AI (Cognitive Loop)

### 6.1 Cognitive Loop: Think → Act → Observe → Reflect

```
┌─────────────────────────────────────────────────────────┐
│                   AGENT ORCHESTRATOR                     │
│   INPUT: Wallet Address / TX Hash                        │
│                    │                                     │
│                    ▼                                     │
│   THINK → ACT → OBSERVE → REFLECT → ...                  │
│                    │                                     │
│          ┌─────────┴─────────┐                          │
│          ▼                   ▼                          │
│   [Lanjut THINK]    [Stopping Criterion]                │
│                     - Max 5 iterasi                     │
│                     - Confidence > 0.85                │
│                     - Critical finding                  │
│                                  │                      │
│                                  ▼                      │
│                          GENERATE REPORT                 │
└─────────────────────────────────────────────────────────┘
```

### 6.2 Tool Registry Agent

| Tool ID | Nama | Provider |
|---|---|---|
| T01 | `get_eth_transactions` | Alchemy |
| T02 | `get_sol_transactions` | Helius |
| T03 | `check_sanctions` | Chainalysis |
| T04 | `run_gnn_inference` | Local PyG |
| T05 | `trace_forward` | Neo4j |
| T06 | `trace_backward` | Neo4j |
| T07 | `check_bridge_lz` | LayerZero Scan |
| T08 | `check_bridge_wh` | WormholeScan |
| T09 | `get_entity_label` | Etherscan |
| T10 | `detect_anomaly` | Local Rules |
| T11 | `generate_report` | Internal |
| T12 | `send_alert` | Telegram API |

---

## 7. Alur Sistem End-to-End

1. **INPUT:** Analyst memasukkan wallet address
2. **PREPROCESSING:** Cek cache Redis
3. **INITIAL SCAN:** Parallel calls ke Chainalysis, Etherscan, Alchemy
4. **AGENT COGNITIVE LOOP:** Think → Act → Observe → Reflect (10–60 detik)
5. **CROSS-CHAIN CHECK:** LayerZero/Wormhole jika ada bridge TX
6. **SCORING & REPORT:** Hitung Risk Score, generate PDF, pin IPFS
7. **OUTPUT:** Dashboard dengan Risk Score, Graph, Anomaly flags
8. **ALERT:** Telegram jika Risk Score ≥ 60

Total waktu: 20–80 detik tergantung jumlah hop dan TX

---

## 8. Tech Stack Lengkap

### 8.1 Backend
| Komponen | Teknologi |
|---|---|
| API Framework | FastAPI (Python 3.11) |
| GNN Inference | PyTorch + PyTorch Geometric |
| XAI | SHAP |
| Graph Query | neo4j Python driver |
| Task Queue | Celery + Redis |
| ORM | SQLAlchemy 2.0 |
| IPFS Client | py-ipfs-client |
| PDF Generator | WeasyPrint |
| HTTP Client | httpx |

### 8.2 Frontend
| Komponen | Teknologi |
|---|---|
| UI Framework | React 18.x |
| Graph Viz | D3.js 7.x |
| State Management | Zustand |
| API Client | TanStack Query |
| UI Components | Shadcn/ui |
| Charts | Recharts |
| Styling | Tailwind CSS |

---

## 9. Infrastruktur & Deployment

### 9.1 Arsitektur Deployment
- **Frontend:** Vercel (React SPA)
- **Backend:** Railway/Render (FastAPI + Celery)
- **Database:** Supabase PostgreSQL, Neo4j AuraDB
- **Cache:** Upstash Redis
- **Evidence:** Infura IPFS

### 9.2 Environment Variables
```
ALCHEMY_API_KEY, HELIUS_API_KEY, ETHERSCAN_API_KEY
CHAINALYSIS_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
DATABASE_URL, REDIS_URL, INFURA_IPFS_PROJECT_ID
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SECRET_KEY
```

---

## 10. Keamanan & Compliance

### 10.1 Keamanan Aplikasi
- JWT dengan RS256 algorithm
- API Key dengan bcrypt hashing
- RBAC: analyst, supervisor, admin
- Rate limiting 100 req/menit per API key
- HTTPS/TLS 1.3

### 10.2 Privasi & Compliance
- Data Minimization
- Kepatuhan UU PDP Indonesia
- Hak penghapusan data
- Data retention: 2 tahun

---

## 11. Matriks Fitur

| Fitur | MVP | Phase 2 | Phase 3 |
|---|---|---|---|
| Blockchain | ETH + SOL | + BSC, Polygon, Base | + Avalanche, TRON, BTC |
| Input | Wallet, TX hash | + Email, Domain | + Phone, IP |
| GNN | GAT node classification | + Temporal GNN | + Heterogeneous GNN |
| Cross-chain | LZ + Wormhole | + Axelar, Stargate | + Intent-based |
| Alert | Telegram | + Email, Slack | + WhatsApp |
| Report | PDF internal | + PPATK format | + FinCEN SAR |

---

## 12. Risiko Teknikal & Mitigasi

| Risiko | Mitigasi |
|---|---|
| GNN false positive | Human-in-the-loop validation |
| API rate limit | Circuit breaker + fallback |
| Neo4j query timeout | Hop limit + pagination |
| IPFS unavailable | Local backup + retry |

---

## 13. Estimasi Biaya

| Komponen | Biaya |
|---|---|
| Neo4j AuraDB Professional | $65/bulan |
| Supabase Pro | $25/bulan |
| Upstash Redis | $5/bulan |
| Alchemy Growth | $49/bulan |
| Helius Starter | $49/bulan |
| Railway Hobby | $5/bulan |
| **Total MVP** | **~$200/bulan** |

---

## 14. Roadmap Pengembangan

- **Bulan 1–3 (MVP):** Core investigation flow, basic GNN, Ethereum + Solana
- **Bulan 4–8 (Phase 2):** Multi-chain, OSINT enrichment, batch analysis
- **Bulan 9–18 (Phase 3):** Advanced GNN, real-time streaming, SIEM integration