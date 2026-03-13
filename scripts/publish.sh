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
python -m build
twine upload dist/*
echo "✓ Published $VERSION to PyPI"
