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
    if (!card) return;

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

// Sync and persist exclude_tracked checkbox state across navigation
function initTrackedFilterPersistence() {
  const checkbox = document.getElementById("exclude_tracked");
  const form = document.getElementById("curation-form");
  if (!checkbox) return;

  try {
    const saved = localStorage.getItem("pyjobs_exclude_tracked");
    if (saved !== null) {
      const shouldBeChecked = saved === "true";
      if (checkbox.checked !== shouldBeChecked) {
        checkbox.checked = shouldBeChecked;
        checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      }
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

document.addEventListener("DOMContentLoaded", () => {
  window.initProfileFormState();
  initTrackedFilterPersistence();
});

document.addEventListener("htmx:afterSwap", (evt) => {
  if (
    evt.detail &&
    (evt.detail.target.id === "profile-sidebar-container" ||
      evt.detail.target.closest?.("#profile-sidebar-container"))
  ) {
    window.initProfileFormState();
  }
  const toast = document.getElementById("save-status-toast");
  if (toast) {
    toast.style.position = "fixed";
    toast.style.top = "1.25rem";
    toast.style.right = "1.5rem";
    toast.style.zIndex = "999999";
    toast.style.pointerEvents = "none";
  }
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
