# Tool Registry Reference

## Tool Dataclass

```python
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

ToolFn = Callable[[dict[str, Any], "ToolContext"], Awaitable[dict[str, Any]]]

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (OpenAI function calling format)
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

## Registry Pattern

```python
REGISTRY: dict[str, Tool] = {}

def _register(name: str, description: str, parameters: dict, fn: ToolFn):
    REGISTRY[name] = Tool(name=name, description=description, parameters=parameters, fn=fn)
```

### Registration Example

```python
_register(
    name="check_sanctions",
    description="Check if an address appears on sanctions lists (OFAC, UN, EU)",
    parameters={
        "type": "object",
        "properties": {
            "address": {"type": "string", "description": "Blockchain address to check"},
            "chain": {"type": "string", "enum": ["ETH", "BTC", "TRON"]}
        },
        "required": ["address"]
    },
    fn=_check_sanctions
)
```

## ToolContext

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

Context is created per-request in the endpoint and passed to every tool execution.

## Tool Execution

### Correct Invocation

```python
tool_func = REGISTRY.get(tool_name)
if tool_func:
    ctx = ToolContext(
        case_id=str(case.id) if case else "agent",
        address=case.input_address if case else "unknown",
        chain="ETH",
        seen_addresses=set(),
        transactions=[],
        bridge_events=[],
        anomaly_flags=[],
    )
    try:
        result = await tool_func.fn(tool_args, ctx)  # .fn is the callable
        result_str = json.dumps(result)[:1000] if result else "No result"
    except Exception as te:
        result_str = f"Error: {str(te)}"
```

### Common Mistake

```python
# WRONG - Tool is a dataclass, not callable
result = await tool_func(tool_args, ctx)  # TypeError: 'Tool' object is not callable

# CORRECT - Access the .fn attribute
result = await tool_func.fn(tool_args, ctx)
```

## Tool Result Handling

- Results are JSON-serialized and truncated to 1000 characters
- If a tool is unavailable (missing API key), it returns `{"unavailable": true, "reason": "..."}`
- The agent uses this signal to pick a different tool
- Tool errors are caught and returned as `Error: <message>` strings — the LLM sees the error and adapts

## OpenAI Schema Format

Tools are exposed to the LLM via `to_openai_schema()`:

```json
{
  "type": "function",
  "function": {
    "name": "check_sanctions",
    "description": "Check if an address appears on sanctions lists",
    "parameters": {
      "type": "object",
      "properties": {
        "address": {"type": "string", "description": "Blockchain address"},
        "chain": {"type": "string", "enum": ["ETH", "BTC", "TRON"]}
      },
      "required": ["address"]
    }
  }
}
```

The LLM generates tool calls matching this schema. The agent parses `tool_name` and `tool_args` from the LLM response and looks up the tool in REGISTRY.
