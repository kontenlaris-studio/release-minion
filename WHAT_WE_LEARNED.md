# What We Learned — ReleaseMinion on OpenMinion 0.1

Actionable feedback from building a small, real, local-first agent with
OpenMinion 0.1.23 (details and repro steps in `BUILDING_BLOCKS.md`).

## What worked well

- **The SDK surface is genuinely small.** `@tool` + `Agent(...)` +
  `agent.run()` got a working tool-using agent in one file; docstrings as
  tool descriptions and `min_scope`/`idempotent` hints are the right level
  of ceremony.
- **Project-scoped config via `OPENMINION_HOME` / `OPENMINION_DATA_ROOT`**
  makes a repo self-contained and reproducible — ideal for hackathon and CI
  use. The shipped `config/agents.json` + three env vars reproduce our
  exact setup.
- **`openminion doctor --check-turn` is the right idea.** A one-command
  readiness probe that performs a real turn caught two of our three
  environment problems before the agent code even ran.
- **Sessions just work.** A follow-up question in the same `session_id`
  answered from context with no extra plumbing.
- **Tools are directly callable**, which made a deterministic, model-free
  selftest (10/10) possible — a big deal for testing agent tooling in CI.

## What cost us the most time (in order)

1. **Timeout layers (60 s provider / 90 s chat-turn / 300 s brain).** Local
   CPU inference with a small model needs minutes per multi-tool turn. We
   burned two long runs discovering the layers one at a time. Fix:
   document the layers together in the local-provider guide, and name the
   firing config key in the `TurnTimeoutError` message.
2. **Proxy env vars break localhost providers.** In sandboxed/CI VMs with
   `http_proxy` set and bracketed IPv6 entries in `no_proxy`, the Ollama
   provider fails with a cryptic `Invalid port: ':1]'`. Localhost traffic
   should bypass proxy handling entirely, and the parser should tolerate
   bracketed entries.
3. **`output_type` does not constrain output when real tools are present.**
   With a small local model the coercion path fails on prose. Either
   auto-add a final schema-constrained turn, or warn at `Agent(...)`
   construction time when `output_type` is combined with tools and a
   fallback-strategy provider.
4. **Config discoverability.** The model id lives under
   `providers.<id>.model` (not on the agent profile), `default_agent`
   becomes mandatory only after adding a second profile, and
   `config init --provider` accepts a much smaller enum than
   `setup --list-providers` (including the legacy `cortensor` id resolving
   to the Router, not the Portal). A short "config anatomy" page with one
   annotated `agents.json` would remove all four surprises at once.
5. **Docs/version drift.** The docs reference models newer than the 0.1.23
   package line; a visible docs version banner would set expectations.

## Pattern we would recommend to other builders

For small local models, treat the model as an **untrusted proposer** and
build the workflow around it:

1. **Two-phase flow.** A free-text inspection turn (tools + prose), then a
   structure-only turn that emits JSON validated against a Pydantic
   schema, with the tool facts re-supplied as ground truth.
2. **Deterministic guardrails on load-bearing fields.** Our 1.5B model
   returned the right facts in the JSON but the wrong verdict — once even
   an off-schema readiness value (`"comfortable"`). A ~40-line checker
   re-derives version/tag/commit count from the tool outputs and enforces
   the documented readiness rule, logging every correction
   (`[guardrail] readiness 'comfortable' -> 'needs_work'`). The final
   report is correct on every run; the model's prose is not trusted.
3. **Recap-assisted recall.** Session-recall questions answered from deep
   history came back garbled; restating the verified report in the
   follow-up question ("your verified report was: …") makes the memory
   demo reliable while staying inside one session.
4. **Retry classifier refusals.** The freshness classifier's canned
   refusal is detectable verbatim; retrying the turn in-session passes,
   because classification is per-turn and non-deterministic.

None of this is OpenMinion-specific — but OpenMinion's design (directly
callable tools, shared session state, project-scoped config) made each
guardrail a few lines instead of a subsystem.
