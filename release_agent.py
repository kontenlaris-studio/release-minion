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
    parser.add_argument("--session", default="release-demo")
    parser.add_argument("--out", default="data/report.json")
    parser.add_argument("--notes", default="data/release-notes.md")
    args = parser.parse_args()

    repo = str(Path(args.repo).resolve())
    prompt = f"Inspect the repository at {repo} and produce the release report."

    try:
        with Agent(
            agent_id=args.agent,
            config_path=args.config,
            instructions=INSTRUCTIONS,
            tools=[git_history, diff_summary, project_version, changelog_status],
            output_type=ReleaseReport,
            session_id=args.session,
        ) as agent:
            try:
                result = agent.run(prompt)
                report = result.output
            except AgentOutputValidationError:
                # Fallback path: free-text inspection first, then a structured
                # pass over the gathered facts (documented in What We Learned).
                raw = agent.run(prompt + " Answer as plain text with all facts.")
                follow = agent.run(
                    "Convert your inspection into the structured report now. "
                    f"Facts you found: {raw.text[:2000]}"
                )
                report = follow.output
            print(report.model_dump_json(indent=2))

            memory = agent.run(
                "From your inspection in this session: what is the current "
                "version, and which blockers remain? Two short sentences."
            )
            print(f"\n[session memory] {memory.text}")
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
