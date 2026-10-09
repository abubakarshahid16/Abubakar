# AI task runner (#644)

`backend/app/ai_task_runner.py`. "AI reads, code checks": small strict model tasks run from a background queue. It is the runner only; nothing in the review pipeline calls it yet.

| Rule | Where |
|---|---|
| A task is about 300 words of source text, one instruction, one JSON schema | `TaskSpec`, `ai_task_max_words`. Longer input is refused by name, never cut |
| Schema goes to Ollama's `format` field, is checked again in code, then the task's own `check` runs. One retry that names what was wrong | `run_task` |
| An invalid, empty, cut-off or late reply is `could_not_read` with a reason. Data is None. No guess | `TaskResult` |
| Cache by task, version, model, schema and exact input. A hit makes no model call. Only `ok` is cached | `ai_task_cache` |
| The model is a setting: `AI_TASK_MODEL` (default `qwen3.5:2b`; set `qwen3.5:4b` or a larger local model) | `config.py` |
| One job at a time. `keep_alive` "10m" during a batch, model unloaded (0) at the end | `run_batch`, `model_transport.keep_alive_override` |
| Pauses (jobs stay queued) while a chat answer is produced, while pytest or the P1 run is going, or below 1.5 GB free RAM (`AI_TASK_MIN_FREE_RAM_GB`) | `pause_reason` |

Add a task: `ai_task_runner.register(TaskSpec(...))`, then `enqueue(name, text, ref=...)` and `run_batch()`.
Privacy: the only socket is `model_transport` (loopback Ollama). Source text is never logged; failures store the error type only.
