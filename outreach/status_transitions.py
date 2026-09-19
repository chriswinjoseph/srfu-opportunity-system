import logging

from django.db import models, transaction

from .models import Bank, Branch, Club, Opportunity


logger = logging.getLogger("outreach.status_transitions")


class InvalidStatusTransition(ValueError):
    """Raised when a requested status transition is not permitted."""


ORGANISATION_STATUSES = {
    "not_yet_contacted",
    "contacted",
}


def validate_contact_status_transition(
    current_status,
    new_status,
    *,
    contact_confirmed=False,
):
    """
    Validate an organisation contact-status transition.

    An organisation may move from Not Yet Contacted to Contacted only
    when successful or confirmed external outreach has occurred.
    """
    if current_status not in ORGANISATION_STATUSES:
        raise InvalidStatusTransition(
            f"Unknown current contact status: {current_status}."
        )

    if new_status not in ORGANISATION_STATUSES:
        raise InvalidStatusTransition(
            f"{new_status} is an opportunity outcome, not an "
            "organisation contact status."
        )

    if current_status == new_status:
        return

    if (
        current_status == "not_yet_contacted"
        and new_status == "contacted"
        and contact_confirmed
    ):
        return

    if (
        current_status == "not_yet_contacted"
        and new_status == "contacted"
    ):
        raise InvalidStatusTransition(
            "The organisation cannot become Contacted until outreach "
            "has been successfully completed or externally confirmed."
        )

    if (
        current_status == "contacted"
        and new_status == "not_yet_contacted"
    ):
        raise InvalidStatusTransition(
            "A Contacted organisation cannot be reset to "
            "Not Yet Contacted through the normal workflow."
        )

    raise InvalidStatusTransition(
        f"Transition from {current_status} to {new_status} "
        "is not permitted."
    )


def update_organisation_contact_status(
    organisation,
    new_status,
    *,
    contact_confirmed=False,
    actor=None,
):
    """
    Lock and update one organisation after validating its transition.

    Using a database transaction and row lock prevents an older concurrent
    request from silently overwriting a newer status.
    """
    model_class = type(organisation)

    if model_class not in (Bank, Branch, Club):
        raise InvalidStatusTransition(
            "The supplied object is not a supported organisation."
        )

    with transaction.atomic():
        locked_organisation = (
            model_class.objects.select_for_update()
            .get(pk=organisation.pk)
        )

        old_status = locked_organisation.contact_status

        try:
            validate_contact_status_transition(
                old_status,
                new_status,
                contact_confirmed=contact_confirmed,
            )
        except InvalidStatusTransition:
            logger.warning(
                "Rejected organisation status transition: "
                "model=%s id=%s from=%s to=%s actor=%s",
                model_class.__name__,
                organisation.pk,
                old_status,
                new_status,
                actor,
            )
            raise

        if old_status != new_status:
            locked_organisation.contact_status = new_status
            locked_organisation.save(
                update_fields=["contact_status"],
            )

        logger.info(
            "Accepted organisation status transition: "
            "model=%s id=%s from=%s to=%s actor=%s",
            model_class.__name__,
            organisation.pk,
            old_status,
            new_status,
            actor,
        )

        return locked_organisation


def record_positive_response(opportunity, *, actor=None):
    """
    Record a positive response safely.

    The organisation must already be Contacted and remains Contacted.
    Only the opportunity changes to Interested.
    """
    with transaction.atomic():
        locked_opportunity = (
            Opportunity.objects.select_for_update()
            .select_related("content_type")
            .get(pk=opportunity.pk)
        )

        model_class = locked_opportunity.content_type.model_class()

        if model_class not in (Bank, Branch):
            logger.warning(
                "Rejected positive response: opportunity=%s "
                "unsupported_model=%s actor=%s",
                locked_opportunity.pk,
                model_class,
                actor,
            )
            raise InvalidStatusTransition(
                "Only a bank or branch opportunity can trigger "
                "supported-club lookup."
            )

        organisation = (
            model_class.objects.select_for_update()
            .get(pk=locked_opportunity.object_id)
        )

        if organisation.contact_status != "contacted":
            logger.warning(
                "Rejected positive response: opportunity=%s "
                "organisation_status=%s actor=%s",
                locked_opportunity.pk,
                organisation.contact_status,
                actor,
            )
            raise InvalidStatusTransition(
                "A positive response can only be recorded after "
                "the organisation has been contacted."
            )

        # Treat the same request as idempotent rather than creating
        # another update.
        if locked_opportunity.status == "interested":
            logger.info(
                "Duplicate positive response ignored: "
                "opportunity=%s actor=%s",
                locked_opportunity.pk,
                actor,
            )
        elif locked_opportunity.status == "contacted":
            locked_opportunity.status = "interested"
            locked_opportunity.save(update_fields=["status"])

            logger.info(
                "Positive response recorded: opportunity=%s actor=%s",
                locked_opportunity.pk,
                actor,
            )
        else:
            logger.warning(
                "Rejected positive response: opportunity=%s "
                "opportunity_status=%s actor=%s",
                locked_opportunity.pk,
                locked_opportunity.status,
                actor,
            )
            raise InvalidStatusTransition(
                "A positive response cannot be applied from the "
                f"{locked_opportunity.status} opportunity status."
            )

        bank = (
            organisation
            if isinstance(organisation, Bank)
            else organisation.bank
        )

        supported_clubs = list(
            Club.objects.filter(
                models.Q(supported_by_bank=bank)
                | models.Q(supported_by_branch__bank=bank)
            )
            .distinct()
            .order_by("club_name")
        )

        return locked_opportunity, supported_clubs