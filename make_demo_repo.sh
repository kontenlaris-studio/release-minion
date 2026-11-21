#!/usr/bin/env bash
# Recreate the deterministic demo repository used in the README/video.
# State: tag v0.2.0, version bumped to 0.3.0, 4 commits since the tag,
# CHANGELOG.md still only documents 0.2.0 (the planted release blocker).
set -euo pipefail
cd "$(dirname "$0")"
rm -rf demo-repo
mkdir demo-repo && cd demo-repo
git init -q
git config user.email "demo@kontenlaris.studio"
git config user.name "Kontenlaris Studio"
printf '[project]\nname = "sample-app"\nversion = "0.2.0"\n' > pyproject.toml
printf '# Changelog\n\n## 0.2.0\n- Initial public release\n' > CHANGELOG.md
echo "print('hello')" > app.py
git add -A && git commit -qm "feat: initial release"
git tag v0.2.0
sed -i 's/version = "0.2.0"/version = "0.3.0"/' pyproject.toml
git add -A && git commit -qm "chore: bump version to 0.3.0"
printf "def export_csv():\n    return 'csv'\n" >> app.py
git add -A && git commit -qm "feat: add CSV export"
sed -i "s/print('hello')/print('hello world')/" app.py
git add -A && git commit -qm "fix: greeting truncated on narrow terminals"
echo "# Sample App" > README.md
git add -A && git commit -qm "docs: add README"
echo "demo-repo ready: $(git describe --tags)"
