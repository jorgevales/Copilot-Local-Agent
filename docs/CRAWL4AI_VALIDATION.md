# Crawl4AI integration validation — 14 October 2026

Windows Python 3.14.2; actual Crawl4AI 0.9.5 offline extraction, synthetic HTTPS
transport fixtures. This is not a live VDI, authenticated-site or S:/UNC proof.

- Core discovery/contracts/knowledge/transport/storage/persistence: 66 tests passed.
- Tools/site knowledge/repair/health/startup: 89 tests completed, 87 passed and two
  existing platform checks skipped.
- After adding explicit S: alias normalization, targeted mapping/tools/site
  checks completed: 70 tests, 68 passed and the same two checks skipped.
- A 126-page crawl used real Crawl4AI extraction, overlapped bounded page reads,
  saved all routes and read every route through pagination. An interrupted
  frontier was reused only from an approved bound map; cancellation stopped all
  child reads. Password pages, secret values and unapproved origins were excluded.
- Existing independent-run route trust and static navigation tests passed.
- Dependency installation and `pip check` passed; compilation and Git whitespace
  checks passed. The full repository suite was not run.

Run `Setup.cmd` in the target shared deployment before using the new extractor.
Verify a real approved discovery, cancellation, knowledge save/readback and a
long redirected UNC ledger read in that environment before claiming live success.
