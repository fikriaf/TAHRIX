# tahrix-agent

Claude Code Skill — Build AI agents with LLM streaming, tool calling, and flow-based frontend rendering.

## Install

```bash
npx skills add https://github.com/fikriaf/TAHRIX --skill tahrix-agent
```

## What This Skill Provides

- **Hybrid LLM Streaming** — Redis-backed polling architecture that avoids SSE/reverse-proxy timeouts
- **Tool Calling Registry** — Dataclass-based tool registry with `Tool.fn` callable pattern
- **Flow-Based Frontend Rendering** — Reasoning, tool calls, and content rendered in exact LLM output order
- **Loading Dots Animation** — Persistent during streaming, hidden on completion
- **Follow-Up Synthesis** — Automatic second LLM call after tool execution with content deduplication

## Quick Start

After installing the skill, ask Claude:

> "Build me an AI agent chat with streaming and tool calling using the tahrix-agent pattern"

Claude will use the skill's references and assets to scaffold:
1. **Backend** (`assets/streaming-backend.py`) — FastAPI endpoints + `_run_stream_job` coroutine
2. **Frontend** (`assets/streaming-frontend.js`) — Polling + flow-based DOM rendering
3. **API Reference** (`references/streaming-api.md`) — Endpoint specs, Redis schema, chunk types
4. **Tool Registry** (`references/tool-registry.md`) — Tool dataclass, REGISTRY, ToolContext

## Architecture

```
POST /chat-stream-job       → Create job, return job_id
GET  /chat-stream-job/{id}  → Poll for incremental chunks (500ms)
Background coroutine        → Stream LLM, execute tools, store chunks in Redis
```

## Key Pitfalls Covered

| Pitfall | Fix |
|---|---|
| `'Tool' object is not callable` | Use `tool_func.fn(args, ctx)` not `tool_func(args, ctx)` |
| Duplicate content after tools | Reset `full_content`/`full_reasoning` before follow-up call |
| Reasoning at wrong position | Remove first call's DOM on `follow_up` chunk |
| Loading dots disappear | Use `insertBefore` + `appendChild`, hide only on done |
| SSE timeout behind proxy | Use hybrid polling instead of long-lived connections |

## License

MIT
