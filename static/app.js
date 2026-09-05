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
