# CWA current-day images and rainfall

Approved scope: radar/satellite from Taipei 00:00 at 10-minute intervals;
rainfall from 00:30 at 30-minute intervals, through latest verified product.
Remove web backfill controls. No arbitrary-date UI, retention deletion, image
archiving, other-product changes, GitHub setup, commit or push.

- [x] Tests first: candidate times, merging, missing/failed source, rollback,
  official daily metadata, rainfall ranking validity and secret-free failures.
- [x] Reuse CWA resolvers; publish latest plus dated history through extracted
  atomic writer. Same-day successes merge, failures never erase old records.
- [x] Rainfall daily: official today/yesterday/day-before products, explicit
  represented_date and accumulation boundaries. No guessed daily substitute.
- [x] Decouple observation fetch/parse from SQLite; generate all ranking metrics
  from one fetched snapshot, Top 10, preserving old JSON on failure.
- [x] Static API adapters, remove three backfill buttons, isolate panel errors,
  stale/cross-midnight labels, image-load failures and selection race handling.
- [x] Real fetch, Python/frontend verification, build and independent review.

Output paths: data/images/{type}/latest.json;
data/images/{type}/history/YYYY-MM-DD.json (items plus scan status);
data/images/rainfall/daily/latest.json; data/rainfall/rankings/latest.json.
Image product times and observation times have explicit offsets; fetched_at is
UTC; represented_date is a date. Official URLs are not permanent archives.
Key is read only at generation time from environment or ignored root .env;
never log it or serialize request URLs, exceptions or raw upstream payloads.


Final verification (2026-10-22):
- Python unittest: 52 passed, including 15 new tests.
- Frontend Vitest: 63 passed across 6 files; existing router future warnings only.
- Production build passed; all dist JSON bytes match public outputs.
- Real fetch repeated successfully, latest times in Taipei:
  radar 19:10, 116/116 slots; satellite 18:50, 112/114 slots (10:40 and
  18:10 unavailable, complete=false); rainfall 19:00, 38/38 slots.
- Official daily products: today/yesterday/day-before, three verified images.
- Rainfall ranking API succeeded with the user's generator-only key; all nine
  supported metric snapshots have ten entries, original eight UI tabs retained.
- One independent Reviewer/Tester verified 52 Python / 63 frontend tests and
  reviewed final fixes; no blocking findings. Reviewer did not read .env/key.
- Key scan: no credential in public/dist/source; .env is git-ignored.
- No other image outputs, CSS, routes, original-project files, commit/push,
  GitHub automation or hosting settings changed.
