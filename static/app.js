// Toggle job details in curated feed
window.toggleJobDetails = (jobId) => {
  const container = document.getElementById(`job-details-${jobId}`);
  const btn = document.getElementById(`view-details-btn-${jobId}`);
  if (!container) return;

  if (container.dataset.open === "true") {
    container.innerHTML = "";
    container.dataset.open = "false";
    if (btn) {
      btn.textContent = "View Details";
      btn.classList.remove("active");
    }
  } else {
    if (btn) btn.textContent = "Loading...";
    fetch(`/job/${jobId}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load details");
        return res.text();
      })
      .then((html) => {
        container.innerHTML = html;
        window.htmx?.process(container);
        container.dataset.open = "true";
        if (btn) {
          btn.textContent = "Hide Details";
          btn.classList.add("active");
        }
      })
      .catch(() => {
        if (btn) {
          btn.textContent = "View Details";
          btn.classList.remove("active");
        }
      });
  }
};

window.closeJobDetails = (jobId) => {
  const container = document.getElementById(`job-details-${jobId}`);
  const btn = document.getElementById(`view-details-btn-${jobId}`);
  if (container) {
    container.innerHTML = "";
    container.dataset.open = "false";
  }
  if (btn) {
    btn.textContent = "View Details";
    btn.classList.remove("active");
  }
};

// ==============================================================================
// Interactive Drag & Drop Controller for Pipeline Kanban Board
// ==============================================================================
(function initKanbanDragAndDrop() {
  let draggedCard = null;

  document.addEventListener("dragstart", (e) => {
    const card = e.target.closest(".kanban-card");
    if (!card?.draggable) return;

    draggedCard = card;
    window.isDraggingCard = true;
    card.classList.add("is-dragging");
    if (e.dataTransfer) {
      e.dataTransfer.setData("text/plain", card.dataset.appId || "");
      e.dataTransfer.effectAllowed = "move";
    }
  });

  document.addEventListener("dragend", (e) => {
    const card = e.target.closest(".kanban-card");
    if (card) {
      card.classList.remove("is-dragging");
    }
    document.querySelectorAll(".kanban-column").forEach((col) => {
      col.classList.remove("drag-over");
    });
    setTimeout(() => {
      window.isDraggingCard = false;
      draggedCard = null;
    }, 50);
  });

  document.addEventListener("dragover", (e) => {
    const column = e.target.closest(".kanban-column");
    if (!column || !draggedCard) return;

    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = "move";
    }

    document.querySelectorAll(".kanban-column").forEach((col) => {
      if (col === column) {
        col.classList.add("drag-over");
      } else {
        col.classList.remove("drag-over");
      }
    });
  });

  document.addEventListener("dragleave", (e) => {
    const column = e.target.closest(".kanban-column");
    if (column && !column.contains(e.relatedTarget)) {
      column.classList.remove("drag-over");
    }
  });

  document.addEventListener("drop", (e) => {
    const column = e.target.closest(".kanban-column");
    if (!column || !draggedCard) return;

    e.preventDefault();
    column.classList.remove("drag-over");

    const appId = draggedCard.dataset.appId;
    const targetStage = column.dataset.stage;
    const currentStage = draggedCard.dataset.currentStage;

    if (!appId || !targetStage || targetStage === currentStage) return;

    // Optimistically move card in the DOM immediately
    const targetCardsList = column.querySelector(".kanban-cards-list");
    if (targetCardsList) {
      const placeholder = targetCardsList.querySelector(".empty-column-placeholder");
      if (placeholder) {
        placeholder.remove();
      }
      targetCardsList.appendChild(draggedCard);
      draggedCard.dataset.currentStage = targetStage;
    }

    // Read active search & filter values from tracker form if present
    const filterForm = document.getElementById("tracker-filter-form");
    const params = new URLSearchParams();
    if (filterForm) {
      const formData = new FormData(filterForm);
      for (const [k, v] of formData.entries()) {
        if (typeof v === "string") params.append(k, v);
      }
    }
    const queryStr = params.toString() ? `?${params.toString()}` : "";

    if (window.htmx) {
      window.htmx.ajax("POST", `/applications/${appId}/status${queryStr}`, {
        values: { new_status: targetStage },
        target: "#applications-content",
        swap: "innerHTML",
        headers: { "HX-Target": "applications-content" },
      });
    } else {
      const formData = new FormData();
      formData.append("new_status", targetStage);
      fetch(`/applications/${appId}/status${queryStr}`, {
        method: "POST",
        body: formData,
      }).then(() => window.location.reload());
    }
  });
})();

// ==============================================================================
// Search Profile Form Dirtiness Tracking & Scrape Modal Controller
// ==============================================================================
window.initProfileFormState = () => {
  const form = document.getElementById("profile-form");
  if (!form) return;
  const formData = new FormData(form);
  const params = new URLSearchParams();
  for (const [k, v] of formData.entries()) {
    if (typeof v === "string") {
      params.append(k, v);
    }
  }
  form.dataset.initialState = params.toString();
};

window.isProfileFormDirty = () => {
  const form = document.getElementById("profile-form");
  if (!form?.dataset.initialState) return false;
  const formData = new FormData(form);
  const params = new URLSearchParams();
  for (const [k, v] of formData.entries()) {
    if (typeof v === "string") {
      params.append(k, v);
    }
  }
  return params.toString() !== form.dataset.initialState;
};

window.triggerProfileScrape = (profileId) => {
  const target = document.getElementById("scrape-progress-container");
  if (window.htmx && target) {
    window.htmx.ajax("POST", `/scrape/start?profile_id=${profileId}`, target);
  }
};

window.handleProfileScrape = (profileId) => {
  if (window.isProfileFormDirty()) {
    const modal = document.getElementById("unsaved-profile-modal");
    if (modal) {
      modal.showModal();
      return;
    }
  }
  window.triggerProfileScrape(profileId);
};

window.scrapeWithoutSaving = (profileId) => {
  const modal = document.getElementById("unsaved-profile-modal");
  if (modal) modal.close();
  window.triggerProfileScrape(profileId);
};

window.saveAndScrapeProfile = (profileId) => {
  const modal = document.getElementById("unsaved-profile-modal");
  if (modal) modal.close();

  const form = document.getElementById("profile-form");
  if (!form) {
    window.triggerProfileScrape(profileId);
    return;
  }

  const actionUrl = form.getAttribute("action") || `/profiles/${profileId}`;
  const formData = new FormData(form);

  fetch(actionUrl, {
    method: "POST",
    body: formData,
  })
    .then((res) => {
      if (!res.ok) throw new Error("Failed to save profile");
      return res.text();
    })
    .then((html) => {
      const container = document.getElementById("profile-sidebar-container");
      if (container) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const oobToast = doc.getElementById("save-status-toast");
        if (oobToast) {
          const globalToast = document.getElementById("save-status-toast");
          if (globalToast) {
            globalToast.innerHTML = oobToast.innerHTML;
          }
          oobToast.remove();
        }
        container.innerHTML = doc.body.innerHTML;
        if (window.htmx) window.htmx.process(container);
      }
      window.initProfileFormState();
      window.triggerProfileScrape(profileId);
    })
    .catch((err) => {
      console.error("Error saving profile before scrape:", err);
      window.triggerProfileScrape(profileId);
    });
};

// Keep native checkbox dropdown state, URL hydration, and form reset in sync.
function updateCurationDropdownSummary(details) {
  const summary = details.querySelector("[data-filter-summary]");
  const allOption = details.querySelector("[data-filter-all]");
  const selected = Array.from(details.querySelectorAll("input[name]")).filter(
    (option) => option.checked,
  );

  if (!summary || !allOption) return;

  allOption.checked = selected.length === 0;
  if (selected.length === 0) {
    summary.textContent = details.dataset.allLabel;
  } else if (selected.length === 1) {
    summary.textContent =
      selected[0].closest("label")?.querySelector("span")?.textContent.trim() ?? selected[0].value;
  } else {
    summary.textContent = `${selected.length} selected`;
  }
}

window.resetCurationFilters = () => {
  const form = document.getElementById("curation-form");
  if (!form) return;
  form.reset();
  form.querySelector("#curation-search").value = "";
  for (const [id, value] of [
    ["sort-select", "newest"],
    ["group-select", "none"],
    ["date-select", "all"],
    ["staleness-select", "all"],
  ]) {
    form.querySelector(`#${id}`).value = value;
  }
  for (const details of form.querySelectorAll(".curation-dropdown")) {
    for (const option of details.querySelectorAll("input[name]")) option.checked = false;
    details.open = false;
    updateCurationDropdownSummary(details);
  }
  form.querySelector("#include_unspecified").checked = true;
  form.querySelector("#show_hidden").checked = false;
  form.querySelector("#exclude_tracked").checked = false;
  if (window.htmx) window.htmx.trigger("#curation-form", "change");
};

function isTruthyQueryValue(value) {
  return ["true", "1", "yes", "on"].includes(value.toLowerCase());
}

function restoreCurationFormFromUrl() {
  const form = document.getElementById("curation-form");
  if (!form) return;

  const params = new URLSearchParams(window.location.search);
  const scalarControls = [
    ["q", "curation-search"],
    ["sort", "sort-select"],
    ["group_by", "group-select"],
    ["date_range", "date-select"],
    ["staleness", "staleness-select"],
  ];
  for (const [name, id] of scalarControls) {
    const values = params.getAll(name);
    const control = document.getElementById(id);
    if (values.length && control) {
      const value = values[values.length - 1];
      if (control instanceof HTMLSelectElement) {
        if (Array.from(control.options).some((option) => option.value === value)) {
          control.value = value;
        }
      } else {
        control.value = value;
      }
    }
  }

  for (const details of form.querySelectorAll(".curation-dropdown[data-filter-name]")) {
    const values = params.getAll(details.dataset.filterName).filter((value) => value !== "all");
    if (params.has(details.dataset.filterName)) {
      const options = Array.from(details.querySelectorAll("input[name]"));
      for (const option of options) {
        option.checked = values.includes(option.value);
      }
    }
    updateCurationDropdownSummary(details);
  }

  for (const name of ["include_unspecified", "show_hidden", "exclude_tracked"]) {
    const values = params.getAll(name);
    const checkbox = form.querySelector(`input[type="checkbox"][name="${name}"]`);
    if (values.length && checkbox) {
      checkbox.checked = isTruthyQueryValue(values[values.length - 1]);
    }
  }

  for (const details of form.querySelectorAll(".curation-dropdown")) {
    for (const option of details.querySelectorAll('input[type="checkbox"]')) {
      option.addEventListener("change", () => {
        const allOption = details.querySelector("[data-filter-all]");
        const individualOptions = Array.from(details.querySelectorAll("input[name]"));
        if (option === allOption) {
          if (option.checked) {
            for (const individual of individualOptions) individual.checked = false;
          } else if (!individualOptions.some((individual) => individual.checked)) {
            option.checked = true;
          }
        } else if (option.checked) {
          allOption.checked = false;
        } else if (!individualOptions.some((individual) => individual.checked)) {
          allOption.checked = true;
        }
        updateCurationDropdownSummary(details);
      });
    }
  }

  form.addEventListener("reset", () => {
    window.setTimeout(() => {
      for (const details of form.querySelectorAll(".curation-dropdown")) {
        details.open = false;
        updateCurationDropdownSummary(details);
      }
    }, 0);
  });

  document.addEventListener("click", (event) => {
    for (const details of form.querySelectorAll(".curation-dropdown[open]")) {
      if (!details.contains(event.target)) details.open = false;
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const openDropdowns = Array.from(form.querySelectorAll(".curation-dropdown[open]"));
    if (openDropdowns.length === 0) return;
    const activeDropdown =
      openDropdowns.find((details) => details.contains(document.activeElement)) ?? openDropdowns[0];
    for (const details of openDropdowns) details.open = false;
    activeDropdown.querySelector("summary")?.focus();
  });
}

function initTrackedFilterPersistence() {
  const checkbox = document.getElementById("exclude_tracked");
  const form = document.getElementById("curation-form");
  if (!checkbox) return;

  const hasUrlOverride = new URLSearchParams(window.location.search).has("exclude_tracked");
  try {
    const saved = localStorage.getItem("pyjobs_exclude_tracked");
    if (!hasUrlOverride && saved !== null) {
      const shouldBeChecked = saved === "true";
      if (checkbox.checked !== shouldBeChecked) {
        checkbox.checked = shouldBeChecked;
        checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      }
    } else if (hasUrlOverride) {
      localStorage.setItem("pyjobs_exclude_tracked", checkbox.checked ? "true" : "false");
    }
  } catch (_) {}

  checkbox.addEventListener("change", () => {
    const val = checkbox.checked ? "true" : "false";
    try {
      localStorage.setItem("pyjobs_exclude_tracked", val);
    } catch (_) {}
  });

  if (form) {
    form.addEventListener("reset", () => {
      setTimeout(() => {
        try {
          localStorage.setItem("pyjobs_exclude_tracked", "false");
        } catch (_) {}
      }, 0);
    });
  }
}

// ==============================================================================
// Manual External Application Modal - Status & Date Logic
// ==============================================================================
window.handleManualAppStatusChange = (status) => {
  const appliedDateInput = document.getElementById("manual-applied-date");
  const followUpDateInput = document.getElementById("manual-follow-up-date");
  if (!appliedDateInput || !followUpDateInput) return;

  const formatDate = (d) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  };

  const now = new Date();
  if (status === "applied") {
    appliedDateInput.value = formatDate(now);
    appliedDateInput.dispatchEvent(new Event("input", { bubbles: true }));
    appliedDateInput.dispatchEvent(new Event("change", { bubbles: true }));

    const twoWeeksLater = new Date(now);
    twoWeeksLater.setDate(twoWeeksLater.getDate() + 14);
    followUpDateInput.value = formatDate(twoWeeksLater);
    followUpDateInput.dispatchEvent(new Event("input", { bubbles: true }));
    followUpDateInput.dispatchEvent(new Event("change", { bubbles: true }));
  } else if (status === "saved") {
    appliedDateInput.value = "";
    appliedDateInput.dispatchEvent(new Event("input", { bubbles: true }));
    appliedDateInput.dispatchEvent(new Event("change", { bubbles: true }));

    const oneWeekLater = new Date(now);
    oneWeekLater.setDate(oneWeekLater.getDate() + 7);
    followUpDateInput.value = formatDate(oneWeekLater);
    followUpDateInput.dispatchEvent(new Event("input", { bubbles: true }));
    followUpDateInput.dispatchEvent(new Event("change", { bubbles: true }));
  }
};

window.openManualAppModal = () => {
  const modal = document.getElementById("manual-app-modal");
  if (!modal) return;
  const form = modal.querySelector("form");
  if (form) form.reset();
  const statusSelect = document.getElementById("manual-status");
  if (statusSelect) {
    statusSelect.value = "applied";
    window.handleManualAppStatusChange("applied");
  }
  modal.showModal();
};

window.initManualAppModal = () => {
  const statusSelect = document.getElementById("manual-status");
  if (statusSelect && !statusSelect.dataset.statusListenerAttached) {
    statusSelect.dataset.statusListenerAttached = "true";
    statusSelect.addEventListener("change", (e) => {
      window.handleManualAppStatusChange(e.target.value);
    });
  }
};

document.addEventListener("DOMContentLoaded", () => {
  window.initProfileFormState();
  restoreCurationFormFromUrl();
  initTrackedFilterPersistence();
  window.initManualAppModal();
});

document.addEventListener("htmx:afterSwap", (evt) => {
  if (
    evt.detail &&
    (evt.detail.target.id === "profile-sidebar-container" ||
      evt.detail.target.closest?.("#profile-sidebar-container"))
  ) {
    window.initProfileFormState();
  }
  window.initManualAppModal();
  const toast = document.getElementById("save-status-toast");
  if (toast) {
    toast.style.position = "fixed";
    toast.style.top = "1.25rem";
    toast.style.right = "1.5rem";
    toast.style.zIndex = "999999";
    toast.style.pointerEvents = "none";
  }
});

document.addEventListener("companyUpdated", () => {
  const form = document.getElementById("curation-form");
  if (form && window.htmx) window.htmx.trigger(form, "change");
});

document.addEventListener("click", (e) => {
  const modal = document.getElementById("unsaved-profile-modal");
  if (modal?.open && e.target === modal) {
    const rect = modal.getBoundingClientRect();
    const isInDialog =
      rect.top <= e.clientY &&
      e.clientY <= rect.top + rect.height &&
      rect.left <= e.clientX &&
      e.clientX <= rect.left + rect.width;
    if (!isInDialog) {
      modal.close();
    }
  }
});

// Clean up ?saved= from browser address bar after page load without triggering refresh
if (window.location.search.includes("saved=")) {
  const url = new URL(window.location.href);
  url.searchParams.delete("saved");
  window.history.replaceState(
    {},
    document.title,
    url.pathname + (url.search ? url.search : "") + url.hash,
  );
}
