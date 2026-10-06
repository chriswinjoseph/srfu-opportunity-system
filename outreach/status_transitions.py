import logging

from django.db import models, transaction

from .models import Bank, Branch, Club, Opportunity


logger = logging.getLogger("outreach.status_transitions")


class InvalidStatusTransition(ValueError):
    """Raised when a requested status transition is not permitted."""


# Organisation-level status only answers:
# "Has outreach happened?"
ORGANISATION_STATUSES = {
    "not_yet_contacted",
    "contacted",
}


# Opportunity-level status answers:
# "What was the result of the outreach?"
RESPONSE_STATUSES = {
    "interested",
    "not_interested",
    "do_not_contact",
}


def validate_contact_status_transition(
    current_status,
    new_status,
    *,
    contact_confirmed=False,
):
    """
    Validate an organisation contact-status transition.

    Organisation workflow:

        Not Yet Contacted
            -> Contacted

    Interested / Not Interested / Do Not Contact belong to
    Opportunity.status, not organisation.contact_status.
    """

    if current_status not in ORGANISATION_STATUSES:
        raise InvalidStatusTransition(
            f"Unknown current contact status: {current_status}."
        )

    if new_status not in ORGANISATION_STATUSES:
        raise InvalidStatusTransition(
            f"Unknown new contact status: {new_status}."
        )

    # Repeating the same status is safe.
    if current_status == new_status:
        return

    # Organisation becomes Contacted only after outreach
    # has actually been completed or externally confirmed.
    if (
        current_status == "not_yet_contacted"
        and new_status == "contacted"
    ):
        if contact_confirmed:
            return

        raise InvalidStatusTransition(
            "The organisation cannot become Contacted until outreach "
            "has been successfully completed or externally confirmed."
        )

    # A contacted organisation should not normally be reset.
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
    Lock and safely update one organisation's contact status.
    """

    model_class = type(organisation)

    if model_class not in (
        Bank,
        Branch,
        Club,
    ):
        raise InvalidStatusTransition(
            "The supplied object is not a supported organisation."
        )

    with transaction.atomic():
        locked_organisation = (
            model_class.objects
            .select_for_update()
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
                update_fields=[
                    "contact_status",
                ]
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


def bulk_update_organisation_contact_statuses(
    updates,
    *,
    actor=None,
):
    """
    Process multiple organisation status updates independently.
    """

    updated = []
    errors = []

    for item in updates:
        organisation = item["organisation"]
        new_status = item["new_status"]

        contact_confirmed = item.get(
            "contact_confirmed",
            False,
        )

        try:
            saved_organisation = (
                update_organisation_contact_status(
                    organisation,
                    new_status,
                    contact_confirmed=contact_confirmed,
                    actor=actor,
                )
            )

        except InvalidStatusTransition as error:
            errors.append(
                {
                    "model": type(organisation).__name__,
                    "id": organisation.pk,
                    "error": str(error),
                }
            )

        else:
            updated.append(saved_organisation)

    logger.info(
        "Bulk organisation status update completed: "
        "updated=%s rejected=%s actor=%s",
        len(updated),
        len(errors),
        actor,
    )

    return updated, errors


def record_response(
    opportunity,
    new_status,
    *,
    actor=None,
):
    """
    Record the response/outcome of completed outreach.

    The organisation remains Contacted.

    Opportunity.status changes to:
    - Interested
    - Not Interested
    - Do Not Contact
    """

    if new_status not in RESPONSE_STATUSES:
        raise InvalidStatusTransition(
            f"{new_status} is not a valid response status."
        )

    with transaction.atomic():
        locked_opportunity = (
            Opportunity.objects
            .select_for_update()
            .select_related("content_type")
            .get(pk=opportunity.pk)
        )

        model_class = (
            locked_opportunity
            .content_type
            .model_class()
        )

        if model_class not in (
            Bank,
            Branch,
            Club,
        ):
            logger.warning(
                "Response rejected because organisation type "
                "is unsupported: opportunity=%s actor=%s",
                locked_opportunity.pk,
                actor,
            )

            raise InvalidStatusTransition(
                "The opportunity does not belong to a "
                "supported organisation."
            )

        organisation = (
            model_class.objects
            .select_for_update()
            .get(pk=locked_opportunity.object_id)
        )

        # A response can only be recorded after outreach
        # has already occurred.
        if organisation.contact_status != "contacted":
            logger.warning(
                "Response rejected because organisation is not contacted: "
                "opportunity=%s organisation=%s status=%s actor=%s",
                locked_opportunity.pk,
                organisation.pk,
                organisation.contact_status,
                actor,
            )

            raise InvalidStatusTransition(
                "A response cannot be recorded until the "
                "organisation has been contacted."
            )

        # Repeating the same response is safe.
        if locked_opportunity.status == new_status:
            logger.info(
                "Duplicate response status ignored: "
                "opportunity=%s status=%s actor=%s",
                locked_opportunity.pk,
                new_status,
                actor,
            )

            return (
                locked_opportunity,
                organisation,
            )

        # A response normally follows Contacted.
        if locked_opportunity.status != "contacted":
            logger.warning(
                "Response rejected because opportunity is not "
                "in Contacted state: opportunity=%s "
                "current_status=%s requested_status=%s actor=%s",
                locked_opportunity.pk,
                locked_opportunity.status,
                new_status,
                actor,
            )

            raise InvalidStatusTransition(
                "A response cannot be applied from the "
                f"{locked_opportunity.status} opportunity status."
            )

        # Only Opportunity.status changes.
        # Organisation remains Contacted.
        locked_opportunity.status = new_status

        locked_opportunity.save(
            update_fields=[
                "status",
            ]
        )

        logger.info(
            "Organisation response recorded: "
            "opportunity=%s organisation_status=%s "
            "response_status=%s actor=%s",
            locked_opportunity.pk,
            organisation.contact_status,
            new_status,
            actor,
        )

        return (
            locked_opportunity,
            organisation,
        )


def record_positive_response(
    opportunity,
    *,
    actor=None,
):
    """
    Record a positive response.

    Organisation:
        remains Contacted

    Opportunity:
        Contacted -> Interested

    Only banks and branches can trigger supported-club lookup.
    """

    organisation = opportunity.organisation

    # A Club cannot trigger supported-club lookup.
    if isinstance(
        organisation,
        Club,
    ):
        logger.warning(
            "Positive response rejected for club opportunity: "
            "opportunity=%s actor=%s",
            opportunity.pk,
            actor,
        )

        raise InvalidStatusTransition(
            "Only a bank or branch can trigger "
            "supported club lookup."
        )

    (
        locked_opportunity,
        organisation,
    ) = record_response(
        opportunity,
        "interested",
        actor=actor,
    )

    supported_clubs = []

    if isinstance(
        organisation,
        Bank,
    ):
        bank = organisation

        supported_clubs = list(
            Club.objects.filter(
                models.Q(
                    supported_by_bank=bank
                )
                | models.Q(
                    supported_by_branch__bank=bank
                )
            )
            .distinct()
            .order_by("club_name")
        )

    elif isinstance(
        organisation,
        Branch,
    ):
        bank = organisation.bank

        supported_clubs = list(
            Club.objects.filter(
                models.Q(
                    supported_by_bank=bank
                )
                | models.Q(
                    supported_by_branch__bank=bank
                )
            )
            .distinct()
            .order_by("club_name")
        )

    return (
        locked_opportunity,
        supported_clubs,
    )