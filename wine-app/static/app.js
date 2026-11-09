const state = {
    wines: [],
    locations: [],
    selectedPhoto: null,
    photoPreviewUrl: null,
    scanDraft: null,
    editingLocationId: null,
    nextBottleQrId: null,
    editingWine: null,
    selectingWineForForm: false,
    collectionView: (() => {
        try {
            return localStorage.getItem("wineCellar.collectionView") === "table" ? "table" : "cards";
        } catch (_) {
            return "cards";
        }
    })(),
    tableSortColumn: (() => {
        try {
            return localStorage.getItem("wineCellar.tableSortColumn") || "qr_id";
        } catch (_) {
            return "qr_id";
        }
    })(),
    tableSortDirection: (() => {
        try {
            return localStorage.getItem("wineCellar.tableSortDirection") === "desc" ? "desc" : "asc";
        } catch (_) {
            return "asc";
        }
    })(),
};

const byId = (id) => document.getElementById(id);
const cellar = byId("cellar");
const signIn = byId("sign-in");
const dialog = byId("wine-dialog");
const wineGrid = byId("wine-grid");
const toast = byId("toast");

async function api(path, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const headers = new Headers(options.headers || {});
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
        headers.set("X-Requested-With", "WineCellar");
    }
    const response = await fetch(path, {
        ...options,
        method,
        headers,
        credentials: "same-origin",
    });
    if (response.status === 401 && path !== "/auth/login") {
        showSignIn();
        throw new Error("Your session expired. Please sign in again.");
    }
    const contentType = response.headers.get("content-type") || "";
    const body = response.status === 204
        ? null
        : contentType.includes("application/json")
            ? await response.json()
            : await response.text();
    if (!response.ok) {
        const detail = typeof body === "object" && body !== null ? body.detail : null;
        const message = typeof detail === "string"
            ? detail
            : detail?.message || (typeof body === "string" ? body : null) || "Something went wrong.";
        const error = new Error(message);
        error.status = response.status;
        error.body = body;
        throw error;
    }
    return body;
}

function showSignIn() {
    cellar.hidden = true;
    signIn.hidden = false;
    byId("username").focus();
}

function showCellar() {
    signIn.hidden = true;
    cellar.hidden = false;
}

function notify(message, kind = "success") {
    toast.textContent = message;
    toast.className = `toast toast--${kind}`;
    toast.hidden = false;
    window.clearTimeout(notify.timeout);
    notify.timeout = window.setTimeout(() => {
        toast.hidden = true;
    }, 3800);
}

function setBusyStatus(status, message, busy) {
    status.textContent = message;
    status.classList.toggle("is-busy", busy);
    if (busy) {
        status.setAttribute("aria-busy", "true");
    } else {
        status.removeAttribute("aria-busy");
    }
}

function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = text;
    return element;
}

function formatDate(value) {
    if (!value) return "";
    try {
        const strVal = String(value);
        const dateStr = strVal.includes("T") ? strVal : `${strVal}T00:00:00`;
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return strVal.split("T")[0];
        return new Intl.DateTimeFormat(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
        }).format(d);
    } catch {
        return String(value).split("T")[0] || "";
    }
}

function wineMetadataText(value) {
    if (typeof value === "string") return value.trim();
    if (value && typeof value === "object") {
        return value.text || value.text_long || value.en || "";
    }
    return "";
}

function wineGrapeNames(wine) {
    if (Array.isArray(wine.grape_varieties)) {
        const names = wine.grape_varieties
            .map((grape) => typeof grape === "string" ? grape : grape?.name)
            .filter(Boolean);
        if (names.length) return names.join(", ");
    }
    return wine.grape_type || "";
}

function hasGrapemindsDetails(wine) {
    return [
        wine.color,
        wine.comment,
        wine.grape_varieties,
        wine.description,
        wine.pairing,
        wine.grapeminds_tasting_notes,
        wine.flavor_profile,
    ].some((value) => {
        if (Array.isArray(value)) return value.length > 0;
        if (value && typeof value === "object") return Object.keys(value).length > 0;
        return value !== null && value !== undefined && String(value).trim() !== "";
    });
}

function grapemindsPreviewFields(metadata, getCurrentValue) {
    const fields = [
        ["name", "Wine name", metadata.name],
        ["winery", "Producer / winery", metadata.winery],
        ["vintage", "Vintage", metadata.vintage],
        ["region", "Region", metadata.region],
        ["country_of_origin", "Country", metadata.country_of_origin],
        ["color", "Color", metadata.color],
        ["market_price", "Market price / value ($)", metadata.market_price],
        ["grape_type", "Grape varieties", wineGrapeNames(metadata)],
        ["description", "Description", metadata.description],
        ["pairing", "Food pairing", metadata.pairing],
        ["grapeminds_tasting_notes", "Tasting notes", metadata.grapeminds_tasting_notes],
        ["flavor_profile", "Flavor profile", metadata.flavor_profile],
    ];
    return fields
        .map(([name, label, value]) => {
            const displayValue = name === "flavor_profile"
                ? Object.entries(value || {})
                    .map(([key, item]) => `${key.replaceAll("_", " ")}: ${item}`)
                    .join(", ")
                : name === "grape_type"
                    ? String(value || "")
                    : wineMetadataText(value) || String(value ?? "");
            if (!displayValue) return null;
            return {
                name,
                label,
                displayValue,
                currentValue: getCurrentValue(name),
                serverFields: name === "grape_type"
                    ? ["grape_type", "grape_varieties"]
                    : [name],
            };
        })
        .filter(Boolean);
}

function renderGrapemindsPreview(container, metadata, getCurrentValue, onApply) {
    container.replaceChildren();
    const headingText = [
        metadata.winery,
        metadata.name,
        metadata.vintage,
    ].filter(Boolean).join(" · ") || `Grapeminds record ${metadata.id || ""}`;
    container.append(makeElement("h4", "grapeminds-preview__heading", headingText));
    container.append(makeElement(
        "p",
        "grapeminds-preview__hint",
        "Select details to apply. Existing values start unchecked; selecting them will replace those values.",
    ));

    const fields = grapemindsPreviewFields(metadata, getCurrentValue);
    const list = makeElement("div", "grapeminds-preview__fields");
    const selection = [];
    fields.forEach((field) => {
        const row = makeElement("label", "grapeminds-preview__field");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = isBlankValue(field.currentValue);
        checkbox.addEventListener("change", () => {
            checkbox.dataset.userToggled = "true";
        });
        const title = makeElement("span", "", field.label);
        const value = makeElement("span", "grapeminds-preview__value", field.displayValue);
        row.append(checkbox, title, value);
        list.append(row);
        selection.push({ ...field, checkbox });
    });
    container.append(list);

    const actions = makeElement("div", "grapeminds-preview__actions");
    const applyButton = makeElement("button", "button button--small button--wine", "Apply selected");
    applyButton.type = "button";
    applyButton.addEventListener("click", async () => {
        const selected = selection.filter(({ checkbox, name, currentValue }) =>
            checkbox.checked && (
                checkbox.dataset.userToggled === "true" ||
                sameFieldValue(currentValue, getCurrentValue(name))
            )
        );
        applyButton.disabled = true;
        applyButton.setAttribute("aria-busy", "true");
        try {
            await onApply(selected);
            container.hidden = true;
            container.replaceChildren();
        } catch (error) {
            notify(error.message, "error");
            applyButton.disabled = false;
            applyButton.removeAttribute("aria-busy");
        }
    });
    const cancelButton = makeElement("button", "button button--small button--outline", "Cancel");
    cancelButton.type = "button";
    cancelButton.addEventListener("click", () => {
        container.hidden = true;
        container.replaceChildren();
    });
    actions.append(applyButton, cancelButton);
    container.append(actions);
    container.hidden = false;
}

function isBlankValue(value) {
    if (value === null || value === undefined || value === "") return true;
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === "object") return Object.keys(value).length === 0;
    return false;
}

function sameFieldValue(left, right) {
    return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

async function lookupWineByGrapemindsId({
    idInput,
    lookupButton,
    preview,
    status,
    lookupPath,
    getCurrentValue,
    apply,
}) {
    const grapemindsId = idInput.value.trim();
    if (!grapemindsId || !/^[A-Za-z0-9_-]{1,64}$/.test(grapemindsId)) {
        status.hidden = false;
        status.textContent = "Enter a valid Grapeminds wine ID.";
        idInput.focus();
        return;
    }

    lookupButton.disabled = true;
    lookupButton.setAttribute("aria-busy", "true");
    status.hidden = false;
    setBusyStatus(status, "Looking up this Grapeminds ID…", true);
    preview.hidden = true;
    try {
        const result = await api(lookupPath, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ grapeminds_id: grapemindsId }),
        });
        if (!["updated", "mock"].includes(result.status) || !result.metadata) {
            const httpStatus = result.status?.match(/^http_(\d+)$/)?.[1];
            const message = result.status === "quota_limit"
                ? "The Grapeminds monthly lookup limit has been reached."
                : result.status === "not_configured"
                    ? "Grapeminds lookup is not configured. Add GRAPEMINDS_API_KEY to .env, or set GRAPEMINDS_MOCK_MODE=true."
                    : result.status === "request_error"
                    ? "Grapeminds could not be reached. Your wine details are unchanged."
                    : httpStatus
                        ? `Grapeminds returned HTTP ${httpStatus}.`
                        : "No Grapeminds record was returned for that ID.";
            setBusyStatus(status, message, false);
            return;
        }

        const metadata = result.metadata;
        idInput.value = metadata.id || grapemindsId;
        setBusyStatus(status, result.status === "mock"
            ? "Mock Grapeminds record returned. Review before applying."
            : "Record found. Review each field before applying.", false);
        renderGrapemindsPreview(
            preview,
            metadata,
            getCurrentValue,
            (selected) => apply(
                idInput.value.trim(),
                metadata,
                [...new Set(selected.flatMap((field) => field.serverFields))],
                selected,
            ),
        );
    } catch (error) {
        setBusyStatus(status, `Grapeminds lookup failed: ${error.message}`, false);
    } finally {
        lookupButton.disabled = false;
        lookupButton.removeAttribute("aria-busy");
    }
}

function getLocationLabel(location) {
    if (!location) return "";
    const parent = state.locations.find((item) => item.id === location.parent_location_id);
    return [
        parent?.name,
        location.name,
        location.sub_location,
    ].filter(Boolean).join(" · ");
}

function getDescendants(parentId) {
    const children = state.locations.filter(
        (location) => location.parent_location_id === parentId,
    );
    return children.flatMap((location) => [
        location,
        ...getDescendants(location.id),
    ]);
}

function locationBottleCount(locationId) {
    const ids = new Set([locationId, ...getDescendants(locationId).map((item) => item.id)]);
    return state.wines.filter(
        (wine) => ids.has(wine.location_id) && (wine.status || "in_cellar") === "in_cellar",
    ).length;
}

function locationHasChildren(locationId) {
    return state.locations.some((location) => location.parent_location_id === locationId);
}

function renderLocationOptions() {
    const selects = [
        byId("manual-location"),
        byId("location-parent"),
        byId("location-filter"),
    ].filter(Boolean);
    const renderChildren = (parentId, depth, visited) => {
        const children = state.locations
            .filter((location) => parentId === null
                ? !location.parent_location_id
                : location.parent_location_id === parentId)
            .sort((a, b) => a.name.localeCompare(b.name) || (a.sub_location || "").localeCompare(b.sub_location || ""));
        return children.flatMap((location) => {
            if (visited.has(location.id)) return [];
            const nextVisited = new Set(visited).add(location.id);
            const label = [
                "\u00a0\u00a0".repeat(depth),
                location.name,
                location.sub_location ? ` · ${location.sub_location}` : "",
            ].join("");
            return [
                { id: location.id, label },
                ...renderChildren(location.id, depth + 1, nextVisited),
            ];
        });
    };
    const options = renderChildren(null, 0, new Set());

    selects.forEach((select) => {
        const previousValue = select.value;
        while (select.options.length > 1) select.remove(1);
        options.forEach(({ id, label }) => {
            const option = document.createElement("option");
            option.value = String(id);
            option.textContent = label;
            select.append(option);
        });
        if (options.some(({ id }) => String(id) === previousValue)) {
            select.value = previousValue;
        }
    });
}

function renderLocations() {
    const container = byId("location-list");
    container.replaceChildren();
    renderLocationOptions();
    if (state.locations.length === 0) {
        const empty = makeElement("div", "location-empty");
        empty.append(
            makeElement("span", "location-empty__icon", "⌂"),
            makeElement("span", "", "No storage locations yet"),
        );
        container.append(empty);
        return;
    }

    const roots = state.locations
        .filter((location) => !location.parent_location_id)
        .sort((a, b) => a.name.localeCompare(b.name) || (a.sub_location || "").localeCompare(b.sub_location || ""));
    const makeActions = (location) => {
        if (state.currentUser?.role !== "admin") {
            return makeElement("span", "");
        }
        const actions = makeElement("div", "location-actions");
        const edit = makeElement("button", "location-action", "Rename");
        edit.type = "button";
        edit.addEventListener("click", () => openLocationEditor(location));

        const bottleCount = locationBottleCount(location.id);
        const hasChildren = locationHasChildren(location.id);
        const remove = makeElement("button", "location-action location-action--remove", "Remove");
        remove.type = "button";
        remove.disabled = bottleCount > 0 || hasChildren;
        remove.title = bottleCount > 0
            ? "Move all bottles in this location and its child locations first."
            : hasChildren
                ? "Remove child locations first."
                : "Remove this empty location.";
        remove.addEventListener("click", () => removeLocation(location));
        actions.append(edit, remove);
        return actions;
    };
    const selectedLocId = Number(byId("location-filter")?.value || 0);
    const toggleLocationFilter = (locId) => {
        const locSelect = byId("location-filter");
        if (!locSelect) return;
        const nextVal = String(locSelect.value) === String(locId) ? "" : String(locId);
        locSelect.value = nextVal;
        renderWines();
        renderLocations();
        if (nextVal) {
            document.querySelector(".collection")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    };

    roots.forEach((root) => {
        const section = makeElement(
            "article",
            `location-card${selectedLocId === root.id ? " is-active-filter" : ""}`,
        );
        const heading = makeElement("div", "location-card__heading location-card__filter-target");
        heading.title = `Click to filter collection by ${root.name}`;
        heading.addEventListener("click", (e) => {
            if (e.target.closest(".location-actions")) return;
            toggleLocationFilter(root.id);
        });
        heading.append(
            makeElement("span", "location-card__icon", "⌂"),
            makeElement("h3", "", root.name),
        );
        if (root.sub_location) heading.append(makeElement("span", "location-card__detail", root.sub_location));
        const count = locationBottleCount(root.id);
        const children = getDescendants(root.id);
        heading.append(
            makeElement("span", "location-card__count", `${count} ${count === 1 ? "bottle" : "bottles"}`),
        );
        heading.append(makeActions(root));
        section.append(heading);
        const appendChildren = (parentId, list, depth) => {
            state.locations
                .filter((location) => location.parent_location_id === parentId)
                .sort((a, b) => a.name.localeCompare(b.name))
                .forEach((child) => {
                    const row = makeElement(
                        "li",
                        `location-card__child location-card__filter-target${selectedLocId === child.id ? " is-active-filter" : ""}`,
                    );
                    row.title = `Click to filter collection by ${child.name}${child.sub_location ? " · " + child.sub_location : ""}`;
                    row.addEventListener("click", (e) => {
                        if (e.target.closest(".location-actions")) return;
                        toggleLocationFilter(child.id);
                    });
                    const name = makeElement("span", "", child.name);
                    name.style.paddingInlineStart = `${depth * 14}px`;
                    const detail = makeElement("span", "location-card__detail", child.sub_location || "");
                    const childCount = locationBottleCount(child.id);
                    const childInfo = makeElement(
                        "span",
                        "location-card__count",
                        `${childCount} ${childCount === 1 ? "bottle" : "bottles"}`,
                    );
                    const info = makeElement("span", "location-card__child-info");
                    info.append(detail, childInfo);
                    row.append(name, info, makeActions(child));
                    list.append(row);
                    appendChildren(child.id, list, depth + 1);
                });
        };
        if (children.length) {
            const list = makeElement("ul", "location-card__children");
            appendChildren(root.id, list, 0);
            section.append(list);
        }
        container.append(section);
    });

    state.locations
        .filter((location) => location.parent_location_id > 0
            && !state.locations.some((item) => item.id === location.parent_location_id))
        .forEach((orphan) => {
            const section = makeElement("article", "location-card");
            section.append(makeElement("h3", "", orphan.name));
            container.append(section);
        });
}

function openLocationEditor(location) {
    if (state.currentUser?.role !== "admin") {
        notify("Only the cellar administrator can rename storage locations.", "warn");
        return;
    }
    state.editingLocationId = location.id;
    const form = byId("location-form");
    form.elements.name.value = location.name;
    form.elements.sub_location.value = location.sub_location || "";
    byId("location-parent").closest("label").hidden = true;
    byId("location-dialog").querySelector(".dialog__head h2").textContent = "Rename a location.";
    byId("location-submit").textContent = "Save changes";
    byId("location-dialog").showModal();
}

function openLocationCreator() {
    if (state.currentUser?.role !== "admin") {
        notify("Only the cellar administrator can add storage locations.", "warn");
        return;
    }
    state.editingLocationId = null;
    const form = byId("location-form");
    form.reset();
    byId("location-parent").closest("label").hidden = false;
    byId("location-dialog").querySelector(".dialog__head h2").textContent = "Add a location.";
    byId("location-submit").textContent = "Save location";
    renderLocationOptions();
    byId("location-dialog").showModal();
}

async function removeLocation(location) {
    if (locationBottleCount(location.id) > 0 || locationHasChildren(location.id)) {
        notify("Move bottles and remove child locations before removing this location.", "error");
        return;
    }
    if (!window.confirm(`Remove “${location.name}”? This cannot be undone.`)) return;
    try {
        await api(`/locations/${location.id}`, { method: "DELETE" });
        await Promise.all([loadLocations(), loadWines()]);
        notify("Location removed.");
    } catch (error) {
        notify(error.message, "error");
    }
}

function visibleWines() {
    const query = byId("search").value.trim().toLowerCase();
    const status = byId("status-filter").value;
    const sort = byId("sort-order").value;
    const colorFilter = byId("color-filter")?.value || "";
    const locationFilterRaw = byId("location-filter")?.value || "";
    const allowedLocationIds = locationFilterRaw
        ? new Set([
            Number(locationFilterRaw),
            ...getDescendants(Number(locationFilterRaw)).map((item) => item.id),
        ])
        : null;

    return state.wines
        .filter((wine) => {
            const wineStatus = wine.status || "in_cellar";
            return (
                status === "all" ||
                (status === "in_cellar" && wineStatus === "in_cellar") ||
                (status === "removed" && wineStatus !== "in_cellar") ||
                wineStatus === status
            );
        })
        .filter((wine) => {
            if (!colorFilter) return true;
            return wineTypeCategory(wine) === colorFilter;
        })
        .filter((wine) => {
            if (!allowedLocationIds) return true;
            return allowedLocationIds.has(Number(wine.location_id));
        })
        .filter((wine) => {
            if (!query) return true;
            const personalNotes = (wine.tasting_notes || [])
                .map((note) => [note.notes, note.author_name].filter(Boolean).join(" "))
                .join(" ");
            const searchable = [
                wine.name,
                wine.winery,
                wine.vintage,
                wine.region,
                wine.country_of_origin,
                wineGrapeNames(wine),
                wine.color,
                wine.comment,
                wine.grapeminds_id,
                wine.qr_id,
                getLocationLabel(wine.location),
                wineMetadataText(wine.pairing),
                wineMetadataText(wine.grapeminds_tasting_notes),
                wineMetadataText(wine.description),
                personalNotes,
            ].filter(Boolean).join(" ").toLowerCase();
            const tokens = query.split(/\s+/).filter(Boolean);
            return tokens.every((token) => searchable.includes(token));
        })
        .sort((a, b) => {
            const nameA = `${a.winery || ""} ${a.name || ""}`.toLowerCase();
            const nameB = `${b.winery || ""} ${b.name || ""}`.toLowerCase();
            return sort === "name" ? nameA.localeCompare(nameB) : b.id - a.id;
        });
}


function getSearchMatchSnippet(winesOrBottle) {
    const rawQuery = (byId("search")?.value || "").trim().toLowerCase();
    if (!rawQuery) return null;
    const bottles = Array.isArray(winesOrBottle) ? winesOrBottle : [winesOrBottle];
    const sample = bottles[0];
    if (!sample) return null;

    const primaryText = [
        sample.name,
        sample.winery,
        sample.vintage,
        sample.region,
        sample.country_of_origin,
        wineGrapeNames(sample),
        sample.color,
        ...bottles.map((b) => b.qr_id),
        ...bottles.map((b) => (b.location ? getLocationLabel(b.location) : "")),
    ].filter(Boolean).join(" ").toLowerCase();

    const tokens = rawQuery.split(/\s+/).filter(Boolean);
    const unmatchedInPrimary = tokens.filter((t) => !primaryText.includes(t));
    const searchTokens = unmatchedInPrimary.length ? unmatchedInPrimary : tokens;

    const extractAround = (text, token) => {
        const clean = String(text || "").replace(/\s+/g, " ").trim();
        const idx = clean.toLowerCase().indexOf(token);
        if (idx === -1) return null;
        const start = Math.max(0, idx - 28);
        const end = Math.min(clean.length, idx + token.length + 42);
        return `${start > 0 ? "…" : ""}${clean.slice(start, end).trim()}${end < clean.length ? "…" : ""}`;
    };

    const pairingText = wineMetadataText(sample.pairing);
    for (const token of searchTokens) {
        const hit = extractAround(pairingText, token);
        if (hit) return { label: "🍽 Pairing", snippet: hit };
    }

    const tastingText = [
        wineMetadataText(sample.grapeminds_tasting_notes),
        ...bottles.flatMap((b) => (b.tasting_notes || []).map((n) => n.notes)),
    ].filter(Boolean).join(" · ");
    for (const token of searchTokens) {
        const hit = extractAround(tastingText, token);
        if (hit) return { label: "📝 Tasting note", snippet: hit };
    }

    const descText = wineMetadataText(sample.description);
    for (const token of searchTokens) {
        const hit = extractAround(descText, token);
        if (hit) return { label: "📖 Description", snippet: hit };
    }

    return null;
}

function stableValue(value) {
    if (Array.isArray(value)) return value.map(stableValue);
    if (value && typeof value === "object") {
        return Object.fromEntries(
            Object.keys(value).sort().map((key) => [key, stableValue(value[key])]),
        );
    }
    return value ?? null;
}

function wineIdentityKey(wine) {
    const identityFields = [
        "name",
        "winery",
        "vintage",
        "region",
        "country_of_origin",
        "grape_type",
        "grape_varieties",
        "color",
        "description",
        "pairing",
        "grapeminds_tasting_notes",
        "flavor_profile",
        "grapeminds_id",
    ];
    return JSON.stringify([
        ...identityFields.map((field) =>
            field === "color"
                ? (String(wine.color || "").trim().toLowerCase() || null)
                : stableValue(wine[field])
        ),
    ]);
}

function groupWines(wines) {
    const groups = new Map();
    wines.forEach((wine) => {
        const key = wineIdentityKey(wine);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(wine);
    });
    return [...groups.values()].map((group) =>
        group.sort((a, b) => a.qr_id.localeCompare(b.qr_id))
    );
}

function matchingWineGroup(wine) {
    const identity = wineIdentityKey(wine);
    return state.wines
        .filter((candidate) => wineIdentityKey(candidate) === identity)
        .sort((a, b) => a.qr_id.localeCompare(b.qr_id));
}

function getDrinkingWindowInfo(wine) {
    const fromYear = wine.drink_from ? Number(wine.drink_from) : null;
    const untilYear = wine.drink_until ? Number(wine.drink_until) : null;
    if (!fromYear && !untilYear) return null;

    const currentYear = new Date().getFullYear();
    let rangeText = "";
    if (fromYear && untilYear) {
        rangeText = fromYear === untilYear ? `${fromYear}` : `${fromYear}–${untilYear}`;
    } else if (fromYear) {
        rangeText = `from ${fromYear}`;
    } else {
        rangeText = `until ${untilYear}`;
    }

    let stateKey = "ready";
    let label = "Ready to drink";
    let sortRank = 2; // 1 = Past peak / Drink soon, 2 = Ready to drink, 3 = Hold

    if (fromYear && currentYear < fromYear) {
        stateKey = "hold";
        label = "Hold";
        sortRank = 3;
    } else if (untilYear && currentYear > untilYear) {
        stateKey = "past-peak";
        label = "Past peak";
        sortRank = 0;
    } else if (untilYear && untilYear - currentYear <= 1) {
        stateKey = "drink-soon";
        label = "Drink soon";
        sortRank = 1;
    }

    return {
        fromYear,
        untilYear,
        rangeText,
        stateKey,
        label,
        badgeText: `${label} · ${rangeText}`,
        sortRank,
        sortYear: untilYear || fromYear || 9999,
    };
}

function normalizeWineColor(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    const lower = raw.toLowerCase().replace("é", "e");
    if (lower.startsWith("red") || lower === "rouge" || lower === "tinto") return "Red";
    if (lower.startsWith("white") || lower === "blanc" || lower === "blanco") return "White";
    if (lower.startsWith("rose") || lower.startsWith("rosado") || lower.startsWith("blush")) return "Rosé";
    if (lower.includes("sparkling") || lower.includes("champagne") || lower.includes("prosecco") || lower.includes("cava")) return "Sparkling";
    if (lower.includes("dessert") || lower.includes("fortified") || lower.includes("port") || lower.includes("sherry")) return "Dessert";
    if (lower.startsWith("orange") || lower.includes("skin contact")) return "Orange";
    return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function wineTypeCategory(wine) {
    const normalized = normalizeWineColor(wine.color).toLowerCase();
    if (normalized === "red") return "red";
    if (normalized === "white") return "white";
    if (normalized === "rosé") return "rose";
    if (normalized === "sparkling") return "sparkling";
    if (normalized === "dessert") return "dessert";
    if (normalized === "orange") return "orange";
    return "other";
}

function renderActiveFiltersBar() {
    const bar = byId("active-filters-bar");
    if (!bar) return;
    bar.replaceChildren();

    const colorFilter = byId("color-filter")?.value || "";
    const locationFilterId = Number(byId("location-filter")?.value || 0);
    const searchQuery = byId("search")?.value.trim() || "";

    const pills = [];
    if (colorFilter) {
        const labels = {
            red: "Red",
            white: "White",
            rose: "Rosé",
            sparkling: "Sparkling",
            dessert: "Dessert",
            orange: "Orange",
        };
        const pill = makeElement("button", "active-filter-pill", `Color: ${labels[colorFilter] || colorFilter} ×`);
        pill.type = "button";
        pill.addEventListener("click", () => {
            byId("color-filter").value = "";
            renderWines();
        });
        pills.push(pill);
    }

    if (locationFilterId) {
        const locObj = state.locations.find((item) => item.id === locationFilterId);
        const locLabel = locObj ? getLocationLabel(locObj) : `Location #${locationFilterId}`;
        const pill = makeElement("button", "active-filter-pill", `⌂ ${locLabel} ×`);
        pill.type = "button";
        pill.addEventListener("click", () => {
            byId("location-filter").value = "";
            renderWines();
            renderLocations();
        });
        pills.push(pill);
    }

    if (searchQuery) {
        const pill = makeElement("button", "active-filter-pill", `Search: "${searchQuery}" ×`);
        pill.type = "button";
        pill.addEventListener("click", () => {
            byId("search").value = "";
            renderWines();
        });
        pills.push(pill);
    }

    if (pills.length === 0) {
        bar.hidden = true;
        return;
    }

    bar.hidden = false;
    bar.append(makeElement("span", "active-filters-bar__label", "Active filters:"));
    pills.forEach((p) => bar.append(p));

    if (pills.length > 1) {
        const clearAll = makeElement("button", "text-button active-filters-bar__clear", "Clear all");
        clearAll.type = "button";
        clearAll.addEventListener("click", () => {
            byId("search").value = "";
            if (byId("color-filter")) byId("color-filter").value = "";
            if (byId("location-filter")) byId("location-filter").value = "";
            renderWines();
            renderLocations();
        });
        bar.append(clearAll);
    }
}

function syncInteractiveMetricCards() {
    const activeColor = byId("color-filter")?.value || "";
    const activeLocation = byId("location-filter")?.value || "";
    const status = byId("status-filter")?.value || "in_cellar";

    byId("metric-card-all")?.classList.toggle(
        "is-active",
        !activeColor && !activeLocation && status === "in_cellar",
    );
    ["red", "white", "rose"].forEach((cat) => {
        byId(`metric-card-${cat}`)?.classList.toggle("is-active", activeColor === cat);
    });
}

function renderMetrics() {
    const inCellar = state.wines.filter((wine) => (wine.status || "in_cellar") === "in_cellar");
    const vintages = new Set(inCellar.map((wine) => wine.vintage).filter(Boolean));
    byId("metric-total").textContent = String(inCellar.length).padStart(2, "0");
    ["red", "white", "rose"].forEach((category) => {
        const count = inCellar.filter((wine) => wineTypeCategory(wine) === category).length;
        const el = byId(`metric-${category}`);
        if (el) el.textContent = String(count).padStart(2, "0");
    });
    byId("metric-vintages").textContent = String(vintages.size).padStart(2, "0");
    byId("metric-notes").textContent = String(
        state.wines.reduce((sum, wine) => sum + (wine.tasting_notes || []).length, 0),
    ).padStart(2, "0");
    syncInteractiveMetricCards();
    renderActiveFiltersBar();
}

function renderWineCard(wines) {
    const wine = wines[0];
    const card = makeElement("article", "wine-card");
    const top = makeElement("div", "wine-card__top");
    const emblem = makeElement("div", "wine-card__emblem", "W");
    emblem.setAttribute("aria-hidden", "true");
    const title = makeElement("div", "wine-card__title");
    title.append(
        makeElement("h3", "", wine.name || "Untitled wine"),
        makeElement("p", "", wine.winery || "Producer not recorded"),
    );
    top.append(emblem, title);

    const quantity = makeElement(
        "span",
        "wine-card__quantity",
        `${wines.length} ${wines.length === 1 ? "bottle" : "bottles"}`,
    );
    const statuses = new Map();
    wines.forEach((bottle) => {
        const status = bottle.status || "in_cellar";
        statuses.set(status, (statuses.get(status) || 0) + 1);
    });
    const statusBadges = makeElement("div", "wine-card__statuses");
    statuses.forEach((count, status) => {
        const label = status === "in_cellar" ? "in cellar" : "checked out";
        statusBadges.append(makeElement(
            "span",
            `status-pill status-pill--${status}`,
            `${label} · ${count}`,
        ));
    });
    top.append(quantity, statusBadges);

    const details = makeElement("div", "wine-card__details");
    const vintage = wine.vintage ? String(wine.vintage) : "NV";
    details.append(
        makeElement("span", "wine-card__vintage", vintage),
        makeElement("span", "", wine.region || "Region unknown"),
    );
    if (wine.country_of_origin) {
        details.append(makeElement("span", "", wine.country_of_origin));
    }
    if (wine.color) {
        const normalizedColor = normalizeWineColor(wine.color);
        const colorCat = wineTypeCategory(wine);
        details.append(
            makeElement(
                "span",
                `wine-card__color wine-card__color--${colorCat}`,
                normalizedColor,
            ),
        );
    }
    const windowInfo = getDrinkingWindowInfo(wine);
    if (windowInfo) {
        details.append(
            makeElement(
                "span",
                `drinking-window-badge drinking-window-badge--${windowInfo.stateKey}`,
                windowInfo.badgeText,
            ),
        );
    }
    const uniqueLocations = [
        ...new Set(
            wines
                .map((b) => (b.location ? getLocationLabel(b.location) : ""))
                .filter(Boolean),
        ),
    ];
    if (uniqueLocations.length === 1) {
        details.append(makeElement("span", "wine-card__location", `⌂ ${uniqueLocations[0]}`));
    } else if (uniqueLocations.length > 1) {
        details.append(makeElement("span", "wine-card__location", `⌂ ${uniqueLocations.join(" / ")}`));
    }
    const grape = makeElement(
        "p",
        "wine-card__grape",
        wineGrapeNames(wine) || "Grape variety not recorded",
    );
    const uniqueComments = [...new Set(wines.map((b) => (b.comment || "").trim()).filter(Boolean))];
    const sharedComment = uniqueComments.length === 1 && wines.every((b) => (b.comment || "").trim() === uniqueComments[0])
        ? uniqueComments[0]
        : null;
    const commentEl = sharedComment
        ? makeElement("p", "wine-card__comment", sharedComment)
        : null;
    const groupActions = makeElement("div", "wine-group-actions");
    const fullGroup = matchingWineGroup(wine);
    const activeInGroup = fullGroup.filter((b) => (b.status || "in_cellar") === "in_cellar");
    if (activeInGroup.length > 0) {
        const groupCheckoutButton = makeElement(
            "button",
            "text-button bottle-row__open",
            "Check out bottle 🍷",
        );
        groupCheckoutButton.type = "button";
        groupCheckoutButton.addEventListener("click", () => {
            if (activeInGroup.length === 1) {
                openCheckoutDialog({ bottle: activeInGroup[0], groupBottles: activeInGroup });
            } else {
                openCheckoutDialog({ bottle: null, groupBottles: activeInGroup });
            }
        });
        groupActions.append(groupCheckoutButton);
    }
    const groupEditButton = makeElement(
        "button",
        "text-button",
        fullGroup.length > 1 ? `Edit all ${fullGroup.length} bottles` : "Edit wine details",
    );
    groupEditButton.type = "button";
    groupEditButton.addEventListener("click", () => openWineEditor(fullGroup, true));
    groupActions.append(groupEditButton);
    const bottleList = document.createElement("details");
    bottleList.className = "bottle-list";
    const bottleSummary = makeElement(
        "summary",
        "",
        `Bottle IDs · ${wines.length}`,
    );
    bottleList.append(bottleSummary);

    wines.forEach((bottle) => {
        const row = makeElement("div", "bottle-row");
        const identity = makeElement("div", "bottle-row__identity");
        identity.append(
            makeElement("strong", "", bottle.qr_id),
            makeElement(
                "span",
                "",
                bottle.location ? `⌂ ${getLocationLabel(bottle.location)}` : "No storage location",
            ),
        );
        if (bottle.checkout_date && (bottle.status || "in_cellar") !== "in_cellar") {
            identity.append(makeElement("span", "bottle-row__checkout", `· Checked out ${formatDate(bottle.checkout_date)}`));
        }
        if (bottle.comment) {
            identity.append(makeElement("span", "bottle-row__comment", `· ${bottle.comment}`));
        }
        const actions = makeElement("div", "bottle-row__actions");
        const detailsButton = makeElement("button", "text-button", "Wine details");
        detailsButton.type = "button";
        detailsButton.setAttribute("aria-expanded", "false");
        detailsButton.addEventListener("click", () => toggleWineDetails(bottle, row, detailsButton));
        const editButton = makeElement("button", "text-button", "Edit bottle");
        editButton.type = "button";
        editButton.addEventListener("click", () => openWineEditor([bottle], false));

        if ((bottle.status || "in_cellar") === "in_cellar") {
            const openButton = makeElement("button", "text-button bottle-row__open", "Check out 🍷");
            openButton.type = "button";
            openButton.setAttribute("aria-label", `Check out bottle ${bottle.qr_id}`);
            openButton.addEventListener("click", () => openCheckoutDialog({ bottle, groupBottles: activeInGroup }));
            actions.append(openButton);
        } else {
            const returnButton = makeElement("button", "text-button", "Return to cellar");
            returnButton.type = "button";
            returnButton.setAttribute("aria-label", `Return bottle ${bottle.qr_id} to cellar`);
            returnButton.addEventListener("click", () => updateStatus(bottle, "in_cellar"));
            actions.append(returnButton);
        }

        const tastingCount = (bottle.tasting_notes || []).length;
        const notesButton = makeElement(
            "button",
            "text-button",
            tastingCount
                ? `${tastingCount} tasting ${tastingCount === 1 ? "note" : "notes"}`
                : "Add a tasting note",
        );
        notesButton.type = "button";
        notesButton.addEventListener("click", () => toggleTastingPanel(bottle, row));

        actions.append(detailsButton, editButton, notesButton);
        if (state.currentUser?.role === "admin") {
            const deleteButton = makeElement("button", "text-button bottle-row__delete", "Delete");
            deleteButton.type = "button";
            deleteButton.setAttribute("aria-label", `Permanently delete bottle ${bottle.qr_id}`);
            deleteButton.addEventListener("click", () => deleteBottle(bottle, deleteButton));
            actions.append(deleteButton);
        }
        row.append(identity, actions);
        bottleList.append(row);
    });

    card.append(top, details, grape);
    if (commentEl) card.append(commentEl);
    const matchInfo = getSearchMatchSnippet(wines);
    if (matchInfo) {
        const matchEl = makeElement("p", "wine-card__search-match");
        matchEl.append(
            makeElement("strong", "", `${matchInfo.label}: `),
            makeElement("span", "", matchInfo.snippet),
        );
        card.append(matchEl);
    }
    card.append(groupActions, bottleList);
    return card;
}

function toggleWineDetails(wine, card, button) {
    const existing = card.querySelector(".wine-metadata");
    if (existing) {
        existing.remove();
        button.setAttribute("aria-expanded", "false");
        return;
    }

    const panel = makeElement("section", "wine-metadata");
    const sections = [
        ["Grapeminds ID", wine.grapeminds_id],
        ["Color", wine.color],
        ["Drinking window", getDrinkingWindowInfo(wine)?.badgeText || ""],
        ["Market price / value", wine.market_price != null ? `$${Number(wine.market_price).toFixed(2)}` : ""],
        ["Purchase price", wine.purchase_price != null ? `$${Number(wine.purchase_price).toFixed(2)}` : ""],
        ["Country of origin", wine.country_of_origin],
        ["Grape varieties", wineGrapeNames(wine)],
        ["Checkout date", wine.checkout_date ? formatDate(wine.checkout_date) : ""],
        ["Comment", wine.comment],
        ["Description", wineMetadataText(wine.description)],
        ["Food pairing", wineMetadataText(wine.pairing)],
        ["Grapeminds tasting notes", wineMetadataText(wine.grapeminds_tasting_notes)],
    ];
    sections.forEach(([heading, value]) => {
        if (!value) return;
        const section = makeElement("div", "wine-metadata__section");
        section.append(makeElement("h4", "", heading), makeElement("p", "", value));
        panel.append(section);
    });

    if (wine.photo_path) {
        const photoSection = makeElement("div", "wine-metadata__section");
        photoSection.append(makeElement("h4", "", "Bottle label"));
        const img = document.createElement("img");
        img.className = "wine-metadata__label-image";
        img.src = `/wine-labels/${encodeURIComponent(wine.photo_path)}`;
        img.alt = `Label for ${wine.name || "wine"}`;
        img.loading = "lazy";
        photoSection.append(img);
        panel.append(photoSection);
    }

    const profile = wine.flavor_profile;
    if (profile && typeof profile === "object") {
        const entries = Object.entries(profile).filter(([, value]) => Number.isFinite(Number(value)));
        if (entries.length) {
            const section = makeElement("div", "wine-metadata__section");
            section.append(makeElement("h4", "", "Flavor profile"));
            const bars = makeElement("div", "flavor-profile");
            entries.forEach(([name, rawValue]) => {
                const value = Math.max(0, Math.min(10, Number(rawValue)));
                const row = makeElement("div", "flavor-profile__row");
                const label = makeElement("span", "", name.replaceAll("_", " "));
                const track = makeElement("span", "flavor-profile__track");
                const fill = makeElement("span", "flavor-profile__fill");
                fill.style.width = `${value * 10}%`;
                track.append(fill);
                row.append(label, track, makeElement("strong", "", String(rawValue)));
                bars.append(row);
            });
            section.append(bars);
            panel.append(section);
        }
    }

    if (!hasGrapemindsDetails(wine)) {
        panel.append(makeElement("p", "wine-metadata__empty", "No additional Grapeminds details are available for this bottle."));
    }
    const lookup = makeElement("div", "wine-metadata__grapeminds");
    const idLabel = document.createElement("label");
    idLabel.append(document.createTextNode("Grapeminds wine ID"));
    const idInput = document.createElement("input");
    idInput.type = "text";
    idInput.maxLength = 64;
    idInput.pattern = "[A-Za-z0-9_-]+";
    idInput.value = wine.grapeminds_id || "";
    idInput.placeholder = "Enter an ID you already know";
    idLabel.append(idInput);
    const lookupButton = makeElement(
        "button",
        "button button--small button--outline",
        "Look up by ID",
    );
    lookupButton.type = "button";
    const preview = makeElement("div", "grapeminds-preview");
    preview.hidden = true;
    const status = makeElement("p", "form-hint");
    status.hidden = true;
    lookupButton.addEventListener("click", () => lookupWineByGrapemindsId({
        idInput,
        lookupButton,
        preview,
        status,
        lookupPath: `/wines/${encodeURIComponent(wine.qr_id)}/enrichment/lookup`,
        getCurrentValue: (name) => name === "grape_type"
            ? wineGrapeNames(wine)
            : wine[name],
        apply: async (grapemindsId, metadata, selectedFields) => {
            const updated = await api(
                `/wines/${encodeURIComponent(wine.qr_id)}/enrichment/apply`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        grapeminds_id: grapemindsId,
                        metadata,
                        selected_fields: selectedFields,
                    }),
                },
            );
            Object.assign(wine, updated);
            const wineIndex = state.wines.findIndex((item) => item.qr_id === wine.qr_id);
            if (wineIndex !== -1) state.wines[wineIndex] = wine;
            renderWines();
            notify("Selected Grapeminds details saved.");
        },
    }));
    lookup.append(idLabel, lookupButton, preview, status);
    panel.append(lookup);
    card.append(panel);
    button.setAttribute("aria-expanded", "true");
}

function toggleTastingPanel(wine, card) {
    const existing = card.querySelector(".tasting-panel");
    if (existing) {
        existing.remove();
        return;
    }

    const panel = makeElement("section", "tasting-panel");
    const heading = makeElement("h4", "", "Tasting journal");
    panel.append(heading);
    (wine.tasting_notes || []).forEach((note) => {
        const noteLine = makeElement("p", "tasting-panel__note");
        let headerText = formatDate(note.tasting_date) || "Tasting note";
        if (note.author_name) {
            headerText += ` · ${note.author_name}`;
        }
        const date = makeElement("strong", "", headerText);
        const text = makeElement("span", "", note.notes || "No note added.");
        noteLine.append(date, text);
        panel.append(noteLine);
    });

    const form = document.createElement("form");
    form.className = "tasting-form";
    const input = document.createElement("textarea");
    input.name = "notes";
    input.rows = 2;
    input.maxLength = 1000;
    input.placeholder = "Aroma, structure, and what stood out…";
    input.required = true;
    const submit = makeElement("button", "button button--small button--outline", "Save note");
    submit.type = "submit";
    form.append(input, submit);
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        try {
            await api(`/wines/${encodeURIComponent(wine.qr_id)}/tasting-notes`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ notes: input.value.trim() }),
            });
            await loadWines();
            notify("Tasting note saved.");
        } catch (error) {
            notify(error.message, "error");
            submit.disabled = false;
        }
    });
    panel.append(form);
    card.append(panel);
}

function getBottleTableSortValue(bottle, column) {
    switch (column) {
        case "qr_id":
            return String(bottle.qr_id || "");
        case "name":
            return String(bottle.name || "");
        case "winery":
            return String(bottle.winery || "");
        case "vintage":
            return bottle.vintage ? Number(bottle.vintage) : 0;
        case "region":
            return String(bottle.region || "");
        case "country_of_origin":
            return String(bottle.country_of_origin || "");
        case "color":
            return String(bottle.color || "");
        case "drinking_window": {
            const info = getDrinkingWindowInfo(bottle);
            if (!info) return 999999;
            return info.sortRank * 10000 + info.sortYear;
        }
        case "location":
            return bottle.location ? String(getLocationLabel(bottle.location) || "") : "";
        case "comment": {
            const statusText = (bottle.status || "in_cellar") === "in_cellar"
                ? "In cellar"
                : `Checked out ${bottle.checkout_date || ""}`;
            return `${bottle.comment || ""} ${statusText}`.trim();
        }
        default:
            return String(bottle[column] || "");
    }
}

function sortBottlesForTable(wines) {
    const col = state.tableSortColumn || "qr_id";
    const dir = state.tableSortDirection === "desc" ? -1 : 1;
    return [...wines].sort((a, b) => {
        const valA = getBottleTableSortValue(a, col);
        const valB = getBottleTableSortValue(b, col);

        if (typeof valA === "number" && typeof valB === "number") {
            if (valA !== valB) return (valA - valB) * dir;
        } else {
            const strA = String(valA).trim();
            const strB = String(valB).trim();
            if (!strA && strB) return 1;
            if (strA && !strB) return -1;
            const cmp = strA.localeCompare(strB, undefined, { numeric: true, sensitivity: "base" });
            if (cmp !== 0) return cmp * dir;
        }
        return String(a.qr_id || "").localeCompare(String(b.qr_id || ""), undefined, { numeric: true });
    });
}

function buildEmptyCollectionState() {
    const empty = makeElement("div", "empty-state");
    empty.append(
        makeElement("div", "empty-state__mark", "✳"),
        makeElement("h3", "", state.wines.length ? "No bottles match this view" : "Your cellar starts here"),
        makeElement(
            "p",
            "",
            state.wines.length
                ? "Try another search or status filter."
                : "Add your first bottle or scan a label to begin your collection.",
        ),
    );
    const add = makeElement("button", "button button--wine", state.wines.length ? "Clear search" : "Add your first bottle");
    add.type = "button";
    add.addEventListener("click", () => {
        if (state.wines.length) {
            byId("search").value = "";
            if (byId("color-filter")) byId("color-filter").value = "";
            if (byId("location-filter")) byId("location-filter").value = "";
            byId("status-filter").value = "in_cellar";
            renderWines();
            renderLocations();
        } else {
            openDialog("manual");
        }
    });
    empty.append(add);
    return empty;
}

function renderWineTable(wines) {
    const tableWrap = byId("wine-table-wrap");
    if (!tableWrap) return;
    tableWrap.replaceChildren();

    if (wines.length === 0) {
        tableWrap.append(buildEmptyCollectionState());
        return;
    }

    const columns = [
        { key: "qr_id", label: "ID" },
        { key: "name", label: "Wine Name" },
        { key: "winery", label: "Producer" },
        { key: "vintage", label: "Vintage" },
        { key: "region", label: "Region" },
        { key: "country_of_origin", label: "Country" },
        { key: "color", label: "Color" },
        { key: "drinking_window", label: "Drinking Window" },
        { key: "location", label: "Location" },
        { key: "comment", label: "Comment / Status" },
    ];

    const table = makeElement("table", "collection-table");
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    columns.forEach((col) => {
        const th = document.createElement("th");
        th.scope = "col";
        const isActive = state.tableSortColumn === col.key;
        th.setAttribute(
            "aria-sort",
            isActive ? (state.tableSortDirection === "asc" ? "ascending" : "descending") : "none",
        );

        const sortBtn = makeElement("button", `collection-table__sort${isActive ? " is-sorted" : ""}`);
        sortBtn.type = "button";
        const labelSpan = makeElement("span", "", col.label);
        const arrow = isActive ? (state.tableSortDirection === "asc" ? "▲" : "▼") : "↕";
        const iconSpan = makeElement("span", "collection-table__sort-icon", arrow);
        iconSpan.setAttribute("aria-hidden", "true");
        sortBtn.append(labelSpan, iconSpan);

        sortBtn.addEventListener("click", () => {
            if (state.tableSortColumn === col.key) {
                state.tableSortDirection = state.tableSortDirection === "asc" ? "desc" : "asc";
            } else {
                state.tableSortColumn = col.key;
                state.tableSortDirection = "asc";
            }
            try {
                localStorage.setItem("wineCellar.tableSortColumn", state.tableSortColumn);
                localStorage.setItem("wineCellar.tableSortDirection", state.tableSortDirection);
            } catch (_) {
                // Ignore storage errors
            }
            renderWines();
        });

        th.append(sortBtn);
        headerRow.append(th);
    });

    const actionsTh = makeElement("th", "collection-table__actions-head", "Actions");
    actionsTh.scope = "col";
    headerRow.append(actionsTh);
    thead.append(headerRow);
    table.append(thead);

    const tbody = document.createElement("tbody");
    const sortedBottles = sortBottlesForTable(wines);
    const totalColSpan = columns.length + 1;

    sortedBottles.forEach((bottle) => {
        const tr = makeElement("tr", "collection-table__row");

        const tdId = makeElement("td", "collection-table__id");
        tdId.append(makeElement("strong", "", bottle.qr_id));

        const tdName = makeElement("td", "collection-table__name");
        tdName.append(makeElement("span", "collection-table__name-title", bottle.name || "Untitled wine"));
        const rowMatch = getSearchMatchSnippet(bottle);
        if (rowMatch) {
            const matchSub = makeElement("small", "collection-table__search-match");
            matchSub.append(
                makeElement("strong", "", `${rowMatch.label}: `),
                makeElement("span", "", rowMatch.snippet),
            );
            tdName.append(matchSub);
        }
        const tdProducer = makeElement("td", "", bottle.winery || "—");
        const tdVintage = makeElement("td", "collection-table__vintage", bottle.vintage ? String(bottle.vintage) : "NV");
        const tdRegion = makeElement("td", "", bottle.region || "—");
        const tdCountry = makeElement("td", "", bottle.country_of_origin || "—");

        const tdColor = makeElement("td", "");
        if (bottle.color) {
            const normalizedColor = normalizeWineColor(bottle.color);
            const colorCat = wineTypeCategory(bottle);
            tdColor.append(
                makeElement(
                    "span",
                    `wine-card__color wine-card__color--${colorCat}`,
                    normalizedColor,
                ),
            );
        } else {
            tdColor.textContent = "—";
        }

        const tdWindow = makeElement("td", "collection-table__window");
        const winInfo = getDrinkingWindowInfo(bottle);
        if (winInfo) {
            tdWindow.append(
                makeElement(
                    "span",
                    `drinking-window-badge drinking-window-badge--${winInfo.stateKey}`,
                    winInfo.badgeText,
                ),
            );
        } else {
            tdWindow.textContent = "—";
        }

        const tdLocation = makeElement(
            "td",
            "collection-table__location",
            bottle.location ? `⌂ ${getLocationLabel(bottle.location)}` : "—",
        );

        const tdComment = makeElement("td", "collection-table__comment");
        const bottleStatus = bottle.status || "in_cellar";
        if (bottleStatus !== "in_cellar") {
            const pillText = bottle.checkout_date
                ? `Checked out ${formatDate(bottle.checkout_date)}`
                : "Checked out";
            tdComment.append(makeElement("span", `status-pill status-pill--${bottleStatus}`, pillText));
        }
        if (bottle.comment) {
            tdComment.append(makeElement("span", "collection-table__comment-text", bottle.comment));
        }
        if (bottleStatus === "in_cellar" && !bottle.comment) {
            tdComment.textContent = "—";
        }

        const expandRow = makeElement("tr", "collection-table__expand-row");
        expandRow.hidden = true;
        const expandCell = document.createElement("td");
        expandCell.colSpan = totalColSpan;
        expandCell.className = "collection-table__expand-cell";
        expandRow.append(expandCell);

        const syncExpandRow = () => {
            expandRow.hidden = expandCell.children.length === 0;
        };

        const tdActions = makeElement("td", "collection-table__actions");
        const actionWrap = makeElement("div", "collection-table__action-buttons");

        const editButton = makeElement("button", "text-button", "Edit");
        editButton.type = "button";
        editButton.title = `Edit bottle ${bottle.qr_id}`;
        editButton.addEventListener("click", () => openWineEditor([bottle], false));
        actionWrap.append(editButton);

        const fullGroup = matchingWineGroup(bottle);
        if (fullGroup.length > 1) {
            const groupEditBtn = makeElement(
                "button",
                "text-button",
                `Edit group (${fullGroup.length})`,
            );
            groupEditBtn.type = "button";
            groupEditBtn.title = `Edit shared details across all ${fullGroup.length} bottles of this wine`;
            groupEditBtn.addEventListener("click", () => openWineEditor(fullGroup, true));
            actionWrap.append(groupEditBtn);
        }
        const activeInGroup = fullGroup.filter((b) => (b.status || "in_cellar") === "in_cellar");
        if (bottleStatus === "in_cellar") {
            const checkoutButton = makeElement("button", "text-button bottle-row__open", "Check out 🍷");
            checkoutButton.type = "button";
            checkoutButton.title = `Check out bottle ${bottle.qr_id}`;
            checkoutButton.addEventListener("click", () => openCheckoutDialog({ bottle, groupBottles: activeInGroup }));
            actionWrap.append(checkoutButton);
        } else {
            const returnButton = makeElement("button", "text-button", "Return to cellar");
            returnButton.type = "button";
            returnButton.addEventListener("click", () => updateStatus(bottle, "in_cellar"));
            actionWrap.append(returnButton);
        }

        const detailsButton = makeElement("button", "text-button", "Details");
        detailsButton.type = "button";
        detailsButton.setAttribute("aria-expanded", "false");
        detailsButton.addEventListener("click", () => {
            toggleWineDetails(bottle, expandCell, detailsButton);
            syncExpandRow();
        });
        actionWrap.append(detailsButton);

        const tastingCount = (bottle.tasting_notes || []).length;
        const notesButton = makeElement(
            "button",
            "text-button",
            tastingCount ? `Notes (${tastingCount})` : "Notes",
        );
        notesButton.type = "button";
        notesButton.addEventListener("click", () => {
            toggleTastingPanel(bottle, expandCell);
            syncExpandRow();
        });
        actionWrap.append(notesButton);

        if (state.currentUser?.role === "admin") {
            const deleteButton = makeElement("button", "text-button bottle-row__delete", "Delete");
            deleteButton.type = "button";
            deleteButton.addEventListener("click", () => deleteBottle(bottle, deleteButton));
            actionWrap.append(deleteButton);
        }

        tdActions.append(actionWrap);
        tr.append(
            tdId,
            tdName,
            tdProducer,
            tdVintage,
            tdRegion,
            tdCountry,
            tdColor,
            tdWindow,
            tdLocation,
            tdComment,
            tdActions,
        );
        tbody.append(tr, expandRow);
    });

    table.append(tbody);
    tableWrap.append(table);
}

function exportCollectionCsv() {
    const wines = visibleWines();
    const rows = state.collectionView === "table" ? sortBottlesForTable(wines) : wines;
    if (rows.length === 0) {
        notify("No bottles in the current view to export.", "warn");
        return;
    }

    const headers = [
        "ID",
        "Wine Name",
        "Producer",
        "Vintage",
        "Color",
        "Grape Varieties",
        "Region",
        "Country",
        "Drinking Window",
        "Drink From",
        "Drink Until",
        "Location",
        "Status",
        "Checkout Date",
        "Purchase Price",
        "Market Price",
        "Purchase Date",
        "Comment",
        "Food Pairing",
        "Tasting Notes",
    ];

    const escapeCsv = (val) => {
        if (val === null || val === undefined) return "";
        const str = String(val).replace(/\r?\n/g, " ").trim();
        if (/[",\n]/.test(str)) {
            return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
    };

    const csvLines = [headers.map(escapeCsv).join(",")];
    rows.forEach((bottle) => {
        const windowInfo = getDrinkingWindowInfo(bottle);
        const personalNotes = (bottle.tasting_notes || [])
            .map((n) => n.notes)
            .filter(Boolean)
            .join(" | ");
        const combinedNotes = [
            wineMetadataText(bottle.grapeminds_tasting_notes),
            personalNotes,
        ].filter(Boolean).join(" | ");

        const line = [
            bottle.qr_id || "",
            bottle.name || "",
            bottle.winery || "",
            bottle.vintage || "NV",
            bottle.color ? normalizeWineColor(bottle.color) : "",
            wineGrapeNames(bottle) || "",
            bottle.region || "",
            bottle.country_of_origin || "",
            windowInfo ? windowInfo.badgeText : "",
            bottle.drink_from || "",
            bottle.drink_until || "",
            bottle.location ? getLocationLabel(bottle.location) : "",
            bottle.status || "in_cellar",
            bottle.checkout_date || "",
            bottle.purchase_price != null ? Number(bottle.purchase_price).toFixed(2) : "",
            bottle.market_price != null ? Number(bottle.market_price).toFixed(2) : "",
            bottle.purchase_date || "",
            bottle.comment || "",
            wineMetadataText(bottle.pairing) || "",
            combinedNotes,
        ];
        csvLines.push(line.map(escapeCsv).join(","));
    });

    const csvContent = "\uFEFF" + csvLines.join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const today = new Date().toISOString().slice(0, 10);
    link.href = url;
    link.download = `wine-cellar-${today}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    notify(`Exported ${rows.length} ${rows.length === 1 ? "bottle" : "bottles"} to CSV.`);
}

function syncCollectionViewTabs() {
    const cardsTab = byId("view-tab-cards");
    const tableTab = byId("view-tab-table");
    const tableWrap = byId("wine-table-wrap");
    const sortOrderWrap = byId("sort-order-wrap");
    const isTable = state.collectionView === "table";
    if (cardsTab) {
        cardsTab.classList.toggle("is-active", !isTable);
        cardsTab.setAttribute("aria-selected", String(!isTable));
    }
    if (tableTab) {
        tableTab.classList.toggle("is-active", isTable);
        tableTab.setAttribute("aria-selected", String(isTable));
    }
    if (wineGrid) wineGrid.hidden = isTable;
    if (tableWrap) tableWrap.hidden = !isTable;
    if (sortOrderWrap) sortOrderWrap.hidden = isTable;
}

function setCollectionView(view) {
    state.collectionView = view === "table" ? "table" : "cards";
    try {
        localStorage.setItem("wineCellar.collectionView", state.collectionView);
    } catch (_) {
        // Ignore storage errors
    }
    const cardsTab = byId("view-tab-cards");
    const tableTab = byId("view-tab-table");
    const tableWrap = byId("wine-table-wrap");
    const sortOrderWrap = byId("sort-order-wrap");

    const isTable = state.collectionView === "table";
    if (cardsTab) {
        cardsTab.classList.toggle("is-active", !isTable);
        cardsTab.setAttribute("aria-selected", String(!isTable));
    }
    if (tableTab) {
        tableTab.classList.toggle("is-active", isTable);
        tableTab.setAttribute("aria-selected", String(isTable));
    }
    if (wineGrid) wineGrid.hidden = isTable;
    if (tableWrap) tableWrap.hidden = !isTable;
    if (sortOrderWrap) sortOrderWrap.hidden = isTable;

    renderWines();
}

function renderWines() {
    const wines = visibleWines();
    const groups = groupWines(wines);
    byId("visible-count").textContent = String(groups.length);
    byId("collection-count").textContent =
        `${groups.length} ${groups.length === 1 ? "wine" : "wines"} · ` +
        `${wines.length} ${wines.length === 1 ? "bottle" : "bottles"} shown`;

    const isTable = state.collectionView === "table";
    const tableWrap = byId("wine-table-wrap");
    if (wineGrid) wineGrid.hidden = isTable;
    if (tableWrap) tableWrap.hidden = !isTable;

    wineGrid.replaceChildren();
    if (groups.length === 0) {
        wineGrid.append(buildEmptyCollectionState());
    } else {
        groups.forEach((group) => wineGrid.append(renderWineCard(group)));
    }

    renderWineTable(wines);
    renderMetrics();
    renderActiveFiltersBar();
}

async function loadWines() {
    state.wines = await api("/wines/?limit=500");
    renderWines();
    renderLocations();
}

async function loadLocations() {
    state.locations = await api("/locations/");
    renderLocations();
}

async function updateStatus(wine, status) {
    try {
        await api(`/wines/${encodeURIComponent(wine.qr_id)}/status?new_status=${encodeURIComponent(status)}`, {
            method: "PATCH",
        });
        await loadWines();
        notify(`Bottle marked ${status.replaceAll("_", " ")}.`);
    } catch (error) {
        notify(error.message, "error");
        await loadWines();
    }
}

async function deleteBottle(wine, button) {
    if (!window.confirm(
        `Permanently delete bottle ${wine.qr_id} and its tasting notes? This cannot be undone.`,
    )) {
        return;
    }
    button.disabled = true;
    try {
        await api(`/wines/${encodeURIComponent(wine.qr_id)}`, { method: "DELETE" });
        await loadWines();
        notify(`Bottle ${wine.qr_id} permanently deleted.`);
    } catch (error) {
        notify(error.message, "error");
        button.disabled = false;
    }
}

let checkoutSelectedBottle = null;
let checkoutGroupBottles = [];
let checkoutInitialTaste = "";
let checkoutInitialPairing = "";
let checkoutScannerStream = null;
let checkoutScannerActive = false;

function extractQrIdFromInput(raw) {
    const trimmed = String(raw || "").trim();
    if (!trimmed) return "";
    try {
        const parsed = new URL(trimmed, window.location.origin);
        const match = parsed.pathname.match(/\/wines\/([^/?#]+)/i);
        if (match) return decodeURIComponent(match[1]);
        const param = parsed.searchParams.get("checkout") || parsed.searchParams.get("qr_id");
        if (param) return param.trim();
    } catch (_) {
        // Not a URL
    }
    const pathMatch = trimmed.match(/\/wines\/([^/?#\s]+)/i);
    if (pathMatch) return decodeURIComponent(pathMatch[1]);
    return trimmed;
}

function stopCheckoutCamera() {
    checkoutScannerActive = false;
    if (checkoutScannerStream) {
        checkoutScannerStream.getTracks().forEach((track) => track.stop());
        checkoutScannerStream = null;
    }
    const video = byId("checkout-qr-video");
    if (video) {
        video.srcObject = null;
    }
    const wrap = byId("checkout-video-wrap");
    if (wrap) wrap.hidden = true;
}

function populateCheckoutDatalist() {
    const datalist = byId("checkout-bottle-datalist");
    if (!datalist) return;
    datalist.replaceChildren();
    const activeBottles = state.wines.filter((b) => (b.status || "in_cellar") === "in_cellar");
    activeBottles.forEach((bottle) => {
        const option = document.createElement("option");
        option.value = bottle.qr_id;
        const labelParts = [
            bottle.winery,
            bottle.name,
            bottle.vintage || "NV",
            bottle.location ? `⌂ ${getLocationLabel(bottle.location)}` : "",
        ].filter(Boolean);
        option.label = labelParts.join(" · ");
        datalist.append(option);
    });
}

function selectCheckoutBottle(bottle) {
    checkoutSelectedBottle = bottle;
    const detailsSection = byId("checkout-details-section");
    const submitBtn = byId("removal-submit");
    const scopePrompt = byId("checkout-scope-prompt");
    if (scopePrompt) scopePrompt.hidden = true;

    if (!bottle) {
        byId("removal-qr-id").value = "";
        byId("removal-bottle-info").textContent = "Select or scan a bottle to check out";
        if (detailsSection) detailsSection.hidden = true;
        if (submitBtn) submitBtn.disabled = true;
        return;
    }

    byId("removal-qr-id").value = bottle.qr_id;
    const wineName = [bottle.winery, bottle.name, bottle.vintage].filter(Boolean).join(" ");
    const locText = bottle.location ? ` · ⌂ ${getLocationLabel(bottle.location)}` : "";
    const statusWarn = (bottle.status || "in_cellar") !== "in_cellar" ? " [Already checked out]" : "";
    byId("removal-bottle-info").textContent = `${wineName || "Bottle"} (${bottle.qr_id})${locText}${statusWarn}`;

    const today = new Date().toISOString().split("T")[0];
    byId("removal-date").value = bottle.checkout_date || today;
    byId("removal-comment").value = (bottle.comment || "").trim() || "Opened";

    const currentTaste = wineMetadataText(bottle.grapeminds_tasting_notes) || "";
    const currentPairing = wineMetadataText(bottle.pairing) || "";
    checkoutInitialTaste = currentTaste.trim();
    checkoutInitialPairing = currentPairing.trim();

    byId("removal-taste").value = currentTaste;
    byId("removal-pairing").value = currentPairing;

    byId("removal-record-note").checked = false;
    byId("removal-note-fields").hidden = true;
    byId("removal-notes").value = "";
    ["tannin", "acidity", "body", "alcohol", "fruit"].forEach((trait) => {
        const slider = byId(`removal-${trait}`);
        const val = byId(`removal-${trait}-val`);
        if (slider) slider.value = "0.5";
        if (val) val.textContent = "0.5";
    });
    byId("removal-aroma-tags").value = "";

    if (detailsSection) detailsSection.hidden = false;
    if (submitBtn) submitBtn.disabled = false;
}

function findAndSelectBottleByQr(rawInput) {
    const qrId = extractQrIdFromInput(rawInput);
    const errorEl = byId("checkout-lookup-error");
    if (errorEl) {
        errorEl.hidden = true;
        errorEl.textContent = "";
    }
    if (!qrId) {
        if (errorEl) {
            errorEl.textContent = "Please enter or scan a bottle ID.";
            errorEl.hidden = false;
        }
        return false;
    }
    const lower = qrId.toLowerCase();
    const match = state.wines.find((b) => (b.qr_id || "").toLowerCase() === lower);
    if (!match) {
        if (errorEl) {
            errorEl.textContent = `No bottle found with ID "${qrId}".`;
            errorEl.hidden = false;
        }
        return false;
    }
    byId("checkout-qr-input").value = match.qr_id;
    checkoutGroupBottles = matchingWineGroup(match);
    selectCheckoutBottle(match);
    stopCheckoutCamera();
    return true;
}

function openCheckoutDialog(options = {}) {
    const dialog = byId("removal-dialog");
    const form = byId("removal-form");
    if (!dialog || !form) return;

    stopCheckoutCamera();
    const errorEl = byId("checkout-lookup-error");
    if (errorEl) {
        errorEl.hidden = true;
        errorEl.textContent = "";
    }
    const scopePrompt = byId("checkout-scope-prompt");
    if (scopePrompt) scopePrompt.hidden = true;

    const bottle = options.bottle || null;
    const groupBottles = Array.isArray(options.groupBottles) ? options.groupBottles : [];
    checkoutGroupBottles = groupBottles.length
        ? groupBottles
        : (bottle ? matchingWineGroup(bottle) : []);

    const groupPicker = byId("checkout-group-picker");
    const groupSelect = byId("checkout-group-select");
    const lookupBox = byId("checkout-lookup-box");

    populateCheckoutDatalist();

    if (groupBottles.length > 1 && !bottle) {
        // Opened from a multi-bottle wine card in group mode: prompt user to choose which bottle ID
        if (groupPicker && groupSelect) {
            groupPicker.hidden = false;
            groupSelect.replaceChildren();
            const placeholder = document.createElement("option");
            placeholder.value = "";
            placeholder.textContent = `— Choose one of ${groupBottles.length} bottles —`;
            groupSelect.append(placeholder);
            groupBottles.forEach((b) => {
                const opt = document.createElement("option");
                opt.value = b.qr_id;
                const loc = b.location ? `⌂ ${getLocationLabel(b.location)}` : "No storage location";
                const commentPart = b.comment ? ` · ${b.comment}` : "";
                opt.textContent = `${b.qr_id} (${loc}${commentPart})`;
                groupSelect.append(opt);
            });
        }
        if (lookupBox) lookupBox.hidden = true;
        const firstWine = groupBottles[0];
        const wineTitle = [firstWine.winery, firstWine.name, firstWine.vintage].filter(Boolean).join(" ");
        selectCheckoutBottle(null);
        byId("removal-bottle-info").textContent = `${wineTitle || "Wine"} — select a specific bottle ID below`;
    } else if (bottle) {
        if (groupPicker) groupPicker.hidden = true;
        if (lookupBox) lookupBox.hidden = true;
        selectCheckoutBottle(bottle);
    } else {
        // Top-level "Check out a bottle" flow: enter ID or scan QR
        if (groupPicker) groupPicker.hidden = true;
        if (lookupBox) lookupBox.hidden = false;
        byId("checkout-qr-input").value = "";
        selectCheckoutBottle(null);
    }

    dialog.showModal();
    if (!bottle && !(groupBottles.length > 1)) {
        setTimeout(() => byId("checkout-qr-input")?.focus(), 50);
    }
}

function openRemovalDialog(bottle) {
    openCheckoutDialog({ bottle });
}

async function scanQrFromFile(file) {
    if (!file) return;
    const errorEl = byId("checkout-lookup-error");
    if (errorEl) {
        errorEl.hidden = true;
        errorEl.textContent = "";
    }
    const scanBtn = byId("checkout-scan-qr-btn");
    if (scanBtn) {
        scanBtn.disabled = true;
        scanBtn.textContent = "Reading QR…";
    }
    try {
        if ("BarcodeDetector" in window) {
            try {
                const bitmap = await createImageBitmap(file);
                const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
                const codes = await detector.detect(bitmap);
                if (codes && codes.length > 0 && codes[0].rawValue) {
                    findAndSelectBottleByQr(codes[0].rawValue);
                    return;
                }
            } catch (_) {
                // Fall back to server endpoint
            }
        }
        const formData = new FormData();
        formData.append("photo", file);
        const result = await api("/wines/scan-qr", {
            method: "POST",
            body: formData,
        });
        if (result && result.qr_id) {
            findAndSelectBottleByQr(result.qr_id);
        } else if (errorEl) {
            errorEl.textContent = "Could not detect a bottle QR code in that photo. Try again or type the ID.";
            errorEl.hidden = false;
        }
    } catch (error) {
        if (errorEl) {
            errorEl.textContent = error.message || "Could not read QR code.";
            errorEl.hidden = false;
        }
    } finally {
        if (scanBtn) {
            scanBtn.disabled = false;
            scanBtn.textContent = "Scan QR with camera";
        }
    }
}

async function startCheckoutQrScanner() {
    const errorEl = byId("checkout-lookup-error");
    if (errorEl) {
        errorEl.hidden = true;
        errorEl.textContent = "";
    }

    if ("BarcodeDetector" in window && navigator.mediaDevices?.getUserMedia) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: "environment" } },
                audio: false,
            });
            checkoutScannerStream = stream;
            checkoutScannerActive = true;
            const video = byId("checkout-qr-video");
            const wrap = byId("checkout-video-wrap");
            if (video && wrap) {
                video.srcObject = stream;
                wrap.hidden = false;
                await video.play();
                const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
                const scanLoop = async () => {
                    if (!checkoutScannerActive) return;
                    try {
                        const barcodes = await detector.detect(video);
                        if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
                            findAndSelectBottleByQr(barcodes[0].rawValue);
                            return;
                        }
                    } catch (_) {
                        // ignore frame error
                    }
                    if (checkoutScannerActive) {
                        requestAnimationFrame(scanLoop);
                    }
                };
                requestAnimationFrame(scanLoop);
                return;
            }
        } catch (_) {
            // Fall through to file/camera capture input
        }
    }

    stopCheckoutCamera();
    // Fallback (e.g. mobile HTTP where getUserMedia is restricted): open phone camera photo input
    byId("checkout-qr-file")?.click();
}

async function submitBottleCheckout(applyToAllInGroup = false) {
    const dialog = byId("removal-dialog");
    const submitBtn = byId("removal-submit");
    const scopePrompt = byId("checkout-scope-prompt");
    const qrId = byId("removal-qr-id").value;
    if (!qrId) return;

    const checkoutDate = byId("removal-date").value || new Date().toISOString().split("T")[0];
    const comment = byId("removal-comment").value.trim() || "Opened";
    const taste = byId("removal-taste").value.trim();
    const pairing = byId("removal-pairing").value.trim();
    const shouldRecordNote = byId("removal-record-note").checked;

    let tastingNote = null;
    if (shouldRecordNote) {
        const notes = byId("removal-notes").value.trim();
        const tannin = parseFloat(byId("removal-tannin").value) || 0.5;
        const acidity = parseFloat(byId("removal-acidity").value) || 0.5;
        const body = parseFloat(byId("removal-body").value) || 0.5;
        const alcohol = parseFloat(byId("removal-alcohol").value) || 0.5;
        const fruitIntensity = parseFloat(byId("removal-fruit").value) || 0.5;
        const aromaTags = byId("removal-aroma-tags").value.trim();

        tastingNote = {
            tasting_date: checkoutDate,
            notes: notes || null,
            tannin,
            acidity,
            body,
            alcohol,
            fruit_intensity: fruitIntensity,
            aroma_tags: aromaTags || null,
        };
    }

    const fullGroup = checkoutSelectedBottle ? matchingWineGroup(checkoutSelectedBottle) : [];
    const applyGroupIds = applyToAllInGroup && fullGroup.length > 1
        ? fullGroup.map((b) => b.qr_id)
        : [];

    submitBtn.disabled = true;
    submitBtn.setAttribute("aria-busy", "true");
    try {
        await api(`/wines/${encodeURIComponent(qrId)}/checkout`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                status: "removed",
                checkout_date: checkoutDate,
                comment,
                grapeminds_tasting_notes: taste || null,
                pairing: pairing || null,
                apply_to_group_qr_ids: applyGroupIds,
                tasting_note: tastingNote,
            }),
        });
        if (scopePrompt) scopePrompt.hidden = true;
        stopCheckoutCamera();
        dialog.close();
        await loadWines();
        notify(`Bottle ${qrId} checked out.`);
    } catch (error) {
        notify(error.message, "error");
    } finally {
        submitBtn.disabled = false;
        submitBtn.removeAttribute("aria-busy");
    }
}

function initRemovalDialog() {
    const dialog = byId("removal-dialog");
    const form = byId("removal-form");
    if (!dialog || !form) return;

    const closeDialog = () => {
        stopCheckoutCamera();
        dialog.close();
    };

    byId("removal-dialog-close")?.addEventListener("click", closeDialog);
    byId("removal-cancel")?.addEventListener("click", closeDialog);
    dialog.addEventListener("close", stopCheckoutCamera);

    byId("checkout-group-select")?.addEventListener("change", (e) => {
        const chosenId = e.target.value;
        const found = checkoutGroupBottles.find((b) => b.qr_id === chosenId)
            || state.wines.find((b) => b.qr_id === chosenId);
        selectCheckoutBottle(found || null);
    });

    byId("checkout-find-btn")?.addEventListener("click", () => {
        findAndSelectBottleByQr(byId("checkout-qr-input")?.value);
    });

    byId("checkout-qr-input")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            findAndSelectBottleByQr(e.target.value);
        }
    });

    byId("checkout-qr-input")?.addEventListener("change", (e) => {
        const val = e.target.value.trim();
        if (state.wines.some((b) => (b.qr_id || "").toLowerCase() === val.toLowerCase())) {
            findAndSelectBottleByQr(val);
        }
    });

    byId("checkout-scan-qr-btn")?.addEventListener("click", () => {
        startCheckoutQrScanner();
    });

    byId("checkout-stop-video")?.addEventListener("click", () => {
        stopCheckoutCamera();
    });

    byId("checkout-qr-file")?.addEventListener("change", (e) => {
        const file = e.target.files?.[0];
        if (file) {
            scanQrFromFile(file);
        }
        e.target.value = "";
    });

    byId("removal-record-note")?.addEventListener("change", (e) => {
        byId("removal-note-fields").hidden = !e.target.checked;
    });

    ["tannin", "acidity", "body", "alcohol", "fruit"].forEach((trait) => {
        const slider = byId(`removal-${trait}`);
        const val = byId(`removal-${trait}-val`);
        if (slider && val) {
            slider.addEventListener("input", () => {
                val.textContent = Number(slider.value).toFixed(1);
            });
        }
    });

    byId("checkout-scope-all")?.addEventListener("click", () => {
        submitBottleCheckout(true);
    });
    byId("checkout-scope-one")?.addEventListener("click", () => {
        submitBottleCheckout(false);
    });
    byId("checkout-scope-cancel")?.addEventListener("click", () => {
        const scopePrompt = byId("checkout-scope-prompt");
        if (scopePrompt) scopePrompt.hidden = true;
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!checkoutSelectedBottle) {
            findAndSelectBottleByQr(byId("checkout-qr-input")?.value);
            if (!checkoutSelectedBottle) return;
        }

        const tasteChanged = byId("removal-taste").value.trim() !== checkoutInitialTaste;
        const pairingChanged = byId("removal-pairing").value.trim() !== checkoutInitialPairing;
        const fullGroup = matchingWineGroup(checkoutSelectedBottle);

        if ((tasteChanged || pairingChanged) && fullGroup.length > 1) {
            const scopePrompt = byId("checkout-scope-prompt");
            const scopeText = byId("checkout-scope-text");
            if (scopePrompt && scopeText) {
                scopeText.textContent = `You updated the taste or food pairing notes. Apply these changes to all ${fullGroup.length} bottles of this wine, or only bottle ${checkoutSelectedBottle.qr_id}?`;
                scopePrompt.hidden = false;
                scopePrompt.scrollIntoView({ behavior: "smooth", block: "nearest" });
                return;
            }
        }

        await submitBottleCheckout(false);
    });
}

function checkUrlBottleCheckout() {
    const pathMatch = window.location.pathname.match(/^\/wines\/([^/?#]+)$/i);
    const params = new URLSearchParams(window.location.search);
    const qrParam = params.get("checkout") || (pathMatch ? decodeURIComponent(pathMatch[1]) : "");
    if (!qrParam) return;

    window.history.replaceState({}, document.title, "/");
    const lower = qrParam.toLowerCase();
    const match = state.wines.find((b) => (b.qr_id || "").toLowerCase() === lower);
    if (match) {
        openCheckoutDialog({ bottle: match });
    } else {
        openCheckoutDialog();
        const input = byId("checkout-qr-input");
        if (input) {
            input.value = qrParam;
            findAndSelectBottleByQr(qrParam);
        }
    }
}

async function openDialog() {
    clearDialog();
    renderLocationOptions();
    if (!state.locations.length) {
        try {
            await loadLocations();
        } catch {
            // Ignore if locations cannot be fetched right now
        }
    }
    if (state.nextBottleQrId) {
        byId("manual-form").elements.namedItem("qr_id").value = state.nextBottleQrId;
    }
    dialog.showModal();
}

function openWineEditor(wines, editGroup) {
    clearDialog();
    const form = byId("manual-form");
    const wine = wines[0];
    const bottleIds = wines.map((bottle) => bottle.qr_id);
    const groupComments = new Set(wines.map((bottle) => (bottle.comment || "").trim()));
    state.editingWine = { bottleIds, editGroup };
    renderLocationOptions();

    const fields = {
        qr_id: wine.qr_id,
        grapeminds_id: wine.grapeminds_id,
        name: wine.name,
        winery: wine.winery,
        vintage: wine.vintage,
        region: wine.region,
        country_of_origin: wine.country_of_origin,
        grape_type: wineGrapeNames(wine),
        color: normalizeWineColor(wine.color),
        comment: editGroup && groupComments.size > 1 ? "" : wine.comment,
        description: wineMetadataText(wine.description),
        pairing: wineMetadataText(wine.pairing),
        grapeminds_tasting_notes: wineMetadataText(wine.grapeminds_tasting_notes),
        purchase_price: wine.purchase_price,
        market_price: wine.market_price,
        purchase_date: wine.purchase_date,
        drink_from: wine.drink_from,
        drink_until: wine.drink_until,
        location_id: wine.location_id,
    };
    Object.entries(fields).forEach(([name, value]) => {
        const input = form.elements.namedItem(name);
        if (input) input.value = value ?? "";
    });
    ["sweetness", "acidity", "tannins", "alcohol", "body", "finish"].forEach((name) => {
        const input = form.elements.namedItem(`flavor_${name}`);
        if (input) input.value = wine.flavor_profile?.[name] ?? "";
    });

    const bottleIdInput = form.elements.namedItem("qr_id");
    form.noValidate = true;
    bottleIdInput.required = false;
    form.elements.namedItem("quantity").required = false;
    bottleIdInput.closest("label").hidden = true;
    form.elements.namedItem("quantity").closest("label").hidden = true;
    ["purchase_price", "market_price", "purchase_date", "location_id"].forEach((name) => {
        const field = form.elements.namedItem(name);
        field.closest("label").hidden = false;
        if (editGroup) {
            const distinctValues = new Set(
                wines.map((bottle) => bottle[name] ?? ""),
            );
            field.value = distinctValues.size === 1
                ? String(wine[name] ?? "")
                : "";
        }
    });
    byId("scan-intro").hidden = true;
    byId("scan-label").hidden = true;
    byId("photo-input").hidden = true;
    byId("photo-preview").hidden = true;
    const explorerCallout = byId("explorer-callout");
    if (explorerCallout) {
        explorerCallout.hidden = false;
        const calloutTitle = explorerCallout.querySelector("strong");
        const calloutDesc = explorerCallout.querySelector("p");
        if (calloutTitle) {
            calloutTitle.textContent = editGroup
                ? "Update details with Grapeminds?"
                : "Enrich bottle with Grapeminds?";
        }
        if (calloutDesc) {
            calloutDesc.textContent = editGroup
                ? "Search the catalog to update wine details across this group of bottles."
                : "Search the catalog to enrich or update wine details for this bottle.";
        }
    }
    byId("grapeminds-preview").replaceChildren();
    byId("grapeminds-preview").hidden = true;
    byId("scan-status").hidden = true;
    const heading = dialog.querySelector(".dialog__head");
    heading.querySelector(".eyebrow").textContent = editGroup
        ? `EDIT WINE · ${bottleIds.length} BOTTLES`
        : `EDIT BOTTLE · ${wine.qr_id}`;
    heading.querySelector("h2").textContent = editGroup
        ? "Edit wine details for the group."
        : "Edit this bottle.";
    byId("manual-submit").textContent = editGroup ? "Save group changes" : "Save bottle changes";

    const batchSummary = byId("batch-bottles-summary");
    if (batchSummary) {
        if (editGroup) {
            batchSummary.hidden = false;
            batchSummary.textContent = `Bottles in this batch (${bottleIds.length}): ${bottleIds.join(", ")}`;
        } else {
            batchSummary.hidden = true;
            batchSummary.textContent = "";
        }
    }

    const deleteBatchBtn = byId("delete-batch-btn");
    if (deleteBatchBtn) {
        if (state.currentUser?.role === "admin") {
            deleteBatchBtn.hidden = false;
            deleteBatchBtn.disabled = false;
            deleteBatchBtn.removeAttribute("aria-busy");
            deleteBatchBtn.textContent = editGroup
                ? (bottleIds.length > 1 ? `Delete batch (${bottleIds.length} bottles)` : "Delete wine")
                : "Delete bottle";
        } else {
            deleteBatchBtn.hidden = true;
        }
    }

    dialog.showModal();
}

function clearDialog() {
    state.editingWine = null;
    byId("manual-form").reset();
    byId("manual-submit").disabled = false;
    byId("manual-submit").removeAttribute("aria-busy");
    const batchSummary = byId("batch-bottles-summary");
    if (batchSummary) {
        batchSummary.hidden = true;
        batchSummary.textContent = "";
    }
    const deleteBatchBtn = byId("delete-batch-btn");
    if (deleteBatchBtn) {
        deleteBatchBtn.hidden = true;
        deleteBatchBtn.disabled = false;
        deleteBatchBtn.removeAttribute("aria-busy");
    }
    const explorerCallout = byId("explorer-callout");
    if (explorerCallout) {
        explorerCallout.hidden = false;
        const calloutTitle = explorerCallout.querySelector("strong");
        const calloutDesc = explorerCallout.querySelector("p");
        if (calloutTitle) calloutTitle.textContent = "Search catalog with Grapeminds?";
        if (calloutDesc) calloutDesc.textContent = "Browse the Grapeminds catalog to populate wine details, grapes, pairings, and flavor profile.";
    }
    const form = byId("manual-form");
    form.noValidate = false;
    const bottleId = form.elements.namedItem("qr_id");
    bottleId.required = true;
    bottleId.closest("label").hidden = false;
    const quantity = form.elements.namedItem("quantity");
    quantity.required = true;
    quantity.closest("label").hidden = false;
    ["purchase_price", "purchase_date", "location_id"].forEach((name) => {
        form.elements.namedItem(name).closest("label").hidden = false;
    });
    byId("scan-intro").hidden = false;
    byId("scan-label").hidden = false;
    byId("photo-input").hidden = false;
    const heading = dialog.querySelector(".dialog__head");
    heading.querySelector(".eyebrow").textContent = "ADD TO YOUR COLLECTION";
    heading.querySelector("h2").innerHTML = "A bottle worth <em>remembering.</em>";
    byId("manual-submit").textContent = "Save bottle ↗";
    byId("grapeminds-preview").hidden = true;
    byId("grapeminds-preview").replaceChildren();
    byId("scan-status").textContent = "";
    byId("scan-status").hidden = true;
    byId("scan-status").classList.remove("is-busy");
    byId("scan-status").removeAttribute("aria-busy");
    byId("photo-preview").hidden = true;
    byId("photo-preview").removeAttribute("src");
    byId("photo-input").value = "";
    if (state.photoPreviewUrl) URL.revokeObjectURL(state.photoPreviewUrl);
    state.photoPreviewUrl = null;
    state.selectedPhoto = null;
    state.scanDraft = null;
}

function buildQrIdSequence(startingId, quantity) {
    if (quantity === 1) return [startingId];

    const match = startingId.match(/^(.*?)(\d+)$/);
    if (!match) {
        throw new Error("For multiple bottles, the QR / bottle ID must end in a number.");
    }

    const [, prefix, digits] = match;
    const start = BigInt(digits);
    return Array.from({ length: quantity }, (_, index) => {
        const qrId = `${prefix}${(start + BigInt(index)).toString().padStart(digits.length, "0")}`;
        if (qrId.length > 64) {
            throw new Error("One of the generated QR IDs exceeds the 64-character limit.");
        }
        return qrId;
    });
}

function formToWine(form, qrId, photoPath = null) {
    const data = new FormData(form);
    const vintageText = String(data.get("vintage") || "").trim();
    const priceText = String(data.get("purchase_price") || "").trim();
    const marketPriceText = String(data.get("market_price") || "").trim();
    const drinkFromText = String(data.get("drink_from") || "").trim();
    const drinkUntilText = String(data.get("drink_until") || "").trim();
    const grapes = String(data.get("grape_type") || "")
        .split(",")
        .map((grape) => grape.trim())
        .filter(Boolean);
    const enrichment = state.scanDraft?.enrichment_metadata || {};
    const flavorKeys = [
        "sweetness",
        "acidity",
        "tannins",
        "alcohol",
        "body",
        "finish",
    ];
    const flavorProfile = Object.fromEntries(
        Object.entries(enrichment.flavor_profile || {}).filter(
            ([name]) => !flavorKeys.includes(name),
        ),
    );
    flavorKeys.forEach((name) => {
        const value = String(data.get(`flavor_${name}`) || "").trim();
        if (value) flavorProfile[name] = Number(value);
    });
    return {
        qr_id: qrId,
        grapeminds_id: String(data.get("grapeminds_id") || "").trim() || null,
        name: String(data.get("name") || "").trim() || null,
        winery: String(data.get("winery") || "").trim() || null,
        vintage: vintageText ? Number(vintageText) : null,
        region: String(data.get("region") || "").trim() || null,
        country_of_origin: String(data.get("country_of_origin") || "").trim() || null,
        grape_type: grapes.join(", ") || null,
        color: normalizeWineColor(data.get("color")) || null,
        comment: String(data.get("comment") || "").trim() || null,
        grape_varieties: grapes.length ? grapes : null,
        description: String(data.get("description") || "").trim() || null,
        pairing: String(data.get("pairing") || "").trim() || null,
        grapeminds_tasting_notes:
            String(data.get("grapeminds_tasting_notes") || "").trim() || null,
        flavor_profile: Object.keys(flavorProfile).length ? flavorProfile : null,
        purchase_price: priceText ? Number(priceText) : null,
        market_price: marketPriceText ? Number(marketPriceText) : null,
        purchase_date: String(data.get("purchase_date") || "") || null,
        drink_from: drinkFromText ? Number(drinkFromText) : null,
        drink_until: drinkUntilText ? Number(drinkUntilText) : null,
        location_id: data.get("location_id") ? Number(data.get("location_id")) : null,
        photo_path: photoPath,
        is_verified: true,
    };
}

async function submitWine(wine, button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try {
        const batch = Array.isArray(wine);
        const saved = await api(batch ? "/wines/confirm/batch" : "/wines/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(batch ? { wines: wine } : wine[0]),
        });
        dialog.close();
        clearDialog();
        await loadWines();
        if (batch) {
            const firstId = saved[0].qr_id;
            const lastId = saved[saved.length - 1].qr_id;
            state.nextBottleQrId = nextQrId(lastId);
            notify(
                `${saved.length} bottles added (${firstId} through ${lastId}). Next QR ID: ${state.nextBottleQrId || "enter one manually"}.`,
            );
        } else {
            state.nextBottleQrId = nextQrId(wine[0].qr_id);
            notify(
                `Bottle added to your cellar. Next QR ID: ${state.nextBottleQrId || "enter one manually"}.`,
            );
        }
    } catch (error) {
        notify(error.message, "error");
        button.disabled = false;
        button.removeAttribute("aria-busy");
    }
}

function nextQrId(qrId) {
    const match = qrId.match(/^(.*?)(\d+)$/);
    if (!match) return null;
    const [, prefix, digits] = match;
    const nextDigits = (BigInt(digits) + 1n).toString().padStart(digits.length, "0");
    return nextDigits.length + prefix.length <= 64
        ? `${prefix}${nextDigits}`
        : "maximum ID length reached";
}

byId("sign-in-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = byId("sign-in-submit");
    button.disabled = true;
    byId("sign-in-error").textContent = "";
    try {
        await api("/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username: byId("username").value.trim(),
                password: byId("password").value,
            }),
        });
        byId("password").value = "";
        const session = await api("/auth/session");
        updateUserUI(session);
        showCellar();
        await Promise.all([loadWines(), loadLocations()]);
        checkUrlBottleCheckout();
    } catch (error) {
        byId("sign-in-error").textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

byId("logout").addEventListener("click", async () => {
    try {
        await api("/auth/logout", { method: "POST" });
    } finally {
        showSignIn();
    }
});

byId("add-bottle").addEventListener("click", () => openDialog());
byId("menu-add-bottle").addEventListener("click", () => {
    byId("top-menu").open = false;
    openDialog();
});
byId("checkout-bottle")?.addEventListener("click", () => openCheckoutDialog());
byId("menu-checkout-bottle")?.addEventListener("click", () => {
    byId("top-menu").open = false;
    openCheckoutDialog();
});
byId("menu-settings").addEventListener("click", () => {
    byId("top-menu").open = false;
    byId("restart-status").hidden = true;
    byId("restart-status").textContent = "";
    byId("settings-dialog").showModal();
});
byId("settings-close").addEventListener("click", () => {
    byId("settings-dialog").close();
});
byId("restart-server").addEventListener("click", restartServer);
byId("manage-locations").addEventListener("click", () => {
    openLocationCreator();
});
byId("add-location").addEventListener("click", () => {
    openLocationCreator();
});
byId("location-dialog-close").addEventListener("click", () => {
    byId("location-dialog").close();
});
byId("location-dialog").addEventListener("close", () => {
    state.editingLocationId = null;
    byId("location-parent").closest("label").hidden = false;
    byId("location-dialog").querySelector(".dialog__head h2").textContent = "Add a location.";
    byId("location-submit").textContent = "Save location";
    byId("location-form").reset();
});
byId("dialog-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("close", () => {
    if (state.selectingWineForForm) return;
    clearDialog();
});
byId("delete-batch-btn")?.addEventListener("click", async () => {
    if (!state.editingWine) return;
    const { bottleIds, editGroup } = state.editingWine;
    if (state.currentUser?.role !== "admin") {
        notify("Admin privileges required to delete wines.", "warn");
        return;
    }

    const count = bottleIds.length;
    const confirmMessage = editGroup
        ? (count > 1
            ? `Permanently delete all ${count} bottles in this batch (${bottleIds.join(", ")}) and their tasting notes?\n\nThis action cannot be undone.`
            : `Permanently delete bottle ${bottleIds[0]} and its tasting notes?\n\nThis action cannot be undone.`)
        : `Permanently delete bottle ${bottleIds[0]} and its tasting notes?\n\nThis action cannot be undone.`;

    if (!window.confirm(confirmMessage)) return;

    const btn = byId("delete-batch-btn");
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    try {
        if (count > 1) {
            await api("/wines/batch/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ qr_ids: bottleIds }),
            });
        } else {
            await api(`/wines/${encodeURIComponent(bottleIds[0])}`, {
                method: "DELETE",
            });
        }
        dialog.close();
        clearDialog();
        await loadWines();
        notify(`Permanently deleted ${count} bottle${count > 1 ? "s" : ""}.`);
    } catch (error) {
        notify(error.message || "Failed to delete bottles.", "error");
        btn.disabled = false;
        btn.removeAttribute("aria-busy");
    }
});
byId("location-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const button = byId("location-submit");
    const parentId = String(data.get("parent_location_id") || "");
    const editing = state.editingLocationId !== null;
    button.disabled = true;
    try {
        await api(editing ? `/locations/${state.editingLocationId}` : "/locations/", {
            method: editing ? "PATCH" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: String(data.get("name") || "").trim(),
                sub_location: String(data.get("sub_location") || "").trim() || null,
                ...(!editing && {
                    parent_location_id: parentId ? Number(parentId) : null,
                }),
            }),
        });
        form.reset();
        byId("location-dialog").close();
        await loadLocations();
        notify(editing ? "Location updated." : "Storage location added.");
    } catch (error) {
        notify(error.message, "error");
    } finally {
        button.disabled = false;
    }
});
byId("manual-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const startingId = String(data.get("qr_id") || "").trim();
    const button = byId("manual-submit");
    if (state.editingWine) {
        const numericFields = [
            ["vintage", "Vintage must be a whole number."],
            ["purchase_price", "Purchase price must be a number."],
            ["market_price", "Market price must be a number."],
            ...["sweetness", "acidity", "tannins", "alcohol", "body", "finish"]
                .map((name) => [`flavor_${name}`, `${name} must be a number.`]),
        ];
        for (const [name, message] of numericFields) {
            const value = String(data.get(name) || "").trim();
            if (value && !Number.isFinite(Number(value))) {
                notify(message, "error");
                form.elements.namedItem(name).focus();
                return;
            }
        }
        const vintage = String(data.get("vintage") || "").trim();
        if (vintage && !Number.isInteger(Number(vintage))) {
            notify("Vintage must be a whole number.", "error");
            form.elements.namedItem("vintage").focus();
            return;
        }
        const { bottleIds, editGroup } = state.editingWine;
        const update = formToWine(form, bottleIds[0]);
        delete update.qr_id;
        delete update.photo_path;
        delete update.is_verified;
        if (editGroup) {
            const sharedFields = [
                "grapeminds_id",
                "name",
                "vintage",
                "winery",
                "region",
                "country_of_origin",
                "grape_type",
                "color",
                "comment",
                "grape_varieties",
                "description",
                "pairing",
                "grapeminds_tasting_notes",
                "flavor_profile",
                "location_id",
                "purchase_date",
                "purchase_price",
                "market_price",
                "drink_from",
                "drink_until",
            ];
            const sharedUpdate = {};
            for (const field of sharedFields) {
                const value = update[field];
                if (value !== null && value !== undefined && value !== "") {
                    sharedUpdate[field] = value;
                } else if (field === "comment" || field === "drink_from" || field === "drink_until") {
                    sharedUpdate[field] = null;
                }
            }
            const sendUpdate = async (forceMove) => {
                return api("/wines/batch/update", {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        qr_ids: bottleIds,
                        updates: sharedUpdate,
                        force_move: forceMove,
                    }),
                });
            };
            const finish = async () => {
                dialog.close();
                clearDialog();
                await loadWines();
                notify(`Updated wine details for ${bottleIds.length} bottles.`);
            };
            button.disabled = true;
            try {
                await sendUpdate(false);
                await finish();
            } catch (error) {
                const conflicts = error.body?.detail?.conflicts;
                if (
                    error.status === 409 &&
                    Array.isArray(conflicts) &&
                    "location_id" in sharedUpdate
                ) {
                    const newLocId = sharedUpdate.location_id;
                    const newLoc = (state.locations || []).find((l) => l.id === newLocId);
                    const newLocLabel = newLoc
                        ? `${newLoc.name}${newLoc.sub_location ? ` · ${newLoc.sub_location}` : ""}`
                        : `location #${newLocId}`;
                    const lines = conflicts
                        .map((c) => `• Bottle ${c.qr_id} → ${c.current_location}`)
                        .join("\n");
                    const ok = window.confirm(
                        `This batch is currently spread across multiple locations:\n\n${lines}\n\n` +
                        `Move all ${bottleIds.length} bottles to "${newLocLabel}"?`
                    );
                    if (ok) {
                        try {
                            await sendUpdate(true);
                            await finish();
                        } catch (e2) {
                            notify(e2.message || "Could not save group changes.", "error");
                            button.disabled = false;
                        }
                    } else {
                        button.disabled = false;
                    }
                } else {
                    notify(error.message, "error");
                    button.disabled = false;
                }
            }
        } else {
            button.disabled = true;
            try {
                await api(`/wines/${encodeURIComponent(bottleIds[0])}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(update),
                });
                dialog.close();
                clearDialog();
                await loadWines();
                notify(`Bottle ${bottleIds[0]} updated.`);
            } catch (error) {
                notify(error.message, "error");
                button.disabled = false;
            }
        }
        return;
    }

    const quantity = Number(data.get("quantity"));
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 100) {
        notify("Enter a number of bottles between 1 and 100.", "error");
        return;
    }

    let qrIds;
    try {
        qrIds = buildQrIdSequence(startingId, quantity);
    } catch (error) {
        notify(error.message, "error");
        return;
    }

    const photoPath = state.scanDraft?.photo_path || null;
    const wines = qrIds.map((qrId) => formToWine(form, qrId, photoPath));
    await submitWine(wines, button);
});

byId("scan-label").addEventListener("click", () => byId("photo-input").click());

byId("photo-input").addEventListener("change", (event) => {
    state.selectedPhoto = event.currentTarget.files[0] || null;
    event.currentTarget.value = "";
    const preview = byId("photo-preview");
    if (state.photoPreviewUrl) URL.revokeObjectURL(state.photoPreviewUrl);
    if (state.selectedPhoto) {
        state.photoPreviewUrl = URL.createObjectURL(state.selectedPhoto);
        preview.src = state.photoPreviewUrl;
        preview.hidden = false;
    } else {
        preview.hidden = true;
        preview.removeAttribute("src");
        state.photoPreviewUrl = null;
    }
    if (state.selectedPhoto) scanSelectedLabel();
});

async function scanSelectedLabel() {
    const button = byId("scan-label");
    const saveButton = byId("manual-submit");
    state.scanDraft = null;
    byId("grapeminds-preview").hidden = true;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    saveButton.disabled = true;
    const status = byId("scan-status");
    status.hidden = false;
    setBusyStatus(status, "Reading the label…", true);
    try {
        const data = new FormData();
        const qrId = String(new FormData(byId("manual-form")).get("qr_id") || "").trim();
        if (qrId) data.append("qr_id", qrId);
        data.append("photo", state.selectedPhoto);
        state.scanDraft = await api("/wines/scan", { method: "POST", body: data });
        const fields = state.scanDraft.suggested_fields || {};
        ["name", "winery", "vintage", "region", "country_of_origin", "grape_type", "color"].forEach((key) => {
            const input = byId("manual-form").elements.namedItem(key);
            const suggestion = fields[key];
            if (input && !input.value && suggestion !== null && suggestion !== undefined) {
                input.value = key === "color" ? normalizeWineColor(suggestion) : suggestion;
            }
        });
        const vision = state.scanDraft.vision_extraction || {};
        const provider = vision._provider === "wineapi"
            ? "WineAPI.io fallback"
            : vision._provider === "openrouter"
                ? "OpenRouter fallback"
                : "local Ollama";
        if (vision._error) {
            setBusyStatus(status, vision._fallback_status === "failed"
                ? "Local and cloud fallback label reading failed. Enter the wine details manually."
                : "Label reading is unavailable. Enter the wine details manually.", false);
        } else if (vision._fallback_status === "used") {
            const fallbackName = vision._provider === "wineapi" ? "WineAPI.io" : "OpenRouter";
            setBusyStatus(status, `Local Ollama was uncertain, so ${fallbackName} identified the label. Review the suggestions before saving.`, false);
        } else if (vision._fallback_status === "failed") {
            setBusyStatus(status, "The local label read is shown; cloud fallback failed. Review or enter details manually.", false);
        } else if (vision._fallback_status === "not_configured") {
            setBusyStatus(status, "Ollama’s identity read may be uncertain; no cloud fallback (WINEAPIIO_KEY or OPENROUTER_API_KEY) is configured.", false);
        } else if (vision._fallback_status === "no_better_result") {
            setBusyStatus(status, "Ollama was uncertain, and cloud fallback did not improve the read. Review the local suggestions.", false);
        } else {
            setBusyStatus(status, `Label read with ${provider}. Review the suggestions before saving.`, false);
        }
    } catch (error) {
        setBusyStatus(status, `Could not scan this label: ${error.message}`, false);
    } finally {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        saveButton.disabled = false;
    }
}

function applyGrapemindsToForm(metadata, selected) {
    const fields = byId("manual-form").elements;
    selected.forEach(({ name }) => {
        if (name === "flavor_profile") {
            Object.entries(metadata.flavor_profile || {}).forEach(([key, value]) => {
                const input = fields.namedItem(`flavor_${key}`);
                if (input && value !== null && value !== undefined) {
                    input.value = String(value);
                }
            });
            return;
        }
        const inputName = name === "grape_type" ? "grape_type" : name;
        const input = fields.namedItem(inputName);
        if (!input) return;
        const value = name === "grape_type"
            ? wineGrapeNames(metadata)
            : name === "color"
                ? normalizeWineColor(metadata.color)
                : ["description", "pairing", "grapeminds_tasting_notes"].includes(name)
                    ? wineMetadataText(metadata[name])
                    : metadata[name];
        if (value !== null && value !== undefined) input.value = String(value);
    });
    state.scanDraft ||= {};
    state.scanDraft.enrichment_metadata = {
        ...metadata,
        flavor_profile: selected.some(({ name }) => name === "flavor_profile")
            ? metadata.flavor_profile
            : null,
    };
    setBusyStatus(
        byId("scan-status"),
        "Selected Grapeminds details are in the form. Review and save the bottle.",
        false,
    );
}

// grapeminds-lookup replaced by grapeminds explorer integration

byId("search").addEventListener("input", renderWines);
byId("color-filter")?.addEventListener("change", renderWines);
byId("location-filter")?.addEventListener("change", () => {
    renderWines();
    renderLocations();
});
byId("status-filter").addEventListener("change", renderWines);
byId("sort-order").addEventListener("change", renderWines);
byId("view-tab-cards")?.addEventListener("click", () => setCollectionView("cards"));
byId("view-tab-table")?.addEventListener("click", () => setCollectionView("table"));
byId("export-csv-btn")?.addEventListener("click", exportCollectionCsv);
syncCollectionViewTabs();

["all", "red", "white", "rose"].forEach((key) => {
    const card = byId(`metric-card-${key}`);
    if (!card) return;
    const activate = () => {
        const colorSelect = byId("color-filter");
        const locationSelect = byId("location-filter");
        const statusSelect = byId("status-filter");
        if (key === "all") {
            if (colorSelect) colorSelect.value = "";
            if (locationSelect) locationSelect.value = "";
            if (statusSelect) statusSelect.value = "in_cellar";
        } else if (colorSelect) {
            colorSelect.value = colorSelect.value === key ? "" : key;
        }
        renderWines();
        renderLocations();
    };
    card.addEventListener("click", activate);
    card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            activate();
        }
    });
});

async function restartServer() {
    if (!window.confirm("Restart the cellar server now?")) return;

    const button = byId("restart-server");
    const status = byId("restart-status");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    status.hidden = false;
    setBusyStatus(status, "Requesting a supervised restart…", true);
    try {
        await api("/admin/restart", { method: "POST" });
        setBusyStatus(status, "Server restarting…", true);
        await new Promise((resolve) => window.setTimeout(resolve, 2500));

        for (let attempt = 0; attempt < 45; attempt += 1) {
            try {
                const response = await fetch("/auth/session", {
                    credentials: "same-origin",
                    cache: "no-store",
                });
                if (response.ok) {
                    const session = await response.json();
                    if (session.authenticated) {
                        setBusyStatus(status, "Server is back online. Reloading the cellar…", false);
                        window.setTimeout(() => window.location.reload(), 500);
                        return;
                    }
                }
            } catch {
                // The server is expected to be briefly unreachable while systemd restarts it.
            }
            await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
        throw new Error("The server did not come back online within 45 seconds.");
    } catch (error) {
        setBusyStatus(status, error.message, false);
        button.disabled = false;
        button.removeAttribute("aria-busy");
    }
}

// --- Multi-User Account UI & Password Controls ---

const EYE_OPEN_SVG = `<svg class="eye-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
const EYE_OFF_SVG = `<svg class="eye-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;

function setupPasswordToggles(root = document) {
    root.querySelectorAll(".password-toggle-btn").forEach((btn) => {
        btn.onclick = (e) => {
            e.preventDefault();
            const wrapper = btn.closest(".password-input-wrapper");
            if (!wrapper) return;
            const input = wrapper.querySelector("input");
            if (!input) return;
            const isPassword = input.type === "password";
            input.type = isPassword ? "text" : "password";
            btn.innerHTML = isPassword ? EYE_OFF_SVG : EYE_OPEN_SVG;
            btn.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
            btn.setAttribute("title", isPassword ? "Hide password" : "Show password");
        };
    });
}

function updateUserUI(session) {
    if (!session || !session.authenticated) return;
    state.currentUser = session;

    const usernameEl = byId("current-username");
    if (usernameEl) usernameEl.textContent = session.username || "user";

    const roleEl = byId("current-user-role");
    if (roleEl) {
        roleEl.textContent = session.role || "user";
        roleEl.className = session.role === "admin" ? "badge badge--warn" : "badge";
    }

    const menuUsers = byId("menu-users");
    if (menuUsers) {
        if (session.role === "admin") {
            menuUsers.hidden = false;
            fetchPendingUsersCount();
        } else {
            menuUsers.hidden = true;
        }
    }

    const menuLabels = byId("menu-generate-labels");
    if (menuLabels) {
        menuLabels.hidden = session.role !== "admin";
    }

    const accUser = byId("account-username-display");
    if (accUser) accUser.textContent = session.username || "—";
    const accEmail = byId("account-email-display");
    if (accEmail) accEmail.textContent = session.email || "—";
    const accRole = byId("account-role-display");
    if (accRole) {
        accRole.textContent = session.role || "user";
        accRole.className = session.role === "admin" ? "badge badge--warn" : "badge";
    }

    const addLocBtn = byId("add-location");
    if (addLocBtn) {
        addLocBtn.hidden = session.role !== "admin";
    }

    const deleteBatchBtn = byId("delete-batch-btn");
    if (deleteBatchBtn && session.role !== "admin") {
        deleteBatchBtn.hidden = true;
    }
}

async function fetchPendingUsersCount() {
    try {
        const users = await api("/admin/users?status=pending");
        const count = Array.isArray(users) ? users.length : 0;
        const menuBadge = byId("pending-users-badge");
        const tabBadge = byId("pending-tab-badge");
        if (menuBadge) {
            menuBadge.textContent = count;
            menuBadge.hidden = count === 0;
        }
        if (tabBadge) {
            tabBadge.textContent = count;
        }
    } catch {
        // Silently ignore if not authorized
    }
}

function checkUrlAuthTokens() {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("token") || url.searchParams.get("reset_token");
    if (token) {
        const resetDialog = byId("reset-password-dialog");
        if (resetDialog) {
            byId("reset-token").value = token;
            byId("reset-feedback").textContent = "";
            resetDialog.showModal();
        }
    }
}

function initMultiUserModals() {
    // 1. Request Access Modal
    const reqDialog = byId("request-access-dialog");
    const btnRequestAccess = byId("btn-request-access");
    if (btnRequestAccess && reqDialog) {
        btnRequestAccess.addEventListener("click", () => {
            byId("request-access-form").reset();
            byId("req-feedback").textContent = "";
            reqDialog.showModal();
            byId("req-username").focus();
        });
    }
    byId("req-dialog-close")?.addEventListener("click", () => reqDialog?.close());
    byId("req-cancel")?.addEventListener("click", () => reqDialog?.close());

    byId("request-access-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submitBtn = byId("req-submit");
        const feedback = byId("req-feedback");
        feedback.textContent = "";

        const password = byId("req-password").value;
        const confirm = byId("req-confirm-password").value;
        if (password && password !== confirm) {
            feedback.textContent = "Passwords do not match.";
            return;
        }

        submitBtn.disabled = true;
        try {
            const payload = {
                username: byId("req-username").value.trim(),
                email: byId("req-email").value.trim(),
            };
            if (password) payload.password = password;

            const res = await api("/auth/request-access", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            reqDialog.close();
            notify(res.message || "Access request submitted! You will receive an email once approved.");
            byId("sign-in-error").textContent = "Access request submitted! An administrator will review your request.";
            byId("sign-in-error").style.color = "var(--green)";
        } catch (err) {
            feedback.textContent = err.message;
        } finally {
            submitBtn.disabled = false;
        }
    });

    // 2. Forgot Password Modal
    const forgotDialog = byId("forgot-password-dialog");
    const btnForgotPassword = byId("btn-forgot-password");
    if (btnForgotPassword && forgotDialog) {
        btnForgotPassword.addEventListener("click", () => {
            byId("forgot-password-form").reset();
            byId("forgot-feedback").textContent = "";
            forgotDialog.showModal();
            byId("forgot-identifier").focus();
        });
    }
    byId("forgot-dialog-close")?.addEventListener("click", () => forgotDialog?.close());
    byId("forgot-cancel")?.addEventListener("click", () => forgotDialog?.close());

    byId("forgot-password-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submitBtn = byId("forgot-submit");
        const feedback = byId("forgot-feedback");
        feedback.textContent = "";
        submitBtn.disabled = true;

        try {
            const res = await api("/auth/forgot-password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    identifier: byId("forgot-identifier").value.trim(),
                }),
            });
            forgotDialog.close();
            notify(res.message || "Password recovery email sent.");
        } catch (err) {
            feedback.textContent = err.message;
        } finally {
            submitBtn.disabled = false;
        }
    });

    // 3. Reset Password Modal
    const resetDialog = byId("reset-password-dialog");
    byId("reset-dialog-close")?.addEventListener("click", () => resetDialog?.close());
    byId("reset-cancel")?.addEventListener("click", () => resetDialog?.close());

    byId("reset-password-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submitBtn = byId("reset-submit");
        const feedback = byId("reset-feedback");
        feedback.textContent = "";

        const newPass = byId("reset-new-password").value;
        const confirmPass = byId("reset-confirm-password").value;
        if (newPass !== confirmPass) {
            feedback.textContent = "Passwords do not match.";
            return;
        }

        submitBtn.disabled = true;
        try {
            const res = await api("/auth/reset-password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    token: byId("reset-token").value.trim(),
                    new_password: newPass,
                }),
            });
            resetDialog.close();
            const cleanUrl = window.location.pathname;
            window.history.replaceState({}, document.title, cleanUrl);
            notify(res.message || "Password updated successfully. Please sign in.");
            showSignIn();
        } catch (err) {
            feedback.textContent = err.message;
        } finally {
            submitBtn.disabled = false;
        }
    });

    // 4. My Account Modal
    const accountDialog = byId("account-dialog");
    byId("menu-account")?.addEventListener("click", () => {
        byId("top-menu").open = false;
        byId("change-password-form").reset();
        byId("change-password-feedback").textContent = "";
        if (state.currentUser) {
            updateUserUI(state.currentUser);
        }
        accountDialog?.showModal();
    });
    byId("account-close")?.addEventListener("click", () => accountDialog?.close());
    byId("account-cancel")?.addEventListener("click", () => accountDialog?.close());

    byId("change-password-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submitBtn = byId("change-password-submit");
        const feedback = byId("change-password-feedback");
        feedback.textContent = "";

        const currentPass = byId("change-curr-password").value;
        const newPass = byId("change-new-password").value;
        const confirmPass = byId("change-confirm-password").value;

        if (newPass !== confirmPass) {
            feedback.textContent = "New passwords do not match.";
            return;
        }

        submitBtn.disabled = true;
        try {
            const res = await api("/auth/change-password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    current_password: currentPass,
                    new_password: newPass,
                }),
            });
            accountDialog.close();
            notify(res.message || "Password changed successfully.");
        } catch (err) {
            feedback.textContent = err.message;
        } finally {
            submitBtn.disabled = false;
        }
    });

    // 5. Users & Permissions Modal (Admin Only)
    const usersDialog = byId("users-dialog");
    byId("menu-users")?.addEventListener("click", () => {
        byId("top-menu").open = false;
        usersDialog?.showModal();
        loadUsersManagement();
    });
    byId("users-dialog-close")?.addEventListener("click", () => usersDialog?.close());
    byId("users-done-btn")?.addEventListener("click", () => usersDialog?.close());
    byId("users-refresh-btn")?.addEventListener("click", loadUsersManagement);

    // Tab switching in Users dialog
    const tabPending = byId("tab-btn-pending");
    const tabActive = byId("tab-btn-active");
    const panelPending = byId("panel-pending-users");
    const panelActive = byId("panel-all-users");

    if (tabPending && tabActive) {
        tabPending.addEventListener("click", () => {
            tabPending.classList.add("users-tab-btn--active");
            tabPending.setAttribute("aria-selected", "true");
            tabActive.classList.remove("users-tab-btn--active");
            tabActive.setAttribute("aria-selected", "false");
            if (panelPending) panelPending.hidden = false;
            if (panelActive) panelActive.hidden = true;
        });

        tabActive.addEventListener("click", () => {
            tabActive.classList.add("users-tab-btn--active");
            tabActive.setAttribute("aria-selected", "true");
            tabPending.classList.remove("users-tab-btn--active");
            tabPending.setAttribute("aria-selected", "false");
            if (panelActive) panelActive.hidden = false;
            if (panelPending) panelPending.hidden = true;
        });
    }

    // 6. Generate Bottle Labels Modal (Admin Only)
    const labelsDialog = byId("generate-labels-dialog");
    const labelsForm = byId("generate-labels-form");
    const labelStartInput = byId("label-start-id");
    const labelRangeText = byId("labels-range-text");
    const labelConflictAlert = byId("labels-conflict-alert");
    const labelConflictMsg = byId("labels-conflict-msg");
    const labelForceCheckbox = byId("labels-force-checkbox");
    const labelSubmitBtn = byId("labels-submit-btn");

    function parseLabelPreview(val) {
        const text = String(val || "").trim();
        const match = text.match(/^(.*?)(\d+)$/);
        if (!match) return null;
        const prefix = match[1];
        const numStr = match[2];
        const startNum = parseInt(numStr, 10);
        const width = numStr.length;
        const endNum = startNum + 160 - 1;
        const first = `${prefix}${String(startNum).padStart(width, "0")}`;
        const last = `${prefix}${String(endNum).padStart(width, "0")}`;
        return { first, last, startNum, endNum };
    }

    let checkTimeout = null;
    function updateLabelPreviewAndCheck(val) {
        if (!labelRangeText) return;
        const parsed = parseLabelPreview(val);
        if (!parsed) {
            labelRangeText.textContent = "Enter a starting label ending with a number (e.g. 1048)";
            if (labelConflictAlert) labelConflictAlert.hidden = true;
            return;
        }
        labelRangeText.textContent = `160 labels: ${parsed.first} through ${parsed.last}`;

        if (checkTimeout) clearTimeout(checkTimeout);
        checkTimeout = setTimeout(async () => {
            try {
                const checkRes = await api("/admin/labels/check", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ starting_label: val.trim() }),
                });
                if (checkRes.has_conflicts) {
                    const sample = checkRes.conflicts.slice(0, 5).join(", ");
                    const extra = checkRes.conflicts.length > 5 ? ` (+${checkRes.conflicts.length - 5} more)` : "";
                    if (labelConflictMsg) {
                        labelConflictMsg.textContent = `⚠️ Warning: Numbers ${sample}${extra} were previously generated or already exist in the cellar.`;
                    }
                    if (labelConflictAlert) labelConflictAlert.hidden = false;
                } else {
                    if (labelConflictAlert) labelConflictAlert.hidden = true;
                    if (labelForceCheckbox) labelForceCheckbox.checked = false;
                }
            } catch (err) {
                // If invalid format or network error during debounce, ignore
            }
        }, 300);
    }

    async function openGenerateLabelsDialog() {
        if (!labelsDialog) return;
        const topMenu = byId("top-menu");
        if (topMenu) topMenu.open = false;
        if (labelConflictAlert) labelConflictAlert.hidden = true;
        if (labelForceCheckbox) labelForceCheckbox.checked = false;
        if (labelSubmitBtn) labelSubmitBtn.disabled = true;
        labelsDialog.showModal();

        try {
            const info = await api("/admin/labels/info");
            const startVal = info.next_starting_label || "1000";
            if (labelStartInput) {
                labelStartInput.value = startVal;
                updateLabelPreviewAndCheck(startVal);
            }
        } catch (err) {
            if (labelStartInput) {
                labelStartInput.value = "1000";
                updateLabelPreviewAndCheck("1000");
            }
        } finally {
            if (labelSubmitBtn) labelSubmitBtn.disabled = false;
            if (labelStartInput) {
                labelStartInput.focus();
                labelStartInput.select();
            }
        }
    }

    byId("menu-generate-labels")?.addEventListener("click", openGenerateLabelsDialog);
    byId("labels-dialog-close")?.addEventListener("click", () => labelsDialog?.close());
    byId("labels-cancel-btn")?.addEventListener("click", () => labelsDialog?.close());

    labelStartInput?.addEventListener("input", (e) => {
        updateLabelPreviewAndCheck(e.target.value);
    });

    labelsForm?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const startVal = labelStartInput?.value?.trim() || "";
        if (!startVal) {
            notify("Please enter a starting label.", "error");
            return;
        }

        const force = Boolean(labelForceCheckbox?.checked);
        if (labelSubmitBtn) {
            labelSubmitBtn.disabled = true;
            labelSubmitBtn.setAttribute("data-orig-text", labelSubmitBtn.textContent);
            labelSubmitBtn.textContent = "Generating PDF...";
        }

        try {
            const res = await fetch("/admin/labels/generate", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "WineCellar",
                },
                body: JSON.stringify({ starting_label: startVal, force }),
                credentials: "same-origin",
            });

            if (res.status === 409) {
                const errData = await res.json().catch(() => ({}));
                if (labelConflictAlert) labelConflictAlert.hidden = false;
                if (labelConflictMsg) {
                    labelConflictMsg.textContent = `⚠️ ${errData.detail || "Conflicts with existing bottles or numbers."}`;
                }
                if (labelForceCheckbox) labelForceCheckbox.checked = true;
                notify("Conflicts detected. Check 'Generate anyway' to proceed.", "error");
                return;
            }

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || "Failed to generate labels.");
            }

            const blob = await res.blob();
            const disp = res.headers.get("Content-Disposition");
            const match = disp && disp.match(/filename="?([^";]+)"?/);
            const filename = match ? match[1] : `labels_${startVal}.pdf`;

            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);

            const firstLbl = res.headers.get("X-First-Label") || startVal;
            const lastLbl = res.headers.get("X-Last-Label") || "";
            notify(`Generated & downloaded 160 labels (${firstLbl} through ${lastLbl})!`);
            labelsDialog?.close();
        } catch (err) {
            notify(err.message, "error");
        } finally {
            if (labelSubmitBtn) {
                labelSubmitBtn.disabled = false;
                labelSubmitBtn.textContent = labelSubmitBtn.getAttribute("data-orig-text") || "Generate & Download PDF ↗";
            }
        }
    });
}

async function loadUsersManagement() {
    const listPending = byId("pending-users-list");
    const tbodyAll = byId("all-users-tbody");
    if (!listPending || !tbodyAll) return;

    try {
        const users = await api("/admin/users");
        const pendingUsers = users.filter((u) => u.status === "pending");

        // Update counts
        const countPending = pendingUsers.length;
        byId("pending-tab-badge").textContent = countPending;
        byId("all-users-count").textContent = users.length;
        const menuBadge = byId("pending-users-badge");
        if (menuBadge) {
            menuBadge.textContent = countPending;
            menuBadge.hidden = countPending === 0;
        }

        // Render Pending Requests
        listPending.innerHTML = "";
        if (pendingUsers.length === 0) {
            listPending.innerHTML = `
                <div class="empty-state" style="padding: 24px 0; text-align: center; color: var(--muted);">
                    <p style="margin: 0; font-size: 13px;">No pending user access requests.</p>
                </div>`;
        } else {
            pendingUsers.forEach((user) => {
                const card = makeElement("div", "pending-user-card");
                const info = makeElement("div", "pending-user-info");
                info.innerHTML = `
                    <strong>${user.username}</strong>
                    <span>${user.email} &bull; Requested ${formatDate(user.created_at) || "recently"}</span>
                `;

                const actions = makeElement("div", "pending-user-actions");

                const approveBtn = makeElement("button", "button button--small button--wine", "Approve 🍷");
                approveBtn.type = "button";
                approveBtn.onclick = async () => {
                    approveBtn.disabled = true;
                    try {
                        await api(`/admin/users/${user.id}/approve`, { method: "POST" });
                        notify(`Approved access for ${user.username}. Confirmation email sent.`);
                        loadUsersManagement();
                    } catch (err) {
                        notify(err.message, "warn");
                        approveBtn.disabled = false;
                    }
                };

                const rejectBtn = makeElement("button", "button button--small button--outline", "Decline");
                rejectBtn.type = "button";
                rejectBtn.onclick = async () => {
                    if (!confirm(`Decline access request for ${user.username}?`)) return;
                    rejectBtn.disabled = true;
                    try {
                        await api(`/admin/users/${user.id}/reject`, { method: "POST" });
                        notify(`Declined request for ${user.username}.`);
                        loadUsersManagement();
                    } catch (err) {
                        notify(err.message, "warn");
                        rejectBtn.disabled = false;
                    }
                };

                actions.append(approveBtn, rejectBtn);
                card.append(info, actions);
                listPending.append(card);
            });
        }

        // Render All Users Table
        tbodyAll.innerHTML = "";
        users.forEach((user) => {
            const tr = document.createElement("tr");

            const tdUser = document.createElement("td");
            tdUser.innerHTML = `<strong>${user.username}</strong>${user.username === "cellar" ? ' <span style="font-size: 10px; color: var(--gold);">(Root)</span>' : ""}`;

            const tdEmail = document.createElement("td");
            tdEmail.textContent = user.email || "—";

            const tdRole = document.createElement("td");
            tdRole.innerHTML = `<span class="badge ${user.role === "admin" ? "badge--warn" : ""}">${user.role}</span>`;

            const tdStatus = document.createElement("td");
            let statusBadge = "badge--muted";
            if (user.status === "approved") statusBadge = "badge--success";
            else if (user.status === "pending") statusBadge = "badge--warn";
            tdStatus.innerHTML = `<span class="badge ${statusBadge}">${user.status}</span>`;

            const tdLogin = document.createElement("td");
            tdLogin.textContent = user.last_login ? formatDate(user.last_login) : "Never";

            const tdActions = document.createElement("td");
            tdActions.style.textAlign = "right";

            if (user.username !== "cellar" && state.currentUser?.username !== user.username) {
                const isApproved = user.status === "approved";
                const toggleStatusBtn = makeElement(
                    "button",
                    "text-button user-action-btn",
                    isApproved ? "Deactivate" : "Activate"
                );
                toggleStatusBtn.type = "button";
                toggleStatusBtn.onclick = async () => {
                    const nextStatus = isApproved ? "disabled" : "approved";
                    try {
                        await api(`/admin/users/${user.id}/status`, {
                            method: "PATCH",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ status: nextStatus }),
                        });
                        notify(`Updated status for ${user.username}.`);
                        loadUsersManagement();
                    } catch (err) {
                        notify(err.message, "warn");
                    }
                };

                const deleteBtn = makeElement("button", "text-button user-action-btn", "Delete");
                deleteBtn.type = "button";
                deleteBtn.style.color = "var(--wine-light)";
                deleteBtn.onclick = async () => {
                    if (!confirm(`Permanently delete account for ${user.username}?`)) return;
                    try {
                        await api(`/admin/users/${user.id}`, { method: "DELETE" });
                        notify(`Deleted user ${user.username}.`);
                        loadUsersManagement();
                    } catch (err) {
                        notify(err.message, "warn");
                    }
                };

                tdActions.append(toggleStatusBtn, deleteBtn);
            } else {
                tdActions.innerHTML = '<span style="color: var(--faint); font-size: 11px;">Protected</span>';
            }

            tr.append(tdUser, tdEmail, tdRole, tdStatus, tdLogin, tdActions);
            tbodyAll.append(tr);
        });
    } catch (err) {
        notify("Could not load users list: " + err.message, "warn");
    }
}

async function start() {
    setupPasswordToggles();
    initMultiUserModals();
    initRemovalDialog();
    checkUrlAuthTokens();
    showSignIn();
    try {
        const session = await api("/auth/session");
        if (session.authenticated) {
            updateUserUI(session);
            showCellar();
            await Promise.all([loadWines(), loadLocations()]);
            checkUrlBottleCheckout();
        } else {
            showSignIn();
        }
    } catch (error) {
        if (!signIn.hidden) {
            byId("sign-in-error").textContent =
                "Could not reach the cellar service. Refresh to try again.";
        }
    }
}

start();











// --- Grapeminds Explorer ---
function showExplorer() {
    const cellar = byId("cellar");
    const explorer = byId("grapeminds-explorer");
    if (cellar) cellar.hidden = true;
    if (explorer) {
        explorer.hidden = false;
        explorer.style.display = "block";
    }
    const topMenu = byId("top-menu");
    if (topMenu) topMenu.open = false;

    const backBtn = byId("explorer-back");
    const subtitle = byId("explorer-subtitle");
    if (state.selectingWineForForm) {
        if (state.editingWine?.editGroup) {
            if (backBtn) backBtn.textContent = "← Back to group edit (keep current data)";
            if (subtitle) subtitle.textContent = "Select a wine from Grapeminds to update this group of bottles.";
        } else if (state.editingWine) {
            if (backBtn) backBtn.textContent = "← Back to bottle edit (keep current data)";
            if (subtitle) subtitle.textContent = "Select a wine from Grapeminds to update this bottle.";
        } else {
            if (backBtn) backBtn.textContent = "← Back to bottle form (keep current data)";
            if (subtitle) subtitle.textContent = "Select a wine from Grapeminds to populate your bottle entry form.";
        }
    } else {
        if (backBtn) backBtn.textContent = "← Back to cellar";
        if (subtitle) subtitle.textContent = "Discover new wines from the Grapeminds catalog.";
    }

    const query = byId("explorer-query");
    if (query) query.focus();
}

function hideExplorer() {
    const explorer = byId("grapeminds-explorer");
    const cellar = byId("cellar");
    if (explorer) {
        explorer.hidden = true;
        explorer.style.display = "none";
    }
    if (cellar) cellar.hidden = false;
    const query = byId("explorer-query");
    if (query) query.value = "";

    if (state.selectingWineForForm) {
        state.selectingWineForForm = false;
        if (!dialog.open) {
            dialog.showModal();
        }
    }
}

function formatProviderLabel(provider) {
    if (provider === "wineapi") return "WineAPI.io";
    if (provider === "grapeminds") return "Grapeminds";
    return "Catalog";
}

function renderExplorerResults(results) {
    const body = byId("explorer-results-body");
    const table = byId("explorer-results-table");
    const empty = byId("explorer-empty");
    body.replaceChildren();
    if (!results || results.length === 0) {
        table.style.display = "none";
        empty.style.display = "block";
        empty.replaceChildren(makeElement("h3", "", "No wines found in either WineAPI.io or Grapeminds."));
        return;
    }
    empty.style.display = "none";
    table.style.display = "table";
    for (const wine of results) {
        const row = makeElement("tr", "explorer-row");
        row.dataset.grapemindsId = wine.id || "";
        const provider = wine.provider || "grapeminds";
        const styleParts = [wine.region, normalizeWineColor(wine.color), wine.vintage].filter(
            (part) => part !== null && part !== undefined && String(part).trim() !== "",
        );

        const idTd = makeElement("td", "");
        const shortId = String(wine.id ?? "").length > 12
            ? `${String(wine.id).slice(0, 8)}…`
            : String(wine.id ?? "");
        const providerTag = makeElement(
            "span",
            "status-pill",
            formatProviderLabel(provider),
        );
        providerTag.style.marginRight = "6px";
        idTd.append(providerTag, makeElement("span", "", shortId));
        idTd.title = String(wine.id ?? "");

        row.append(
            idTd,
            makeElement("td", "", wine.name ?? ""),
            makeElement("td", "", wine.producer ?? ""),
            makeElement("td", "", styleParts.join(" · ") || "—"),
        );

        const actionTd = makeElement("td", "explorer-action-cell");
        if (state.selectingWineForForm && wine.id) {
            const selectBtn = makeElement("button", "button button--small button--wine", "Select ↗");
            selectBtn.type = "button";
            selectBtn.addEventListener("click", (event) => {
                event.stopPropagation();
                selectWineFromExplorer(wine.id, null, provider);
            });
            actionTd.append(selectBtn);
        } else if (wine.id) {
            const viewBtn = makeElement("button", "button button--small button--outline", "View");
            viewBtn.type = "button";
            viewBtn.addEventListener("click", (event) => {
                event.stopPropagation();
                openExplorerDetail(wine.id, provider);
            });
            actionTd.append(viewBtn);
        }
        row.append(actionTd);

        if (wine.id) {
            row.addEventListener("click", () => openExplorerDetail(wine.id, provider));
        } else {
            row.classList.add("explorer-row--disabled");
        }
        body.append(row);
    }
}

async function runExplorerSearch() {
    const queryInput = byId("explorer-query");
    const q = (queryInput.value || "").trim();
    if (q.length < 2) {
        notify("Enter at least 2 characters to search.", "error");
        return;
    }
    const providerSelect = byId("explorer-provider");
    const requestedProvider = providerSelect?.value || "wineapi";
    const notice = byId("explorer-provider-notice");
    if (notice) {
        notice.hidden = true;
        notice.textContent = "";
    }

    const table = byId("explorer-results-table");
    const empty = byId("explorer-empty");
    const loading = byId("explorer-loading");
    const button = byId("explorer-button");
    table.style.display = "none";
    empty.style.display = "none";
    loading.style.display = "block";
    if (button) button.disabled = true;
    try {
        const payload = await api(
            `/grapeminds/search?q=${encodeURIComponent(q)}&provider=${encodeURIComponent(requestedProvider)}&include_meta=true`,
        );
        loading.style.display = "none";
        const results = Array.isArray(payload) ? payload : (payload?.results || []);
        if (payload?.fallback_used && notice) {
            const fromLabel = formatProviderLabel(payload.requested_provider);
            const toLabel = formatProviderLabel(payload.active_provider);
            notice.textContent = `No matches in ${fromLabel} — showing fallback results from ${toLabel}.`;
            notice.hidden = false;
        }
        renderExplorerResults(results);
    } catch (error) {
        loading.style.display = "none";
        const msg =
            error.status === 401 ? "Your session expired. Please sign in again." :
            error.status === 403 ? "Catalog access is protected. Please sign in." :
            (error.message || "Catalog search failed.");
        notify(msg, "error");
        empty.style.display = "block";
        empty.replaceChildren(makeElement("h3", "", "Search failed."));
    } finally {
        if (button) button.disabled = false;
    }
}

async function openExplorerDetail(grapemindsId, provider = null) {
    const modal = byId("explorer-modal");
    const content = byId("explorer-detail-content");
    modal.style.display = "block";
    content.replaceChildren(makeElement("p", "", `Loading ${grapemindsId}…`));
    try {
        const providerParam = provider ? `?provider=${encodeURIComponent(provider)}` : "";
        const metadata = await api(`/grapeminds/details/${encodeURIComponent(grapemindsId)}${providerParam}`);
        renderExplorerDetail(content, metadata);
    } catch (error) {
        content.replaceChildren(makeElement("p", "", error.message || "Could not load details."));
    }
}

function renderExplorerDetail(container, metadata) {
    container.replaceChildren();
    if (!metadata) return;

    const title = metadata.name || metadata.winery || metadata.id || "Wine details";
    container.append(makeElement("h3", "", title));

    const subtitleParts = [
        metadata.winery,
        metadata.region,
        metadata.country_of_origin,
    ].filter(Boolean);
    if (subtitleParts.length) {
        container.append(makeElement("p", "explorer-detail-id", subtitleParts.join(" \u00b7 ")));
    }
    if (metadata.id) {
        container.append(makeElement("p", "explorer-detail-id", `Grapeminds ID: ${metadata.id}`));
    }

    // Grapeminds wraps long prose in {"text": "..."}; unwrap so we never show raw JSON.
    const prose = (value) => {
        if (value === null || value === undefined) return "";
        if (typeof value === "string") return value.trim();
        if (typeof value === "object" && typeof value.text === "string") return value.text.trim();
        return "";
    };
    // grape_varieties is [{id, name}, ...]
    const varieties = (value) => {
        if (!Array.isArray(value)) return "";
        return value
            .map((item) => (typeof item === "string" ? item : item && item.name))
            .filter(Boolean)
            .join(", ");
    };
    const vintage = metadata.vintage ? String(metadata.vintage) : "";

    const priceSummary = metadata.price_range_display
        || (metadata.market_price != null ? `$${Number(metadata.market_price).toFixed(2)}` : "");
    const grid = makeElement("dl", "explorer-detail-grid");
    const rows = [
        ["Source", formatProviderLabel(metadata.provider || "grapeminds")],
        ["Grapes", varieties(metadata.grape_varieties) || metadata.grape_type],
        ["Colour", normalizeWineColor(metadata.color) || metadata.color],
        ["Vintage", vintage],
        ["Market price", priceSummary],
        ["Description", prose(metadata.description) || prose(metadata.notes)],
        ["Pairing", prose(metadata.pairing)],
        ["Tasting notes", prose(metadata.grapeminds_tasting_notes)],
        ["Drinking window", prose(metadata.drinking_window)],
    ];
    for (const [label, value] of rows) {
        if (!value) continue;
        grid.append(makeElement("dt", "", label));
        grid.append(makeElement("dd", "", value));
    }
    container.append(grid);

    // flavor_profile is a 0-10 scale: render it as readable bars.
    const profile = metadata.flavor_profile;
    if (profile && typeof profile === "object") {
        const labels = {
            sweetness: "Sweetness",
            acidity: "Acidity",
            tannins: "Tannins",
            alcohol: "Alcohol",
            body: "Body",
            finish: "Finish",
        };
        const entries = Object.entries(labels).filter(([key]) => {
            const value = profile[key];
            return typeof value === "number" && Number.isFinite(value);
        });
        if (entries.length) {
            const section = makeElement("div", "explorer-profile");
            section.append(makeElement("h4", "", "Flavour profile"));
            for (const [key, label] of entries) {
                const raw = Number(profile[key]);
                const pct = Math.max(0, Math.min(100, (raw / 10) * 100));
                const row = makeElement("div", "explorer-profile__row");
                row.append(makeElement("span", "explorer-profile__label", label));
                const track = makeElement("span", "explorer-profile__track");
                const fill = makeElement("span", "explorer-profile__fill");
                fill.style.width = `${pct}%`;
                track.append(fill);
                row.append(track);
                row.append(makeElement("span", "explorer-profile__value", `${raw}`));
                section.append(row);
            }
            container.append(section);
        }
    }

    if (!grid.children.length) {
        container.append(makeElement("p", "wine-metadata__empty",
            "No additional details are available for this record."));
    }

    const modalActions = makeElement("div", "dialog__actions explorer-modal-actions");
    if (state.selectingWineForForm && metadata.id) {
        const selectLabel = state.editingWine?.editGroup
            ? "Select this wine for group ↗"
            : "Select this wine for bottle ↗";
        const selectModalBtn = makeElement("button", "button button--wine", selectLabel);
        selectModalBtn.type = "button";
        selectModalBtn.addEventListener("click", () => {
            selectWineFromExplorer(metadata.id, metadata);
        });
        modalActions.append(selectModalBtn);
    }
    const closeBtn = makeElement("button", "button button--outline", "Close");
    closeBtn.type = "button";
    closeBtn.addEventListener("click", closeExplorerDetail);
    modalActions.append(closeBtn);
    container.append(modalActions);
}

function closeExplorerDetail() {
    const modal = byId("explorer-modal");
    if (modal) modal.style.display = "none";
}

async function selectWineFromExplorer(grapemindsId, preloadedMetadata = null, provider = null) {
    let metadata = preloadedMetadata;
    if (!metadata) {
        try {
            const providerParam = provider ? `?provider=${encodeURIComponent(provider)}` : "";
            metadata = await api(`/grapeminds/details/${encodeURIComponent(grapemindsId)}${providerParam}`);
        } catch (error) {
            notify(error.message || "Could not load catalog wine details.", "error");
            return;
        }
    }
    closeExplorerDetail();
    hideExplorer();
    handleGrapemindsSelectionForForm(metadata);
}

function handleGrapemindsSelectionForForm(metadata) {
    if (!metadata) return;
    state.selectingWineForForm = false;

    if (!dialog.open) {
        dialog.showModal();
    }

    const form = byId("manual-form");
    const preview = byId("grapeminds-preview");
    const status = byId("scan-status");
    const idInput = byId("grapeminds-id-input");
    const prevGrapemindsId = idInput ? idInput.value : "";

    const getCurrentValue = (name) => {
        if (name === "flavor_profile") {
            const profile = {};
            ["sweetness", "acidity", "tannins", "alcohol", "body", "finish"].forEach((key) => {
                const val = form.elements.namedItem(`flavor_${key}`)?.value;
                if (val !== "" && val !== null && val !== undefined) {
                    profile[key] = Number(val);
                }
            });
            return Object.keys(profile).length ? profile : null;
        }
        const input = form.elements.namedItem(name);
        return input?.value || "";
    };

    renderGrapemindsConflictReview(preview, metadata, getCurrentValue, {
        onApply: (selected) => {
            applyGrapemindsToForm(metadata, selected);
            if (idInput) idInput.value = metadata.id || "";
            const targetDesc = state.editingWine?.editGroup
                ? "group edit form"
                : state.editingWine
                    ? "bottle edit form"
                    : "bottle form";
            const reviewPrompt = state.editingWine
                ? "Review and save your changes."
                : "Review and save your bottle.";
            setBusyStatus(
                status,
                `Grapeminds details copied for "${metadata.name || metadata.winery || metadata.id}". ${reviewPrompt}`,
                false,
            );
            status.hidden = false;
            notify(`Grapeminds details applied to ${targetDesc}.`, "success");
        },
        onCancel: () => {
            if (idInput) idInput.value = prevGrapemindsId;
            setBusyStatus(
                status,
                "Grapeminds request cancelled. Prior form data was preserved.",
                false,
            );
            status.hidden = false;
            notify("Grapeminds request cancelled. Prior form data was kept.", "neutral");
        },
    });
}

function renderGrapemindsConflictReview(container, metadata, getCurrentValue, { onApply, onCancel }) {
    container.replaceChildren();

    const headingText = [
        metadata.winery,
        metadata.name,
        metadata.vintage,
    ].filter(Boolean).join(" · ") || `Grapeminds record ${metadata.id || ""}`;

    const fields = grapemindsPreviewFields(metadata, getCurrentValue);

    const enrichedFields = fields.map((field) => {
        const isBlank = isBlankValue(field.currentValue);
        let isConflict = false;
        if (!isBlank) {
            if (field.name === "flavor_profile") {
                isConflict = JSON.stringify(field.currentValue) !== JSON.stringify(field.displayValue);
            } else {
                const curStr = String(field.currentValue).trim().toLowerCase();
                const newStr = String(field.displayValue).trim().toLowerCase();
                isConflict = curStr !== newStr;
            }
        }
        return {
            ...field,
            isConflict,
            isChecked: !isConflict && !isBlankValue(field.displayValue),
        };
    });

    const hasConflicts = enrichedFields.some((f) => f.isConflict);

    const head = makeElement("div", "grapeminds-preview__header");
    head.append(makeElement("h4", "grapeminds-preview__heading", `Grapeminds: ${headingText}`));
    if (metadata.id) {
        head.append(makeElement("span", "grapeminds-preview__id-tag", `ID: ${metadata.id}`));
    }
    container.append(head);

    if (hasConflicts) {
        const alertBox = makeElement("div", "grapeminds-conflict-alert");
        alertBox.append(makeElement("strong", "", "⚠️ Conflicting data detected"));
        alertBox.append(makeElement(
            "p",
            "",
            "Some details from Grapeminds differ from what is currently in your form. Conflicting fields are unchecked by default to preserve your existing entries. Check any fields you want to replace with Grapeminds data, or click Cancel to reject all Grapeminds data.",
        ));
        container.append(alertBox);
    } else {
        const infoBox = makeElement("div", "grapeminds-new-alert");
        infoBox.append(makeElement(
            "p",
            "grapeminds-preview__hint",
            "Review details to copy to your bottle form. All fields are checked by default:",
        ));
        container.append(infoBox);
    }

    const list = makeElement("div", "grapeminds-preview__fields");
    const selection = [];

    enrichedFields.forEach((field) => {
        const row = makeElement(
            "label",
            `grapeminds-preview__field ${field.isConflict ? "grapeminds-preview__field--conflict" : ""}`,
        );
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = field.isChecked;

        const content = makeElement("div", "grapeminds-preview__field-content");
        const labelRow = makeElement("div", "grapeminds-preview__field-header");
        const title = makeElement("strong", "grapeminds-preview__field-title", field.label);
        labelRow.append(title);

        if (field.isConflict) {
            const badge = makeElement("span", "conflict-badge", "Conflict");
            labelRow.append(badge);
        }
        content.append(labelRow);

        const val = makeElement("div", "grapeminds-preview__value", field.displayValue);
        content.append(val);

        if (field.isConflict) {
            const curr = makeElement(
                "div",
                "conflict-current",
                `Current in form: "${field.currentValue}"`,
            );
            content.append(curr);
        }

        row.append(checkbox, content);
        list.append(row);
        selection.push({ ...field, checkbox });
    });
    container.append(list);

    const actions = makeElement("div", "grapeminds-preview__actions");
    const applyButton = makeElement(
        "button",
        "button button--small button--wine",
        hasConflicts ? "Save selected data to form" : "Apply to form",
    );
    applyButton.type = "button";
    applyButton.addEventListener("click", () => {
        const selected = selection.filter(({ checkbox }) => checkbox.checked);
        container.hidden = true;
        container.replaceChildren();
        onApply(selected);
    });

    const cancelButton = makeElement(
        "button",
        "button button--small button--outline",
        "Cancel Grapeminds request",
    );
    cancelButton.type = "button";
    cancelButton.addEventListener("click", () => {
        container.hidden = true;
        container.replaceChildren();
        onCancel();
    });

    actions.append(applyButton, cancelButton);
    container.append(actions);
    container.hidden = false;
}

function setupExplorer() {
    // Menu button must reveal the explorer and close the top-menu details panel.
    // The earlier Explorer stub wired this via DOMContentLoaded, but my refactor
    // replaced that block entirely, so the menu button became a no-op. Re-wire it.
    const openExplorerBtn = byId("open-grapeminds-explorer");
    if (openExplorerBtn) {
        openExplorerBtn.addEventListener("click", () => {
            state.selectingWineForForm = true;
            const form = byId("manual-form");
            const nameVal = form.elements.namedItem("name")?.value?.trim() || "";
            const wineryVal = form.elements.namedItem("winery")?.value?.trim() || "";
            const searchSeed = nameVal || wineryVal;

            if (dialog.open) {
                dialog.close("explorer");
            }

            showExplorer();

            if (searchSeed) {
                const queryInput = byId("explorer-query");
                if (queryInput) {
                    queryInput.value = searchSeed;
                    runExplorerSearch();
                }
            }
        });
    }

    const menuBtn = byId("menu-explorer");
    if (menuBtn) {
        menuBtn.addEventListener("click", (event) => {
            event.preventDefault();
            showExplorer();
        });
    }
    const button = byId("explorer-button");
    if (button) button.addEventListener("click", runExplorerSearch);
    const input = byId("explorer-query");
    if (input) {
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                runExplorerSearch();
            }
        });
    }
    const providerSelect = byId("explorer-provider");
    if (providerSelect) {
        providerSelect.addEventListener("change", () => {
            if ((byId("explorer-query")?.value || "").trim().length >= 2) {
                runExplorerSearch();
            }
        });
    }
    const backBtn = byId("explorer-back");
    if (backBtn) backBtn.addEventListener("click", hideExplorer);
    const cancelBtn = byId("explorer-cancel");
    if (cancelBtn) {
        cancelBtn.addEventListener("click", () => {
            closeExplorerDetail();
            hideExplorer();
        });
    }
    const cancelBottomBtn = byId("explorer-cancel-bottom");
    if (cancelBottomBtn) {
        cancelBottomBtn.addEventListener("click", () => {
            closeExplorerDetail();
            hideExplorer();
        });
    }
    const closeBtn = byId("explorer-close");
    if (closeBtn) closeBtn.addEventListener("click", closeExplorerDetail);
    const modal = byId("explorer-modal");
    if (modal) {
        modal.addEventListener("click", (event) => {
            if (event.target === modal) closeExplorerDetail();
        });
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupExplorer);
} else {
    setupExplorer();
}
