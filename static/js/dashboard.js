(() => {
    "use strict";

    const app = document.getElementById("dashboardApp");

    if (!app) {
        return;
    }

    const apiUrl = app.dataset.apiUrl;
    const detailUrlTemplate = app.dataset.detailUrlTemplate;
    const pageSize = 4;

    const statusLabels = {
        not_yet_contacted: "Not Yet Contacted",
        contacted: "Contacted",
        interested: "Interested",
        not_interested: "Not Interested",
        do_not_contact: "Do Not Contact",
        needs_review: "Needs Review",
    };

    const state = {
        pages: {
            not_yet_contacted: 1,
            contacted: 1,
        },
    };

    const elements = {
        filters: document.getElementById("dashboardFilters"),
        search: document.getElementById("searchInput"),
        type: document.getElementById("typeFilter"),
        region: document.getElementById("regionFilter"),
        sort: document.getElementById("sortControl"),
        clearFilters: document.getElementById("clearFilters"),
        error: document.getElementById("dashboardError"),
        template: document.getElementById(
            "organisationCardTemplate"
        ),

        percentContacted: document.getElementById(
            "percentContacted"
        ),
        progressRing: document.getElementById("progressRing"),
        notYetCount: document.getElementById("notYetCount"),
        contactedCount: document.getElementById(
            "contactedCount"
        ),
        interestedCount: document.getElementById(
            "interestedCount"
        ),
        notInterestedCount: document.getElementById(
            "notInterestedCount"
        ),
        doNotContactCount: document.getElementById(
            "doNotContactCount"
        ),
        needsReviewCount: document.getElementById(
            "needsReviewCount"
        ),

        detailsPanel: document.getElementById("detailsPanel"),
        closeDetails: document.getElementById("closeDetails"),
        detailName: document.getElementById("detailName"),
        detailType: document.getElementById("detailType"),
        detailStatus: document.getElementById("detailStatus"),
        detailOutcome: document.getElementById(
            "detailOutcome"
        ),
        detailRegion: document.getElementById("detailRegion"),
        detailEmail: document.getElementById("detailEmail"),
        detailPhone: document.getElementById("detailPhone"),
        fullDetailsLink: document.getElementById(
            "fullDetailsLink"
        ),
    };

    const columns = {
        not_yet_contacted: {
            cards: document.getElementById("notYetCards"),
            loading: document.getElementById("notYetLoading"),
            empty: document.getElementById("notYetEmpty"),
            total: document.getElementById("notYetTotal"),
            previous: document.getElementById(
                "notYetPrevious"
            ),
            next: document.getElementById("notYetNext"),
            page: document.getElementById("notYetPage"),
        },
        contacted: {
            cards: document.getElementById("contactedCards"),
            loading: document.getElementById(
                "contactedLoading"
            ),
            empty: document.getElementById(
                "contactedEmpty"
            ),
            total: document.getElementById("contactedTotal"),
            previous: document.getElementById(
                "contactedPrevious"
            ),
            next: document.getElementById("contactedNext"),
            page: document.getElementById("contactedPage"),
        },
    };

    function getDisplayValue(value) {
        if (
            value === null
            || value === undefined
            || String(value).trim() === ""
        ) {
            return "Not provided";
        }

        return String(value);
    }

    function formatOrganisationType(value) {
        const text = getDisplayValue(value);

        if (text === "Not provided") {
            return text;
        }

        return (
            text.charAt(0).toUpperCase()
            + text.slice(1).toLowerCase()
        );
    }

    function getEffectiveStatus(row) {
        if (row.status_conflict) {
            return "needs_review";
        }

        if (row.opportunity_outcome) {
            return row.opportunity_outcome;
        }

        return row.contact_status;
    }

    function getStatusLabel(row) {
        const effectiveStatus = getEffectiveStatus(row);

        return (
            statusLabels[effectiveStatus]
            || row.contact_status_label
            || effectiveStatus
        );
    }

    function getDetailUrl(row) {
        return detailUrlTemplate
            .replace(
                "999999999",
                encodeURIComponent(row.content_type_id)
            )
            .replace(
                "888888888",
                encodeURIComponent(row.id)
            );
    }

    function getPagination(data) {
        if (data.pagination) {
            return {
                totalItems:
                    data.pagination.total_items
                    ?? data.pagination.count
                    ?? 0,
                currentPage:
                    data.pagination.current_page
                    ?? data.pagination.page
                    ?? 1,
                totalPages:
                    data.pagination.total_pages
                    ?? data.pagination.num_pages
                    ?? 1,
                hasPrevious:
                    data.pagination.has_previous ?? false,
                hasNext:
                    data.pagination.has_next ?? false,
            };
        }

        return {
            totalItems: data.count ?? 0,
            currentPage: data.page ?? 1,
            totalPages: data.num_pages ?? 1,
            hasPrevious: (data.page ?? 1) > 1,
            hasNext:
                (data.page ?? 1) < (data.num_pages ?? 1),
        };
    }

    function getRequestParameters(contactStatus) {
        const [sortBy, sortDirection] =
            elements.sort.value.split(":");

        const parameters = new URLSearchParams({
            status: contactStatus,
            sort_by: sortBy,
            sort_dir: sortDirection,
            page: state.pages[contactStatus],
            page_size: pageSize,
        });

        const search = elements.search.value.trim();
        const type = elements.type.value.trim();
        const region = elements.region.value.trim();

        if (search) {
            parameters.set("q", search);
        }

        if (type) {
            parameters.set("type", type);
        }

        if (region) {
            parameters.set("region", region);
        }

        return parameters;
    }

    async function fetchOrganisations(contactStatus) {
        const parameters = getRequestParameters(
            contactStatus
        );

        const response = await fetch(
            `${apiUrl}?${parameters.toString()}`,
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                credentials: "same-origin",
            }
        );

        let responseData;

        try {
            responseData = await response.json();
        } catch (error) {
            throw new Error(
                "The server returned an invalid response."
            );
        }

        if (!response.ok) {
            const errorMessage =
                typeof responseData.error === "string"
                    ? responseData.error
                    : "The organisation list could not be loaded.";

            throw new Error(errorMessage);
        }

        return responseData;
    }

    function setLoading(contactStatus, isLoading) {
        const column = columns[contactStatus];

        column.loading.hidden = !isLoading;

        if (isLoading) {
            column.empty.hidden = true;
            column.cards.replaceChildren();
            column.previous.disabled = true;
            column.next.disabled = true;
            column.cards.setAttribute("aria-busy", "true");
        } else {
            column.cards.removeAttribute("aria-busy");
        }
    }

    function showError(message) {
        elements.error.textContent = message;
        elements.error.hidden = false;
    }

    function clearError() {
        elements.error.textContent = "";
        elements.error.hidden = true;
    }

    function updateBrowserUrl() {
        const [sortBy, sortDirection] =
            elements.sort.value.split(":");

        const parameters = new URLSearchParams();
        const search = elements.search.value.trim();
        const type = elements.type.value.trim();
        const region = elements.region.value.trim();

        if (search) {
            parameters.set("q", search);
        }

        if (type) {
            parameters.set("type", type);
        }

        if (region) {
            parameters.set("region", region);
        }

        if (sortBy !== "name") {
            parameters.set("sort_by", sortBy);
        }

        if (sortDirection !== "asc") {
            parameters.set("sort_dir", sortDirection);
        }

        const queryString = parameters.toString();
        const newUrl = queryString
            ? `${window.location.pathname}?${queryString}`
            : window.location.pathname;

        window.history.replaceState({}, "", newUrl);
    }

    function createOrganisationCard(row) {
        const card = elements.template.content
            .firstElementChild
            .cloneNode(true);

        const effectiveStatus = getEffectiveStatus(row);
        const detailUrl = getDetailUrl(row);

        card.classList.add(`status-${effectiveStatus}`);
        card.dataset.organisationId = row.id;
        card.dataset.contentTypeId = row.content_type_id;

        card.querySelector(
            '[data-field="type"]'
        ).textContent = formatOrganisationType(row.type);

        card.querySelector(
            '[data-field="name"]'
        ).textContent = getDisplayValue(row.name);

        card.querySelector(
            '[data-field="status-label"]'
        ).textContent = getStatusLabel(row);

        const stateField = card.querySelector(
    '[data-field="state"], [data-field="region"]'
);

if (stateField) {
    stateField.textContent = getDisplayValue(row.state);
}

        card.querySelector(
            '[data-field="email"]'
        ).textContent = getDisplayValue(
            row.public_email ?? row.email
        );

        card.querySelector(
            '[data-field="phone"]'
        ).textContent = getDisplayValue(
            row.public_phone ?? row.phone
        );

        card.querySelector(
            '[data-field="details-link"]'
        ).href = detailUrl;

        card.addEventListener("click", (event) => {
            if (event.target.closest("a, button")) {
                return;
            }

            selectOrganisation(card, row);
        });

        card.addEventListener("keydown", (event) => {
            if (
                event.key !== "Enter"
                && event.key !== " "
            ) {
                return;
            }

            event.preventDefault();
            selectOrganisation(card, row);
        });

        return card;
    }

    function selectOrganisation(card, row) {
        document
            .querySelectorAll(".organisation-card.selected")
            .forEach((selectedCard) => {
                selectedCard.classList.remove("selected");
            });

        card.classList.add("selected");

        elements.detailName.textContent =
            getDisplayValue(row.name);

        elements.detailType.textContent =
            formatOrganisationType(row.type);

        elements.detailStatus.textContent =
            row.contact_status_label
            || statusLabels[row.contact_status]
            || getDisplayValue(row.contact_status);

        if (row.status_conflict) {
            elements.detailOutcome.textContent =
                "Needs Review";
        } else if (row.opportunity_outcome) {
            elements.detailOutcome.textContent =
                statusLabels[row.opportunity_outcome]
                || row.opportunity_outcome;
        } else {
            elements.detailOutcome.textContent =
                "No outcome recorded";
        }

        elements.detailRegion.textContent =
            getDisplayValue(row.region);

        elements.detailEmail.textContent =
            getDisplayValue(
                row.public_email ?? row.email
            );

        elements.detailPhone.textContent =
            getDisplayValue(
                row.public_phone ?? row.phone
            );

        elements.fullDetailsLink.href = getDetailUrl(row);
        elements.detailsPanel.hidden = false;

        elements.detailsPanel.scrollIntoView({
            behavior: "smooth",
            block: "nearest",
        });
    }

    function renderColumn(contactStatus, data) {
        const column = columns[contactStatus];
        const pagination = getPagination(data);
        const results = Array.isArray(data.results)
            ? data.results
            : [];

        column.cards.replaceChildren();

        results.forEach((row) => {
            column.cards.appendChild(
                createOrganisationCard(row)
            );
        });

        column.total.textContent = pagination.totalItems;
        column.page.textContent =
            `Page ${pagination.currentPage} `
            + `of ${pagination.totalPages}`;

        column.previous.disabled =
            !pagination.hasPrevious;

        column.next.disabled =
            !pagination.hasNext;

        column.empty.hidden = results.length !== 0;
        column.loading.hidden = true;
        column.cards.removeAttribute("aria-busy");
    }

    function countPageOutcomes(results, outcome) {
        return results.filter((row) => {
            return (
                row.opportunity_outcome === outcome
                && !row.status_conflict
            );
        }).length;
    }

    function updateSummary(notYetData, contactedData) {
        const notYetPagination =
            getPagination(notYetData);

        const contactedPagination =
            getPagination(contactedData);

        const notYetTotal = notYetPagination.totalItems;
        const contactedTotal =
            contactedPagination.totalItems;

        const total = notYetTotal + contactedTotal;

        const percentage = total
            ? Math.round((contactedTotal / total) * 100)
            : 0;

        elements.notYetCount.textContent = notYetTotal;
        elements.contactedCount.textContent =
            contactedTotal;

        elements.percentContacted.textContent =
            `${percentage}%`;

        elements.progressRing.style.setProperty(
            "--progress",
            percentage
        );

        elements.progressRing.setAttribute(
            "aria-label",
            `${percentage} percent contacted`
        );

        const ringText =
            elements.progressRing.querySelector("span");

        if (ringText) {
            ringText.textContent = `${percentage}%`;
        }

        const contactedSummary =
            contactedData.summary || {};

        const notYetSummary =
            notYetData.summary || {};

        const outcomeCounts =
            contactedSummary.opportunity_outcome_counts
            || contactedSummary.outcomes
            || {};

        const contactedResults =
            contactedData.results || [];

        const notYetResults =
            notYetData.results || [];

        elements.interestedCount.textContent =
            outcomeCounts.interested
            ?? countPageOutcomes(
                contactedResults,
                "interested"
            );

        elements.notInterestedCount.textContent =
            outcomeCounts.not_interested
            ?? countPageOutcomes(
                contactedResults,
                "not_interested"
            );

        elements.doNotContactCount.textContent =
            outcomeCounts.do_not_contact
            ?? countPageOutcomes(
                contactedResults,
                "do_not_contact"
            );

        elements.needsReviewCount.textContent =
            notYetSummary.needs_review
            ?? notYetResults.filter(
                (row) => row.status_conflict
            ).length;
    }

    async function loadDashboard() {
        clearError();

        setLoading("not_yet_contacted", true);
        setLoading("contacted", true);

        try {
            const [notYetData, contactedData] =
                await Promise.all([
                    fetchOrganisations(
                        "not_yet_contacted"
                    ),
                    fetchOrganisations("contacted"),
                ]);

            renderColumn(
                "not_yet_contacted",
                notYetData
            );

            renderColumn("contacted", contactedData);

            updateSummary(notYetData, contactedData);
            updateBrowserUrl();
        } catch (error) {
            setLoading("not_yet_contacted", false);
            setLoading("contacted", false);

            showError(
                error.message
                || "The dashboard could not be loaded."
            );
        }
    }

    function resetPages() {
        state.pages.not_yet_contacted = 1;
        state.pages.contacted = 1;
    }

    elements.filters.addEventListener(
        "submit",
        (event) => {
            event.preventDefault();
            resetPages();
            elements.detailsPanel.hidden = true;
            loadDashboard();
        }
    );

    elements.clearFilters.addEventListener(
        "click",
        () => {
            elements.search.value = "";
            elements.type.value = "";
            elements.region.value = "";
            elements.sort.value = "name:asc";

            resetPages();
            elements.detailsPanel.hidden = true;
            loadDashboard();
        }
    );

    columns.not_yet_contacted.previous.addEventListener(
        "click",
        () => {
            if (state.pages.not_yet_contacted > 1) {
                state.pages.not_yet_contacted -= 1;
                loadDashboard();
            }
        }
    );

    columns.not_yet_contacted.next.addEventListener(
        "click",
        () => {
            state.pages.not_yet_contacted += 1;
            loadDashboard();
        }
    );

    columns.contacted.previous.addEventListener(
        "click",
        () => {
            if (state.pages.contacted > 1) {
                state.pages.contacted -= 1;
                loadDashboard();
            }
        }
    );

    columns.contacted.next.addEventListener(
        "click",
        () => {
            state.pages.contacted += 1;
            loadDashboard();
        }
    );

    elements.closeDetails.addEventListener(
        "click",
        () => {
            elements.detailsPanel.hidden = true;

            document
                .querySelectorAll(
                    ".organisation-card.selected"
                )
                .forEach((card) => {
                    card.classList.remove("selected");
                });
        }
    );

    loadDashboard();
})();