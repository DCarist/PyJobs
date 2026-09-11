# Frontend & UI Development Standards

Guidelines and constraints for templates, styles, and client-side interactions in PyJobs.

---

## 1. UI Architecture & Libraries
* **HTML & Templates**: Jinja2 templates served via FastAPI `Jinja2Templates`.
* **Dynamic Interactivity**: HTMX for seamless partial page replacements and live updates.
* **Styling**: Vanilla CSS with CSS custom properties (variables) for design tokens. Do not introduce CSS utility frameworks like Tailwind unless explicitly instructed.
* **Linter & Formatter**: Biome (`@biomejs/biome`) formats and validates all `.html`, `.css`, and `.js` files.

---

## 2. Design Tokens & Aesthetics
* **Theme**: Modern dark-mode glassmorphic aesthetics.
* **Palette**: Tailored dark backgrounds (`--bg-primary`, `--bg-card`, `--bg-card-hover`), subtle border highlights (`--border-subtle`, `--border-accent`), and vibrant accent colors (`--primary`, `--primary-hover`, `--success`, `--warning`, `--danger`).
* **Micro-interactions**: Subtle hover elevations, smooth transitions (`transition: all 0.2s ease`), and clear focus outlines.

---

## 3. Accessibility & Markup Best Practices
* **Explicit Button Types**: Every `<button>` element MUST have an explicit `type="button"`, `type="submit"`, or `type="reset"` attribute for accessibility and Biome compliance.
* **Semantic HTML**: Use proper HTML5 landmark tags (`<nav>`, `<header>`, `<main>`, `<section>`, `<article>`, `<footer>`).
* **Form Controls**: Ensure all form inputs have associated `<label>` tags with matching `for` attributes or `aria-label` attributes.
* **Unique IDs**: Ensure interactive and HTMX target elements have clear, unique IDs (e.g. `id="applications-table"`, `id="unemployment-summary-card"`).

---

## 4. HTMX Integration Conventions
* Target partials cleanly using `hx-target` and `hx-swap="outerHTML"` or `hx-swap="innerHTML"`.
* For sub-components that update multiple areas, use HTMX out-of-band swaps (`hx-swap-oob="true"`).
* Include visual indicators (`hx-indicator`) for asynchronous requests to provide responsive feedback.
