# Scraper and import: points for BA / client clarification

Source requirements: `FR-And-AC-data import-duplicates-live scraper.md` (quoted exactly below;
numbering is that document's).

Status of this document: **a list of questions and proposals. Nothing here is approved.** The
requirements have not been rewritten. Where the table says "Current behaviour", that is what the
code does today (commit be5b49c plus the uncommitted changes of the 25 October 2026 task); it
is an interpretation made so the system is safe, not a BA decision. Work that does not depend on
these answers has continued.

Evidence references: `intake/matching.py`, `intake/ingest.py` (`finish_run`), `intake/sources.py`,
`handover/verification-records/scraper-live-check-2026-10-23.md`, and the tests named in each item.

| # | Topic | BA / client approval needed? |
|---|---|---|
| 1 | Can a name alone establish an exact Bank match? | Yes |
| 2 | Run status for review-only, incomplete-only, failed-only and empty runs | Yes |
| 3 | FR-15 "may collect": optional fields versus minimum scope | Yes |
| 4 | Source limitations: Clubs blocked, Branches absent, Banks Victoria only | Yes (sources / permission) |
| 5 | Website-only operation still needs a background service; hosting undecided | Yes (client hosting details) |
| 6 | Summary counts: "exact duplicates" overlap "updated" / "unchanged"; pages versus results | Yes (confirm wording) |
| 7 | Source link kept for an archived organisation | Yes |
| 8 | Run stopped by the time limit | Confirm |

---

## 1. Can a name alone establish an exact Bank match?

**Requirement wording**

* Section 6, Exact Bank Duplicate: "A bank is an exact duplicate when: The trusted source
  organisation ID or name matches; or The organisation type is Bank and the normalised bank name
  and state match."
* AC-08: "**Given** an imported or scraped bank has the same normalised name and state as an
  existing bank ... **Then** a second bank must not be created".
* Section 4.2 step 2-3: "first checks the trusted source identifier. ... then compares the
  organisation type, name and location."

**Ambiguity / evidence.** The first bullet of Section 6 reads as "(source ID) or (name)" or as
"(source ID or name) of the trusted source"; the second bullet and AC-08 require name **and**
state. If name alone were enough, "Community Bank Springvale (VIC)" and a same-named bank in
another state would merge silently, which contradicts FR-12 (no automatic merging of similar
records) and the principle that a missing location is not evidence. In the supplied data, bank
names repeat across states, so the stricter reading matters.

**Current behaviour.** A bank is exact only when a trusted source ID for that source matches
(and name, state and type do not conflict), or when the normalised name **and** state match.
Same name with a different or missing state is a *likely* duplicate held for Admin review.
A source ID that points at a record with a conflicting name or state is held, not trusted.
Tests: `test_matching` (name-only is not exact; conflicting source ID is held).

**User impact.** Under the current reading some same-name records are held for an Admin
decision rather than merged automatically (safe, a little more review work). Under the loose
reading, wrong merges would be possible and would not be shown to the Admin.

**Proposed clarification.** "A Bank is an exact duplicate when (a) the trusted source
organisation ID for the same source matches, provided the name and state are not in conflict, or
(b) the normalised name **and** state match. A name match without a matching state is a likely
duplicate." No code change would be needed.

**Approval:** BA confirmation required.

---

## 2. Run status for review-only, incomplete-only, failed-only and empty runs

**Requirement wording.** Section 9: "The final run status must be: **Successful:** All records
were processed. **Partially Successful:** Some records were processed, but others require review
or failed. **Failed:** The file or scraper run could not be processed."

**Ambiguity / evidence.** The definitions do not say what applies when:

* every result is "review required" (held for an Admin decision) and nothing else was created;
* every result is "incomplete" (AC-18, "reported as incomplete");
* every record, or every page, failed;
* the run had nothing to process (no organisations matched the filters, or no pages to visit);
* the run was stopped early.
"Others require review or failed" suggests review-only is not a clean success, but "Some records
were processed" is arguable when none were created or updated. Incomplete results are not named
in the Partially Successful definition at all.

**Current behaviour** (`finish_run`, tests in `test_scraper_status.py` and `test_scraper_audit.py`):

| Situation | Status shown |
|---|---|
| All pages and records processed, nothing held or failed | Successful |
| Some work saved and some failed / incomplete / held | Partially Successful |
| Only review-required results (nothing created) | Partially Successful |
| Only incomplete results | Partially Successful |
| Every page failed, or every record failed (no review/incomplete) | Failed |
| Source blocked (automated-access check) on every page | Failed (reason and "not bypassed" shown) |
| Source loaded but listed nothing (no recognised organisations) | Failed, with a different message and action from a blocked source |
| No pages to visit | Failed ("No pages to process") |
| Pages fine but the filters matched no organisations | Successful, with a notice "no organisations were found to process" |
| Stopped by the time limit after some work | Partially Successful; the unvisited pages are stated |

Before 25 October a run in which every import row failed was shown as Partially Successful, and
a run with no pages as Successful. Both were corrected as defects (neither fits the BA
definitions). The labels were not changed.

**User impact.** An Admin reading "Partially Successful" on a review-only run must open the
review list; "Successful" is never shown when anything awaits review or failed.

**Proposed explicit rules for BA confirmation.**
1. *Successful*: at least one page/file was read, no page or record failed, and no result is
   incomplete or awaiting review. (A run that found nothing is Successful but must say so.)
2. *Partially Successful*: at least one record was created, updated, matched or held for review,
   **and** at least one page/record failed, is incomplete, or awaits review.
3. *Failed*: no record was processed (every page/record failed, the file/source could not be
   read, or there was nothing to visit); an Admin can still see why, per result.
4. Decide whether a run containing **only** review-required or incomplete results should be
   Partially Successful (current) or Failed.
5. Decide whether "nothing found" should be Successful (current) or a distinct outcome.

**Approval:** BA approval required.

---

## 3. FR-15: optional fields versus a minimum collection scope

**Requirement wording.** FR-15: "Where publicly available, the scraper **may** collect:
Organisation name. Organisation type. Parent bank for a branch. State. Region or suburb.
Postcode. Public contact name. Public email. Public phone number. Public website. Public source
URL." Compare AC-18 / Section 7: "If the organisation name, type or state cannot be identified:
An active organisation must not be created." and FR-18: "a genuinely new organisation with
**sufficient** information".

**Ambiguity / evidence.** "May collect ... where publicly available" makes every field optional,
yet name, type and state are mandatory elsewhere (AC-18) and "sufficient information" is not
defined. Nothing says which fields a source must supply to count as meeting FR-15.
Evidence (live check 23 Oct 2026; 11 Bendigo pages): name, state (from the page address), public
phone and the page address were collected; the pages show other numbers and company email
addresses that are not collected (not clearly organisation-contact details); no suburb,
postcode, public contact name, parent bank or email is collected from that source. The club
adapter can collect suburb, postcode, email, phone and website but its source is blocked
(item 4), so that path is tested only on mocked pages.

**Current behaviour.** Required to create: name, type, state (anything else is optional and left
empty, never guessed; AC-17). Optional fields are saved when the source shows them. Fields the
source did not supply are recorded as not collected.

**User impact.** Bank records created by the scraper have a name, state, phone (when present) and
website but no email or location, so they cannot be emailed until an Admin adds an address
manually.

**Proposed clarification.** State two tiers: *Required to create a record*: name, type, state.
*Collected where the source publishes it*: all other FR-15 fields. Add a **minimum expected
scope per source type** (for example, Bank: name, state, public phone or email) so a source that
cannot supply it is reported as partial coverage rather than silently accepted. BA to say whether
"public contact name" and "parent bank" are expected at all (the Bendigo pages do not show them).

**Approval:** BA / client approval required for the minimum scope.

---

## 4. Source limitations (Clubs blocked, Branches absent, Banks Victoria only)

**Requirement wording.** Section 4.3: "The scraper visits approved public sources." FR-15 /
Section 10: "The scraper must not: Access pages requiring a login. Attempt to bypass website
access controls." AC-21: "it must not collect that information." The requirements name Bank,
Branch and Club but no source and no geography.

**Evidence and current behaviour** (configured in `intake/sources.py`; the Scraper page states
this before queueing):

| Type | Configured source | Result |
|---|---|---|
| Bank | 11 Bendigo Community Bank pages, Victoria only | Collected on 23 Oct 2026 (11 of 11) |
| Club | Moonee Valley City Council sports-club directory, Victoria | The site answered with an automated-access check; nothing was collected; the check is **not bypassed** (live check 23 Oct 2026). Club extraction is verified only on mocked pages |
| Branch | None | Refused when queued: "no approved public source is configured" |
| Any state except VIC | None | Refused or reported as unsupported |

A blocked source is a **source limitation, not a code defect**. The system now separates
"inaccessible" (blocked, login, robots, timeout) from "reachable but listed no organisations".

**User impact.** Only Victorian Community Banks can be scraped today. Selecting Clubs leaves
the Admin with a Failed run and an explanation. The Scraper page does not promise national
coverage and does not select Clubs by default.

**Proposed clarification / alternatives.**
* BA/client to state whether **nationwide** coverage is required. It has not been assumed.
* Clubs: obtain written permission or a data export from the council, or name another permitted
  public source. Do not attempt to defeat the access check.
* Branches: name the public source (for example a bank's branch locator that permits automated
  collection) or confirm that Branches are entered manually / by import only.
* Banks outside Victoria: identify further Community Bank pages or another permitted source.
* Who approves a new source (BA, client, or Admin) and whether each needs a robots.txt /
  terms-of-use review should be written down.

**Approval:** BA / client decision and, for Clubs, permission from the site owner.

---

## 5. Website-only operation still needs a background service; hosting is undecided

**Requirement wording.** Section 4.3: "The Admin opens the scraper page. ... The Admin starts the
scraper." Section 9 requires clear reporting of "Unable to access the public source" and
"Database or system error". Nothing specifies where or how scraping executes.

**Evidence.** Scraping must not run inside a web request (long, can time out). The project
therefore queues a database job and a separate worker process runs it (`docs/Intake-Jobs.md`).
Without that process a queued job waits. The repository holds no deployment configuration; the
hosting platform, database and web server are undecided.

**Current behaviour.** The Admin never types a command: they use the Scraper page. On the
Windows demo machine an operator double-clicks `Start-SRFU.bat` once (it starts the website and
the service, avoids duplicates, and reports failures), `Stop-SRFU.bat` to stop. The pages say
plainly when the service is stopped ("Queued - not started", "Running - service stopped") and
never show a waiting job as successful. This is not production hosting.

**User impact.** If the computer is off, or nobody has started the service, scrapes do not run
and the Admin is told so. They cannot start it from the website.

**Proposed clarification.** Record as a dependency that "Admin starts the scraper from the
website" means *queues* it, and that a managed background process must run in the client's
environment. Client to provide: hosting platform and owner, how the website is run, database
(PostgreSQL if website and worker are on separate machines), environment/secret storage,
outbound HTTPS to the approved hosts only, restart policy and health check
(`manage.py intake_status`). Until then production readiness cannot be claimed.

**Approval:** Client hosting details required; BA to accept the wording.

---

## 6. Summary counts: overlap and unit

**Requirement wording.** FR-20: "Pages or results processed. New organisations created. Existing
organisations updated. Existing organisations unchanged. **Exact duplicates matched.** Likely
duplicates awaiting review. Incomplete results. Failed pages or results." FR-09 / AC-07 list
similar totals for imports.

**Ambiguity.** (a) An exact duplicate *is* an existing organisation that was either updated or
left unchanged, so the three categories overlap if shown as parallel counts. (b) "Pages or
results" mixes units: one page can hold many organisations.

**Current behaviour.** Pages and organisations are shown in separate groups. Exact duplicates
are shown as matched existing organisations and the page states they are also counted under
Updated or Unchanged. Failed pages and failed organisation records are separate figures. Totals
are checked by `test_counts_separate_pages_from_organisations_and_are_internally_consistent`.

**Proposed clarification.** Define *Exact duplicates matched* as "existing organisations
matched by the exact rules (a subset of Updated + Unchanged)" or remove it from the parallel
list; state that "processed" is pages for the page line and organisations for the others.

**Approval:** BA to confirm the wording.

---

## 7. Source link kept for an archived organisation

**Requirement wording.** None specific. Section 8 requires that repeat runs "Update the
last-imported or last-checked date"; the system rules (not in this document) say archived
organisations are not restored or contacted.

**Evidence / current behaviour.** When a scrape matches an archived organisation it is not
created, changed, restored or contacted, but a source link (and a last-checked time) is recorded
so later runs recognise it. See `docs/Intake-Requirements-Status.md`, note 1.

**Proposed clarification.** Confirm that a source link on an archived organisation is
acceptable, or specify that no record at all should be written for archived matches.

**Approval:** BA decision.

---

## 8. A run stopped by the time limit

**Requirement wording.** Section 9 has no state for a run that cannot finish all pages.

**Current behaviour.** A run is bounded to 60 pages and 20 minutes. If stopped early after
useful work it is Partially Successful and the unvisited pages are named; if nothing was
processed it is Failed. Work done is kept and a later run does not duplicate it.

**Proposed clarification.** Confirm these limits and the status for an incomplete run.

**Approval:** Confirm (low risk).
