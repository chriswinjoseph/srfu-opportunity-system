# Data Import, Duplicate Review and Live Scraper: interpretations and open questions

Source requirement: `FR-And-AC-data import-duplicates-live scraper.md`.
Code: the `intake` app (`/data/` pages, Admin only).

## Interpretations used (conservative)

| Topic | Interpretation |
|---|---|
| Source identifiers | Stored per source (`source_key` + source ID). They are never the internal organisation UUID, and an ID is only trusted within its own source. |
| Bank exact match | A trusted source ID, or the same normalised name **and** state. A name alone is never exact. |
| Branch exact match | Same parent bank, normalised name and (same postcode, or same suburb and state). A branch with no known parent bank is never exact. |
| Club exact match | Same normalised name and state, and (same postcode or same suburb). |
| Missing location | Never evidence of a match. Same name and state with a missing or different location is a *likely* duplicate and goes to review. |
| Conflicting evidence | A source ID that points at one organisation while the name/state/type points at another, or more than one exact match, goes to review. |
| Likely duplicates | Never merged automatically. Name at least 90% similar in the same state; at least 80% with the same suburb or postcode; same email, phone or website under a different name; same name in another type; a branch resembling a bank with no parent. |
| Name similarity | Generic words (community, bank, district, branch, club, ltd, and, ...) are ignored when judging similarity, because they are shared by many different organisations ("Community Bank Yea & District" and "Community Bank Kyabram & District" are different towns). Exact matching still uses the full normalised name. |
| Normalisation | Case, spacing and punctuation are ignored. `&` equals `and`. Periods and apostrophes join letters (`F.C.` = `FC`). States use standard codes. Emails are compared case-insensitively. Phones are compared as digits (`+61` = `0`). |
| Shared email | The same normalised email in the same organisation is an exact contact. The same email on a different organisation is held for review and never merged. |
| Review Required | A state of a run result or review item. It is never a `contact_status`. |
| Contact status from evidence | Contacted when at least one contact has `sent_and_human_reply_received` or `sent_no_human_reply_found`. Otherwise Not Yet Contacted. `overall_status` and `sent_to_by_srfu` are never used on their own. |
| Conflicting evidence rows | A status that contradicts its own flags (for example "sent, no reply" with `sent_to_by_srfu = FALSE`) or an unknown status is held for an Admin decision. A delivery failure with `sent_to_by_srfu = TRUE` is consistent and maps to Not Yet Contacted. |
| Replies | Kept as evidence on the contact record. A reply never becomes Interested. |
| Existing records | Blank fields may be filled. A populated field is never replaced, and never replaced by a blank. Different values become *proposed changes* for an Admin. Legacy populated values are treated as protected; they are not assumed to be unverified. |
| Verification | An Admin-approved change is recorded as verified (who and when). Fields that disappear from a website keep their value and are marked "not found since" and the source is marked for verification. |
| Archived organisations | Matched, never recreated, restored, changed or given new contacts. |
| Optional fields | Imports and scrapers keep email, region, suburb and postcode optional. The manual Add Organisation form's rules do not apply to them. |
| Legacy State in Region | Banks imported earlier kept the state code in Region with State blank. For matching, a Region that is a recognised state is read as the State (a Region such as "Metropolitan Melbourne" is not). Nothing is overwritten; blank State is filled by the import. |
| Unsupported organisation type | A row whose organisation_type is not Bank, Branch or Club is not imported and is listed as **Review required** (not Failed), with the action "correct the type and import again" (FR-05). |
| Optional columns for other types | Future files may add parent_bank_name, parent_bank_state, region, suburb, postcode, address, website_url, public_phone, public_email and club_type. A branch with no known parent bank is reported incomplete, not created. |
| Delivery failure with `sent_to_by_srfu = TRUE` | In the supplied workbook both delivery-failure-only organisations have `sent_to_by_srfu = TRUE` and `human_reply_received = FALSE`: SRFU did send, delivery failed. The flag records the attempt, so the combination is consistent. Section 5 of the requirements maps `delivery_failure_recorded` only to Not Yet Contacted, so the result is deterministic. Only contradictions (e.g. a successful-send status with `sent_to_by_srfu = FALSE`, or an unknown status) are held. |
| Bot-protection pages | A page that answers with an automated-access check instead of content is reported as a failed page. The check is never bypassed. |
| First/last observed dates | Stored as Melbourne dates (timezone-aware) on the contact source record. |

## Unresolved BA points (work continues; not blocking)

1. **Bank exact rule wording.** The BA says "source ID or name matches" in one place and "name and state" elsewhere. The stricter reading is used.
2. **Branch/club location precedence.** Two exact rules can disagree when only one location field is present; the "both present and equal" rule is used.
3. **Review Required has no contact status.** It exists only on results and review items.
4. **"Permitted" updates on repeat runs.** Only blank-field fills are automatic; everything else is proposed for review.
5. **Shared email level.** The BA flags it for contacts and for organisations; it is held at contact level.
6. **Organisation type in the client workbook.** The workbook has no type column, so its rows are imported as Banks (FR-05). A future `organisation_type` column is honoured; unsupported types are reported and not imported.
7. **Approved scraper sources.** Only the two sources already used by the project are configured. No source exists for Branches or for states other than Victoria; this is reported to the Admin, not invented.

## Scraper data reliability

* Bendigo Bank page: the name comes from the page heading (must contain "Community Bank"); the state comes from the page URL path, or an unambiguous UPPERCASE state code in the page text; otherwise the result is incomplete and held. The phone is the first phone-shaped number on the page (moderate reliability). The website and source URL are the page address.
* Council club directory: the state is the council's state (Victoria, an adapter constant); name, sport, suburb (from a fixed suburb list), postcode, email, phone and website come from the listing text.
