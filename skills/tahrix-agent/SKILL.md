---
name: tahrix-agent
description: Build an AI agent with LLM streaming, tool calling, and flow-based frontend rendering. This skill should be used when building chat-based AI agents that need real-time streaming responses with reasoning, tool execution, and dynamic UI updates. Covers hybrid polling architecture (Redis + background coroutine), Tool dataclass registry pattern, and flow-ordered DOM rendering.
---

# Tahrix Agent

## Overview

Build a production-grade AI agent chat interface with three core capabilities: (1) hybrid LLM streaming via Redis-backed polling, (2) structured tool calling with a dataclass registry, and (3) flow-based frontend rendering that displays reasoning, tool calls, and content in the exact order produced by the LLM.

## Architecture

The agent uses a **hybrid streaming** pattern to avoid SSE/reverse-proxy timeouts:

1. **POST** `/chat-stream-job` — Creates a background streaming job, returns `job_id`
2. **Background coroutine** (`_run_stream_job`) — Streams LLM response, executes tool calls, stores incremental chunks in Redis
3. **GET** `/chat-stream-job/{job_id}` — Frontend polls every 500ms for incremental chunks

This avoids long-lived HTTP connections that get killed by reverse proxies (Nginx, Cloudflare).

## Backend: Streaming Job

### Job Creation Endpoint

```
POST /api/v1/agent/chat-stream-job
Body: { message: str, case_id: str|null, history: list }
Response: { job_id: str, meta: dict }
```

- Build context messages from case data + history
- Prepare tool schemas from REGISTRY
- Generate unique `job_id`, store initial state in Redis (`chatjob:{job_id}`)
- Launch `asyncio.create_task(_run_stream_job(...))` — fire and forget
- Return job_id immediately

### Background Coroutine

The `_run_stream_job` coroutine:

1. Calls `llm.chat_stream(messages, tools=tools_schema)` — async generator yielding events
2. For each event, pushes a chunk to Redis state:
   - `reasoning` — LLM thinking text (pushed incrementally)
   - `content` — LLM response text (pushed incrementally)
   - `tool_call` — Tool name + args (pushed once, status set to "running")
   - `tool_result` — Tool result (pushed once, status set to "done")
   - `follow_up` — Signals start of post-tool synthesis LLM call
3. On `done` event with tool_calls_executed:
   - Append assistant tool_call messages + tool result messages to conversation
   - **Reset** `full_content` and `full_reasoning` to empty strings
   - Push `follow_up` chunk
   - Add user instruction: "Based on the tool results above, provide your final analysis. Do NOT repeat your earlier assessment."
   - Stream follow-up LLM call, pushing reasoning/content chunks
4. On final `done`, set `status: "done"`, clear chunks, persist to Redis

### Polling Endpoint

```
GET /api/v1/agent/chat-stream-job/{job_id}
Response: { status, content, reasoning, chunks[], tool_calls[], usage }
```

- Read from Redis, return current state
- `chunks` array contains incremental events since last poll (frontend tracks `lastChunkIdx`)
- When `status: "done"`, `chunks` is empty — frontend uses `content`/`reasoning` fields

### Redis State Schema

```json
{
  "status": "streaming" | "done" | "error",
  "content": "accumulated content text",
  "reasoning": "accumulated reasoning text",
  "chunks": [
    {"type": "reasoning", "text": "..."},
    {"type": "content", "text": "..."},
    {"type": "tool_call", "name": "...", "args": {...}},
    {"type": "tool_result", "name": "...", "result": "..."},
    {"type": "follow_up", "text": "Synthesizing results..."}
  ],
  "tool_calls": [{"name": "...", "status": "running"|"done"}],
  "usage": {"prompt_tokens": N, "completion_tokens": N}
}
```

TTL: 180 seconds (auto-cleanup after streaming completes).

## Backend: Tool Registry

### Tool Dataclass

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    fn: ToolFn  # async callable: (args, ctx) -> dict

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
```

### Registry Pattern

```python
REGISTRY: dict[str, Tool] = {}

def _register(name, description, parameters, fn):
    REGISTRY[name] = Tool(name=name, description=description, parameters=parameters, fn=fn)
```

### Critical: Tool Execution

**The Tool object is NOT callable.** Always invoke via `.fn`:

```python
tool_func = REGISTRY.get(tool_name)
if tool_func:
    result = await tool_func.fn(tool_args, ctx)  # NOT tool_func(tool_args, ctx)
```

### ToolContext

```python
@dataclass
class ToolContext:
    case_id: str
    address: str
    chain: str
    seen_addresses: set[str]
    transactions: list
    bridge_events: list
    anomaly_flags: list
```

## Frontend: Flow-Based Rendering

### Core Concept

Events are appended to a flow container **in the exact order received from the LLM**, not grouped by type. This means reasoning, tool calls, and content interleave naturally.

### Stream Message Structure

```javascript
function createStreamMessage() {
  // Returns: { el, flowEl, badgeEl, fullContent, fullReasoning,
  //            activeReasoningEl, activeContentEl, activeToolName, activeToolStatusEl }
}
```

The `flowEl` is a single container. All event blocks are appended as children.

### Loading Dots

- Created on send, appended to `flowEl`
- **Never removed** during streaming — moved to end of flow on each new event
- Use `insertBefore(newEl, loadingDots)` to insert events before dots
- Then `appendChild(loadingDots)` to move dots to end
- Hidden via `display:none` only on `done`, `error`, or `timeout`

### Event Rendering Logic

| Chunk Type | Action |
|---|---|
| `reasoning` | Create `.ta-reasoning` block if none active. Collapse previous content block. Append text. |
| `content` | Create `.ta-msg-content.ta-typing` block if none active. Collapse previous reasoning block. Render markdown. |
| `tool_call` | Close active content/reasoning. Create `.ta-tool-call` with "running..." status. |
| `tool_result` | Update matching tool_call status to "done". |
| `follow_up` | Reset `fullContent`/`fullReasoning`. Remove all old content/reasoning DOM blocks. Create synthesizing indicator. |

### Follow-Up Handling

When `follow_up` chunk arrives:
1. Reset `stream.fullContent = ''` and `stream.fullReasoning = ''`
2. Remove all `.ta-msg-content` and `.ta-reasoning` DOM elements from flow (tool calls remain)
3. Show synthesizing indicator (removed when new reasoning/content starts)

This prevents duplicate content — the first LLM call's content is discarded, replaced by the follow-up synthesis.

### Fallback Sync

After processing chunks, check `status.content` vs `stream.fullContent`. If Redis has more text than what chunks provided (e.g., chunks were trimmed), create a new content block and render the full text. This handles edge cases where polling misses chunks.

## CSS Classes

| Class | Purpose |
|---|---|
| `.ta-loading-dots` | Animated pulse dots container |
| `.ldot` | Individual dot with staggered animation |
| `.ta-reasoning` | Reasoning block, auto-collapses when next phase starts |
| `.ta-reasoning.collapsed` | Truncated to one line with ellipsis |
| `.ta-tool-call` | Tool execution indicator with name + status |
| `.tc-status.done` | Green checkmark for completed tools |
| `.ta-typing::after` | Blinking cursor on active content block |
| `.ta-token-badge` | Token usage display (In/Out) |

## Common Pitfalls

1. **`'Tool' object is not callable`** — Always use `tool_func.fn(args, ctx)`, never `tool_func(args, ctx)`
2. **Duplicate content after tool calls** — Reset `full_content`/`full_reasoning` before follow-up LLM call, remove old DOM blocks
3. **Reasoning appears at wrong position** — Must remove first call's DOM elements when follow_up starts, otherwise they stay and push new content below them
4. **Loading dots disappear** — Never `.remove()` dots during streaming; use `insertBefore` + `appendChild` to keep them at flow end
5. **SSE timeout behind reverse proxy** — Use hybrid polling instead of long-lived SSE connections
6. **Missing import** — Ensure `REGISTRY` and `ToolContext` are imported in endpoint files

## Resources

### references/

- `streaming-api.md` — Detailed API endpoint specifications and Redis state schema
- `tool-registry.md` — Tool dataclass, registry pattern, and ToolContext specification

### assets/

- `streaming-frontend.js` — Complete frontend streaming implementation (createStreamMessage, streamTaMessage, event handlers)
- `streaming-backend.py` — Complete backend implementation (_run_stream_job, job endpoints)
