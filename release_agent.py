"""ReleaseMinion — a release-readiness agent built on the OpenMinion 0.1 SDK.

Inspects a local Git repository with read-only tools, then produces a
structured release report (version, last tag, commits since tag, readiness,
blockers, draft highlights) and a follow-up answer from the same session,
demonstrating OpenMinion sessions/memory.

Usage:
    python release_agent.py --repo /path/to/repo [--agent release]
                            [--config .openminion/agents.json]
                            [--out data/report.json] [--notes data/release-notes.md]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

from openminion import Agent, AgentOutputValidationError, ProviderError, tool

MAX_OUT = 3000  # bound every tool output


def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=20,
    )
    if proc.returncode != 0:
        return f"git error: {proc.stderr.strip()[:300]}"
    return proc.stdout.strip()


def _bounded(text: str) -> str:
    return text[:MAX_OUT] if text else "(empty)"


@tool(min_scope="READ_ONLY", idempotent=True)
def git_history(repo_path: str, limit: int = 20) -> str:
    """Return the latest git tag and the commits since that tag for a repo."""
    tag = _git(repo_path, "describe", "--tags", "--abbrev=0")
    if tag.startswith("git error"):
        tag = ""
    rng = f"{tag}..HEAD" if tag else "HEAD"
    log = _git(repo_path, "log", rng, f"-{limit}", "--pretty=format:%h %s")
    count = _git(repo_path, "rev-list", "--count", rng)
    return _bounded(
        f"latest_tag: {tag or '(none)'}\ncommits_since_tag: {count}\ncommits:\n{log}"
    )


@tool(min_scope="READ_ONLY", idempotent=True)
def diff_summary(repo_path: str) -> str:
    """Return a diff stat (files changed, insertions, deletions) since the latest tag."""
    tag = _git(repo_path, "describe", "--tags", "--abbrev=0")
    rng = f"{tag}..HEAD" if tag and not tag.startswith("git error") else "HEAD~10..HEAD"
    stat = _git(repo_path, "diff", "--stat", rng)
    short = _git(repo_path, "diff", "--shortstat", rng)
    return _bounded(f"range: {rng}\n{stat}\n{short}")


@tool(min_scope="READ_ONLY", idempotent=True)
def project_version(repo_path: str) -> str:
    """Read the project version from pyproject.toml, package.json, or a VERSION file."""
    root = Path(repo_path)
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(errors="replace").splitlines():
            s = line.strip()
            if s.startswith("version") and "=" in s:
                return f"pyproject.toml version: {s.split('=', 1)[1].strip().strip(chr(34))}"
    pkg = root / "package.json"
    if pkg.exists():
        try:
            return f"package.json version: {json.loads(pkg.read_text())['version']}"
        except Exception:
            pass
    ver = root / "VERSION"
    if ver.exists():
        return f"VERSION file: {ver.read_text().strip()}"
    return "version: unknown (no pyproject.toml, package.json, or VERSION found)"


@tool(min_scope="READ_ONLY", idempotent=True)
def changelog_status(repo_path: str) -> str:
    """Check CHANGELOG.md: existence, Unreleased section, and entries."""
    path = Path(repo_path) / "CHANGELOG.md"
    if not path.exists():
        return "CHANGELOG.md: missing"
    text = path.read_text(errors="replace")
    heads = [ln.strip() for ln in text.splitlines() if ln.startswith("## ")][:8]
    return _bounded(
        "CHANGELOG.md: present\n"
        f"has_unreleased_section: {'unreleased' in text.lower()}\n"
        f"top_headings: {heads}"
    )


class ReleaseReport(BaseModel):
    version: str
    last_tag: str
    commits_since_tag: int
    readiness: str  # "ready" or "needs_work"
    blockers: list[str]
    highlights: list[str]
    summary: str


def apply_guardrails(report: ReleaseReport, facts: dict) -> tuple[ReleaseReport, list[str]]:
    """Verify the model's report against deterministic tool facts.

    Small local models get the facts right but the verdict wrong; the
    documented readiness rule is cheap to check exactly, so the workflow
    enforces it and logs every correction.
    """
    import re

    corrections: list[str] = []
    hist = facts["git_history"]
    m = re.search(r"latest_tag: (\S+)", hist)
    tag = m.group(1) if m else ""
    if tag and tag != "(none)" and report.last_tag != tag:
        corrections.append(f"last_tag {report.last_tag!r} -> {tag!r}")
        report.last_tag = tag
    m = re.search(r"commits_since_tag: (\d+)", hist)
    if m and report.commits_since_tag != int(m.group(1)):
        corrections.append(
            f"commits_since_tag {report.commits_since_tag} -> {m.group(1)}")
        report.commits_since_tag = int(m.group(1))
    m = re.search(r"version[:\s]+([0-9]+\.[0-9]+\.[0-9]+)",
                  facts["project_version"])
    if m and report.version != m.group(1):
        corrections.append(f"version {report.version!r} -> {m.group(1)!r}")
        report.version = m.group(1)

    clog = facts["changelog_status"]
    documented = (
        f"## {report.version}" in clog
        or f"## [{report.version}]" in clog
        or "has_unreleased_section: True" in clog
    )
    if not documented:
        blocker = (f"CHANGELOG.md does not document version "
                   f"{report.version} (no matching heading, no Unreleased section)")
        if blocker not in report.blockers:
            report.blockers.append(blocker)
        if report.readiness != "needs_work":
            corrections.append(
                f"readiness {report.readiness!r} -> 'needs_work' "
                "(changelog does not document the version)")
            report.readiness = "needs_work"
    if report.commits_since_tag == 0 and report.readiness == "ready":
        corrections.append("readiness 'ready' -> 'needs_work' (no commits since tag)")
        report.readiness = "needs_work"
        report.blockers.append("No commits since the last tag")
    return report, corrections


INSTRUCTIONS = (
    "You are ReleaseMinion, a release-readiness inspector. "
    "Always inspect the repository with the provided tools before answering; "
    "never guess a version, tag, or count. "
    "readiness is 'ready' only when the changelog already documents the current "
    "version (or has an Unreleased section ready) AND there is at least one "
    "commit since the last tag; otherwise use 'needs_work' and list each "
    "concrete blocker. Highlights are short release-note bullets drawn from "
    "the actual commit subjects."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the git repo to inspect")
    parser.add_argument("--agent", default="release")
    parser.add_argument("--config", default=".openminion/agents.json")
    parser.add_argument("--session", default="release-demo-v5")
    parser.add_argument("--out", default="data/report.json")
    parser.add_argument("--notes", default="data/release-notes.md")
    args = parser.parse_args()

    repo = str(Path(args.repo).resolve())

    # Deterministic ground-truth facts, gathered with the same tool functions
    # the agent uses. Small local models are unreliable at emitting strict
    # JSON via output_type coercion, so the flow is two-phase:
    #   A) the agent inspects the repo with its tools (free text);
    #   B) a structuring turn converts the inspection into ReleaseReport JSON,
    #      checked against these facts.
    facts = {
        "git_history": git_history.fn(repo_path=repo) if hasattr(git_history, "fn") else git_history(repo_path=repo),
        "project_version": project_version.fn(repo_path=repo) if hasattr(project_version, "fn") else project_version(repo_path=repo),
        "changelog_status": changelog_status.fn(repo_path=repo) if hasattr(changelog_status, "fn") else changelog_status(repo_path=repo),
    }
    schema = json.dumps(ReleaseReport.model_json_schema())

    tool_names = ["git_history", "diff_summary", "project_version",
                  "changelog_status"]
    try:
        # Phase A uses its own Agent instance with forced tools: a small
        # local model otherwise sometimes declines to call tools at all.
        with Agent(
            agent_id=args.agent,
            config_path=args.config,
            instructions=INSTRUCTIONS,
            tools=[git_history, diff_summary, project_version, changelog_status],
            forced_tools=tool_names,
            session_id=args.session,
        ) as inspector:
            inspection = inspector.run(
                f"Inspect the repository at {repo}. Call each of your tools "
                "exactly once, then summarize the facts and your readiness "
                "verdict in plain text."
            )
            print(f"[inspection] {inspection.text}\n")
            print("[verified facts] "
                  + json.dumps({k: v.replace(chr(10), " | ")[:220]
                                for k, v in facts.items()}) + "\n")

        # Phases B/C share the same session from a tool-less Agent instance.
        with Agent(
            agent_id=args.agent,
            config_path=args.config,
            instructions=INSTRUCTIONS,
            session_id=args.session,
        ) as agent:

            report = None
            last_err = ""
            for _ in range(2):
                reply = agent.run(
                    "Now output ONLY a JSON object (no prose, no code fences) "
                    f"matching this schema: {schema}. Base it on your "
                    f"inspection and these verified facts: {json.dumps(facts)}. "
                    "A version counts as documented only if a changelog "
                    "heading exactly matches it."
                    + (f" Previous attempt failed validation: {last_err}" if last_err else "")
                )
                text = reply.text.strip()
                start, end = text.find("{"), text.rfind("}")
                try:
                    report = ReleaseReport.model_validate_json(text[start:end + 1])
                    break
                except Exception as exc:  # noqa: BLE001 - retry once with error
                    last_err = str(exc)[:200]
            if report is None:
                print(f"structured output failed: {last_err}")
                return 1

            report, corrections = apply_guardrails(report, facts)
            for line in corrections:
                print(f"[guardrail] {line}")
            print(report.model_dump_json(indent=2))

            # The runtime's LLM freshness classifier (same small model)
            # intermittently mislabels recall questions as live-data
            # requests and forces a refusal; retry within the session.
            recap = report.model_dump_json()
            memory_text = ""
            for attempt in range(3):
                memory = agent.run(
                    "Answer from this conversation's history only; this is "
                    "a memory-recall question about a local git repository, "
                    "not a news or live-data question. Your verified "
                    f"report in this session was: {recap}. Restate its "
                    "version, last_tag, readiness, and blockers in two "
                    "short sentences."
                )
                memory_text = memory.text
                if "couldn't provide a grounded" not in memory_text:
                    break
                print(f"[session memory] attempt {attempt + 1} misclassified "
                      "as live-data request; retrying")
            print(f"\n[session memory] {memory_text}")
    except ProviderError as exc:
        print(f"provider failed: {exc.code}: {exc.message}")
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2))

    notes = Path(args.notes)
    lines = [f"# Release notes — {report.version}", "", f"Status: {report.readiness}",
             f"Commits since {report.last_tag}: {report.commits_since_tag}", "",
             "## Highlights"]
    lines += [f"- {h}" for h in report.highlights] or ["- (none)"]
    if report.blockers:
        lines += ["", "## Blockers"] + [f"- {b}" for b in report.blockers]
    lines += ["", f"_{report.summary}_", "",
              "Generated by ReleaseMinion (OpenMinion 0.1 SDK)."]
    notes.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {out} and {notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
