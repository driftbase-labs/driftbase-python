# Release Skill

**Read this skill before releasing a new version of driftbase.**

## Release Process

Driftbase uses **setuptools_scm** for automatic versioning from git tags.

### Pre-Release Checklist

1. **Clean working tree** — No uncommitted changes, no untracked files
2. **Tests passing** — `PYTHONPATH=src pytest tests/ --tb=short`
3. **Linting clean** — `ruff check src/ tests/`
4. **No backup files** — Delete any `.backup`, `.bak`, `.orig` files

### Versioning Convention

Follow semantic versioning: `MAJOR.MINOR.PATCH`

- **MAJOR** — Breaking changes (schema migrations, API changes)
- **MINOR** — New features (backward compatible)
- **PATCH** — Bug fixes (backward compatible)

### Tagging

```bash
# Ensure working tree is clean
git status

# Delete backup files if any exist
find . -name "*.backup" -delete
find . -name "*.bak" -delete

# Create annotated tag (required for setuptools_scm)
git tag -a v0.8.0 -m "Release v0.8.0: Add power analysis and adaptive confidence tiers"

# Push tag to origin
git push origin v0.8.0
```

**Important:**
- Always use annotated tags (`-a`), not lightweight tags
- Tag format: `vMAJOR.MINOR.PATCH` (e.g., `v0.8.0`)
- Tag message should summarize key changes

### Building Distribution

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build wheel and source distribution
python -m build

# Verify build contents
tar -tzf dist/driftbase-0.8.0.tar.gz | head -20
unzip -l dist/driftbase-0.8.0-py3-none-any.whl | head -20
```

**Check for:**
- No `.backup` or `.bak` files in the archive
- `hypothesis_rules.yaml` is included (package data)
- All Python files from `src/driftbase/` are present

### Uploading to PyPI

```bash
# Install twine if not already installed
pip install twine

# Upload to TestPyPI first (recommended)
twine upload --repository testpypi dist/* --skip-existing

# Test install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ driftbase

# If TestPyPI works, upload to real PyPI
twine upload dist/* --skip-existing

# Verify upload landed (PyPI index takes 2-3 minutes to update)
pip index versions driftbase | head -3
# Must show new version as LATEST
```

**Twine credentials:**
- Stored in `~/.pypirc` or passed via environment variables
- Use API tokens, not passwords (more secure)
- Never commit `.pypirc` to git

### Post-Release

1. **Verify PyPI page** — Check [pypi.org/project/driftbase](https://pypi.org/project/driftbase)
2. **Test install** — `pip install --upgrade driftbase` in a fresh venv
3. **Update README** — If installation instructions changed
4. **Announce** — Post release notes to GitHub, Discord, etc.

## setuptools_scm Configuration

In `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61.0", "setuptools_scm[toml]>=8.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools_scm]
```

**setuptools_scm behavior:**
- Reads git tags to determine version
- `v0.8.0` → `0.8.0` in package metadata
- Uncommitted changes → `0.8.0.dev1+g1234567` (dev version)
- Between tags → `0.8.1.dev0+g1234567` (next version)

**Never manually edit version in `__init__.py` or `pyproject.toml`.** Let git tags control versioning.

## Package Data

YAML files and other non-Python resources must be declared:

```toml
[tool.setuptools.package-data]
driftbase = ["**/*.yaml", "hypothesis_rules.yaml"]
```

Verify these files are included in the wheel after building.

## Common Release Issues

### Issue: `hypothesis_rules.yaml` missing from wheel

**Cause:** Not declared in `package-data`

**Fix:** Add to `[tool.setuptools.package-data]` and rebuild

### Issue: Backup files in distribution

**Cause:** `.backup` files not deleted before building

**Fix:**
```bash
find . -name "*.backup" -delete
find . -name "*.bak" -delete
rm -rf dist/ build/ *.egg-info
python -m build
```

### Issue: Version is `0.0.0` or `0.0.0.dev0`

**Cause:** No git tags found, or not using annotated tags

**Fix:**
```bash
# Create annotated tag
git tag -a v0.8.0 -m "Release v0.8.0"
git push origin v0.8.0
```

### Issue: `twine upload` hangs or times out

**Cause:** Large wheel, slow network, or PyPI rate limiting

**Fix:**
- Use `--skip-existing` to avoid re-uploading
- Wait 5-10 minutes and retry
- Check PyPI status page for outages

### Issue: License classifier warning

In `pyproject.toml`:

```toml
classifiers = [
    "License :: OSI Approved :: Apache Software License",
]
license-files = ["LICENSE"]
```

Ensure `LICENSE` file exists in repo root.

## License File

Driftbase is Apache 2.0 licensed. `LICENSE` file must be present in repo root.

If missing:
```bash
curl -o LICENSE https://www.apache.org/licenses/LICENSE-2.0.txt
git add LICENSE
git commit -m "Add Apache 2.0 license"
```

## Testing Pre-Release

Before tagging, test locally:

```bash
# Install in development mode
pip install -e .

# Or install from local build
python -m build
pip install dist/driftbase-*.whl

# Run tests against installed package
pytest tests/
```

## Changelog Maintenance

Keep `CHANGELOG.md` updated with each release:

```markdown
## [0.8.0] - 2025-01-15

### Added
- Power analysis for adaptive sample size requirements
- Confidence tiers (TIER1/TIER2/TIER3) based on statistical power
- Per-dimension significance tracking

### Fixed
- Calibration cache invalidation on baseline growth
- Weight sum invariant after correlation adjustment

### Changed
- Minimum runs now computed dynamically per agent (was fixed at 50)
```

## Git Workflow

Recommended branch workflow:

1. Work on feature branches: `git checkout -b feature/my-feature`
2. Merge to `main` when ready: `git checkout main && git merge feature/my-feature`
3. Tag main for release: `git tag -a v0.8.0 -m "..."`
4. Push main + tags: `git push origin main --follow-tags`

**Never tag feature branches.** Only tag `main`.

## Rollback

If a release has critical bugs:

1. **Yank the broken version on PyPI** (doesn't delete, just marks as broken)
2. **Create hotfix branch** from last good tag
3. **Fix bug, test thoroughly**
4. **Tag new patch version** (e.g., `v0.8.1`)
5. **Release new version**

**Don't delete PyPI releases.** Yanking is safer (pip won't install by default, but old installs still work).

## Summary

- Use semantic versioning: `vMAJOR.MINOR.PATCH`
- Always annotated tags: `git tag -a v0.8.0 -m "..."`
- Clean working tree before tagging
- Delete backup files before building: `rm -rf dist/ build/ *.egg-info`
- Test on TestPyPI first, then real PyPI
- Verify package data (YAML files) in wheel
- Let setuptools_scm handle version numbers, don't hardcode
- Update CHANGELOG.md with each release
