/*
 * "Email Organisation" dialog.
 *
 * The dialog content is fetched with GET (read-only: opening it never
 * creates a draft, calls the AI or changes any status). Every action in
 * it is a normal form POST to an existing workflow endpoint with CSRF
 * protection; the server redirects back here (post/redirect/get), so a
 * refresh never repeats an action.
 */
(function () {
    "use strict";

    const overlay = document.getElementById("emailModal");

    if (!overlay) {
        return;
    }

    const dialog = overlay.querySelector(".em-dialog");
    const body = document.getElementById("emailModalBody");

    let requestCounter = 0;
    let controller = null;
    let trigger = null;
    let currentKey = null;
    let submitting = false;
    let currentUrl = null;

    const FOCUSABLE = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled]):not([type=hidden])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    function visible(element) {
        return !element.closest("[hidden]");
    }

    function focusables() {
        return Array.from(dialog.querySelectorAll(FOCUSABLE)).filter(
            visible
        );
    }

    function announce(text) {
        const status = body.querySelector("#emStatus");

        if (status) {
            status.textContent = "";
            window.setTimeout(function () {
                status.textContent = text;
            }, 30);
        }
    }

    function showMessage(html) {
        body.innerHTML = "";

        const box = document.createElement("div");
        box.className = "em-fragment";
        box.innerHTML = html;
        body.appendChild(box);
    }

    function messageBlock(title, text, link) {
        const wrapper = document.createElement("div");
        const heading = document.createElement("h2");
        heading.className = "em-title";
        heading.textContent = title;
        const paragraph = document.createElement("p");
        paragraph.className = "em-message em-message-error";
        paragraph.setAttribute("role", "alert");
        paragraph.textContent = text;
        wrapper.appendChild(heading);
        wrapper.appendChild(paragraph);

        if (link) {
            const anchor = document.createElement("a");
            anchor.href = link.href;
            anchor.textContent = link.label;
            wrapper.appendChild(anchor);
        }

        body.innerHTML = "";
        const box = document.createElement("div");
        box.className = "em-fragment";
        box.appendChild(wrapper);
        body.appendChild(box);
    }

    function editableFields() {
        return Array.from(
            body.querySelectorAll("[data-em-editable] [data-em-field]")
        );
    }

    function isDirty() {
        return editableFields().some(function (field) {
            return field.value !== field.dataset.initial;
        });
    }

    function hasContent() {
        return editableFields().some(function (field) {
            return field.value.trim() !== "";
        });
    }

    function showPanel(name, focus) {
        const panels = body.querySelectorAll(".em-panel");
        let found = false;

        panels.forEach(function (panel) {
            const match = panel.dataset.panel === name;
            panel.hidden = !match;
            found = found || match;
        });

        if (!found) {
            const compose = body.querySelector('[data-panel="compose"]');

            if (compose) {
                compose.hidden = false;
            }
        }

        if (focus !== false) {
            const target =
                body.querySelector(".em-panel:not([hidden]) input:not([readonly]):not([type=hidden]), .em-panel:not([hidden]) textarea:not([readonly])")
                || body.querySelector(".em-panel:not([hidden]) button");

            if (target) {
                target.focus();
            }
        }
    }

    function remember() {
        editableFields().forEach(function (field) {
            field.dataset.initial = field.value;
        });
    }

    function init(expectedKey) {
        const fragment = body.querySelector(".em-fragment");

        if (!fragment || fragment.dataset.orgKey !== expectedKey) {
            // Never show another organisation's content.
            messageBlock(
                "Email Organisation",
                "The email dialog could not be loaded for this organisation. Please try again."
            );
            return;
        }

        remember();
        showPanel(fragment.dataset.initialPanel || "compose", true);
    }

    function showSessionExpired(form) {
        const errorBox = form.querySelector("[data-em-error]");
        const text =
            "Your session has expired. Nothing was sent and what you typed is still here. " +
            "Log in again in a new tab, then come back and press the button again.";

        if (errorBox) {
            errorBox.textContent = text + " ";
            const anchor = document.createElement("a");
            anchor.href = "/accounts/login/";
            anchor.target = "_blank";
            anchor.rel = "noopener";
            anchor.textContent = "Log in (opens in a new tab)";
            errorBox.appendChild(anchor);
            errorBox.hidden = false;
        }

        // The inline message above is an alert; clear the status line.
        announce("");
    }

    function open(options) {
        trigger = options.trigger || document.activeElement;
        currentKey = options.key;
        currentUrl = options.url;
        submitting = false;
        requestCounter += 1;
        const requestId = requestCounter;

        if (controller) {
            controller.abort();
        }

        controller = new AbortController();

        overlay.hidden = false;
        document.body.classList.add("em-open");
        body.innerHTML =
            '<div class="em-fragment"><h2 class="em-title">Email Organisation</h2>' +
            '<p class="em-loading-state" role="status"><span class="em-spinner" aria-hidden="true"></span> Loading...</p></div>';
        dialog.focus();

        fetch(options.url, {
            method: "GET",
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" },
            signal: controller.signal,
        })
            .then(function (response) {
                if (requestId !== requestCounter) {
                    return null;
                }

                if (
                    response.redirected
                    && /\/accounts\/login\//.test(response.url)
                ) {
                    messageBlock(
                        "Session expired",
                        "Your session has expired. Please log in again.",
                        { href: response.url, label: "Log in" }
                    );
                    return null;
                }

                if (response.status === 403) {
                    messageBlock(
                        "Not allowed",
                        "You do not have permission to open this email."
                    );
                    return null;
                }

                if (!response.ok) {
                    messageBlock(
                        "Email Organisation",
                        "The email dialog could not be loaded. Please try again."
                    );
                    return null;
                }

                return response.text();
            })
            .then(function (html) {
                if (html === null || html === undefined) {
                    return;
                }

                if (requestId !== requestCounter) {
                    return;
                }

                body.innerHTML = html;
                init(currentKey);
            })
            .catch(function (error) {
                if (error && error.name === "AbortError") {
                    return;
                }

                if (requestId === requestCounter) {
                    messageBlock(
                        "Email Organisation",
                        "The email dialog could not be loaded. Please check your connection and try again."
                    );
                }
            });
    }

    function close(force) {
        if (!force && isDirty() && !window.confirm(
            "You have unsaved changes. Discard them and close?"
        )) {
            return;
        }

        requestCounter += 1;

        if (controller) {
            controller.abort();
        }

        overlay.hidden = true;
        document.body.classList.remove("em-open");
        body.innerHTML = "";

        if (trigger && document.contains(trigger)) {
            trigger.focus();
        }

        trigger = null;
        currentKey = null;
    }

    function copyText(text, label) {
        function done(success) {
            announce(
                success
                    ? label + " copied."
                    : label + " could not be copied. Select the text and copy it manually."
            );
        }

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(
                function () { done(true); },
                function () { done(fallbackCopy(text)); }
            );
            return;
        }

        done(fallbackCopy(text));
    }

    function fallbackCopy(text) {
        const area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();

        let success = false;

        try {
            success = document.execCommand("copy");
        } catch (error) {
            success = false;
        }

        area.remove();

        return success;
    }

    overlay.addEventListener("click", function (event) {
        if (event.target === overlay) {
            close(false);
            return;
        }

        const closeButton = event.target.closest("[data-em-close]");

        if (closeButton) {
            close(false);
            return;
        }

        const panelButton = event.target.closest("[data-em-panel]");

        if (panelButton && body.contains(panelButton)) {
            const target = panelButton.dataset.emPanel;

            if (
                target === "generate"
                && hasContent()
                && isDirty()
                && !window.confirm(
                    "The generated draft will replace the unsaved text in the editor. Continue?"
                )
            ) {
                return;
            }

            showPanel(target, true);
            return;
        }

        const clearButton = event.target.closest("[data-em-clear]");

        if (clearButton) {
            if (
                hasContent()
                && !window.confirm(
                    "Clear the subject and message? Unsaved text will be discarded. Saved drafts and history are not deleted."
                )
            ) {
                return;
            }

            editableFields().forEach(function (field) {
                field.value = "";
            });

            const first = editableFields()[0];

            if (first) {
                first.focus();
            }

            announce("Fields cleared. Save the draft to keep this change.");
            return;
        }

        const copyButton = event.target.closest(
            "[data-em-copy-value], [data-em-copy-from]"
        );

        if (copyButton) {
            let text = copyButton.dataset.emCopyValue;

            if (text === undefined) {
                const source = body.querySelector(
                    copyButton.dataset.emCopyFrom
                );
                text = source ? source.value : "";
            }

            copyText(text, copyButton.dataset.emCopyLabel || "Text");
        }
    });

    overlay.addEventListener("submit", function (event) {
        const form = event.target.closest("form[data-em-form]");

        if (!form) {
            return;
        }

        if (submitting) {
            event.preventDefault();
            return;
        }

        // Inline validation: keep what the user typed, explain what is missing.
        const missing = Array.from(
            form.querySelectorAll("[required]")
        ).filter(function (field) {
            return field.type === "checkbox"
                ? !field.checked
                : field.value.trim() === "";
        });

        const errorBox = form.querySelector("[data-em-error]");

        form.querySelectorAll("[aria-invalid]").forEach(function (field) {
            field.removeAttribute("aria-invalid");
        });

        if (missing.length) {
            event.preventDefault();
            missing.forEach(function (field) {
                field.setAttribute("aria-invalid", "true");
            });

            if (errorBox) {
                errorBox.textContent =
                    "Please complete the required fields before continuing.";
                errorBox.hidden = false;
            }

            missing[0].focus();
            return;
        }

        if (errorBox) {
            errorBox.hidden = true;
        }

        const submitter = event.submitter;

        if (
            submitter
            && submitter.hasAttribute("data-em-confirm-submit")
            && !window.confirm(
                "Submit this email for approval? The subject and message shown here will be submitted."
            )
        ) {
            event.preventDefault();
            return;
        }

        // Before sending anything, make sure the session is still valid, so
        // an expired session never discards what the user typed: the form
        // stays as it is and they can log in again in another tab.
        if (!form.dataset.emProbed && currentUrl) {
            event.preventDefault();
            submitting = true;

            fetch(currentUrl, {
                method: "GET",
                credentials: "same-origin",
                redirect: "manual",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            })
                .then(function (response) {
                    return response.type === "opaqueredirect";
                })
                .catch(function () {
                    return false;
                })
                .then(function (expired) {
                    submitting = false;

                    if (expired) {
                        showSessionExpired(form);
                        return;
                    }

                    form.dataset.emProbed = "1";

                    if (form.requestSubmit) {
                        form.requestSubmit(submitter || undefined);
                    } else {
                        form.submit();
                    }

                    delete form.dataset.emProbed;
                });

            return;
        }

        submitting = true;

        const loading = form.querySelector("[data-em-loading]");

        if (loading) {
            loading.hidden = false;
        }

        window.setTimeout(function () {
            body.querySelectorAll("button").forEach(function (button) {
                button.disabled = true;
            });

            if (submitter && submitter.dataset.emBusy) {
                submitter.textContent = submitter.dataset.emBusy;
            }
        }, 0);

        announce("Working...");
    });

    document.addEventListener("keydown", function (event) {
        if (overlay.hidden) {
            return;
        }

        if (event.key === "Escape") {
            event.preventDefault();
            close(false);
            return;
        }

        if (event.key !== "Tab") {
            return;
        }

        const items = focusables();

        if (!items.length) {
            event.preventDefault();
            dialog.focus();
            return;
        }

        const first = items[0];
        const last = items[items.length - 1];

        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    // Restore the page if it comes back from the back/forward cache.
    window.addEventListener("pageshow", function (event) {
        if (event.persisted) {
            submitting = false;
            body.querySelectorAll("button").forEach(function (button) {
                button.disabled = false;
            });
        }
    });

    window.EmailModal = { open: open, close: close };

    // Buttons outside the dashboard cards (for example the organisation page).
    document.addEventListener("click", function (event) {
        const button = event.target.closest("[data-em-open]");

        if (!button || overlay.contains(button)) {
            return;
        }

        event.preventDefault();
        open({
            url: button.dataset.emUrl,
            key: button.dataset.emKey,
            trigger: button,
        });
    });

    // Re-open after an action posted from the dialog (post/redirect/get).
    document.addEventListener("DOMContentLoaded", function () {
        const params = new URLSearchParams(window.location.search);
        const key = params.get("open_email");
        const template = document.body.dataset.emailModalUrlTemplate
            || (document.getElementById("dashboardApp") || {}).dataset
                && document.getElementById("dashboardApp").dataset.emailModalUrlTemplate;

        if (!key || !template) {
            return;
        }

        const parts = key.split("-");

        if (parts.length !== 2 || !/^\d+$/.test(parts[0]) || !/^\d+$/.test(parts[1])) {
            return;
        }

        const panel = params.get("panel") || "";
        const stash = params.get("stash") || "";
        params.delete("open_email");
        params.delete("panel");
        params.delete("stash");

        const cleaned = window.location.pathname
            + (params.toString() ? "?" + params.toString() : "");

        window.history.replaceState({}, "", cleaned);

        const url = new URL(
            template
                .replace("999999999", parts[0])
                .replace("888888888", parts[1]),
            window.location.origin
        );

        url.searchParams.set("return", cleaned);
        url.searchParams.set("reopen", "1");

        if (panel) {
            url.searchParams.set("panel", panel);
        }

        if (stash) {
            url.searchParams.set("stash", stash);
        }

        open({
            url: url.pathname + url.search,
            key: key,
            trigger: document.querySelector(".organisation-card button, body"),
        });
    });
})();
