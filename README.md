# ReleaseMinion — a release-readiness agent on the OpenMinion 0.1 SDK

**Cortensor Hackathon #5 submission** (DoraHacks #2418) by Kontenlaris Studio.

**Demo video (2:21):** https://www.youtube.com/watch?v=DYcOw4r60dU
**Submission summary:** [`SUBMISSION.md`](SUBMISSION.md)

ReleaseMinion inspects a local Git repository and answers one question:
*is this project ready to release, and if not, what exactly blocks it?*

It uses the **OpenMinion 0.1 Python SDK** as a meaningful part of its runtime:
custom read-only tools, a durable session, and Pydantic-validated structured
output. The model runs **fully locally via Ollama** (`qwen2.5:1.5b`) — no API
key, no hosted service, in the local-first spirit of OpenMinion.

## What it does

Given a repository path, the agent:

1. Calls its tools to gather facts — latest tag, commits since the tag,
   diff summary, project version, changelog state.
2. Produces a structured `ReleaseReport`: version, last tag, commit count,
   `ready` / `needs_work` verdict, concrete blockers, and draft release-note
   highlights taken from real commit subjects.
3. Answers a follow-up question **from the same session** (session memory),
   without re-running the inspection.
4. Writes `data/report.json` and a draft `data/release-notes.md`.

## Tools (all `READ_ONLY`, idempotent)

| Tool | Fact it returns |
| --- | --- |
| `git_history` | latest tag + commits since that tag |
| `diff_summary` | diff stat for the release range |
| `project_version` | version from `pyproject.toml` / `package.json` / `VERSION` |
| `changelog_status` | changelog presence, Unreleased section, top headings |

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install openminion

# project-scoped OpenMinion config (Ollama provider, no credential needed)
export OPENMINION_HOME="$PWD"
export OPENMINION_DATA_ROOT="$PWD/.openminion"
mkdir -p .openminion
cp config/agents.json .openminion/agents.json

# local model runtime
ollama serve &          # https://ollama.com
ollama pull qwen2.5:1.5b
```

## Run

```bash
# deterministic tool checks (no model needed)
python selftest.py

# full agent run against any git repo (a sample repo is in demo-repo/)
python release_agent.py --repo ./demo-repo
```

Outputs land in `data/report.json` and `data/release-notes.md`; the console
shows the structured report and the session-memory follow-up answer.

## Recorded run (evidence/)

A full live run against `demo-repo/` is recorded in `evidence/`:

- `run-log.txt` — console transcript: tool facts, the model's draft,
  `[guardrail]` corrections, the final report, and the session-memory
  answer.
- `report.json` — the verified structured report.
- `release-notes.md` — the generated draft release notes.

Ground truth for the demo repo: tag `v0.2.0`, version `0.3.0`, 4 commits
since the tag, and a changelog that still only documents `0.2.0`. The
final report matches on every field: `needs_work`, blocked by the missing
changelog entry.

**Design note — the model is an untrusted proposer.** A 1.5B local model
returns the right facts but unreliable verdicts (it answered "ready"
twice, once with an off-schema readiness string). ReleaseMinion therefore
verifies every load-bearing field deterministically against the tool
outputs and enforces the documented readiness rule, logging each
correction as `[guardrail] …`. See `WHAT_WE_LEARNED.md` for the pattern.

## Notes for reviewers

- `BUILDING_BLOCKS.md` — which OpenMinion building blocks were exercised,
  what worked, and what did not (with repro steps for rough edges).
- `WHAT_WE_LEARNED.md` — actionable product feedback for the OpenMinion /
  Cortensor teams.
- Demo video (1–5 min) is linked from the submission PR.
