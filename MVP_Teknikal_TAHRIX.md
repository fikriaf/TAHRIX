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

```
┌─────────────────────────────────────────────────────────┐
│                    LAYER 6: OUTPUT                       │
│   Risk Dashboard │ Compliance Report │ Evidence PDF      │
│         Real-time Alert (Telegram) │ Graph Export        │
├─────────────────────────────────────────────────────────┤
│                 LAYER 5: INTELLIGENCE                    │
│   Risk Scorer │ XAI (SHAP) │ Compliance Report Generator │
│               Entity Resolution Engine                   │
├─────────────────────────────────────────────────────────┤
│                  LAYER 4: AI CORE                        │
│      Agent Orchestrator (Reasoning Loop)                 │
│  ┌───────────────────────────────────────────────────┐  │
│  │  THINK → ACT → OBSERVE → REFLECT → THINK ...     │  │
│  └───────────────────────────────────────────────────┘  │
│   Agent Memory (Short-term) │ Hypothesis Manager         │
│   Trace Engine │ GNN Engine │ Anomaly Detector            │
├─────────────────────────────────────────────────────────┤
│               LAYER 3: INTEGRATION                       │
│   API Gateway │ Rate Limiter │ Auth Middleware            │
│   Cross-chain Bridge Adapter (LayerZero/Wormhole)        │
├─────────────────────────────────────────────────────────┤
│               LAYER 2: DATA INGESTION                    │
│   Multi-chain Indexer │ Real-time Stream Processor       │
│   External API Adapters (Alchemy, Helius, Etherscan)     │
├─────────────────────────────────────────────────────────┤
│               LAYER 1: STORAGE                           │
│   Neo4j Graph DB │ PostgreSQL (Case) │ Redis (Cache)     │
│   IPFS (Evidence) │ Vector Store (Embeddings)            │
└─────────────────────────────────────────────────────────┘
```

### 3.1 Layer 1: Storage

#### Neo4j AuraDB (Graph Database)
Menyimpan seluruh entitas dan relasi dalam bentuk property graph. Neo4j dipilih karena kemampuan native graph traversal yang secara performa sangat superior dibandingkan relational database untuk query multi-hop (misalnya "temukan semua wallet yang berhubungan 3 hop dari alamat X").

**Tipe Node yang disimpan:**
- `Wallet` — alamat blockchain dengan properti chain, balance, first_seen, last_seen, risk_score
- `Transaction` — hash transaksi dengan properti value, timestamp, gas, status
- `Entity` — identitas yang ter-resolve (exchange, mixer, darknet)
- `BridgeEvent` — event cross-chain dengan properti source_chain, dest_chain, protocol
- `InvestigationCase` — metadata case dengan properti analyst, created_at, status

#### PostgreSQL (Relational — Case Management)
Menyimpan data operasional yang tidak memerlukan graph traversal: user accounts, API keys, investigasi case metadata, audit log operasi, dan konfigurasi sistem.

#### Redis (In-Memory Cache)
Caching hasil query GNN dan risk score untuk wallet yang sering diakses, menghindari re-computation yang mahal. TTL default: 1 jam untuk risk score, 24 jam untuk entity labels.

#### IPFS (Decentralized Evidence Store)
Setiap laporan investigasi yang diselesaikan di-pin ke IPFS untuk memperoleh Content Identifier (CID) yang immutable. CID ini kemudian disimpan di PostgreSQL sebagai bukti yang dapat diverifikasi publik tanpa perlu on-chain write di MVP.

---

### 3.2 Layer 2: Data Ingestion

#### Multi-chain Indexer
Komponen yang bertanggung jawab mengambil data transaksi dari berbagai blockchain melalui external API. Setiap chain memiliki adapter tersendiri yang mengimplementasikan interface `IChainAdapter` dengan metode standar: `getTransactions(address)`, `getTransaction(hash)`, `getBalance(address)`.

#### Real-time Stream Processor
Untuk MVP, stream processing dilakukan dengan polling interval 30 detik terhadap Helius Webhooks (Solana) dan Alchemy WebSocket (Ethereum) untuk transaksi baru di alamat yang sedang dimonitor. Setiap transaksi baru yang masuk trigger pipeline GNN inference dan alert evaluation.

---

### 3.3 Layer 3: Integration

#### API Gateway
Semua request dari frontend dan dari Agentic Module mengalir melalui API Gateway yang mengimplementasikan:
- Rate limiting berbasis API Key (100 req/menit untuk tier free, 1000 req/menit untuk tier analyst)
- Request validation dan schema enforcement
- Logging terstruktur setiap request untuk audit trail
- Circuit breaker pattern untuk mencegah cascade failure saat satu external API mengalami downtime

#### Cross-chain Bridge Adapter
Layer abstraksi yang menyembunyikan kompleksitas protokol bridge yang berbeda-beda. Adapter menerima `source_tx_hash` dan mengembalikan `CrossChainTrace` yang berisi rangkaian transaksi dari source chain ke destination chain, terlepas dari protocol yang digunakan (LayerZero GUID atau Wormhole VAA).

---

### 3.4 Layer 4: AI Core

Ini adalah layer paling kritis, menggabungkan tiga komponen analitik yang bekerja secara sinergis.

#### Agent Orchestrator
Mengimplementasikan Cognitive Reasoning Loop berbasis paradigma ReAct (Reasoning + Acting). Detail arsitektur dibahas di Bab 6.

#### Trace Engine
Komponen yang mengeksekusi graph traversal pada Neo4j untuk melacak aliran dana:
- **Forward tracing:** dari wallet input, temukan semua wallet tujuan hingga N hop
- **Backward tracing:** dari wallet input, temukan semua sumber dana hingga N hop
- **Fan-out detection:** identifikasi pola di mana satu wallet mendistribusikan dana ke banyak wallet dalam waktu singkat (indikasi tumbling)
- **Fan-in detection:** banyak wallet kecil mengirim ke satu wallet (konsolidasi)

Default hop limit MVP: 5 hop. Query Neo4j menggunakan Cypher dengan estimasi complexity O(n^k) di mana n = jumlah transaksi per wallet dan k = jumlah hop.

#### GNN Engine
Mengimplementasikan Graph Attention Network (GAT) yang di-training menggunakan Elliptic Bitcoin Dataset sebagai benchmark awal, kemudian di-fine-tune dengan data Ethereum yang di-label secara heuristik berdasarkan data OFAC sanctions dan known darknet addresses.

**Arsitektur model:**
- 3 GAT layers dengan dimensi hidden [256, 128, 64]
- 8 parallel attention heads di setiap layer
- Output: probability score 0.0–1.0 (0 = legitimate, 1 = illicit)
- Feature vektor per node: 165 fitur (sesuai Elliptic standard) yang mencakup time step, transaction count, total input/output, average fee, dan network centrality metrics

#### Anomaly Detector
Rule-based layer yang bekerja di atas output GNN untuk mendeteksi 17 kategori pola spesifik:

| Kode | Nama Pola | Sinyal Deteksi |
|---|---|---|
| P01 | Mixer Interaction | Transaksi ke known Tornado Cash/Sinbad addresses |
| P02 | Layering | ≥3 hop transfer dengan nilai yang hampir sama (±1%) |
| P03 | Fan-out Structuring | 1 wallet → >10 wallet dalam <1 jam |
| P04 | Fan-in Consolidation | >10 wallet → 1 wallet dalam <24 jam |
| P05 | Peeling Chain | Serangkaian TX single-hop dengan nilai berkurang gradually |
| P06 | Round-trip | Dana yang keluar kembali ke originator melalui intermediary |
| P07 | Bridge Hopping | Dana melewati >2 bridge dalam 24 jam |
| P08 | Whale Movement | Single TX > $1 juta USD |
| P09 | Dormant Reactivation | Wallet tidak aktif >180 hari tiba-tiba aktif dengan nilai besar |
| P10 | Rapid Succession | >50 TX dalam <10 menit |
| P11 | OFAC Indirect | Interaksi dengan wallet 1 hop dari sanctioned address |
| P12 | DEX Wash Trading | Beli-jual token yang sama dalam <5 menit |
| P13 | NFT Wash Trading | Transfer NFT antar wallet yang saling terhubung |
| P14 | DeFi Flash Loan | TX multi-call dengan flash loan pattern |
| P15 | Address Poisoning | Nilai sangat kecil (<$0.01) ke banyak wallet |
| P16 | Rug Pull Indicator | Developer wallet dump seluruh token dalam <1 jam |
| P17 | Sandwich Attack | MEV pattern dengan TX sebelum dan sesudah korban |

---

### 3.5 Layer 5: Intelligence

#### Risk Scorer
Mengaggregasi sinyal dari GNN Engine, Anomaly Detector, dan OFAC Sanctions Screening menjadi satu **Risk Score 0–100** dengan formula:

```
Risk Score = (GNN_score × 0.40) + (Anomaly_weight × 0.30) + 
             (Sanctions_hit × 0.20) + (Network_centrality × 0.10)
```

Risk grade:
- **0–29:** Low Risk (hijau)
- **30–59:** Medium Risk (kuning)
- **60–79:** High Risk (oranye)
- **80–100:** Critical Risk (merah) → auto-trigger alert

#### XAI Module (SHAP)
Setiap prediksi GNN disertai SHAP (SHapley Additive exPlanations) values yang menjelaskan kontribusi relatif setiap fitur terhadap skor akhir. Output berupa teks natural language: *"Alamat ini mendapat skor tinggi terutama karena: (1) interaksi dengan 3 known mixer address, (2) pola fan-out ke 15 wallet dalam 2 jam, (3) nilai transaksi mendekati structuring threshold."*

#### Entity Resolution Engine
Menggunakan kombinasi heuristik untuk menghubungkan data on-chain dengan identitas off-chain:
- **Common-input ownership heuristic:** wallet yang sering muncul sebagai co-input dalam TX yang sama kemungkinan milik entitas sama
- **Exchange deposit clustering:** wallet yang mengirim ke deposit address exchange teridentifikasi dapat di-label dengan nama exchange tersebut
- **OSINT enrichment (future):** integrasi dengan threat intel feeds untuk label tambahan

---

### 3.6 Layer 6: Output

#### Risk Dashboard
Single-page application berbasis React.js yang menampilkan:
- Risk Score gauge dan grade (kode warna)
- Network Graph interaktif menggunakan D3.js (node = wallet, edge = transaksi, warna merah = suspicious)
- Timeline transaksi
- Anomaly flags yang terdeteksi
- SHAP explanation summary

#### Compliance Report Generator
Menghasilkan laporan PDF terstruktur yang mencakup: executive summary, entity timeline, graph visualization, anomaly detail, SHAP explanation, dan chain of evidence (IPFS CID). Format laporan dirancang untuk diserahkan kepada regulator (PPATK Indonesia).

#### Evidence PDF + IPFS Pin
Setelah laporan dibuat, sistem secara otomatis: (1) hash seluruh konten laporan menggunakan SHA-256, (2) upload ke IPFS via Infura Gateway, (3) simpan CID di PostgreSQL terikat dengan `case_id`. CID ini dapat diverifikasi siapapun melalui publik IPFS gateway.

---

## 4. Katalog External API

Berikut adalah spesifikasi lengkap setiap external API yang digunakan sistem AABCI, mencakup kemampuan, endpoint kunci, model autentikasi, dan tier yang relevan untuk MVP.

---

### 4.1 Alchemy — Ethereum & EVM Transaction Data

**URL Dokumentasi:** `https://docs.alchemy.com`  
**Fungsi dalam sistem:** Primary data source untuk Ethereum Mainnet, Base, Polygon. Digunakan untuk mengambil riwayat transaksi wallet, internal transfers, dan EVM execution traces.

**Endpoint Kunci:**

| Endpoint | Method | Deskripsi |
|---|---|---|
| `alchemy_getAssetTransfers` | POST | Ambil semua transfer historis (ERC-20, ERC-721, ETH) dari/ke suatu address dengan single call. Lebih efisien 100× dibandingkan scanning manual per block. |
| `trace_transaction` | POST | Dapatkan EVM execution trace dari suatu TX hash, termasuk internal calls antar contract. Kritis untuk melacak aliran dana yang melewati smart contract. |
| `eth_getTransactionByHash` | POST | Detail lengkap satu transaksi: from, to, value, input, gas, block. |
| `eth_getBalance` | POST | Saldo ETH terkini suatu address. |
| `alchemy_getTokenBalances` | POST | Semua token ERC-20 yang dipegang suatu address beserta balance. |
| WebSocket `alchemy_pendingTransactions` | WS | Stream real-time transaksi pending yang melibatkan address yang dimonitor. |

**Autentikasi:** API Key di URL path (`https://eth-mainnet.g.alchemy.com/v2/{API_KEY}`)  
**Tier MVP:** Free tier (300 juta compute units/bulan) cukup untuk prototype; Growth plan ($49/bulan) untuk produksi.  
**Catatan Penting:** `trace_transaction` membutuhkan minimal tier Pay-as-you-go atau Enterprise karena mengakses archive nodes dengan trace capability.

**Cara Penggunaan di Sistem:**
Ketika Trace Engine menerima wallet address target, request pertama ke Alchemy adalah `alchemy_getAssetTransfers` untuk mendapatkan semua counterparty addresses. Setiap address hasil dikirim kembali sebagai node baru ke Neo4j. Untuk TX yang melibatkan smart contract, `trace_transaction` dipanggil untuk mengurai internal call tree.

---

### 4.2 Helius — Solana Transaction Data & Webhooks

**URL Dokumentasi:** `https://docs.helius.dev`  
**Fungsi dalam sistem:** Primary data source untuk Solana Mainnet. Digunakan untuk riwayat transaksi wallet Solana, token holdings, dan real-time webhook untuk monitoring aktif.

**Endpoint Kunci:**

| Endpoint | Method | Deskripsi |
|---|---|---|
| `getTransactionsForAddress` | POST (JSON-RPC) | Ambil seluruh riwayat TX suatu Solana wallet dalam single call dengan time-based filtering. Menggabungkan `getSignaturesForAddress` + `getTransaction`. |
| `getAssetsByOwner` (DAS API) | POST | Semua token dan NFT Solana yang dimiliki address tertentu dengan metadata lengkap. |
| `getTokenAccounts` | POST | Semua token account dan saldo untuk suatu wallet. |
| `searchAssets` | POST | Pencarian asset Solana dengan filter berbagai kriteria. |
| Webhooks | HTTP POST (inbound) | Helius push notification ke endpoint sistem ketika address yang didaftarkan melakukan transaksi baru. Menghindari polling terus-menerus. |
| gRPC LaserStream | gRPC | Ultra-low latency streaming data block Solana secara real-time. Digunakan untuk whale monitoring. |

**Autentikasi:** API Key di header `Authorization: Bearer {API_KEY}` atau di URL query parameter.  
**Tier MVP:** Developer plan (free, 1 juta credits/bulan) untuk development; Starter plan ($49/bulan) untuk produksi dengan webhook support.  
**Catatan Penting:** Webhooks Helius mendukung filter by address, transaction type, dan minimum value — sangat relevan untuk whale alert (transaksi > $100k).

**Cara Penggunaan di Sistem:**
Untuk investigasi Solana, sistem mendaftarkan address target ke Helius Webhook. Setiap transaksi baru yang masuk diterima sebagai HTTP POST ke endpoint `/api/webhook/helius` sistem, yang kemudian menginsert event ke message queue untuk diproses Anomaly Detector.

---

### 4.3 Etherscan API V2 — Multi-chain Block Explorer Data

**URL Dokumentasi:** `https://docs.etherscan.io`  
**Fungsi dalam sistem:** Supplementary data source untuk labeling entity (exchange, contract verified status, token info), AML Risk Score, dan data Ethereum historis. Juga digunakan untuk BaseScan (Base L2) dan BscScan (BNB Chain).

**Endpoint Kunci:**

| Endpoint | Method | Deskripsi |
|---|---|---|
| `account/txlist` | GET | Daftar normal transaksi suatu address. |
| `account/tokentx` | GET | Daftar ERC-20 token transfer suatu address. |
| `contract/getabi` | GET | ABI smart contract yang sudah diverifikasi. |
| `contract/getsourcecode` | GET | Source code contract yang sudah diverifikasi, penting untuk identifikasi mixer contract. |
| `token/tokeninfo` | GET | Metadata token ERC-20 termasuk total supply, holder count. |
| `stats/tokensupply` | GET | Circulating supply token. |
| `account/addresstagname` (Pro) | GET | Label/tag yang diberikan Etherscan untuk address (exchange, hacker, etc). |

**Autentikasi:** API Key di query parameter `?apikey={KEY}`  
**Tier MVP:** Free tier (5 request/detik, satu chain) untuk development; Lite Plan (Q4 2025, multi-chain + higher rate limit) untuk produksi.  
**Catatan Penting:** Etherscan API V2 menjadi sistem unified multichain sejak pertengahan 2025 dengan single API key untuk semua chain yang didukung (30+ chains). V1 sudah retired per Agustus 2025.

**Cara Penggunaan di Sistem:**
Entity Resolution Engine menggunakan Etherscan `addresstagname` (Pro) untuk mengambil label publik yang sudah diverifikasi (contoh: "Binance: Hot Wallet", "Tornado Cash"). Ini menjadi fitur label tertinggi confidence dalam GNN node features.

---

### 4.4 Chainalysis Free Sanctions API

**URL Dokumentasi:** `https://auth-developers.chainalysis.com/sanctions-screening/docs`  
**Fungsi dalam sistem:** Sanctions screening — memeriksa apakah wallet address ada dalam daftar OFAC SDN (Specially Designated Nationals) dan embargo list internasional lainnya.

**Endpoint Kunci:**

| Endpoint | Method | Deskripsi |
|---|---|---|
| `GET /v1/sanctions/entities/{address}` | GET | Cek satu address — return sanctioned status dan detail entity (nama, program sanksi, tanggal penambahan). |
| Sanctions Oracle (Smart Contract) | On-chain call | Smart contract `0x40C57923924B5c5c5455c48D93317139ADDaC8fb` yang dapat dipanggil dari kontrak lain untuk cek sanctions secara on-chain. Deployed di Ethereum, Base, Arbitrum, dll. |

**Autentikasi:** API Key (gratis, daftar via form Chainalysis)  
**Tier MVP:** Free — tidak ada biaya, tidak ada rate limit yang dipublikasikan untuk basic sanctions check.  
**Coverage:** Daftar OFAC SDN yang diupdate secara berkala. Untuk investigasi yang lebih dalam (mixer, terrorist financing, darknet), diperlukan Chainalysis KYT (enterprise, berbayar).

**Cara Penggunaan di Sistem:**
Setiap wallet address yang masuk ke sistem secara otomatis di-check terhadap Sanctions API sebelum analisis lebih lanjut. Jika status `sanctioned: true`, Risk Score langsung naik ke 90+ dan analyst mendapat immediate alert. CID hasil check disimpan sebagai bagian dari evidence chain.

---

### 4.5 LayerZero API — Cross-chain Message Tracking

**URL Dokumentasi:** `https://docs.layerzero.network/v2`  
**Fungsi dalam sistem:** Melacak pesan cross-chain yang menggunakan protokol LayerZero, termasuk OFT (Omnichain Fungible Token) transfers dan direct contract-to-contract calls.

**Endpoint Kunci:**

| Endpoint | Method | Deskripsi |
|---|---|---|
| `https://scan.layerzero-api.com/v1/messages/tx/{txHash}` | GET | Ambil status dan detail cross-chain message berdasarkan source TX hash. Return GUID, DVN yang memvalidasi, executor, dan destination TX hash. |
| `https://metadata.layerzero-api.com/v1/metadata/experiment/ofts` | GET | Discovery token OFT di semua chain yang didukung LayerZero. |
| LayerZero Scan UI | Browser | `https://layerzeroscan.com` — untuk verifikasi manual oleh analyst. |

**Autentikasi:** OFT Transfer API membutuhkan `OFT_API_KEY`; Scan API bersifat publik untuk read-only.  
**Tier MVP:** Scan API publik, gratis. OFT Transfer API membutuhkan pendaftaran developer.  
**Chain Coverage:** Per awal 2026, >60 jaringan blockchain termasuk semua EVM major chains dan Solana.

**Cara Penggunaan di Sistem:**
Ketika Trace Engine menemukan transaksi ke LayerZero Endpoint contract, sistem otomatis memanggil LayerZero Scan API dengan source TX hash untuk mendapatkan destination TX hash di chain tujuan. Hasilnya direpresentasikan sebagai `BridgeEvent` node di Neo4j yang menghubungkan dua wallet di chain berbeda.

---

### 4.6 Wormhole — Cross-chain VAA Tracking

**URL Dokumentasi:** `https://docs.wormhole.com`  
**Fungsi dalam sistem:** Melacak pesan cross-chain yang menggunakan protokol Wormhole melalui Guardian network. Setiap message Wormhole memiliki VAA (Verified Action Approval) yang merupakan attestasi kriptografis.

**Endpoint Kunci:**

| Endpoint | Method | Deskripsi |
|---|---|---|
| WormholeScan API `GET /api/v1/transactions?address={address}` | GET | Semua transaksi cross-chain yang melibatkan address tertentu di semua chain Wormhole. |
| `GET /api/v1/transactions/{chain}/{tx_hash}` | GET | Detail satu transaksi cross-chain: source chain, dest chain, VAA ID, relayer, status. |
| `GET /api/v1/vaas/{chain_id}/{emitter}/{seq}` | GET | Ambil VAA spesifik berdasarkan chain-emitter-sequence. Bukti kriptografis pesan cross-chain. |

**Autentikasi:** WormholeScan API publik, tidak membutuhkan API key untuk read-only.  
**URL Base:** `https://api.wormholescan.io`

**Cara Penggunaan di Sistem:**
Bridge Adapter memeriksa apakah suatu TX berinteraksi dengan Wormhole Core Bridge contract. Jika ya, WormholeScan API dipanggil untuk mendapatkan VAA dan destination transaction, kemudian keduanya dihubungkan sebagai `BridgeEvent` di Neo4j.

---

### 4.7 Neo4j AuraDB — Graph Database

**URL Dokumentasi:** `https://neo4j.com/docs/aura/`  
**Fungsi dalam sistem:** Database utama untuk menyimpan seluruh Transaction Graph, Entity Graph, dan Case Graph. Semua query multi-hop traversal dieksekusi di sini menggunakan Cypher Query Language.

**Konektivitas:**

| Method | Deskripsi |
|---|---|
| **Bolt Protocol** | Koneksi binary native Neo4j (`neo4j+s://xxxxx.databases.neo4j.io`) untuk aplikasi backend menggunakan official driver. |
| **HTTP API (Query API)** | REST endpoint untuk bahasa yang tidak memiliki official driver. |
| **GraphQL (via Neo4j GraphQL Library)** | Ekspos graph sebagai GraphQL API untuk frontend. |
| **Neo4j Graph Data Science (GDS) Library** | Plugin yang menyediakan 50+ graph algorithms built-in: PageRank, Community Detection (Louvain), Betweenness Centrality, Node Similarity — semua relevan untuk network analysis kripto. |

**Tier MVP:** AuraDB Free (1 instance, 200k nodes, 400k relationships) untuk prototyping; AuraDB Professional ($65/bulan, storage besar) untuk produksi.

**Query Kritis:**
Semua query Trace Engine ditulis dalam Cypher. Contoh pola query yang digunakan:
- `MATCH p=(w:Wallet {address: $input})-[:SENT_TO*1..5]->(t:Wallet) WHERE t.risk_score > 0.7 RETURN p` — temukan semua wallet risiko tinggi dalam 5 hop
- `MATCH (w:Wallet)-[:SENT_TO]->(m:Entity {type: 'mixer'}) RETURN w.address, count(*)` — identifikasi pengirim ke mixer

---

### 4.8 PyTorch Geometric (PyG) — GNN Framework

**URL Dokumentasi:** `https://pytorch-geometric.readthedocs.io`  
**Fungsi dalam sistem:** Framework untuk mendefinisikan, melatih, dan melakukan inferensi Graph Attention Network (GAT) yang menjadi inti deteksi transaksi ilegal.

**Komponen yang Digunakan:**

| Komponen PyG | Kegunaan |
|---|---|
| `GATConv` | Graph Attention Convolution layer — message passing dengan attention mechanism |
| `EllipticBitcoinDataset` | Dataset benchmark untuk training awal (203.769 nodes, 234.355 edges) |
| `DataLoader` | Mini-batch loading untuk training efisien di GPU |
| `SHAP + PyG integration` | Perhitungan SHAP values untuk explainability |
| `torch.onnx.export` | Export model ke ONNX format untuk deployment inference tanpa GPU |

**Model Lifecycle:**
1. **Training:** Dilakukan offline menggunakan Elliptic dataset + labeled Ethereum addresses. Hardware: minimal NVIDIA T4 GPU (tersedia di Google Colab free tier).
2. **Serving:** Model yang sudah di-train di-export ke ONNX format dan di-load oleh FastAPI inference service. Inferensi CPU-only, latency ~50ms per subgraph.
3. **Update:** Retrain setiap 30 hari dengan data berlabel baru dari investigasi yang sudah selesai (human feedback loop).

---

### 4.9 IPFS via Infura Gateway — Decentralized Evidence Storage

**URL Dokumentasi:** `https://docs.infura.io/networks/ipfs`  
**Fungsi dalam sistem:** Upload dan pin laporan investigasi ke IPFS untuk mendapatkan CID immutable yang berfungsi sebagai bukti forensik yang tidak dapat dipalsukan.

**Endpoint Kunci:**

| Endpoint | Method | Deskripsi |
|---|---|---|
| `POST /api/v0/add` | POST (multipart) | Upload file ke IPFS dan dapatkan CID. |
| `POST /api/v0/pin/add?arg={CID}` | POST | Pin CID agar tidak di-garbage-collect. |
| `GET /ipfs/{CID}` | GET | Retrieve file berdasarkan CID (via public gateway `ipfs.io/ipfs/{CID}`). |

**Autentikasi:** Infura Project ID + Project Secret di Basic Auth header.  
**Tier MVP:** Infura free tier (5GB storage, 3 req/detik) cukup untuk MVP.

---

### 4.10 Telegram Bot API — Real-time Alert

**URL Dokumentasi:** `https://core.telegram.org/bots/api`  
**Fungsi dalam sistem:** Mengirimkan notifikasi alert real-time ke analyst ketika sistem mendeteksi transaksi Critical Risk (skor > 80) atau ketika investigasi selesai.

**Endpoint Kunci:**

| Endpoint | Method | Deskripsi |
|---|---|---|
| `sendMessage` | POST | Kirim pesan teks (mendukung HTML/Markdown formatting) ke chat ID tertentu. |
| `sendDocument` | POST | Kirim file PDF (compliance report) langsung ke chat. |
| `sendPhoto` | POST | Kirim screenshot graph visualization. |

**Autentikasi:** Bot Token di URL path `https://api.telegram.org/bot{TOKEN}/sendMessage`  
**Biaya:** Gratis, tidak ada rate limit yang ketat untuk use case alert.

**Format Alert MVP:**
```
🚨 CRITICAL RISK ALERT
──────────────────────
Wallet: 0xABC...123
Chain: Ethereum
Risk Score: 87/100
Anomalies: P01 (Mixer), P03 (Fan-out)
SHAP Top Reason: Interaksi Tornado Cash
──────────────────────
Klik untuk investigasi penuh: [Case #1042]
```

---

## 5. Data Model & Graph Schema

### 5.1 Node Types

```
(:Wallet)
  - address: String (UNIQUE)
  - chain: Enum [ETH, SOL, BASE, POLYGON]
  - balance_usd: Float
  - first_seen: DateTime
  - last_seen: DateTime
  - tx_count: Integer
  - risk_score: Float (0.0–1.0)
  - gnn_label: Enum [UNKNOWN, LICIT, ILLICIT]
  - entity_label: String (e.g., "Binance", "Tornado Cash")
  - is_contract: Boolean
  - is_sanctioned: Boolean

(:Transaction)
  - hash: String (UNIQUE)
  - chain: Enum
  - value_usd: Float
  - timestamp: DateTime
  - block_number: Integer
  - gas_used: Integer
  - status: Enum [SUCCESS, FAILED]
  - anomaly_flags: List<String>

(:BridgeEvent)
  - id: String (UNIQUE)
  - protocol: Enum [LAYERZERO, WORMHOLE, STARGATE]
  - source_chain: Enum
  - dest_chain: Enum
  - source_tx_hash: String
  - dest_tx_hash: String
  - message_id: String (GUID/VAA)
  - timestamp: DateTime
  - value_usd: Float

(:Entity)
  - name: String
  - type: Enum [EXCHANGE, MIXER, DARKNET, DEFI, UNKNOWN]
  - risk_level: Enum [LOW, MEDIUM, HIGH, CRITICAL]
  - source: Enum [ETHERSCAN_TAG, CHAINALYSIS, MANUAL]

(:InvestigationCase)
  - case_id: String (UNIQUE)
  - input_address: String
  - status: Enum [IN_PROGRESS, COMPLETED, ESCALATED]
  - created_at: DateTime
  - final_risk_score: Float
  - ipfs_cid: String
  - analyst_id: String
```

### 5.2 Relationship Types

```
(:Wallet)-[:SENT_TO {
  tx_hash: String,
  value_usd: Float,
  timestamp: DateTime
}]->(:Wallet)

(:Wallet)-[:SENT_TO]->(:Transaction)-[:RECEIVED_BY]->(:Wallet)

(:Wallet)-[:BRIDGE_OUT {
  event_id: String
}]->(:BridgeEvent)-[:BRIDGE_IN {
  event_id: String
}]->(:Wallet)

(:Wallet)-[:LABELED_AS]->(:Entity)

(:InvestigationCase)-[:INVESTIGATES]->(:Wallet)
(:InvestigationCase)-[:FOUND]->(:Wallet)
```

---

## 6. Arsitektur Agentic AI (Cognitive Loop)

Inti dari sistem AABCI adalah **Agent Orchestrator** yang mengimplementasikan loop kognitif berkelanjutan terinspirasi dari framework LOCARD (arXiv) dan paradigma ReAct.

### 6.1 Cognitive Loop: Think → Act → Observe → Reflect

```
┌─────────────────────────────────────────────────────────┐
│                   AGENT ORCHESTRATOR                     │
│                                                          │
│   INPUT: Wallet Address / TX Hash                        │
│                    │                                     │
│                    ▼                                     │
│   ┌─────────────────────────────────────────────────┐   │
│   │  THINK: Decompose goal menjadi sub-tasks         │   │
│   │  - Buat investigasi plan                         │   │
│   │  - Tentukan urutan tool calls                    │   │
│   │  - Prioritaskan berdasarkan risk signal awal     │   │
│   └──────────────────────┬──────────────────────────┘   │
│                           │                             │
│                           ▼                             │
│   ┌─────────────────────────────────────────────────┐   │
│   │  ACT: Eksekusi tool call                        │   │
│   │  - get_transactions(address)                    │   │
│   │  - check_sanctions(address)                     │   │
│   │  - run_gnn_inference(subgraph)                  │   │
│   │  - trace_forward(address, hops=5)               │   │
│   │  - check_bridge(tx_hash)                        │   │
│   └──────────────────────┬──────────────────────────┘   │
│                           │                             │
│                           ▼                             │
│   ┌─────────────────────────────────────────────────┐   │
│   │  OBSERVE: Analisis hasil tool                   │   │
│   │  - Parse structured response                    │   │
│   │  - Update Neo4j graph dengan data baru          │   │
│   │  - Evaluasi apakah sub-task selesai             │   │
│   │  - Identifikasi anomaly flags baru              │   │
│   └──────────────────────┬──────────────────────────┘   │
│                           │                             │
│                           ▼                             │
│   ┌─────────────────────────────────────────────────┐   │
│   │  REFLECT: Update hypothesis & memory            │   │
│   │  - Apakah ada evidence baru yang mengubah       │   │
│   │    risk assessment?                             │   │
│   │  - Apakah perlu investigasi lebih dalam?        │   │
│   │  - Apakah stopping criterion terpenuhi?         │   │
│   └──────────────────────┬──────────────────────────┘   │
│                           │                             │
│          ┌────────────────┴──────────────┐              │
│          ▼                               ▼              │
│   [Lanjut THINK]               [Stopping Criterion]     │
│                                - Max 5 iterasi          │
│                                - Confidence > 0.85      │
│                                - Critical finding       │
│                                - Manual interrupt       │
│                                          │              │
│                                          ▼              │
│                                  GENERATE REPORT         │
└─────────────────────────────────────────────────────────┘
```

### 6.2 Tool Registry Agent

Agent memiliki akses ke 12 tools yang terdefinisi dengan schema input/output yang ketat:

| Tool ID | Nama | Provider | Input | Output |
|---|---|---|---|---|
| T01 | `get_eth_transactions` | Alchemy | address, start_block | List\<Transaction\> |
| T02 | `get_sol_transactions` | Helius | address, limit | List\<Transaction\> |
| T03 | `check_sanctions` | Chainalysis | address | SanctionResult |
| T04 | `run_gnn_inference` | Local PyG | subgraph (nodes+edges) | Float (0–1) + SHAP |
| T05 | `trace_forward` | Neo4j | address, hops | List\<Wallet\> |
| T06 | `trace_backward` | Neo4j | address, hops | List\<Wallet\> |
| T07 | `check_bridge_lz` | LayerZero Scan | tx_hash | CrossChainTrace |
| T08 | `check_bridge_wh` | WormholeScan | tx_hash | CrossChainTrace |
| T09 | `get_entity_label` | Etherscan | address | EntityLabel |
| T10 | `detect_anomaly` | Local Rules | tx_list | List\<AnomalyFlag\> |
| T11 | `generate_report` | Internal | case_id | PDF + IPFS_CID |
| T12 | `send_alert` | Telegram API | risk_level, case_id | Boolean |

### 6.3 Agent Memory

Agent menggunakan **dual memory** untuk menjaga konteks investigasi:

- **Short-term Memory (Redis TTL: 1 session):** Stack dari semua observations dalam iterasi saat ini. Berisi: wallet addresses yang sudah dikunjungi (untuk menghindari infinite loop), tool calls yang sudah dilakukan, hypothesis aktif.
- **Long-term Memory (Neo4j):** Semua data yang di-persist dari investigasi sebelumnya. Agent dapat cross-reference hasil investigasi sebelumnya melalui query `(:InvestigationCase)-[:FOUND]->(:Wallet)`.

### 6.4 Hypothesis Management

Agent merumuskan dan menguji hipotesis secara eksplisit. Setiap hipotesis memiliki struktur:

```
Hypothesis {
  id: UUID
  statement: String  // "Wallet ini terlibat dalam layering scheme"
  confidence: Float  // 0.0–1.0
  evidence_for: List<String>  // TX hash, anomaly flags
  evidence_against: List<String>
  status: ACTIVE | CONFIRMED | REJECTED
}
```

Confidence diupdate setiap REFLECT phase menggunakan Bayesian update sederhana berdasarkan evidence baru.

---

## 7. Alur Sistem End-to-End

### Skenario: Analyst Menginvestigasi Wallet Mencurigakan

```
Step 1: INPUT
  Analyst mengakses dashboard AABCI
  → Memasukkan wallet address: 0xABC123...
  → Memilih depth: Standard (3 hop) atau Deep (5 hop)
  → Klik "Start Investigation"

Step 2: PREPROCESSING (< 2 detik)
  → API Gateway menerima request, validasi format address
  → Cek cache Redis: adakah hasil investigasi sebelumnya?
    ├── HIT: Tampilkan hasil cache (+ timestamp)
    └── MISS: Lanjut ke Step 3

Step 3: INITIAL SCAN (2–5 detik)
  → Parallel execution:
    ├── Chainalysis API: Cek sanctions status
    ├── Etherscan: Ambil entity label
    └── Alchemy: Ambil 100 transaksi terbaru
  → Hasil dimasukkan ke Neo4j sebagai node Wallet + Transaction
  → Pre-compute awal: apakah ada direct sanctions hit?
    ├── YES: Risk Score = 95, alert langsung, skip deep analysis
    └── NO: Lanjut ke Step 4

Step 4: AGENT COGNITIVE LOOP (10–60 detik)
  Iterasi 1 (THINK):
  → Agent melihat 100 TX awal
  → Hypothesis: "Ada pola fan-out ke banyak wallet kecil"
  → Plan: Jalankan Anomaly Detector P03

  Iterasi 1 (ACT):
  → detect_anomaly(tx_list) → P03 CONFIRMED, P09 CONFIRMED
  → trace_forward(address, hops=3) → 47 connected wallets

  Iterasi 1 (OBSERVE):
  → 3 dari 47 wallets memiliki entity_label = "Tornado Cash"
  → Confidence P01 (Mixer Interaction) naik ke 0.78

  Iterasi 1 (REFLECT):
  → Evidence kuat, perlu GNN inference untuk validasi
  → Update hypothesis: "Kemungkinan besar terlibat mixer"

  Iterasi 2 (THINK):
  → Plan: Ambil subgraph 3-hop, run GNN inference

  Iterasi 2 (ACT):
  → Bangun subgraph dari Neo4j (47 nodes, 89 edges)
  → run_gnn_inference(subgraph) → 0.82 (ILLICIT)

  Iterasi 2 (OBSERVE):
  → GNN score 0.82 mengkonfirmasi assessment
  → SHAP: top factor = "3 interactions with labeled mixer node"

  Iterasi 2 (REFLECT):
  → Confidence > 0.85, stopping criterion terpenuhi
  → Lanjut ke report generation

Step 5: CROSS-CHAIN CHECK (5–15 detik, jika ada bridge TX)
  → Scan TX list untuk interaksi dengan LayerZero/Wormhole endpoint
  → Jika ditemukan: check_bridge_lz(tx_hash) / check_bridge_wh(tx_hash)
  → Append BridgeEvent nodes ke Neo4j
  → Recursive: analisis wallet di chain tujuan (depth-1)

Step 6: SCORING & REPORT (3–5 detik)
  → Hitung final Risk Score:
     GNN(0.82 × 0.40) + Anomaly(P01,P03 × 0.30) + Sanctions(0 × 0.20) + 
     Centrality(0.65 × 0.10) = 73/100 (HIGH RISK)
  → Generate PDF report
  → Pin ke IPFS → dapat CID
  → Simpan CID di PostgreSQL case record

Step 7: OUTPUT (instan)
  → Dashboard menampilkan:
     - Risk Score: 73 (HIGH) dengan gauge visual
     - D3.js Network Graph: 47 nodes, warna merah untuk mixer-adjacent
     - Anomaly flags: P01 ✓, P03 ✓, P09 ✓
     - SHAP explanation: natural language
     - Download PDF button
     - IPFS CID untuk chain of evidence

Step 8: ALERT (jika Risk Score ≥ 60)
  → send_alert() → Telegram Bot kirim notifikasi ke analyst channel
  → Link ke case di dashboard

Total waktu end-to-end: 20–80 detik tergantung jumlah hop dan TX
```

---

## 8. Tech Stack Lengkap

### 8.1 Backend

| Komponen | Teknologi | Versi | Justifikasi |
|---|---|---|---|
| API Framework | FastAPI (Python) | 0.115+ | Async-native, OpenAPI auto-docs, high performance |
| GNN Inference | PyTorch + PyTorch Geometric | 2.6 + 2.5 | State-of-the-art GNN support, ONNX export |
| XAI | SHAP | 0.46+ | Industry standard, PyG integration |
| Graph Query | neo4j Python driver | 5.x | Official driver, async support |
| Task Queue | Celery + Redis | 5.4 + 7.2 | Async task execution untuk heavy computation |
| Caching | Redis | 7.2 | In-memory, TTL support |
| ORM | SQLAlchemy | 2.0 | Async ORM untuk PostgreSQL |
| IPFS Client | py-ipfs-client | 0.8 | Interaksi dengan Infura IPFS |
| PDF Generator | WeasyPrint | 62+ | HTML-to-PDF, CSS support |
| HTTP Client | httpx | 0.27+ | Async HTTP untuk external API calls |
| Config | Pydantic Settings | 2.x | Type-safe environment config |

### 8.2 Frontend

| Komponen | Teknologi | Versi | Justifikasi |
|---|---|---|---|
| UI Framework | React | 18.x | Mature ecosystem, concurrent features |
| Graph Viz | D3.js | 7.x | Highly customizable force-directed graph |
| State Management | Zustand | 4.x | Lightweight, no boilerplate |
| API Client | TanStack Query | 5.x | Caching, background refetch |
| UI Components | Shadcn/ui | Latest | Accessible, customizable |
| Charts | Recharts | 2.x | Risk score gauge, timeline |
| Styling | Tailwind CSS | 3.4 | Utility-first, responsive |
| Build Tool | Vite | 5.x | Fast HMR, ESM-native |

### 8.3 Infrastructure

| Komponen | Teknologi | Tier |
|---|---|---|
| Backend Hosting | Railway atau Render | Starter ($5–20/bulan) |
| Frontend Hosting | Vercel | Free tier |
| Graph Database | Neo4j AuraDB | Free → Professional |
| Relational DB | Supabase PostgreSQL | Free → Pro |
| Cache | Upstash Redis | Free tier |
| IPFS | Infura IPFS | Free tier |
| Container Registry | GitHub Container Registry | Free |
| CI/CD | GitHub Actions | Free |

---

## 9. Infrastruktur & Deployment

### 9.1 Arsitektur Deployment MVP

```
┌──────────────────────────────────────────────────────┐
│                    INTERNET                          │
└──────────────────────┬───────────────────────────────┘
                       │ HTTPS
┌──────────────────────▼───────────────────────────────┐
│              Vercel CDN (Frontend)                   │
│         React SPA + D3.js Dashboard                  │
└──────────────────────┬───────────────────────────────┘
                       │ REST API / WebSocket
┌──────────────────────▼───────────────────────────────┐
│            Railway (Backend API Server)              │
│              FastAPI + Uvicorn (ASGI)                │
│           Celery Workers (3 instances)               │
└──────┬──────────────────────────────┬────────────────┘
       │                              │
┌──────▼──────────┐         ┌─────────▼────────────────┐
│  Upstash Redis  │         │     Supabase PostgreSQL  │
│  (Cache + Queue)│         │     (Case Management)    │
└─────────────────┘         └──────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│              Neo4j AuraDB                           │
│         (Transaction + Entity Graph)                │
└──────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│          External API Layer                         │
│  Alchemy │ Helius │ Etherscan │ Chainalysis          │
│  LayerZero Scan │ WormholeScan │ Infura IPFS         │
│  Telegram Bot API                                   │
└──────────────────────────────────────────────────────┘
```

### 9.2 Environment Variables yang Dibutuhkan

Semua secret disimpan sebagai environment variables, tidak pernah di-hardcode:

| Variable | Deskripsi |
|---|---|
| `ALCHEMY_API_KEY` | Alchemy API key untuk Ethereum |
| `HELIUS_API_KEY` | Helius API key untuk Solana |
| `ETHERSCAN_API_KEY` | Etherscan API V2 key |
| `CHAINALYSIS_API_KEY` | Chainalysis Sanctions API key |
| `NEO4J_URI` | Bolt URI AuraDB |
| `NEO4J_USERNAME` | Neo4j username |
| `NEO4J_PASSWORD` | Neo4j password |
| `DATABASE_URL` | PostgreSQL connection string (Supabase) |
| `REDIS_URL` | Upstash Redis connection URL |
| `INFURA_IPFS_PROJECT_ID` | Infura project ID untuk IPFS |
| `INFURA_IPFS_SECRET` | Infura project secret |
| `TELEGRAM_BOT_TOKEN` | Token Telegram Bot |
| `TELEGRAM_CHAT_ID` | Chat ID channel analyst |
| `SECRET_KEY` | JWT signing key |

### 9.3 CI/CD Pipeline

```
Push ke GitHub main branch
        │
        ▼
GitHub Actions: Run Tests (pytest)
        │ PASS
        ▼
Build Docker image
        │
        ▼
Push ke GitHub Container Registry
        │
        ▼
Railway auto-deploy backend
Vercel auto-deploy frontend
        │
        ▼
Smoke test: POST /health → 200 OK
```

---

## 10. Keamanan & Compliance

### 10.1 Keamanan Aplikasi

**Autentikasi & Autorisasi:**
- JWT (JSON Web Token) dengan RS256 algorithm untuk semua API calls
- API Key dengan hashing bcrypt untuk penyimpanan, rate limiting berbasis key
- Role-based access control (RBAC): roles `analyst`, `supervisor`, `admin`
- Token refresh mechanism (access token: 1 jam, refresh token: 7 hari)

**Keamanan Data:**
- Semua komunikasi menggunakan HTTPS/TLS 1.3
- Database credentials di-encrypt menggunakan environment secrets (tidak di-commit)
- PII (jika ada) di-hash sebelum disimpan di Neo4j
- Audit log setiap query Neo4j yang dilakukan oleh agent (for forensic trail)

**Input Validation:**
- Wallet address divalidasi format (Ethereum checksum, Solana base58) sebelum diproses
- SQL injection prevention via parameterized queries (SQLAlchemy)
- Cypher injection prevention via parameterized Cypher queries
- Rate limiting di API Gateway (100 req/menit per API key)

**Dependency Security:**
- `pip audit` dijalankan setiap CI build untuk mendeteksi vulnerable packages
- Dependabot alerts diaktifkan di GitHub repository

### 10.2 Privasi & Compliance

**Data Minimization:**
Sistem hanya menyimpan data yang langsung relevan dengan investigasi: wallet addresses, TX hashes, dan derived analytics. Sistem tidak menyimpan informasi pribadi (KYC) dari exchange — itu domain exchange, bukan sistem ini.

**Kepatuhan UU PDP Indonesia:**
- Data investigasi yang berisi informasi terkait individu teridentifikasi wajib mendapat dasar hukum pemrosesan yang sah (legitimate interest atau perintah hukum).
- Hak penghapusan data: Sistem menyediakan endpoint `DELETE /api/cases/{case_id}` untuk menghapus data investigasi beserta IPFS unpin (best-effort).
- Data retention policy: Data investigasi dihapus otomatis setelah 2 tahun kecuali ada perintah hukum.

**Disclaimer Hukum:**
Risk score yang dihasilkan sistem bersifat **rekomendasi analitik**, bukan putusan hukum. Semua hasil investigasi wajib diverifikasi oleh analyst manusia sebelum digunakan sebagai dasar tindakan hukum atau pemblokiran akun.

---

## 11. Matriks Fitur: MVP vs Phase 2 vs Phase 3

| Fitur | MVP (0–3 bulan) | Phase 2 (4–8 bulan) | Phase 3 (9–18 bulan) |
|---|---|---|---|
| **Blockchain Support** | ETH + SOL | + BSC + Polygon + Base | + Avalanche + TRON + BTC |
| **Input Type** | Wallet address, TX hash | + Email, Domain, ENS name | + Phone, IP address |
| **GNN Architecture** | GAT (node classification) | + Temporal GNN (time-aware) | + Heterogeneous GNN |
| **Cross-chain** | LayerZero + Wormhole | + Axelar + Stargate + CCTP | + Intent-based routing tracking |
| **OSINT** | Entity label (Etherscan) | + WHOIS, social media Intel | + Breach data integration |
| **Risk Score** | Formula-based | + ML-calibrated score | + Ensemble model |
| **Evidence Storage** | IPFS (centralized pin) | + On-chain smart contract | + IPFS + Arweave redundancy |
| **Compliance Report** | PDF (internal format) | + PPATK format | + FinCEN SAR format |
| **Alert Channel** | Telegram | + Email + Slack | + WhatsApp + SIEM integration |
| **Visualisasi** | D3.js statik | + Real-time streaming | + 3D graph (WebGL) |
| **Entity Resolution** | Heuristik + Etherscan tag | + ML clustering | + Multi-source fusion |
| **Batch Analysis** | Single address | + Bulk upload CSV | + API for programmatic access |
| **Case Management** | Basic CRUD | + Collaboration multi-analyst | + Case workflow + approval |
| **GNN Retrain** | Manual | + Semi-automated (monthly) | + Active learning (weekly) |

---

## 12. Risiko Teknikal & Mitigasi

| Risiko | Dampak | Kemungkinan | Mitigasi |
|---|---|---|---|
| **Rate limit Alchemy/Helius melebihi tier** | Data tidak lengkap, investigasi gagal | Sedang | Implementasi exponential backoff, queue management, upgrade tier saat mendekati limit |
| **Neo4j query timeout untuk subgraph besar (>10.000 nodes)** | Investigasi hang, timeout | Sedang | Set query timeout 30 detik, implementasi subgraph sampling untuk jaringan besar, indeks Neo4j pada `address` dan `timestamp` |
| **GNN model drift (pola penipuan berubah)** | Akurasi menurun, false negative tinggi | Tinggi (over time) | Monitoring F1-score bulanan, scheduled retrain dengan data berlabel baru, human feedback loop |
| **API eksternal downtime (Alchemy/Helius)** | Investigasi tidak bisa jalan | Rendah | Fallback ke Etherscan untuk Ethereum data, Solana public RPC untuk Solana, circuit breaker pattern |
| **IPFS CID tidak dapat diakses karena unpin** | Chain of evidence rusak | Sedang | Dual-pin (Infura + Pinata), simpan juga hash SHA-256 di PostgreSQL sebagai backup integrity proof |
| **False positive tinggi di GNN** | Mengganggu kepercayaan analyst | Sedang | Threshold calibration, SHAP explanation untuk setiap prediksi, escalation workflow untuk kasus ambigus |
| **Cross-chain trace tidak lengkap (intent-based routing)** | Missing link dalam investigasi | Tinggi | Dokumentasikan gap kepada analyst, tambahkan caveat di laporan: "cross-chain coverage terbatas pada protokol message-based" |
| **Biaya infrastruktur melebihi budget** | Shutdown layanan | Rendah | Start dengan free tier, monitoring biaya via Grafana dashboard, auto-scale policy |

---

## 13. Estimasi Biaya & Sumber Daya

### 13.1 Biaya Infrastruktur MVP (Bulanan)

| Komponen | Tier | Biaya/Bulan (USD) |
|---|---|---|
| Railway (Backend) | Starter | $5–10 |
| Vercel (Frontend) | Free | $0 |
| Neo4j AuraDB | Free → Professional | $0 → $65 |
| Supabase | Free | $0 |
| Upstash Redis | Free (10K req/hari) | $0 |
| Infura IPFS | Free (5GB) | $0 |
| Alchemy | Free (300M CU) | $0 → $49 |
| Helius | Developer Free | $0 → $49 |
| Etherscan | Free | $0 |
| Chainalysis Sanctions | Free | $0 |
| Telegram Bot | Free | $0 |
| **TOTAL MVP** | | **$5–173** |

*Estimasi realistis untuk fase development: ~$15–30/bulan*
*Estimasi untuk produksi dengan beban moderat (100 investigasi/hari): ~$100–200/bulan*

### 13.2 Sumber Daya Manusia MVP

| Peran | Tanggung Jawab | Waktu |
|---|---|---|
| Backend Engineer (1 orang) | FastAPI, Celery, Neo4j integration, API adapters | Full-time 3 bulan |
| ML Engineer (1 orang) | GNN training (PyG), SHAP, ONNX serving | Full-time 3 bulan |
| Frontend Engineer (1 orang) | React dashboard, D3.js graph visualization | Full-time 2 bulan |
| DevOps (0.5 orang) | Railway/Vercel setup, GitHub Actions, monitoring | Part-time 1 bulan |

### 13.3 Kebutuhan Komputasi Training GNN

- **Hardware minimum:** NVIDIA T4 GPU 16GB (tersedia gratis di Google Colab atau Kaggle)
- **Training time Elliptic Dataset:** ~2–4 jam untuk 100 epoch pada T4
- **Dataset size:** ~150MB (Elliptic Bitcoin Dataset, tersedia publik di Kaggle)
- **Inference (production):** CPU-only via ONNX, ~50ms per subgraph 100 nodes

---

## 14. Roadmap Pengembangan

### Phase 0: Preparation (Minggu 1–2)
- [ ] Setup repository, CI/CD pipeline, environment management
- [ ] Daftarkan semua API keys (Alchemy, Helius, Etherscan, Chainalysis, Telegram)
- [ ] Setup Neo4j AuraDB Free instance dan Supabase
- [ ] Design database schema PostgreSQL dan graph schema Neo4j
- [ ] Setup Telegram Bot untuk alert channel

### Phase 1: Core Data Pipeline (Minggu 3–5)
- [ ] Implementasi Alchemy adapter: `get_eth_transactions`, `trace_transaction`
- [ ] Implementasi Helius adapter: `getTransactionsForAddress`, webhook receiver
- [ ] Implementasi Chainalysis sanctions check
- [ ] Implementasi Neo4j data writer: insert Wallet, Transaction, BridgeEvent nodes
- [ ] Unit test semua adapters dengan mock data
- [ ] Integration test: input wallet → data tersimpan di Neo4j

### Phase 2: AI Engine (Minggu 6–9)
- [ ] Download dan preprocessing Elliptic Bitcoin Dataset
- [ ] Training GAT model menggunakan PyTorch Geometric
- [ ] Evaluasi model: F1-score, precision, recall, ROC-AUC
- [ ] SHAP integration untuk explainability
- [ ] Export model ke ONNX
- [ ] Implementasi FastAPI inference endpoint
- [ ] Implementasi 17 Anomaly Detection rules
- [ ] Implementasi Risk Scorer formula

### Phase 3: Agentic Loop (Minggu 10–12)
- [ ] Implementasi Agent Orchestrator (Think-Act-Observe-Reflect)
- [ ] Implementasi Tool Registry dengan 12 tools
- [ ] Implementasi Agent Memory (Redis short-term + Neo4j long-term)
- [ ] Implementasi Hypothesis Manager
- [ ] Implementasi LayerZero Scan adapter
- [ ] Implementasi WormholeScan adapter
- [ ] End-to-end test: wallet input → full agent investigasi → risk score

### Phase 4: Output & Polish (Minggu 13–14)
- [ ] Implementasi PDF Report Generator (WeasyPrint)
- [ ] Implementasi IPFS upload (Infura)
- [ ] Implementasi Telegram alert
- [ ] Build React frontend dashboard
- [ ] Build D3.js force-directed graph visualization
- [ ] Performance optimization: caching, database indexing
- [ ] Security hardening: input validation, rate limiting, JWT auth

### Phase 5: Testing & Documentation (Minggu 15–16)
- [ ] Load testing (Locust): simulasi 100 concurrent investigations
- [ ] Security testing: OWASP ZAP scan
- [ ] Write technical documentation dan API docs (FastAPI auto-generated)
- [ ] User acceptance testing dengan 3 analyst skenario investigasi nyata
- [ ] Bug fix dan polish
- [ ] **MVP LAUNCH**

---

## Lampiran A: Referensi API

| Layanan | URL Dokumentasi |
|---|---|
| Alchemy Ethereum API | `https://docs.alchemy.com/reference/ethereum-api-quickstart` |
| Alchemy Transfers API | `https://docs.alchemy.com/reference/alchemy-getassettransfers` |
| Alchemy Trace API | `https://docs.alchemy.com/alchemy/documentation/alchemy-api-reference/trace-api` |
| Helius Solana API | `https://docs.helius.dev` |
| Helius getTransactionsForAddress | `https://www.helius.dev/historical-data` |
| Helius Webhooks | `https://docs.helius.dev/webhooks-and-websockets/what-are-webhooks` |
| Etherscan API V2 | `https://docs.etherscan.io` |
| Chainalysis Sanctions API | `https://auth-developers.chainalysis.com/sanctions-screening/docs` |
| LayerZero Scan API | `https://docs.layerzero.network/v2` |
| WormholeScan API | `https://api.wormholescan.io` |
| Neo4j AuraDB Docs | `https://neo4j.com/docs/aura` |
| PyTorch Geometric Docs | `https://pytorch-geometric.readthedocs.io` |
| IPFS via Infura | `https://docs.infura.io/networks/ipfs` |
| Telegram Bot API | `https://core.telegram.org/bots/api` |

---

## Lampiran B: Glosarium

| Istilah | Definisi |
|---|---|
| **Agentic AI** | Sistem AI yang dapat merencanakan, mengeksekusi, dan merefleksikan tindakannya secara otonom untuk mencapai goal tanpa instruksi per-langkah dari manusia |
| **GAT** | Graph Attention Network — varian GNN yang menggunakan mekanisme attention untuk memberikan bobot berbeda pada tetangga graph yang berbeda |
| **GNN** | Graph Neural Network — kelas model machine learning yang beroperasi langsung pada struktur graph |
| **Layering** | Teknik pencucian uang dengan memindahkan dana melalui serangkaian transaksi kompleks untuk mengaburkan asal-usul |
| **Fan-out** | Pola di mana satu alamat mendistribusikan dana ke banyak alamat, sering digunakan untuk structuring/tumbling |
| **VAA** | Verified Action Approval — attestasi kriptografis dari Guardian network Wormhole untuk setiap cross-chain message |
| **GUID** | Globally Unique Identifier — ID unik yang digunakan LayerZero untuk melacak setiap cross-chain message |
| **DVN** | Decentralized Verifier Network — entitas independen dalam LayerZero yang memvalidasi cross-chain messages |
| **OFAC SDN** | Office of Foreign Assets Control Specially Designated Nationals — daftar sanksi AS |
| **SHAP** | SHapley Additive exPlanations — metode untuk menjelaskan output model ML berdasarkan kontribusi tiap fitur |
| **CID** | Content Identifier — hash kriptografis yang digunakan IPFS untuk mengidentifikasi konten secara unik |
| **OFT** | Omnichain Fungible Token — standar token cross-chain LayerZero |
| **PPATK** | Pusat Pelaporan dan Analisis Transaksi Keuangan — Financial Intelligence Unit Indonesia |

---

*Dokumen ini merupakan spesifikasi teknikal MVP untuk sistem Agentic AI Blockchain Cyber Intelligence.*  
*Universitas Pembangunan Jaya — Blockchain Fundamentals — 2026*
