# Local automatic image updates

Approved scope: a manually started local Python process repeatedly calls the
existing update pipeline. The frontend remains a separate Vite process and reads
published JSON on refresh. No Flask, SQLite, GitHub settings, system scheduler,
automatic commit/push, or startup registration.

Architecture: extract shared single-batch orchestration into src/update_runner.py.
Both update_images.py (once, suitable for future CI) and watch_images.py (local
loop) use it. Keep all service parsing and publication contracts unchanged.
Default interval: 10 minutes after each completed batch, configurable; first
batch starts immediately. Selectable products, bounded cycles and --once allow
verification without leaving a background updater running.

- [x] Add failing tests: per-product failure isolation, private atomic status,
  secret-free failures, last-success preservation, interruption and process locks.
- [x] Implement shared single-run orchestrator and use it in update_images.py.
- [x] Add configurable local loop, Ctrl+C stop, duplicate-loop prevention,
  --once, --max-cycles and status inspection.
- [x] Store runtime locks/status under git-ignored .runtime, never public.
- [x] Verify all Python tests, bounded real updates and independent review.
- [x] Document two-terminal operation and the future CI boundary.

Status distinguishes running/success/partial_failure/failed/stopped, records UTC
attempt/finish/last-success timestamps and each product's result. Exceptions and
credentials are never serialized. Locks release automatically on process exit;
lock files are retained so there is no unsafe stale-lock deletion.


Final verification:
- Python unittest: 65 passed, including 13 new runner/watcher tests.
- Frontend Vitest: 66 passed; production build passed. Existing frontend edits
  from the preceding display-format task were retained, not changed by this work.
- All 13 real resources succeeded in an isolated --once run seeded from existing
  successful JSON. A second real check ran rainfall_rankings twice with a 1.2s
  test interval, then exited. Public website JSON was not modified by these checks.
- One independent Reviewer/Tester ran all 65 Python tests, reviewed the legacy
  SST guard and documentation, and verified Windows locks with separate processes
  including abnormal process exit. No important findings remain.
- Private status confirms stopped, next_run_at=null, both locks released.
- Credential scan passed for source/public/build/runtime JSON; .env and .runtime
  are git-ignored. No background loop, system schedule or GitHub setup left running.
- Updated legacy tests use isolated runtime paths so mock batches do not pollute
  the user's actual status.json. Existing service/publishing data contracts remain.

Follow-up: incomplete local batches on Windows
- Observed a live batch stopping after seaice_arctic despite all 13 products
  being selected. The old record has no exception details, so its precise trigger
  cannot be established retrospectively.
- Reproduced Windows PermissionError when an open status reader blocks atomic
  replacement. Private status writes now retry briefly and warn without aborting
  product updates. Public JSON publication still fails safely as before.
- Private status reads also retry; an unreadable previous record is preserved,
  and that batch continues without overwriting its status history.
- Python unittest: 70 passed, including five additional regression tests.
- The user's running watcher was not stopped or restarted; it must be restarted
  manually to load the updated Python code.
