# Static image expansion

Approved design: reuse the existing CWA, KMA and Ocean resolvers; publish the
same seven-field ImagePayload through one validated atomic JSON writer.
Keep UI/CSS unchanged and route five latest-image types to static resources.

- [x] Add failing publication, service-time and frontend routing tests.
- [x] Extract SST publication into a common writer; retain update_sst compatibility.
- [x] Add a registered multi-product CLI with independent failure handling.
- [x] Populate image_time with explicit offsets, dates only, or null when unknown.
- [x] Generate real JSON, test Dashboard/detail rendering, run all tests and build.
- [x] Document commands, timezone semantics and failure behavior.

Validation: python -B -m unittest discover -s fetchers/tests -v;
npm test -- --run; npm run build. Live source failures must never create fake
public fixtures or replace previous successful JSON.

Results: Python 20 tests passed; React 23 tests passed; production build passed.
All four new official image URLs were checked successfully before publication.
Review finding addressed: metadata success alone must not publish a broken image.
Weather chart time is unknown in the current source page; publish null and use
the existing UI fallback to fetched_at. Original UI/CSS remain unchanged.
