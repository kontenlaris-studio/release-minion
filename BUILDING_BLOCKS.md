# Building Blocks Tested — ReleaseMinion

OpenMinion **0.1.23** (PyPI), Python 3.12, provider **Ollama** (local,
`qwen2.5:1.5b`), tool-call strategy `fallback`.

| Building block | How ReleaseMinion uses it | Result |
| --- | --- | --- |
| Agent execution | `Agent(...)` context manager + `agent.run()` | ✅ works |
| Models / providers | `ollama` provider preset via project-scoped `agents.json`; model selected in `providers.ollama.model` | ✅ works, no credential needed |
| Tools | 4 custom tools via `@tool(min_scope="READ_ONLY", idempotent=True)`; docstrings become tool descriptions | ✅ works; tools also callable directly in tests |
| Permissions | All tools are `READ_ONLY` under an `auto` action policy with `allow_read_only_without_prompt` | ✅ no prompts during runs |
| Sessions / memory | One `session_id` shared by the inspection run and a follow-up question | ✅ follow-up answered from session context (see demo) |
| Structured output | `output_type=ReleaseReport` (Pydantic) attempted first; shipped flow is two-phase (inspect → structure) | ⚠️ coercion fails with small local models — see finding 7 |
| Diagnostics | `openminion doctor --check-turn`, `openminion tools list`, session state in local SQLite | ✅ used to verify readiness before the real run |
| Config system | `openminion config init --provider ollama`, project-scoped via `OPENMINION_HOME` / `OPENMINION_DATA_ROOT` | ✅ works; see notes below |

Not exercised: delegation/handoffs, skills loading, MCP serving, channels —
out of scope for this single-purpose agent.

## Rough edges found

1. **Docs vs package version drift.** `pip install openminion` gives 0.1.23,
   but the docs' provider table lists models (e.g. `claude-sonnet-5`,
   `gpt-oss-120b`) that look newer than the 0.1 line. It is unclear which doc
   version matches 0.1.23; a version banner on the docs would help.
2. **Model lives under `providers.<id>.model`, not on the agent profile.**
   Agent profiles only carry `provider`. This is documented in
   getting-started ("one edit location"), but the first place a new user
   looks is the agent block; `openminion setup --list-providers` output does
   not mention where the model is stored.
3. **`config init` provider enum lags the catalog.** `config init --provider`
   accepts only `{echo, openai, anthropic, claude, openrouter, cerebras,
   groq, ollama, cortensor}`, while `setup --list-providers` lists 20+
   providers (groq, gemini, deepseek, …). The legacy id `cortensor` resolves
   to the direct Router path, not the Portal — easy to misread.
4. **Environment proxy variables break the local Ollama provider.**
   Repro: run `openminion doctor --check-turn` in an environment where
   `http_proxy`/`https_proxy` are set and `no_proxy` contains bracketed
   IPv6 entries (e.g. `[::1]`, common in sandboxed CI VMs).
   Actual: `agent.turn_smoke` fails instantly with
   `PROVIDER_ERROR: InvalidURL: Invalid port: ':1]'` — the tail of `[::1]`
   suggests the proxy/no-proxy parsing mishandles bracketed entries, even
   though the target URL is `http://127.0.0.1:11434/api/chat` (plain IPv4
   localhost). Expected: localhost provider traffic ignores proxy env, or
   the parser tolerates bracketed `no_proxy` entries. Workaround: unset
   `*_proxy`/`no_proxy` for the OpenMinion process; the smoke test then
   reaches the model.
5. **Two independent timeout layers, both too small for local CPU models.**
   The provider timeout (`providers.ollama.timeout_seconds`, default 60 s)
   is only the first layer: after raising it, a multi-tool turn still died
   with `TurnTimeoutError: Turn execution timed out after 90.00 seconds`
   from `runtime.chat_turn_timeout_seconds` (default 90 s) in the ingress
   path — while `runtime.brain_turn_timeout_seconds` defaults to 300 s.
   Three different defaults (60/90/300) across layers is confusing; the
   error message does not name the config key that fired. We set all
   relevant values to 1200 s for CPU inference. Suggestion: name the key
   in the timeout error and document the layers in the local-provider guide.
6. **`output_type` + custom tools + small local model returns prose, not JSON.**
   Repro: `Agent(output_type=ReleaseReport, tools=[...4 custom tools])`
   with Ollama `qwen2.5:1.5b` (fallback tool-call strategy). The model used
   the tools, then answered in prose ("release: ready\n\nThe re…"), and
   `_coerce_output` raised `AgentOutputValidationError` (invalid JSON at
   line 1 column 1). The adapter's native `format=<schema>` path only
   engages for a schema-only submit tool, so with real tools the coercion
   relies on the model voluntarily emitting raw JSON — a 1.5B local model
   does not. Workaround shipped: two-phase flow (free-text inspection turn,
   then a structure-only turn validated against the Pydantic schema, with
   deterministic facts as ground truth). Suggestion: when `output_type` is
   set and tools are present, do a final schema-constrained turn
   automatically, or document this limitation next to `output_type`.
7. **The LLM freshness classifier misfires on small local models and
   hijacks ordinary turns.** Every turn is classified for "freshness
   sensitivity" by the same configured model
   (`modules/brain/bootstrap/freshness_classify.py`). With
   `qwen2.5:1.5b`, plain session-recall questions ("which version and tag
   did you find, and what blockers did the report list?") were classified
   as live-data requests (domains: "sports", then "news") and the runtime
   forced the canned refusal: *"I couldn't provide a grounded current
   news answer because Missing live-data evidence for a freshness-sensitive
   answer."* — in a session about a local git repository, with no news
   involved. There is no config switch to disable or pin the classifier to
   `local_only` for tool/SDK agents. Workaround shipped: detect the canned
   refusal and retry the turn inside the same session (classification is
   per-turn and non-deterministic, so retries pass). Suggestion: allow
   disabling the classifier per agent profile, or fall back to
   `local_only` when classification confidence is low / the model is below
   a capability tier.
8. **Adding a second agent profile silently requires `default_agent`.**
   After `config init` (single agent) we added a `release` profile; every
   command then failed with "multi-agent config requires explicit
   'default_agent'". Reasonable rule, but `config init` could set it
   automatically, and the fix location (top-level key) is only documented
   inside an unrelated action-policy example in getting-started.
   A cold 1.5B model on a shared vCPU needs far longer for a multi-tool run;
   we raised `providers.ollama.timeout_seconds` to 900. Consider a higher
   default, or a cold-start-aware first-request timeout, for the local
   provider.
