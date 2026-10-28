# Fetcher protection implementation plan

**Approved scope:** User-approved stage one only. No commit, push, remote branch,
Actions, Pages, or scheduling setup. Future data branch candidate: `weather-data`;
storage/retention are not finalized. Restore from an explicit local location,
without a branch/provider dependency. Do not clean existing history.

**Design:** Reuse existing Services and publishers. One shared HTTP policy supplies
bounded retries and per-source request/deadline budgets, including history threads.
A protected snapshot command restores a validated immutable local snapshot into a
candidate directory, updates resources independently and validates again. Valid
old bytes are the fallback. A manifest lists approved public files and SHA-256
hashes; private per-run outcomes live outside the snapshot. Snapshot directories
are immutable and promoted by a single atomic local pointer. No image bodies are
archived. Existing live watcher/public files must not be touched during tests.

- [x] Add failing tests for retries, budgets, restore/corruption and resource outcomes.
- [x] Add shared HTTP policy; adapt all Service HTTP calls without stacked retries.
- [x] Add public resource validation and immutable snapshot restore/export.
- [x] Add protected candidate orchestration and local CLI, preserving failed resources.
- [x] Add Dashboard no-data UI and component/interaction tests.
- [x] Document commands, snapshot layout, limits and stage-two recovery contract.
- [x] Main agent runs Python/frontend tests and build; independent Sub-Agent reviews
  actual changes and runs relevant tests; fix blockers and request re-review.

Future publication contract: data schedules require at least one successfully
written resource plus a complete valid candidate. Code releases may use a complete
old snapshot without fetching. Saving a snapshot does not imply deployment; a
future deployment must identify the exact snapshot ID and separately record its
success. Remote compare-and-swap/order guards belong to stage two.


Verification:
- Main agent: 98 Python unittest tests and 73 frontend Vitest tests passed;
  production build succeeded. Temporary directories isolated from public data.
- Independent Reviewer/Tester: separately reran the same 98 Python / 73 frontend
  tests and production build, all passed; independently injected permanent
  directory-install and pointer errors to verify prior pointer bytes survive.
- Reviewer findings fixed and re-reviewed: false updated history classification,
  unaccounted history slots, latest/history lag, malformed rank/string fields,
  error exit status, path overlap, Windows directory rename retries.
- Main agent viewed normal Dashboard in the real browser. The isolated no-data
  server was unreachable from the browser; error/timeout/interaction behavior is
  component-tested, not claimed visually verified. Temporary helper was stopped.
- No live source/API fetching was performed as part of this verification. No
  remote branch, commit/push, Actions, Pages, retention cleanup or scheduling.
- HTTP deadline is cooperative, not an OS hard timeout; documented explicitly.
