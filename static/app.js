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
