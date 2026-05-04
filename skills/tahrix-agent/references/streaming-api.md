# Streaming API Reference

## Endpoints

### POST /api/v1/agent/chat-stream-job

Create a new streaming job. Returns immediately with a job_id for polling.

**Request:**
```json
{
  "message": "Analyze this address",
  "case_id": "uuid-or-null",
  "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
}
```

**Response:**
```json
{
  "job_id": "ba21346c-f0b1-4ab0-b62d-a081867e965d",
  "meta": {
    "has_context": true,
    "address": "0xd882...",
    "chain": "ETH",
    "nodes": 13,
    "edges": 12,
    "risk_grade": "HIGH",
    "input_tokens_est": 1515,
    "output_tokens_est": 377,
    "history_turns": 2
  }
}
```

**Error Responses:**
- `401` — Not authenticated
- `500` — Internal error (check: missing REGISTRY import, ToolContext not available)

### GET /api/v1/agent/chat-stream-job/{job_id}

Poll for incremental streaming status.

**Response (streaming):**
```json
{
  "status": "streaming",
  "content": "accumulated content so far...",
  "reasoning": "accumulated reasoning so far...",
  "chunks": [
    {"type": "reasoning", "text": "Let me analyze..."},
    {"type": "content", "text": "Based on "},
    {"type": "content", "text": "the data..."},
    {"type": "tool_call", "name": "check_sanctions", "args": {"address": "0xd882..."}},
    {"type": "tool_result", "name": "check_sanctions", "result": "{\"sanctioned\": true}"}
  ],
  "tool_calls": [
    {"name": "check_sanctions", "status": "done"}
  ],
  "usage": null
}
```

**Response (done):**
```json
{
  "status": "done",
  "content": "Full final content...",
  "reasoning": "Full reasoning text...",
  "chunks": [],
  "tool_calls": [...],
  "usage": {"prompt_tokens": 2500, "completion_tokens": 800}
}
```

**Response (error):**
```json
{
  "status": "error",
  "content": "Error: description of what went wrong",
  "reasoning": "",
  "chunks": [],
  "tool_calls": [],
  "usage": null
}
```

## Redis State

**Key:** `chatjob:{job_id}`  
**TTL:** 180 seconds

### Initial State
```json
{
  "status": "streaming",
  "content": "",
  "reasoning": "",
  "chunks": [],
  "tool_calls": [],
  "usage": null
}
```

### Chunk Types

| Type | Fields | Description |
|---|---|---|
| `reasoning` | `text` | LLM thinking/reasoning text fragment |
| `content` | `text` | LLM response text fragment |
| `tool_call` | `name`, `args` | Tool invocation with arguments |
| `tool_result` | `name`, `result` | Tool execution result (JSON string, max 1000 chars) |
| `follow_up` | `text` | Signals start of post-tool synthesis call |

### State Transitions

```
streaming -> done    (normal completion)
streaming -> error   (exception in background coroutine)
```

## Polling Strategy

- **Interval:** 500ms
- **Max attempts:** 120 (60 seconds total)
- **Chunk tracking:** Frontend maintains `lastChunkIdx` to only process new chunks
- **Fallback sync:** Compare `status.content.length` vs `stream.fullContent.length` to catch trimmed chunks

## Background Coroutine Flow

```
_run_stream_job(job_id, messages, meta, tools_schema, case)
  |
  +-- llm.chat_stream(messages, tools=tools_schema)
  |     |
  |     +-- event: reasoning -> _push_chunk("reasoning", {text})
  |     +-- event: content   -> _push_chunk("content", {text})
  |     +-- event: tool_call -> execute tool_func.fn(args, ctx)
  |     |                      -> _push_chunk("tool_call", {name, args})
  |     |                      -> _push_chunk("tool_result", {name, result})
  |     +-- event: done       -> if tool_calls_executed:
  |                              |   append tool messages to conversation
  |                              |   reset full_content, full_reasoning
  |                              |   _push_chunk("follow_up", {text})
  |                              |   llm.chat_stream(messages) [follow-up]
  |                              |     -> push reasoning/content chunks
  |                              set status="done", clear chunks
  |
  +-- on exception: set status="error", clear chunks
```
