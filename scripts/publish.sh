#!/bin/bash
set -e
VERSION=$(grep "^version" pyproject.toml | cut -d'"' -f2)
CLI_VERSION=$(grep "version_option" src/driftbase/cli/cli.py | grep -o '"[0-9.]*"' | tr -d '"')

if [ "$VERSION" != "$CLI_VERSION" ]; then
  echo "❌ Version mismatch: pyproject.toml=$VERSION, cli.py=$CLI_VERSION"
  exit 1
fi

echo "✓ Versions match: $VERSION"
rm -rf dist/
git add -A
git commit -m "release: v$VERSION"
git tag "v$VERSION"
git push origin main --tags
echo "✓ Tagged v$VERSION — GitHub Action will publish to PyPI and create release"
