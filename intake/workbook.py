"""
Read and validate the agreed client workbook (.xlsx) before anything is
written. Nothing here touches the database.
"""

import hashlib
import io
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from openpyxl import load_workbook

from .evidence import map_organisation_status
from .normalise import clean_contact_name, collapse, norm_state, parse_bool

MELBOURNE = ZoneInfo("Australia/Melbourne")
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 20000

SOURCE_KEY = "client_workbook"
SOURCE_LABEL = "Client workbook (Shane)"

SHEET_ORGANISATIONS = "Organisations"
SHEET_CONTACTS = "Contacts"

# Ordered so the downloadable template and the on-page guidance list the
# headers in the same order the sheets use. The sets below are what is checked.
ORGANISATION_HEADERS = (
    "organisation_id",
    "bank_name",
    "state",
    "num_contacts",
    "contact_names",
    "emails",
    "contact_types",
    "any_human_reply_received",
    "all_contacts_replied",
    "overall_status",
    "first_observed_date",
    "last_observed_date",
    "needs_verification_flag",
)
CONTACT_HEADERS = (
    "contact_id",
    "organisation_id",
    "bank_name",
    "state",
    "contact_name",
    "email",
    "contact_type",
    "name_needs_verification",
    "bank_affiliation_needs_verification",
    "first_observed_date",
    "last_observed_date",
    "sent_to_by_srfu",
    "human_reply_received",
    "contact_status",
)
ORGANISATION_COLUMNS = set(ORGANISATION_HEADERS)
CONTACT_COLUMNS = set(CONTACT_HEADERS)
TYPE_COLUMN = "organisation_type"

SUPPORTED_TYPES = {"bank": "bank", "branch": "branch", "club": "club"}

# Optional organisation columns for future (non-bank) imports. They are read
# only when the column exists; blank cells stay empty.
OPTIONAL_COLUMNS = {
    "parent_bank_name": "parent_bank_name",
    "parent_bank_state": "parent_bank_state",
    "region": "region",
    "suburb": "suburb",
    "postcode": "postcode",
    "address": "address",
    "website_url": "website",
    "public_phone": "phone",
    "public_email": "email",
    "club_type": "club_type",
}


class ParsedWorkbook:
    def __init__(self):
        self.structure_errors = []
        self.groups = []
        self.row_errors = []  # {row_ref, name, field, message, action}
        self.counts = {"organisation_rows": 0, "contact_rows": 0}
        self.sha256 = ""
        self.type_note = ""

    @property
    def ok(self):
        return not self.structure_errors


def clean(value):
    if value is None:
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return collapse(value)


def parse_date(value):
    """An observed date as an ISO string (Melbourne midnight), or ''."""
    if value is None or value == "":
        return ""

    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=MELBOURNE)

        return moment.isoformat()

    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=MELBOURNE).isoformat()

    text = clean(value)

    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            moment = datetime.strptime(text, pattern)

            return moment.replace(tzinfo=MELBOURNE).isoformat()
        except ValueError:
            continue

    return ""


def _read_sheet(worksheet, expected):
    rows = worksheet.iter_rows(values_only=True)

    try:
        header_row = next(rows)
    except StopIteration:
        return None, [], f"The '{worksheet.title}' sheet is empty."

    headers = [clean(value).lower() for value in header_row]
    missing = sorted(expected - set(headers))

    if missing:
        return (
            None,
            [],
            f"The '{worksheet.title}' sheet is missing the column(s): "
            + ", ".join(missing)
            + ". Row 1 must contain these headers spelled exactly as shown "
            "(capital letters do not matter; underscores do). The downloadable template has them all.",
        )

    data = []

    for number, values in enumerate(rows, start=2):
        if number > MAX_ROWS:
            return None, [], f"The '{worksheet.title}' sheet has too many rows."

        if not any(clean(v) for v in values):
            continue

        data.append((number, dict(zip(headers, values))))

    return headers, data, ""


def parse_workbook(file_bytes, filename=""):
    result = ParsedWorkbook()
    result.sha256 = hashlib.sha256(file_bytes).hexdigest()

    if not filename.lower().endswith(".xlsx"):
        result.structure_errors.append(
            "Only Microsoft Excel .xlsx files can be imported. A CSV or other spreadsheet "
            "cannot simply be renamed to .xlsx: open it in Excel, arrange it like the template "
            "and use Save As > Excel Workbook (.xlsx)."
        )

        return result

    if len(file_bytes) > MAX_BYTES:
        result.structure_errors.append("The file is too large to import.")

        return result

    try:
        workbook = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception:
        result.structure_errors.append(
            "The file could not be opened as an Excel (.xlsx) workbook. A CSV or other file that "
            "has only been renamed to .xlsx cannot be read: open the original in Excel and save it "
            "as an Excel Workbook (.xlsx) instead."
        )

        return result

    try:
        names = set(workbook.sheetnames)
        missing_sheets = sorted({SHEET_ORGANISATIONS, SHEET_CONTACTS} - names)

        if missing_sheets:
            result.structure_errors.append(
                "The workbook is missing the sheet(s): "
                + ", ".join(missing_sheets)
                + ". Sheet names must be exactly 'Organisations' and 'Contacts' (capital first letter). "
                + "Sheets found: "
                + (", ".join(f"'{n}'" for n in workbook.sheetnames) or "none")
                + "."
            )

            return result

        org_headers, org_rows, error = _read_sheet(
            workbook["Organisations"], ORGANISATION_COLUMNS
        )

        if error:
            result.structure_errors.append(error)

        con_headers, con_rows, error = _read_sheet(workbook["Contacts"], CONTACT_COLUMNS)

        if error:
            result.structure_errors.append(error)

        if result.structure_errors:
            return result

        if not org_rows:
            result.structure_errors.append(
                "The Organisations sheet has no readable rows. If you started from the blank "
                "template, add one row per organisation (and its contacts on the Contacts sheet) "
                "before uploading; a headers-only file cannot be previewed."
            )

            return result
    finally:
        workbook.close()

    has_type = "organisation_type" in org_headers
    result.counts["organisation_rows"] = len(org_rows)
    result.counts["contact_rows"] = len(con_rows)

    if not has_type:
        result.type_note = (
            "No organisation_type column was supplied, so these records "
            "are imported as Banks (the confirmed community-bank dataset)."
        )

    contacts_by_org = defaultdict(list)

    for number, row in con_rows:
        contacts_by_org[clean(row.get("organisation_id"))].append((number, row))

    seen_ids = set()

    for number, row in org_rows:
        source_id = clean(row.get("organisation_id"))
        name = clean(row.get("bank_name"))
        row_ref = f"Organisations row {number}"

        def reject(field, message, action, outcome="failed"):
            result.row_errors.append(
                {
                    "row_ref": row_ref,
                    "source_id": source_id,
                    "name": name,
                    "field": field,
                    "message": message,
                    "action": action,
                    "outcome": outcome,
                }
            )

        if not source_id:
            reject("organisation_id", "The row has no organisation ID.",
                   "Add the organisation ID and import again.")
            continue

        if source_id in seen_ids:
            reject("organisation_id",
                   f"The organisation ID '{source_id}' appears more than once.",
                   "Remove the repeated row.")
            continue

        seen_ids.add(source_id)

        if not name:
            reject("bank_name", "The organisation name is missing.",
                   "Add the organisation name.")
            continue

        state = norm_state(row.get("state"))

        if not state:
            reject("state", "The state or territory is missing or not recognised.",
                   "Enter a valid Australian state or territory.")
            continue

        raw_type = clean(row.get("organisation_type")).lower() if has_type else "bank"
        org_type = SUPPORTED_TYPES.get(raw_type)

        if org_type is None:
            reject("organisation_type",
                   f"The organisation type '{raw_type or '(blank)'}' is not supported, so the record was held for review and not imported.",
                   "Correct the type to Bank, Branch or Club and import the file again.",
                   outcome="review")
            continue

        optional = {}

        for column, attribute in OPTIONAL_COLUMNS.items():
            if column in org_headers:
                value = clean(row.get(column))

                if value:
                    optional[attribute] = value

        contacts = []
        contact_problems = []
        seen_contact_ids = set()

        for c_number, c_row in contacts_by_org.get(source_id, []):
            contact_id = clean(c_row.get("contact_id"))
            email = clean(c_row.get("email"))
            c_ref = f"Contacts row {c_number}"

            if not contact_id or contact_id in seen_contact_ids:
                contact_problems.append(
                    {"row_ref": c_ref, "field": "contact_id",
                     "message": "The contact ID is missing or repeated."}
                )
                continue

            seen_contact_ids.add(contact_id)

            if not email:
                contact_problems.append(
                    {"row_ref": c_ref, "field": "email",
                     "message": "The contact has no email address."}
                )
                continue

            try:
                validate_email(email)
            except ValidationError:
                contact_problems.append(
                    {"row_ref": c_ref, "field": "email",
                     "message": "The contact email address is not valid."}
                )
                continue

            contacts.append(
                {
                    "source_contact_id": contact_id,
                    "row_ref": c_ref,
                    "name": clean_contact_name(c_row.get("contact_name")),
                    "email": email,
                    "contact_type": clean(c_row.get("contact_type")),
                    "name_needs_verification": parse_bool(c_row.get("name_needs_verification")),
                    "affiliation_needs_verification": parse_bool(
                        c_row.get("bank_affiliation_needs_verification")
                    ),
                    "first_observed": parse_date(c_row.get("first_observed_date")),
                    "last_observed": parse_date(c_row.get("last_observed_date")),
                    "sent_flag": parse_bool(c_row.get("sent_to_by_srfu")),
                    "human_reply": parse_bool(c_row.get("human_reply_received")),
                    "status": clean(c_row.get("contact_status")),
                }
            )

        status, reasons = map_organisation_status(contacts)

        result.groups.append(
            {
                "source_org_id": source_id,
                "row_ref": row_ref,
                "name": name,
                "state": state,
                "org_type": org_type,
                "optional": optional,
                "overall_status_raw": clean(row.get("overall_status")),
                "needs_verification": parse_bool(row.get("needs_verification_flag")),
                "any_human_reply": parse_bool(row.get("any_human_reply_received")),
                "all_contacts_replied": parse_bool(row.get("all_contacts_replied")),
                "first_observed": parse_date(row.get("first_observed_date")),
                "last_observed": parse_date(row.get("last_observed_date")),
                "contacts": contacts,
                "contact_problems": contact_problems,
                "evidence_status": status,
                "evidence_reasons": reasons,
            }
        )

    known_ids = {clean(r.get("organisation_id")) for _n, r in org_rows}

    for source_id, rows in contacts_by_org.items():
        if source_id not in known_ids:
            for number, row in rows:
                result.row_errors.append(
                    {
                        "row_ref": f"Contacts row {number}",
                        "source_id": source_id,
                        "name": clean(row.get("bank_name")),
                        "field": "organisation_id",
                        "message": (
                            "The contact refers to an organisation that is not in the Organisations sheet."
                            if source_id else "The contact has no organisation ID."
                        ),
                        "action": "Add the organisation or correct the ID.",
                    }
                )

    return result
