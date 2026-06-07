# Activating CI

The CI workflow lives at [`ci.yml.template`](ci.yml.template). It is shipped
outside `.github/workflows/` because the OAuth token used for the initial
push lacked the `workflow` scope.

## To activate

Pick whichever path is easier for you:

### Option A — refresh the gh scope (recommended)

```bash
gh auth refresh -s workflow
mkdir -p .github/workflows
mv ci/ci.yml.template .github/workflows/ci.yml
git add .github/workflows/ci.yml
git rm ci/ci.yml.template
git commit -m "ci: activate GitHub Actions workflow"
git push
```

### Option B — paste it via the GitHub web UI

1. Open https://github.com/bargainfactory/priorauthguard
2. **Actions** tab → **set up a workflow yourself**
3. Replace the default scaffold with the contents of `ci.yml.template`.
4. Commit on `main`.
