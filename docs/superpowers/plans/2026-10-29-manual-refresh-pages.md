# Manual refresh and Pages implementation plan

**Goal:** Extend the existing manual workflow with protected fetching and reusable, validated artifact snapshots. No schedule, Git writes, data branch, or local data mutation.

**Architecture:** Select an explicit Release package or exact earlier workflow run artifact; verify checksum, expiry and JSON contracts. Optional refresh uses the existing isolated snapshot runner. A complete candidate with at least one successful product and changed resource may proceed. After tests/build verification, save the expiring public-only package before deployment. Artifact retention is a required operator choice (1–30 days), not a permanent retention policy. Existing publish-only mode remains available for recovery after deployment failure.

**Tech Stack:** Python unittest, shared snapshot/package validators, GitHub Actions artifacts, existing Vite Pages build.

1. Add failing Python tests for input policy, partial/all-source failure gates, report summaries, immutable archive round trips and workflow ordering.
2. Implement a small orchestration CLI reusing unpack_snapshot, run_candidate and pack_snapshot. Do not duplicate HTTP retries or publication contracts. Save only validated public data; report safe status separately.
3. Extend pages-manual.yml with mode, explicit previous run ID and required retention selection; restore Release or exact artifact, fetch with CWA_API_KEY, skip deployment on no update, preserve all existing tests/build/deployment guards. Save candidate before deploy.
4. Document first bootstrap, repeated runs, expiry/download failure, save/deploy failure recovery, permissions and unresolved retention policies. No automatic history deletion.
5. Main agent runs Python/frontend tests and isolated Pages build with exact manifest comparison. Independent reviewer reads diff and requirements, independently runs relevant tests and reviews cloud-only limitations. Fix/recheck blockers.

User explicitly requested implementation and local verification; do not commit/push, change GitHub settings, upload artifacts or dispatch workflows in this task.
