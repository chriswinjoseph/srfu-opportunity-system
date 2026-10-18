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
| FR-03 | Validate before import | Met | Tests (file type, corrupt file, missing sheet / column, no rows); Browser invalid uploads |
| FR-04 | Organisations and contacts separately, grouped by `organisation_id` | Met | Tests (multiple contacts create one organisation) |
| FR-05 | Organisation type (Bank default; Branch / Club; unsupported held for review) | Met, with a limit | Workbook without a type column imports as Banks. Unsupported types are now listed as Review required (not Failed). Branch / Club rows need the optional columns (e.g. `parent_bank_name`); a branch with no known parent is reported incomplete. No Admin template for such files exists yet |
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
| FR-20 | Scraper summary | Met | Tests; Browser |

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

## Gaps that remain (not hidden by "Met")

1. **Club source is not usable today.** The Moonee Valley council directory answered the honest
   collector with an automated-access (Incapsula) check instead of the page. The check is not
   bypassed. Club scraping therefore works only against mocked pages; a permitted alternative
   (council data export or written permission) is needed.
2. **Only 3 of the 11 Bendigo pages were fetched live** (bounded check). All 11 are configured.
3. **FR-15 is partial** for the reasons above; there is no Branch source at all.
4. **No second typed-import template** exists for Branch / Club files; the optional columns are
   read if present and tested, but the Admin screen only describes the client workbook.
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
