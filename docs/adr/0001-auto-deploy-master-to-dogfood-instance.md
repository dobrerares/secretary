---
status: accepted
---

# Auto-deploy master to a single dogfood instance

Secretary is a single-user, self-hosted product (PRD §2, §3) where the deployer is the developer. There is no shared "production" environment owned by anyone but the user. Master pushes auto-deploy to the developer's own Coolify-managed instance via webhook; the same image is published to GHCR as a public artifact for other deployers to pull.

## Considered options

- **(a) CI only.** Quality gates, no published artifact. Rejected: forces every deployer (including future ones) to clone-and-build, contradicting the open-source self-hosted distribution model.
- **(b) CI + image publish, manual deploy.** Image lands in GHCR; deployer clicks the Coolify button. Rejected: the deploy click adds friction for the only deployer who is also the developer (i.e., adds latency to the dogfood feedback loop) without buying any safety Coolify's healthcheck-gated rollout doesn't already provide.
- **(c2) CI + image publish + staging-then-promote.** Two Coolify apps, master→staging webhook, tag→prod webhook. Rejected: with one running instance and one user, "staging" is ceremony — there's nothing to validate against between staging and prod that the dogfood instance itself wouldn't surface.
- **(c1) CI + image publish + auto-deploy on green master.** Chosen.

## Consequences

- **Migrations must run on container start.** Entrypoint script runs `alembic upgrade head` before launching uvicorn. Without this, auto-deploy ships code that expects a schema the running DB doesn't have. Tradeoff vs. a Coolify pre-deploy hook: the entrypoint approach keeps migration logic in the repo where it's visible, at the cost of running migrations on every restart (idempotent, ~negligible).
- **Persistent volume on `/app/data` is load-bearing.** The Coolify app must mount a persistent volume on `/app/data` from creation; otherwise every deploy wipes the SQLite database silently. This is the failure mode least likely to be caught by anything else.
- **Healthcheck-gated deploy is non-optional.** Coolify must wait for the new container to pass `Dockerfile`'s `HEALTHCHECK` before tearing down the old one, with auto-rollback on failure. This is what catches a broken migration before it takes down the dogfood instance.
- **Image is published as a public GHCR artifact** (`ghcr.io/dobrerares/secretary`). The same image powers the dogfood deploy and external deployers — one pipeline, one artifact, two consumers.
- **Tight coupling between "merging a PR" and "production restart."** Branch protection (required CI checks, no direct push to master, no force-push) is required to keep this safe. Admin bypass is allowed for genuine emergencies; force-push is not (it would invalidate the immutable `:sha-<short>` rollback tags).
