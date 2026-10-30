# Due-resource refresh implementation plan

**Goal:** Extend the existing manual publish/refresh pipeline with due selection, durable safe state, semantic content versions, automatic trusted recovery and protected rolling retention. Do not enable schedule, commit/push, or operate GitHub without the user's later approval.

**Architecture:** Keep update_images/update_snapshot and existing Services as shared entry points. Add small scheduling, content identity and GitHub artifact modules. Snapshot data and scheduler state travel separately and are bound by content identity. Preserve legacy explicit-input publish. New policy values require explicit configuration, not inferred defaults.

**Confirmed:** Intervals supplied by user; fast retry group radar/satellite/rainfall/rainfall_rankings; fast delays 10/20/40/60 minutes, slow 30/60/120/240/360 minutes. Latest success is separate from history completeness. Five distinct recent versions plus protected online version, maximum six. Never delete internal history JSON. No image-body archive.

**Additional confirmed test settings:** Data and scheduler-state artifacts expire after seven days; new ZIPs also expire after seven days, without extending legacy ZIP validity. Seven days is for this online test, not a permanent retention policy. History reconciliation is current-day only, at least 60 minutes apart, at most three rechecks after the initial probe and twelve historical probes per resource per run. Fixed-time catch-up selects only the latest due occurrence, at most yesterday. Internal history JSON retention remains undecided and no history files are deleted.

1. Add failing unittest cases and implement schedule/state primitives: UTC instants, interval due after successful checks, retry precedence, Asia/Taipei fixed times, bounded catch-up, missing/corrupt/mismatched state recovery, strict safe schemas.
2. Add failing content tests and implement stable identity: exclude execution metadata and known synthetic URL parameters, include observations/order/history, hash fixed/unknown-time image bodies, preserve unchanged JSON bytes.
3. Separate latest/history outcomes and bounded reconciliation using existing CWA parsing/slot builders. Avoid reprobes of successful old slots. Persist gap attempts independently; never let history-only faults back off latest checks.
4. Extend package/refresh adapter: backward-compatible legacy packages, user-selected v2 policy, scheduler-state always saved even for no-op/failure, content-aware publication gates and build verification.
5. Implement injectable GitHub transport/recovery/retention: trusted workflow/default branch/events, artifact digest + inner archive/manifest verification, bounded older-candidate fallback, dedup by content generation, read-back verified upload, current deployment marker, cleanup fail-closed. Two safe state artifacts remain separate from the data-version limit.
6. Extend the existing workflow with manual automatic-source/due controls, no schedule trigger; preserve mutual exclusion and reject obsolete runs before save/deploy. Manual publish reuses the selected data artifact without fetching.
7. Main agent runs focused/full Python tests, isolated frontend tests and Pages build/manifest checks. Independent non-implementing reviewer reads requirements and diff, independently tests and reports regressions; main fixes and requests recheck. Produce exact proposed GitHub changes for later authorization, not live execution.

## Local verification checkpoint (2026-10-30, Asia/Taipei)

- Main agent: final Python suite 194/194 passed; isolated frontend suite 76/76 passed; Pages build succeeded; 23 JSON files matched the validated local manifest, 12 detail entries verified and deployment marker copied unchanged; 18 workflow shell scripts passed syntax checks.
- Independent reviewer: pre-fix full suite 191/191 passed; after fixes independently reran 47 relevant cases (due 6, history 11, scheduler 14, cloud 14, CLI 2), all passed. Independently reproduced and rechecked the daily-rain partial-success and corrupt history-retry-cache issues; also checked invalid latest JSON cannot claim successful validation. No unresolved blocking findings.
- This checkpoint does not claim a browser visual check or real GitHub artifact recovery, upload, cleanup or deployment. No UI code changed. GitHub validation remains pending separate user authorization; no commit/push, schedule, data branch or automatic JSON commit was performed.
