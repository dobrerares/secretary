# CI/CD Rollout — Handoff

Status as of this commit. Delete this file once the rollout is fully complete.

See `docs/adr/0001-auto-deploy-master-to-dogfood-instance.md` for the architectural decision being implemented.

## Done

| Phase | PR | What landed |
|---|---|---|
| 1 | [#6](https://github.com/dobrerares/secretary/pull/6) | `entrypoint.sh` runs `alembic upgrade head` then exec uvicorn. `Dockerfile` updated. `.gitattributes` enforces LF for shell scripts. |
| 2 | [#7](https://github.com/dobrerares/secretary/pull/7) | `.github/workflows/ci.yml` with 6 jobs: `lint`, `format`, `test`, `migrations`, `pip-audit`, `docker-build`. `.dockerignore`. Existing codebase brought up to ruff standard (29 files reformatted, 2 F841 fixes). |
| 3 | [#8](https://github.com/dobrerares/secretary/pull/8) | `.github/workflows/release.yml` publishes `ghcr.io/dobrerares/secretary` on master push (`:latest` + `:sha-<short>`) and on `v*.*.*` tags (`:X.Y.Z` + `:X.Y` + `:X`). |
| 6 | [#9](https://github.com/dobrerares/secretary/pull/9) | `.github/dependabot.yml` (pip + github-actions, weekly). `.github/workflows/codeql.yml` (PRs + master + Monday cron, `security-extended`). |

**Master CI is green.** First image published successfully on phase 3 merge.

## Not done — ordered by what to tackle next

### 1. Make GHCR package public (1 minute, manual)

https://github.com/users/dobrerares/packages/container/secretary/settings → Danger Zone → Change visibility → Public.

Verify: `docker pull ghcr.io/dobrerares/secretary:latest` from any anonymous shell.

### 2. Phase 4 — Coolify deploy webhook (PR ready to open on signal)

**Blocked on user**: create the Coolify app first.

Required setup steps before opening the PR (from the deploy guide):
- Create Coolify application, source = Docker Image, image = `ghcr.io/dobrerares/secretary:latest`
- **Mount persistent volume on `/app/data` BEFORE first deploy** (load-bearing — wiping on remount loses the SQLite DB)
- Configure env vars (mirror `.env.example`)
- Enable healthcheck-gated deploy (`/health`) + auto-rollback on failure
- First deploy manually, smoke-test that data survives a redeploy
- Generate Coolify deploy webhook URL → add as repo secret `COOLIFY_DEPLOY_WEBHOOK`

When that's done: I'll PR a 5-line change adding the webhook curl step to `release.yml`.

### 3. Phase 5 — Branch protection ruleset (manual or via gh api)

Required check names that now exist on master and can be referenced:
- `lint`, `format`, `test`, `migrations`, `pip-audit`, `docker-build` (CI workflow)
- `analyze` (CodeQL workflow)

Settings (per ADR-0001 and Q6 of grilling):
- Require PR (no direct push to master)
- Require all 7 status checks to pass before merge
- Required reviewers: 0
- Linear history: on
- Block force-push: on (no admin bypass — protects `:sha-<short>` rollback tags)
- Allow admin bypass on required-checks: yes

GitHub UI: Settings → Rules → Rulesets → New branch ruleset.

### 4. Phase 7 — README deploy section

Open after Phase 4 lands (so the docs reflect the actual webhook flow). Should include:
- "Run with Docker" pointing at `ghcr.io/dobrerares/secretary:latest`
- Required env vars table
- Volume mount note for `/app/data`
- Optional Coolify-specific tips for deployers using the same setup

### 5. 15 open Dependabot PRs

First-run Dependabot opened the maximum (5 github-actions + 10 pip). Branch names under `dependabot/`. CI runs on each. Up to user to review individually or batch-merge.

Notable ones:
- `actions/checkout`, `actions/setup-python`, `docker/build-push-action` — bumps to fix the Node.js 20 deprecation warning the runner flagged
- `ruff` bump → would re-trigger format check; safe but confirm CI green before merging

### 6. Open decision — backup strategy for `/app/data` volume

The volume is the single point of data loss. Options laid out in the deploy guide; user hasn't picked one yet:
- (a) Coolify built-in volume backup
- (b) Periodic SQLite dump to off-host storage
- (c) Litestream / replicated SQLite
- (d) Accept ephemerality, declare it explicitly

If the chosen approach is (b) or (c), this likely warrants its own ADR.

## Reference

- ADR: `docs/adr/0001-auto-deploy-master-to-dogfood-instance.md`
- Domain glossary: `CONTEXT.md`
- Workflows: `.github/workflows/{ci,release,codeql}.yml`
- Dependabot config: `.github/dependabot.yml`
- Container entrypoint: `entrypoint.sh` + `Dockerfile`
- Image registry: `ghcr.io/dobrerares/secretary`
- Tags published: `:latest`, `:sha-<short>` (master); `:X.Y.Z`, `:X.Y`, `:X` (tags only)

## Resuming a session

Quick prompt to bring an agent up to speed: "Read HANDOFF.md and docs/adr/0001-*.md. Status: phases 1-3, 6 merged; 4, 5, 7 pending. Tell me what step is unblocked next."
