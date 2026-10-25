# Requirement status: real data import, duplicates and live scraper

Numbering follows `FR-And-AC-data import-duplicates-live scraper.md` exactly (FR-01 to FR-20,
AC-01 to AC-22). "Tests" are automated tests in `intake/tests/` run on isolated databases with
mocked pages. "Browser" is the headless-browser check on an isolated database. "Live" is the
bounded read-only fetch of the real public sources into a disposable database.

Status words: **Met** = implemented and verified as described; **Met (mocked only)** = verified
only against mocked pages because the real source could not be used; **Partial** = part of the
requirement is not delivered (see Gaps).

## Functional requirements

| ID | Requirement (BA) | Status | Evidence |
|---|---|---|---|
| FR-01 | Restrict data import to Admin | Met | Tests (AccessTests, preview/confirm Admin-only); Browser: Staff gets 403 and sees no controls |
| FR-02 | Accept the agreed `.xlsx` format | Met | Tests; supplied workbook imports 168 organisations / 244 contacts |
| FR-03 | Validate before import | Met | Tests (file type, corrupt file, renamed CSV, missing sheet / column, headers-only file; no organisations or contacts created by any invalid upload); Browser invalid uploads. Messages name the missing sheet or column |
| FR-04 | Organisations and contacts separately, grouped by `organisation_id` | Met | Tests (multiple contacts create one organisation) |
| FR-05 | Organisation type (Bank default; Branch / Club; unsupported held for review) | Met, with a limit | Workbook without a type column imports as Banks. Unsupported types are now listed as Review required (not Failed). Branch / Club rows need the optional columns (e.g. `parent_bank_name`); a branch with no known parent is reported incomplete. The Import Data page now lists these columns and offers a blank template that includes `organisation_type` and the optional columns |
| FR-06 | Preserve source information | Met | Source IDs per source, source filename, import time, starting Admin, verification flags, outreach / reply evidence, observed dates (tests) |
| FR-07 | Missing optional data stays empty; `(unspecified)` is a missing name | Met | Tests; 70 blank names in the supplied workbook |
| FR-08 | Binary `contact_status`, no Partially Contacted | Met | Tests (BA mapping table); supplied workbook 166 Contacted / 2 Not Yet Contacted |
| FR-09 | Import summary | Met | Tests; Browser |
| FR-10 | Normalise before comparing (case, spaces, punctuation, `&`/`and`, states, email, phone), keep originals | Met | `test_matching` |
| FR-11 | Exact duplicates: no new record, add new valid information, preserve history, count | Met | Tests (import and scraper) |
| FR-12 | Likely duplicates: not merged, candidate and causing fields shown, review list, Admin decides | Met | Tests; Browser review pages |
| FR-13 | Duplicate contacts (same email, same organisation = exact; across organisations = review) | Met | Tests (import, review) |
| FR-14 | Scraper controls and approval of scraped changes are Admin-only | Met | Tests; Browser |
| FR-15 | Collect organisation information where public | **Partial** | Name, type, state, suburb, postcode, phone, website, source URL, and email where the page shows them. Not collected: parent bank for a branch, public contact name, region. The Bendigo pages give no email, suburb or postcode |
| FR-16 | Store source: URL, first collected, last checked, fields collected, needs verification | Met | Tests; Live (first run records, repeat run only updates checks) |
| FR-17 | Scraped results use the standard duplicate rules | Met | Tests |
| FR-18 | New scraped organisation: one record, source Scraper, type, Not Yet Contacted, source URL | Met (Bank: live and mocked; Club: mocked only) | Tests; Live: 3 Community Banks created Not Yet Contacted with source URLs |
| FR-19 | Changed information: compare, keep current, show source, no blank replaces a value, no silent replacement of verified values | Met | Tests (changes proposed, removed website kept and flagged) |
| FR-20 | Scraper summary | Met (25 Oct: pages and organisations now shown separately) | Tests (`test_scraper_status`); Browser. Pages processed / failed are page counts; every other figure counts organisations. Exact duplicates are existing organisations that were matched, so they overlap Updated and Unchanged (stated on the page) |

## Acceptance criteria

| ID | Criterion | Status | Evidence |
|---|---|---|---|
| AC-01 | Admin imports a valid dataset | Met | Tests; Browser; supplied workbook |
| AC-02 | Staff cannot start an import (control not displayed) | Met | Browser: no Import or Scraper links for Staff; 403 on direct URLs |
| AC-03 | Invalid file format | Met | Tests; Browser |
| AC-04 | Missing required column is named, nothing imported | Met | Tests |
| AC-05 | Multiple contacts for one organisation | Met | Tests |
| AC-06 | Blank / `(unspecified)` contact name stays empty | Met | Tests; 70 in the supplied workbook |
| AC-07 | Import summary: created, updated, duplicate, review-required, unchanged, failed | Met | Tests; Browser |
| AC-08 | Exact bank duplicate (same normalised name and state) | Met | Tests; also legacy banks whose Region holds the state |
| AC-09 | Exact branch duplicate (parent bank, name, location) | Met (mocked only) | `test_matching`. No approved scraper source for branches; import only via the optional-column workbook |
| AC-10 | Exact club duplicate (name, state, location) | Met (mocked only) | `test_matching`, `test_scraper`. The only club source is currently blocked (below) |
| AC-11 | Likely duplicate held, candidate shown, not merged | Met | Tests; Browser |
| AC-12 | Different organisations confirmed by an Admin; decision recorded | Met | Tests |
| AC-13 | Duplicate contact (same email, same organisation) | Met | Tests |
| AC-14 | New scraped organisation: Not Yet Contacted with source URL | Met for Banks (live); Clubs mocked only | Live + tests |
| AC-15 | Public email / phone never changes contact status | Met | Tests (`test_scraping_never_changes_existing_outreach_status`) |
| AC-16 | Existing organisation found by the scraper is not duplicated | Met | Tests; Live repeat run: 3 matched, 3 unchanged, 0 created |
| AC-17 | Missing optional scraped data stays empty | Met | Tests |
| AC-18 | Missing required data: not created, reported incomplete | Met | Tests |
| AC-19 | Changed information: old and new recorded; verified value not silently replaced | Met | Tests |
| AC-20 | One failed page does not stop the rest | Met | Tests; Live: the blocked club page failed and the bank pages continued |
| AC-21 | No login-protected or non-public information | Met | Tests (login, forbidden, robots, bot-check); Live: the council page's automated-access check was reported, not bypassed |
| AC-22 | Scraper summary: new, updated, unchanged, duplicate, incomplete, failed | Met | Tests; Browser; Live |

## Manual verification, 14 October 2026

Done by the team in the running application. The run figures below are read back from the
project database's own run records (read-only); times there are stored in UTC.

| Check | Result | Evidence |
|---|---|---|
| All 11 Bendigo Community Bank pages collected | **11 of 11 succeeded** | Run 1 (about 11:20 am Melbourne time): processed 11, failed 0 |
| Repeat run creates and updates nothing | **Confirmed** | Runs 2 and 4 (repeats, the last at about 5:25 pm): processed 11, created 0, updated 0, failed 0 (10 unchanged, 1 exact duplicate) |
| Archived organisations stay untouched | **Confirmed** | The three archived banks keep their earlier last-updated times and stay archived. The scraper matched one of them and reported "It was not changed or restored" on every run. See note 1 below |
| Club source blocked, reported honestly | **Confirmed** | Run 3: status Failed, 1 failed, 0 processed; message says the site returned an automated-access check, nothing was collected and the check was not bypassed |
| Staff access denied | **Confirmed** | Staff were refused on all intake pages and see no Import or Scraper links. Also re-checked on 18 October on a disposable database: 403 on every intake page |

Notes:

1. When the scraper matches an archived organisation it records the source link (a provenance
   row in the intake tables, with a "last checked" time) so that later runs recognise it. The
   organisation record itself is never changed or restored. Whether a provenance link to an
   archived organisation is acceptable is a BA decision.
2. Run 1 reported 9 updated: it filled blank fields on existing banks and created no new banks.
   Both repeat runs reported 0 updated.

## Gaps that remain (not hidden by "Met")

1. **Club source is not usable today.** The Moonee Valley council directory answered the honest
   collector with an automated-access (Incapsula) check instead of the page. The check is not
   bypassed. Club scraping therefore works only against mocked pages; a permitted alternative
   (council data export or written permission) is needed.
2. **The earlier bounded live check fetched 3 of the 11 Bendigo pages.** The 14 October manual
   run (above) collected all 11. All 11 are configured.
3. **FR-15 is partial** for the reasons above; there is no Branch source at all.
4. **Branch / Club import** uses the optional columns documented on the Import Data page and in
   the downloadable template. Only a Bank example is verified end to end with a populated
   template (plus one synthetic Club); a Branch needs its parent bank to exist first.
5. **Import confirmation runs inside the web request** (fine for 168 organisations, not for
   very large files).
6. **PostgreSQL concurrency is untested**; SQLite concurrency is tested with real processes.

## Open BA interpretations (7, not 6)

See `Intake-BA-Interpretations.md`. In short:

1. Bank exact rule wording ("source ID **or** name" vs "name and state") - stricter reading used.
2. Branch / club location precedence when only one location field exists - "both present and equal".
3. Review Required has no contact status - it is a result / review state only.
4. "Permitted" updates on repeat runs - only blank fills are automatic; everything else is proposed.
5. Shared email level (organisation or contact) - held at contact level.
6. Organisation type missing from the client workbook - imported as Banks; future files may add it.
7. Approved scraper sources - only the two already used by the project; none for Branches or outside Victoria.

## Update, 25 October 2026 (scraper audit, import guidance, launcher)

Code base for this update: be5b49c (pushed to origin/main) plus the uncommitted changes of this
task. Results below are from automated tests and a headless-browser run on disposable
databases; nothing was run against the project database, and queued job #7 was not touched.

Defects found and fixed (each reproduced by a failing test first):

| Defect | Fix |
|---|---|
| A suburb filter chosen together with Banks silently excluded every Bank (the page said the filter "was not applied") | The filter now applies only to sources that declare suburbs |
| An unknown organisation type, or none at all, was widened to "all types" by `start_scrape` | Rejected with a clear message; nothing is queued |
| A run with no pages to visit finished as Successful | Failed, with the reason recorded |
| A run in which every record failed (for example every import row had an invalid state) finished as Partially Successful | Failed; runs that only hold review or incomplete items stay Partially Successful (see `Scraper-BA-Clarifications.md`, item 2) |
| Summary mixed pages and organisations; a page failure was labelled with the source name as if it were an organisation | Pages and organisations are shown separately; a failed page names its URL, reason, field ("source page") and required action |
| "Source blocked" and "source loaded but listed nothing" looked alike | Separate codes and different required actions |
| A running job whose service had stopped still looked healthy | The run and Scraper pages say the service is stopped |
| The worker loop stopped on any unexpected error | Bounded retries with a growing pause (5 consecutive errors by default), then a clear stop message and non-zero exit |
| The Import Data page did not describe the workbook; no template | Explanation, expandable instructions derived from the parser's rules, blank template and a synthetic example (Admin only) |

Requirements still not fully met or needing a decision: see `Scraper-BA-Clarifications.md`
(FR-15 minimum scope, blocked club source, absent branch source, Victoria-only banks, status
rules for review-only runs, bank "ID or name" wording, hosting).
