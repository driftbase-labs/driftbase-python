# Release Checklist for v0.9.3

## Pre-Release Verification

### ✅ Code Complete
- [x] PHASE 1: Architecture consolidation
- [x] PHASE 2: GitHub Action (standalone + cloud modes)
- [x] PHASE 3: CLI hardening (--ci flag, --offline demo, improved diagnose)
- [x] PHASE 4: Langfuse + LangSmith connectors
- [x] PHASE 5: Weight learner with progressive blending
- [x] PHASE 6: Package verification (demo, MCP, verify_install.sh)
- [x] PHASE 7: Documentation (README, CHANGELOG, Action README)
- [x] PHASE 8: Telemetry (DEFERRED with TODO)
- [x] PHASE 9: Data contribution (DEFERRED with TODO)
- [x] PHASE 10: Release hygiene (pyproject.toml, classifiers, keywords)

### ✅ Tests Passing
```bash
pytest tests/ -v
# Expected: 279+ tests passing
```

### ✅ GitHub Action Tests
```bash
cd github-action/src && python test_run.py
# Expected: All 11 tests passed
```

### ✅ Installation Verification
```bash
pip install -e .
driftbase --version
driftbase demo --offline
# Expected: Demo generates 20 runs successfully
```

### ✅ Package Build
```bash
python -m build
# Expected: Successfully built .tar.gz and .whl
```

### ✅ Documentation
- [x] README.md updated with GitHub Action, demo, LangSmith support
- [x] CHANGELOG.md created with full release notes
- [x] github-action/README.md comprehensive (282 lines)
- [x] pyproject.toml has keywords, classifiers, updated URLs

## Release Steps

### 1. Clean Working Directory
```bash
git status
# Should be clean or only include intended changes
```

### 2. Commit Final Changes
```bash
git add .
git commit -m "Release v0.9.3: GitHub Action, LangSmith connector, progressive weight learning"
```

### 3. Create Git Tag
```bash
git tag -a v0.9.3 -m "Release v0.9.3

- GitHub Action for automated drift checks in CI/CD
- LangSmith connector with full Cloud parity
- Progressive weight learning (30% → 70% blending)
- CLI enhancements (--ci, --offline, improved diagnose)
- Comprehensive documentation and tests

See CHANGELOG.md for full details."
```

### 4. Verify Version
```bash
python -m build
# Should now build as driftbase-0.9.3.tar.gz (no .dev suffix)
```

### 5. Push to GitHub
```bash
git push origin main
git push origin v0.9.3
```

### 6. Publish to PyPI
```bash
# Build clean distributions
rm -rf dist/ build/
python -m build

# Upload to PyPI (requires PyPI credentials)
python -m twine upload dist/*
```

### 7. Verify PyPI Package
```bash
# Wait 2-3 minutes for PyPI to process
pip install --upgrade driftbase
driftbase --version
# Should show: driftbase, version 0.9.3
```

### 8. Test GitHub Action
Create a test repository with `.github/workflows/drift-check.yml`:
```yaml
- uses: driftbase-labs/driftbase-python/github-action@v0.9.3
```

Verify it installs driftbase 0.9.3 from PyPI.

## Post-Release

### Update Documentation Sites
- [ ] Update https://driftbase.io with new features
- [ ] Update docs.driftbase.io/github-action

### Announce Release
- [ ] GitHub release notes (auto-generated from tag)
- [ ] Discord announcement
- [ ] Twitter/X post

## Rollback Plan

If critical issues are found:

1. Yank the PyPI release:
   ```bash
   pip install twine
   twine upload --repository pypi --skip-existing dist/*
   # Then use PyPI web interface to yank version
   ```

2. Create hotfix tag:
   ```bash
   git tag -d v0.9.3
   git push origin :refs/tags/v0.9.3
   # Fix issues
   git tag v0.9.3.1
   git push origin v0.9.3.1
   ```

## Version Numbering

- **Current:** 0.9.3 (pre-1.0 release)
- **Next planned:** 0.9.4 (after Cloud API is deployed with Phases 8+9)
- **Stable 1.0:** After production validation and Cloud integration

## Known Limitations

Document in release notes:

1. **Telemetry disabled** - Deferred until Cloud API is live (Phase 8)
2. **Data contribution disabled** - Deferred until Cloud API is live (Phase 9)
3. **Cloud mode in GitHub Action** - Requires DRIFTBASE_API_KEY (not yet available publicly)
4. **Minimum data requirement** - Need 50+ runs per version for TIER3 confidence

## Support Channels

- **Issues:** https://github.com/driftbase-labs/driftbase-python/issues
- **Discord:** https://discord.gg/driftbase
- **Email:** info@driftbase.io
