"""Admin-only pages for import, duplicate review, proposed changes and the scraper."""

import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .import_template import (
    CLIENT_EXAMPLE_FILENAME,
    CLIENT_TEMPLATE_FILENAME,
    EXAMPLE_FILENAME,
    TEMPLATE_FILENAME,
    build_client_example,
    build_client_template,
    build_example,
    build_template,
    guidance,
)
from .importer import ImportBusy, confirm_import, create_preview, previously_imported
from .matching import ORG_MODELS, TYPE_LABELS
from .models import DuplicateReview, IntakeResult, IntakeRun, ProposedChange
from .reviews import ReviewError, decide_change, decide_review
from .scraper import ScrapeError, start_scrape
from .worker import worker_state
from .sources import ADAPTERS, ORG_TYPE_LABELS, supported_states, supported_suburbs

logger = logging.getLogger("intake")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
RESULT_PAGE_SIZE = 300
STATE_CHOICES = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]


def admin_only(view):
    """Admins only. Anonymous users go to login; Staff and others get 403."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.has_perm("outreach.add_bank"):
            raise PermissionDenied

        return view(request, *args, **kwargs)

    return wrapper


def org_url(content_type_id, object_id):
    if not content_type_id or not object_id:
        return ""

    return reverse("organisation_detail", args=[content_type_id, object_id])


def _result_rows(results):
    return [
        {"result": r, "url": org_url(r.target_content_type_id, r.target_id)}
        for r in results
    ]


@admin_only
@require_GET
def home(request):
    return render(
        request,
        "intake/home.html",
        {
            "runs": IntakeRun.objects.all()[:12],
            "pending_reviews": DuplicateReview.objects.filter(status=DuplicateReview.STATUS_PENDING).count(),
            "pending_changes": ProposedChange.objects.filter(status=ProposedChange.STATUS_PENDING).count(),
        },
    )


# ------------------------------------------------------------------ import
@admin_only
def import_upload(request):
    errors = []

    if request.method == "POST":
        upload = request.FILES.get("workbook")

        if upload is None:
            errors.append("Choose an Excel (.xlsx) workbook to import.")
        elif upload.size > MAX_UPLOAD_BYTES:
            errors.append("The file is too large to import.")
        else:
            run, parsed = create_preview(request.user, upload.read(), upload.name)

            if parsed.ok:
                return redirect("intake_run", run_id=run.pk)

            errors.extend(parsed.structure_errors)

    return render(request, "intake/import.html", {"errors": errors, "guide": guidance()})


def _xlsx_download(content, filename):
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"

    return response


@admin_only
@require_GET
def import_template(request):
    """Blank single-sheet template: the minimum headers, no records."""
    return _xlsx_download(build_template(), TEMPLATE_FILENAME)


@admin_only
@require_GET
def import_example(request):
    """Clearly labelled synthetic example of a populated workbook."""
    return _xlsx_download(build_example(), EXAMPLE_FILENAME)


@admin_only
@require_GET
def import_client_template(request):
    """Blank two-sheet client workbook (headers only)."""
    return _xlsx_download(build_client_template(), CLIENT_TEMPLATE_FILENAME)


@admin_only
@require_GET
def import_client_example(request):
    """Synthetic example of the two-sheet client workbook."""
    return _xlsx_download(build_client_example(), CLIENT_EXAMPLE_FILENAME)


@admin_only
@require_GET
def run_detail(request, run_id):
    run = get_object_or_404(IntakeRun, pk=run_id)
    outcome = request.GET.get("outcome", "")
    results = run.results.all()

    if outcome:
        results = results.filter(outcome=outcome)

    total_results = results.count()
    results = results.select_related("target_content_type")[:RESULT_PAGE_SIZE]
    payload = run.payload or {}
    worker = worker_state()

    return render(
        request,
        "intake/run.html",
        {
            "run": run,
            "worker_alive": worker["alive"],
            "worker_last_seen": worker["last_seen"],
            "totals": run.totals or {},
            "preview": (run.totals or {}).get("preview"),
            "rows": _result_rows(results),
            "outcome": outcome,
            "total_results": total_results,
            "truncated": total_results > RESULT_PAGE_SIZE,
            "type_note": payload.get("type_note", ""),
            "format_label": payload.get("format_label", ""),
            "columns": payload.get("columns", []),
            "contact_notes": [
                {**p, "name": g["name"]}
                for g in payload.get("groups", []) for p in g.get("contact_problems", [])
            ][:50] if run.status == IntakeRun.STATUS_PREVIEWED else [],
            "row_errors": payload.get("row_errors", [])[:50] if run.status == IntakeRun.STATUS_PREVIEWED else [],
            "previous": previously_imported(run) if run.kind == IntakeRun.KIND_IMPORT and run.status == IntakeRun.STATUS_PREVIEWED else None,
            "pending_reviews": run.reviews.filter(status=DuplicateReview.STATUS_PENDING).count(),
            "pending_changes": run.changes.filter(status=ProposedChange.STATUS_PENDING).count(),
            "coverage_notes": (run.options or {}).get("coverage_notes") or (run.options or {}).get("unsupported", []),
            "no_results": (
                run.kind == IntakeRun.KIND_SCRAPER and run.is_finished
                and (run.totals or {}).get("processed", 0) == 0
                and (run.totals or {}).get("pages_failed", 0) == 0
                and run.status != IntakeRun.STATUS_FAILED
            ),
            "outcomes": IntakeResult.OUTCOME_CHOICES,
        },
    )


@admin_only
@require_POST
def run_confirm(request, run_id):
    run = get_object_or_404(IntakeRun, pk=run_id, kind=IntakeRun.KIND_IMPORT)

    try:
        confirm_import(run.pk, request.user)
        messages.success(request, "The import has finished. Review the results below.")
    except ImportBusy as exc:
        messages.warning(request, str(exc))
    except Exception:
        logger.exception("Import confirmation failed for run %s", run.pk)
        messages.error(
            request,
            "The import could not be completed because of a system error. "
            "Records that were processed before the error are listed below.",
        )

    return redirect("intake_run", run_id=run.pk)


@admin_only
@require_GET
def run_status(request, run_id):
    run = get_object_or_404(IntakeRun, pk=run_id)

    return JsonResponse(
        {
            "status": run.status,
            "status_label": run.get_status_display(),
            "finished": run.is_finished,
            "progress_done": run.progress_done,
            "progress_total": run.progress_total,
            "totals": run.totals or {},
            "worker_alive": worker_state()["alive"],
        }
    )


# ----------------------------------------------------------------- reviews
@admin_only
@require_GET
def review_list(request):
    status = request.GET.get("status", "pending")
    reviews = DuplicateReview.objects.all()

    if status == "pending":
        reviews = reviews.filter(status=DuplicateReview.STATUS_PENDING)
    elif status == "decided":
        reviews = reviews.filter(status=DuplicateReview.STATUS_DECIDED)

    return render(
        request, "intake/reviews.html",
        {"reviews": reviews.select_related("run", "decided_by")[:200], "status": status},
    )


def _display(sub):
    keys = [("org_type", "Type"), ("name", "Name"), ("state", "State"), ("suburb", "Suburb"),
            ("postcode", "Postcode"), ("email", "Email"), ("phone", "Phone"), ("website", "Website"),
            ("source_url", "Source URL"), ("source_org_id", "Source ID"), ("source_key", "Source")]

    return [(label, sub.get(key, "")) for key, label in keys if sub.get(key, "")]


@admin_only
def review_detail(request, review_id):
    review = get_object_or_404(DuplicateReview.objects.select_related("run", "decided_by"), pk=review_id)

    if request.method == "POST":
        decision = request.POST.get("decision", "")
        target = None

        if request.POST.get("target"):
            parts = request.POST["target"].split(":")

            if len(parts) == 2 and parts[1].isdigit() and parts[0] in ORG_MODELS:
                target = (parts[0], int(parts[1]))

        try:
            decide_review(review.pk, request.user, decision, target=target, note=request.POST.get("note", ""))
            messages.success(request, "Your decision was saved.")
        except ReviewError as exc:
            messages.error(request, str(exc))
        except PermissionDenied:
            raise
        except Exception:
            logger.exception("Review decision failed for %s", review.pk)
            messages.error(request, "The decision could not be saved because of a system error. Nothing was changed.")

        return redirect("intake_review", review_id=review.pk)

    review.refresh_from_db()
    sub = review.submission if review.kind != DuplicateReview.KIND_CONTACT else review.submission.get("contact", {})
    matches = []

    for match in review.matches:
        matches.append({**match, "url": org_url(_ct_id(match["type"]), match["id"]), "type_label": TYPE_LABELS.get(match["type"], match["type"])})

    return render(
        request, "intake/review.html",
        {
            "review": review,
            "fields": _display(review.submission) if review.kind != DuplicateReview.KIND_CONTACT else
                      [("Organisation", review.submission.get("organisation", {}).get("name", "")),
                       ("Contact name", sub.get("name", "") or "(none)"), ("Contact email", sub.get("email", ""))],
            "contacts": review.submission.get("contacts", []) if review.kind != DuplicateReview.KIND_CONTACT else [],
            "matches": matches,
            "pending": review.status == DuplicateReview.STATUS_PENDING,
        },
    )


def _ct_id(org_type):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(ORG_MODELS[org_type]).pk


# ----------------------------------------------------------------- changes
@admin_only
@require_GET
def change_list(request):
    status = request.GET.get("status", "pending")
    changes = ProposedChange.objects.select_related("content_type", "run", "decided_by")

    if status != "all":
        changes = changes.filter(status=ProposedChange.STATUS_PENDING if status == "pending" else status)

    rows = []

    for change in changes[:200]:
        org = change.organisation

        rows.append({"change": change, "org": org, "url": org_url(change.content_type_id, change.object_id)})

    return render(request, "intake/changes.html", {"rows": rows, "status": status})


@admin_only
@require_POST
def change_decide(request, change_id):
    try:
        change = decide_change(change_id, request.user, request.POST.get("decision", ""), note=request.POST.get("note", ""))

        if change.status == ProposedChange.STATUS_STALE:
            messages.warning(request, "The current value has changed since this was proposed, so it was not applied.")
        else:
            messages.success(request, "Your decision was saved.")
    except ProposedChange.DoesNotExist:
        raise Http404
    except ReviewError as exc:
        messages.error(request, str(exc))
    except PermissionDenied:
        raise
    except Exception:
        logger.exception("Change decision failed for %s", change_id)
        messages.error(request, "The decision could not be saved because of a system error. Nothing was changed.")

    return redirect("intake_changes")


# ----------------------------------------------------------------- scraper
@admin_only
def scraper_page(request):
    if request.method == "POST":
        org_types = request.POST.getlist("org_type")
        states = request.POST.getlist("state")
        suburbs = [s for s in request.POST.getlist("suburb") if s in supported_suburbs()]

        try:
            run = start_scrape(request.user, org_types, states, suburbs)
            messages.success(
                request,
                "The scrape was queued. It runs in the background worker; this page shows its progress.",
            )

            return redirect("intake_run", run_id=run.pk)
        except ScrapeError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Could not queue a scrape")
            messages.error(request, "The scrape could not be queued because of a system error.")

        return redirect("intake_scraper")

    coverage = []

    for adapter in ADAPTERS.values():
        pages = adapter.pages()
        last = (
            IntakeResult.objects.filter(
                kind=IntakeResult.KIND_PAGE, row_ref__in=[p.url for p in pages]
            ).order_by("-id").first()
            if pages else None
        )
        coverage.append(
            {
                "adapter": adapter,
                "page_count": len(pages),
                "last_failure": last.message if last else "",
                "blocked": bool(adapter.known_limitation),
            }
        )

    return render(
        request,
        "intake/scraper.html",
        {
            "adapters": list(ADAPTERS.values()),
            "coverage": coverage,
            "unsourced_types": [
                label for key, label in ORG_TYPE_LABELS.items()
                if key not in {a.org_type for a in ADAPTERS.values()}
            ],
            "blocked_types": sorted({a.org_type for a in ADAPTERS.values() if a.known_limitation}),
            "type_choices": list(ORG_TYPE_LABELS.items()),
            "supported_types": sorted({a.org_type for a in ADAPTERS.values()}),
            "states": STATE_CHOICES,
            "supported_states": supported_states(),
            "suburbs": supported_suburbs(),
            "runs": IntakeRun.objects.filter(kind=IntakeRun.KIND_SCRAPER)[:8],
            "worker_alive": worker_state()["alive"],
            "worker_last_seen": worker_state()["last_seen"],
        },
    )
