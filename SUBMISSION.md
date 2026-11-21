# Cortensor Hackathon #5 — Submission: ReleaseMinion

- **Project repo:** https://github.com/kontenlaris-studio/release-minion
- **Demo video (2:21, unlisted):** https://www.youtube.com/watch?v=DYcOw4r60dU
- **Builder:** Kontenlaris Studio (solo), registered on DoraHacks as
  kontenlaris-studio.

## What it is

ReleaseMinion is a release-readiness agent built on the **OpenMinion 0.1
Python SDK** (0.1.23). Given a local Git repository, it answers: *is this
project ready to release, and if not, what exactly blocks it?* It produces
a structured report (version, last tag, commits since tag, readiness,
blockers, highlights) plus a draft `release-notes.md`.

## OpenMinion workflow

1. Four custom tools (`@tool`, all `READ_ONLY` + idempotent): git history,
   diff summary, project version, changelog status.
2. **Phase A** — an `Agent` with those tools (forced) inspects the repo in
   one session and reasons in prose.
3. **Phase B** — a structure-only turn in the same session emits JSON
   validated against a Pydantic `ReleaseReport` schema.
4. **Guardrails** — deterministic code re-verifies every load-bearing
   field against the raw tool outputs and enforces the readiness rule,
   logging corrections. (A 1.5B local model gets facts right but verdicts
   wrong; the workflow treats the model as an untrusted proposer.)
5. **Session memory** — a follow-up in the same session restates the
   verified report (recap-assisted recall).

Model: **Ollama `qwen2.5:1.5b`, fully local** — no API key, no hosted
service. Project-scoped config ships in the repo (`config/agents.json`),
so setup is: install SDK → copy config → pull model → run. A recorded
live run with ground truth is in `evidence/` (run log, report, notes);
the tool selftest passes 10/10 without a model.

## Building blocks tested

Agent execution, models/providers (Ollama preset), custom tools,
permissions (read-only policy), sessions/memory, structured output,
diagnostics (`doctor --check-turn`), and the config system — detailed in
[`BUILDING_BLOCKS.md`](https://github.com/kontenlaris-studio/release-minion/blob/master/BUILDING_BLOCKS.md).

## What we learned

Full feedback in
[`WHAT_WE_LEARNED.md`](https://github.com/kontenlaris-studio/release-minion/blob/master/WHAT_WE_LEARNED.md).
Headlines: three timeout layers (60s/90s/300s) fight local CPU inference;
proxy env vars break the localhost provider; `output_type` + tools
returns prose on small models; the LLM freshness classifier hijacks
recall turns.

Upstream issues filed:

- Proxy env breaks localhost provider —
  https://github.com/openminion/openminion/issues/834
- Freshness classifier misclassifies recall turns —
  https://github.com/openminion/openminion/issues/835
