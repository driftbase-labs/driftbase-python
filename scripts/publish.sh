#!/bin/bash
# Release script for driftbase. Version is inferred from git tags by setuptools-scm.
# Usage: Set VERSION (e.g. 0.3.1), then run: ./scripts/publish.sh
set -e
if [ -z "$VERSION" ]; then
  echo "Usage: VERSION=0.3.1 ./scripts/publish.sh"
  exit 1
fi
echo "✓ Releasing v$VERSION (setuptools-scm will use tag for package version)"
rm -rf dist/
git add -A
git status
read -p "Commit and tag v$VERSION? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then exit 1; fi
git commit -m "release: v$VERSION" || true
git tag "v$VERSION"
git push origin main --tags
echo "✓ Tagged v$VERSION — GitHub Action will publish to PyPI"
