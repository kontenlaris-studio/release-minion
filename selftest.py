"""Deterministic selftest for ReleaseMinion's tools (no model required).

Builds a throwaway git repo with a known tag/version/changelog state and
checks every tool against the expected facts.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from release_agent import (  # noqa: E402
    changelog_status,
    diff_summary,
    git_history,
    project_version,
)


def call(fn, **kwargs):
    """Invoke an OpenMinion @tool-decorated function directly if possible."""
    target = getattr(fn, "fn", None) or getattr(fn, "func", None) or fn
    return target(**kwargs)


def sh(cwd: str, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def main() -> int:
    passed = failed = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"PASS {name}")
        else:
            failed += 1
            print(f"FAIL {name} {detail}")

    with tempfile.TemporaryDirectory() as tmp:
        sh(tmp, "git", "init", "-q")
        sh(tmp, "git", "config", "user.email", "test@example.com")
        sh(tmp, "git", "config", "user.name", "Test")
        Path(tmp, "pyproject.toml").write_text(
            '[project]\nname = "demo"\nversion = "0.2.0"\n'
        )
        Path(tmp, "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0\n- first\n")
        Path(tmp, "a.txt").write_text("one\n")
        sh(tmp, "git", "add", "-A")
        sh(tmp, "git", "commit", "-qm", "feat: initial release")
        sh(tmp, "git", "tag", "v0.1.0")
        for i, msg in enumerate(["feat: add export", "fix: crash on empty input",
                                 "docs: update readme"]):
            Path(tmp, f"f{i}.txt").write_text(f"{i}\n")
            sh(tmp, "git", "add", "-A")
            sh(tmp, "git", "commit", "-qm", msg)

        hist = call(git_history, repo_path=tmp)
        check("history tag", "latest_tag: v0.1.0" in hist, hist[:120])
        check("history count", "commits_since_tag: 3" in hist, hist[:120])
        check("history subjects", "add export" in hist and "crash on empty" in hist)

        diff = call(diff_summary, repo_path=tmp)
        check("diff range", "v0.1.0..HEAD" in diff, diff[:120])
        check("diff files", "f0.txt" in diff and "f2.txt" in diff, diff[:200])

        ver = call(project_version, repo_path=tmp)
        check("version", "0.2.0" in ver, ver)

        clog = call(changelog_status, repo_path=tmp)
        check("changelog present", "present" in clog, clog[:120])
        check("changelog no unreleased", "has_unreleased_section: False" in clog,
              clog[:200])

        empty = tempfile.mkdtemp()
        ver2 = call(project_version, repo_path=empty)
        check("version unknown", "unknown" in ver2, ver2)
        clog2 = call(changelog_status, repo_path=empty)
        check("changelog missing", "missing" in clog2, clog2)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
