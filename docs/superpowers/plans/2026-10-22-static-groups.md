# CIMSS and Sea Ice static groups

Approved design: extend the existing publisher, retaining the seven image fields
and adding images[] at group level. Copy representative fields from the first
child in UI order, replacing only image_type with the group key. Keep UI,
CSS and routes unchanged. No Flask, SQLite, original-project access, commit or push.

- [x] Add failing unittest coverage for completeness, order, contract and failures.
- [x] Extend shared validation/atomic writer and register four group fetch methods.
- [x] Verify images inside existing Services; use UTC product times, daily dates,
      or null when unknown. Do not treat Last-Modified as observation time.
- [x] Generate real group JSON and cover Dashboard plus every detail tab.
- [x] Run all Python/frontend tests, production build and independent review.
- [x] Document structure, commands, source results and limitations.


Validation results:
- Python unittest: 37 methods passed (20 existing plus 17 new group tests).
- Frontend Vitest: 40 tests passed, including four groups at both base URLs,
  Dashboard representatives and all 14 detail tabs through unchanged App routes.
- Production build passed.
- One independent Reviewer/Tester ran Python and frontend tests. A naive CIMSS
  timestamp was initially treated as UTC; fixed to require explicit UTC/Z, with
  a failing-then-passing regression. Final independent Python run: 37 passed,
  no remaining important findings.
- Live four-group fetch succeeded with 2/6/3/3 nonempty image responses. Times
  currently remain null because existing byte parsers cannot identify product
  dates/times. HTTP Last-Modified is deliberately not used as observation time.
- No UI/CSS/routes changes, no out-of-scope product changes, no commit/push.
