# TAHRIX Backend

Backend untuk **TAHRIX — Agentic AI Blockchain Cyber Intelligence (AABCI)**.
Implementasi MVP berbasis spesifikasi `MVP_Teknikal_TAHRIX.md`.

## Arsitektur

6 layer (Storage → Ingestion → Integration → AI Core → Intelligence → Output) —
detail di dokumen MVP. Stack: **FastAPI + PostgreSQL + Neo4j + Redis + Celery**,
inferensi GNN via **ONNX Runtime**, agentic loop berbasis LLM provider-agnostic.

## Quick Start

```bash
cp .env.example .env          # isi credentials sesuai kebutuhan
docker compose up --build
```

API: <http://localhost:8000/docs>

## Struktur Direktori

```
backend/
├── app/
│   ├── core/          # config, logging, security, exceptions
│   ├── db/            # postgres, neo4j, redis clients
│   ├── models/        # SQLAlchemy + Pydantic schemas
│   ├── repositories/  # data access layer
│   ├── adapters/      # external API clients (Alchemy, Helius, ...)
│   ├── services/      # domain services (risk scorer, anomaly, gnn, trace)
│   ├── agent/         # agentic AI orchestrator + tools + memory
│   ├── api/v1/        # REST endpoints
│   └── workers/       # Celery tasks
├── ml/                # GNN training + ONNX export (offline)
├── scripts/           # ops scripts (init neo4j, seed labels, ...)
└── tests/
```

## Environment

Lihat `.env.example` — semua secret dimuat via `pydantic-settings`.
Tidak ada nilai mock di kode; jika sebuah API key kosong, adapter terkait
akan menolak panggilan dengan exception terdokumentasi (fail loud, no silent mock).
