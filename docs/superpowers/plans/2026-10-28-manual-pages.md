# Manual Pages implementation plan

Approved scope: prepare local files only. No commit, push, Release creation/upload,
data branch, schedule, live Pages deployment or new source fetching.

Design: keep BrowserRouter with BASE_URL basename; use BASE_URL for Hero. Build
real index.html entry points for all 12 known detail URLs, so directory redirects
and refresh work on a plain static host without an SPA fallback.

Transport: package the explicitly selected validated local snapshot as ZIP with
manifest/data and transport.json (7-day input-package validity, unrelated to data
retention). User manually uploads ZIP to a Release and supplies exact tag, filename
and SHA-256. Actions cannot access local .runtime. Missing/expired/corrupt inputs
stop. Release asset storage itself has no automatic expiry/deletion.

Workflow: workflow_dispatch only; default branch only; contents read by default;
no Fetcher or CWA secret. Verify transport, restore into fresh frontend/public/data,
run Python and frontend tests, build routes, verify output against manifest,
upload Pages artifact (1 day), deploy only after successful build job. Serialize
manual runs; block older run numbers after a newer successful deployment workflow.
An explicit Release asset is the retry source when a Pages artifact expires.

- [x] RED tests: package roundtrip, expiry, corruption, unknown files, traversal;
  nested-base routing/Hero/API and built static entry points.
- [x] Implement package/restore tool and shared cross-resource completeness check.
- [x] Implement basename/Hero and Pages build/verify helper.
- [x] Add manual workflow and documented GitHub setup / first snapshot transfer.
- [x] Package current valid snapshot locally; restore to isolated test/build workspace.
- [x] Main agent tests/build and real browser direct-open/reload with plain static host.
- [x] Independent Reviewer reads diff/requirements and independently tests; resolve blockers.


Verification (2026-10-28):
- Main agent: 105 Python tests, 76 isolated frontend tests, root and nested-base
  Pages builds passed. 20 built JSON hashes match the selected manifest.
- Independent Reviewer: separately ran 105 Python tests, 76 frontend tests and
  nested-base build; verified ZIP faults, workflow gates and manifest enforcement.
  No unresolved blocking findings. No .env read or real fetching by Reviewer.
- Plain static host (no SPA fallback): HTTP checks passed for 24 detail routes,
  40 JSON hash comparisons, Hero on both bases; unknown URLs returned 404.
- Main browser: nested Radar direct open + reload, Dashboard/Hero/back navigation,
  root CIMSS direct open + reload + child switch all observed; screenshots under
  .runtime/pages-manual. Reviewer did not independently operate the browser.
- Snapshot ZIP was prepared locally only. No upload, Git write, remote branch,
  schedule, real Actions execution or Pages publish was performed.
- Cloud authorization/download/deploy remain unverified until user-approved first run.
