# MVP TEKNIKAL - TAHRIX

## Arsitektur Sistem

### Core Components
1. **API Layer** - FastAPI
2. **Worker Layer** - Celery + Redis
3. **Graph Database** - Neo4j AuraDB
4. **LLM Integration** - OpenCode / Ollama

### Teknologi Stack
- **Backend**: Python 3.11, FastAPI, SQLAlchemy, Celery
- **Database**: PostgreSQL (metadata), Neo4j (graph), Redis (queue)
- **AI**: GNN (PyG), LLM (OpenCode Zen / Ollama)
- **Deployment**: Docker, Docker Compose

## API Endpoints

### Authentication
- POST /api/v1/auth/login
- POST /api/v1/auth/refresh
- POST /api/v1/auth/logout

### Cases
- GET /api/v1/cases
- POST /api/v1/cases
- GET /api/v1/cases/{id}
- PUT /api/v1/cases/{id}
- DELETE /api/v1/cases/{id}

### Investigation
- POST /api/v1/cases/{id}/investigate
- GET /api/v1/cases/{id}/events

### Labels
- GET /api/v1/labels
- POST /api/v1/labels
- PUT /api/v1/labels/{id}

## Deployment

### Server
- IP: 100.112.163.104
- Docker containers: api, worker, postgres, redis
- SSL: Let's Encrypt via Caddy

### Environment Variables
- DATABASE_URL
- NEO4J_URI, NEO4J_PASSWORD
- REDIS_URL
- JWT_SECRET
- LLM_API_KEY