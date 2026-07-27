# Design — Dashboard Refactor

## Technical Approach

### Objective

Replace ~550 lines of hand-written dark-mode CSS in `index.html` with NES.css v2.3.0 components, add a light/dark theme system driven by CSS custom properties, remove all emoji characters from HTML/JS, and fix the layout so header and sidebar stay pinned while only content scrolls.

### Strategy: Layered replacement (no breaking API changes)

The refactor is purely presentational. The Python backend (`dashboard_server.py`), the JavaScript data layer (`api()`, `state` object), and all DOM IDs used by `app.js` remain untouched. Only CSS classes, inline styles, and emoji literals change.

Phases execute in dependency order:

1. **Layout skeleton** — establish sticky header/sidebar + scrollable content area
2. **Theme tokens** — define CSS custom properties for light/dark
3. **Emoji removal + NES.css components** — replace `GATE_ICONS`, `STATUS_LABEL`, and all inline emoji with `.nes-icon`, `.nes-badge`, `.nes-btn`
4. **CSS purge** — remove the old ~550-line `<style>` block, keep only layout/theme/overrides

### Why this order?

- Layout must come first: changing from full-page-scroll to sticky-fixed changes all sizing calculations.
- Theme tokens before emoji removal: once colors are tokenized, replacing hardcoded values with `var(--accent)` etc. is mechanical.
- Emoji removal after CSS is clean: ensures new component classes have their styles available before being referenced in JS-rendered HTML.

---

## Architecture Decisions

### AD-1: Single source of truth for layout — `index.html` `<style>` block

**Decision:** All CSS stays in one `<style>` block inside `index.html`. No external `.css` file.

**Rationale:** The dashboard is a single-page app served by a simple Python HTTP server. Adding a separate CSS file introduces an extra network request and complicates the static-file serving setup. NES.css itself is loaded via CDN; custom overrides are minimal once hand-written CSS is removed.

**Trade-off:** As files grow, inline CSS becomes harder to navigate. Not expected here — post-refactor the custom style block will be ~80-120 lines (layout + theme tokens + minor overrides), not 550.

### AD-2: Theme via `[data-theme]` attribute on `<html>`

**Decision:** Use `document.documentElement.setAttribute('data-theme', 'dark')` instead of toggling a class on `<body>`.

**Rationale:** NES.css itself uses `[data-theme="dark"]` for its dark mode, so aligning with that convention avoids conflicts. Also keeps the body element free from presentation concerns.

```css
:root { /* light tokens */ }
[data-theme="dark"] { /* dark tokens override */ }
```

**Trade-off:** NES.css provides a `.is-dark` class on components for per-component theming, but the global token approach is simpler and covers all custom elements uniformly.

### AD-3: Theme persistence via `localStorage` key `ultratimonel-theme`

**Decision:** Store `'light' | 'dark'` in `localStorage.getItem('ultratimonel-theme')`, apply on DOMContentLoaded before first paint (no flash of wrong theme).

**Rationale:** No server-side session, no user accounts. localStorage is the only persistence mechanism available for this SPA. The key is namespaced to avoid collisions with other apps.

**Trade-off:** localStorage is per-browser-per-origin; switching browsers loses preference. Acceptable given the local-only use case.

### AD-4: Theme toggle as NES.css checkbox in header

**Decision:** Add `<input type="checkbox" class="nes-checkbox">` next to the DB status indicator in the header. Label it "Tema". Toggling sets/clears `[data-theme="dark"]`.

**Rationale:** Keeps the theme control visible at all times (sticky header), uses NES.css component for consistency, no JavaScript framework needed.

### AD-5: GATE_ICONS map → `.nes-icon` elements with CSS color classes

**Decision:** Replace `GATE_ICONS = { PASS: '✅', ... }` with a function that returns HTML using `<i class="nes-icon [icon_name] is-small"></i>` wrapped in colored spans, plus remove the emoji from `STATUS_LABEL`.

**Rationale:** `.nes-icon` supports named icons (trophy, star, heart, github, check, close, setting, search, plus, minus, menu, info, warning). Map gate states to the closest NES.css icon:
- PASS → `.nes-icon.check`
- WARN → `.nes-icon.warning`
- BLOCK → `.nes-icon.close`
- SKIP → `.nes-icon.menu` (no skip icon in NES.css)
- PENDING → `.nes-icon.setting`

Color is applied via the existing `gate-pass`, `gate-warn`, etc. classes, now mapped to CSS custom properties.

### AD-6: STATUS_LABEL map — text only, no emoji

**Decision:** Replace values like `'⏳ PENDIENTE'` with `'PENDIENTE'`. Use `.nes-badge.is-splited` or `.nes-badge.is-icon` for the status indicator portion instead of emoji prefix.

**Rationale:** Emojis in dynamic JS strings are the hardest to find and replace (they appear inside template literals across 12+ locations). By stripping them from `STATUS_LABEL`, render functions become cleaner. Status icons use NES.css badge components with semantic colors:
- completada → `.nes-badge.is-success` equivalent via custom class
- bloqueada → error color
- pendiente/en_progreso → warning color

### AD-7: Semantic color classes map to CSS custom properties

**Decision:** Replace hardcoded hex values in `.gate-pass`, `.status-completed`, etc. with `color: var(--accent-success)`, `border-color: var(--accent-warning)`, etc.

**Rationale:** The theme system needs colors that adapt between light and dark. Each semantic color gets a dedicated CSS variable so both themes have complete palettes without duplicating logic.

```css
:root {
  --bg-primary: #ffffff;
  --bg-sidebar: #f0f0f0;
  --text-primary: #212529;
  --text-secondary: #636e72;
  --accent: #209cee;
  --border: #d3d3d3;
  --success: #27ae60;
  --warning: #f39c12;
  --error: #e94560;
}

[data-theme="dark"] {
  --bg-primary: #1a1a2e;
  --bg-sidebar: #16213e;
  --text-primary: #e0e0e0;
  --text-secondary: #7f8c8d;
  --accent: #e94560;
  --border: #0f3460;
  --success: #2ecc71;
  --warning: #f1c40f;
  --error: #ff6b6b;
}
```

### AD-8: Layout — sticky header + flex sidebar + scrollable content

**Decision:** Header uses `position: sticky; top: 0`. Sidebar uses flex stretch (no sticky, no fixed height) via `display: flex; flex: 1` on `.app-layout`. Content uses `overflow-y: auto` for independent scroll.

```css
body {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.app-layout { display: flex; flex: 1; overflow: hidden; }
.sidebar {
  width: 340px;
  overflow-y: auto;
  flex-shrink: 0;
}
.content { flex: 1; overflow-y: auto; }
```

**Rationale:** `sticky` en header mantiene el título visible. El sidebar estirado por flex ocupa toda la altura disponible sin depender de `height: 100vh` que se solapaba con el header. Flex simplifica el layout y evita bugs de posicionamiento.

### AD-9: Font size — NES.css default (16px), sin overrides

**Decision:** Se eliminaron todos los `font-size` menores a 12px. El body usa la fuente NES.css nativa (Press Start 2P en componentes, sistema sans-serif heredado). Solo `.header-title` conserva `font-family: 'Press Start 2P'` para identidad de marca. No hay `font-size` declarados en el CSS custom — NES.css resuelve el tamaño base.

### AD-10: Mission card hover — NES.css `.nes-container` with custom transition

**Decision:** Replace `.mission-card` and `.checklist-item-card` styling with `.nes-container.with-title` where the title is injected via JS, or keep a lightweight wrapper class for hover effects that NES.css doesn't provide.

**Rationale:** NES.css containers don't have built-in hover transitions. A minimal custom rule handles the visual feedback (border color change + slight translate) while the container structure follows NES.css conventions.

---

## Data Flow

### Unchanged data flow (confirmed no changes needed)

```
Browser → fetch('/api/projects')          → dashboard_server.py → SQLite
Browser → fetch('/api/missions/{id}')     → dashboard_server.py → SQLite
Browser → fetch('/api/checklist/{id}/intentos') → dashboard_server.py → SQLite
Browser → fetch('/api/intentos/{id}')     → dashboard_server.py → SQLite
Browser → fetch('/api/intentos/{id}/gate/{name}/logs') → dashboard_server.py → SQLite
```

No API changes. The frontend's `api()` helper, state object, and all DOM IDs remain identical. Only the HTML template strings inside render functions change (emoji → NES.css components).

### New data flow: theme persistence

```
DOMContentLoaded → localStorage.getItem('ultratimonel-theme')
  → 'dark' ? setAttribute('data-theme', 'dark') : noop
  
Checkbox click → toggle [data-theme] on <html>
  → localStorage.setItem('ultratimonel-theme', isDark ? 'dark' : 'light')
```

### New data flow: theme toggle in header

The checkbox's `change` event listener runs inline — no new functions needed. It reads the current state from the attribute, toggles it, and persists.

---

## File Changes

### File 1: `ultratimonel/dashboard/index.html`

**Changes:**
- Remove `<link>` to Google Fonts (keep only NES.css CDN link)
- Replace entire 485-line `<style>` block (~550 lines total with boilerplate):
  - New ~100-line style block containing: theme tokens (`:root`, `[data-theme="dark"]`), layout rules (sticky header/sidebar, scrollable content), semantic color classes mapped to CSS variables, minimal overrides for hover states and responsive behavior
- Add theme toggle checkbox in `<header>` next to DB status
- Remove all emoji characters from static HTML: `🔮`, `✦`, `📋` in sidebar title

|**Before:** 551 lines (485 lines CSS + ~66 lines HTML)
|**After actual:** 460 lines (CSS ~400 lines + ~60 lines HTML) — CSS incluye layout, tokens y estilos de caja

### File 2: `ultratimonel/dashboard/app.js`

**Changes:**
- Remove `GATE_ICONS` constant → replace with `getGateIconHTML(state)` function returning `<i class="nes-icon ..."></i>` HTML string
- Remove emoji from all `STATUS_LABEL` values (strip prefix emojis, keep text)
- Replace inline emoji in render functions:
  - `renderProjects`: `📁` → `.nes-badge.is-splited` or `.nes-icon.folder` equivalent
  - `renderMissions`: `📋`, `🎯`, `🕐`, `✅` → NES.css components via template literals
  - `openMission`: `📝`, `🚫`, `📋`, `✅`, `⬜` → NES.css icons + badge system
  - `openIntentos`: `🔄`, `🎯`, `✅`, `🕐` → NES.css components
  - `openIntentoDetail`: all inline emojis → `.nes-icon` elements with semantic colors
  - `showGateLogs`: emoji arrows and icons → CSS-styled transitions (`→`) + NES.css badges
- Replace inline `style="..."` attributes on dynamically created elements with class references where feasible (progressive enhancement — not every style can be moved to CSS, focus on the most impactful ones)
- Add theme toggle initialization code in `init()` or as a new module-level function
- Remove `.crystal` span styling dependency (keep only for header title, apply 'Press Start 2P' font there)

**Before:** 573 lines
**After estimate:** ~500-520 lines (smaller because emoji maps are removed and template strings simplify)

### File 3: No changes to other files

- `dashboard_server.py` — untouched
- `__init__.py` — untouched
- Static file serving configuration — unchanged

---

## Interfaces / Contracts

### CSS Custom Properties Contract (Public Interface for Theme System)

All render functions and HTML templates MUST reference these tokens instead of hex colors:

| Token | Light Value | Dark Value | Usage |
|-------|-------------|------------|-------|
| `--bg-primary` | `#ffffff` | `#1a1a2e` | Page background, card backgrounds via override |
| `--bg-sidebar` | `#f0f0f0` | `#16213e` | Sidebar background |
| `--text-primary` | `#212529` | `#e0e0e0` | Body text, card titles |
| `--text-secondary` | `#636e72` | `#7f8c8d` | Metadata, breadcrumbs, descriptions |
| `--accent` | `#209cee` | `#e94560` | Primary links, header title crystal color |
| `--border` | `#d3d3d3` | `#0f3460` | Borders on containers, cards, sidebar divider |
| `--success` | `#27ae60` | `#2ecc71` | Completed status, pass gates |
| `--warning` | `#f39c12` | `#f1c40f` | Pending/warning states |
| `--error` | `#e94560` | `#ff6b6b` | Failed/blocked status, error gates |

### DOM Contract (Unchanged IDs)

All existing `id` attributes MUST be preserved. The following are the contract surface:

| ID | Used By | Purpose |
|----|---------|---------|
| `project-list` | JS: renders projects | Sidebar project list container |
| `mission-list` | JS: renders missions/items/intentos | Main content area |
| `content-title` | JS: sets title text | Content header title |
| `content-subtitle` | JS: sets subtitle | Content header subtitle |
| `content-breadcrumb` | JS: renders breadcrumbs | Breadcrumb navigation |
| `detail-overlay` | JS: open/close modal | Detail overlay wrapper |
| `detail-panel` | CSS/JS | Modal panel container |
| `detail-content` | JS: renders detail HTML | Modal content area |
| `detail-close` | JS: click handler | Close button ref |
| `db-status` | JS: sets DB status text | Connection indicator |

**No IDs will be renamed, removed, or added.** This ensures zero breaking changes to the JavaScript layer.

### NES.css Component Usage Contract

All interactive elements must use these exact class patterns:

```
Button actions  → <button class="nes-btn is-primary">...</button>
Data containers → <div class="nes-container with-title">
                  <p slot="title">Section Title</p>  (NES.css v2.3 uses `slot` for titles)
Tables          → <table class="nes-table is-bordered">
Progress        → <progress class="nes-progress" value="75" max="100"></progress>
Tooltips/info   → <div class="nes-balloon from-top">
Text coloring   → <span class="nes-text is-primary">
Icons           → <i class="nes-icon check is-small"></i>
Checkbox        → <input type="checkbox" class="nes-checkbox">
</details>

### Emoji Removal Contract

Zero emoji characters (Unicode codepoints U+1F300–U+1FAFF, plus common UI emojis like ✅❌⚠️🔄🕐📋🎯) MAY appear in:
- JavaScript string literals assigned to `STATUS_LABEL` values — NO, must be text-only
- HTML template strings rendered via `.innerHTML` — NO, use NES.css components instead
- Static HTML in `index.html` — NO

The only exception is the title "ULTRATIMONEL" which may retain a decorative crystal emoji if it serves brand identity, but per spec this must also be replaced by `.nes-icon.trophy` or similar.

---

## Testing Strategy

### Visual Regression (Manual — no automated browser tests in scope)

Since this is a static HTML/JS dashboard with no test runner configured for the frontend:

1. **Light theme verification:** Load dashboard → verify all elements render with light palette (`--bg-primary: #ffffff`, etc.)
2. **Dark theme toggle:** Click checkbox → verify `[data-theme="dark"]` appears on `<html>` and colors invert correctly
3. **Theme persistence:** Toggle to dark, reload page → verify dark theme is restored
4. **Layout scroll test:** Select a project with many missions → verify header stays pinned, sidebar scrolls independently, content scrolls within its area
5. **NES.css component check:** Inspect rendered DOM → verify `.nes-btn`, `.nes-container`, `.nes-badge`, etc. classes are present and no custom button/container CSS remains
6. **Emoji audit:** Search rendered HTML for emoji characters → zero matches expected

### Code-level checks (pre-commit)

- `grep -Pn '[\x{1F300}-\x{1FAFF}]' ultratimonel/dashboard/index.html ultratimonel/dashboard/app.js` — should return 0 results
- Verify all semantic color classes use `var(--...)` references, not hex literals
- Confirm `font-size: 16px` base is present on body (or inherited from NES.css default)

### Regression risk areas

| Area | Risk | Mitigation |
|------|------|------------|
| `app.js` render functions | Template literal changes could break DOM IDs or event handlers | Keep all `id` attributes; only change visual HTML inside innerHTML strings |
| CSS specificity | New NES.css classes might conflict with remaining custom rules | Audit every removed `.class-name` in old CSS to ensure no JS depends on it for state (e.g., toggling a class) |
| Responsive breakpoint | 640px media query needs updating for new font sizes and layout | Test at 640px, 768px, and 1024px widths |

---

## Migration / Rollout

### Deployment model

Rollout is atomic: `index.html` + `app.js` are served as static files. The deployment replaces both files simultaneously — there's no intermediate state where one file has changes and the other doesn't.

### Zero-downtime considerations

1. Cache busting via query parameter (`?v=3`) in `<script src="/static/app.js?v=3">` ensures browsers fetch fresh JS
2. NES.css is version-locked at `@2.3.0` — no unexpected CDN updates
3. No database or backend changes → no migration scripts needed

### Rollback plan

If issues are discovered post-deploy:
1. Revert the two files via git: `git checkout HEAD~1 -- ultratimonel/dashboard/index.html ultratimonel/dashboard/app.js`
2. Redeploy previous version (atomic swap, < 30 seconds)
3. No data loss possible — all changes are purely presentational

### Known migration edge cases

- **Browser localStorage:** Users who visited the old dashboard have no `ultratimonel-theme` key → defaults to light theme (per spec). No migration of old preferences needed since none were persisted before.
- **NES.css CDN availability:** Dashboard requires internet to load NES.css from unpkg.com. If the CDN is unreachable, the dashboard falls back to bare HTML with no styling. This is an existing condition (NES.css was already loaded via CDN pre-refactor).

---

## Open Questions (Resolved)

### OQ-1: Tema toggle visible en mobile — RESUELTO

El toggle permanece visible en todos los viewports. No se implementó stacking en dos filas porque el header se mantiene legible incluso a 640px.

### OQ-2: Mapa de iconos NES.css para gate states — RESUELTO

La implementación usa el mapeo propuesto: PASS→check, WARN→warning, BLOCK→close, SKIP→menu, PENDING→setting. No se identificaron iconos más precisos en NES.css v2.3.0.

### OQ-3: Font Press Start 2P solo en header — RESUELTO

Se conservó 'Press Start 2P' exclusivamente en `.header-title`. El resto del dashboard usa la font nativa de NES.css (Press Start 2P en componentes, sistema sans-serif en body).

### OQ-4: Mission cards con `.nes-container.with-title` — RESUELTO

Se implementó con `<p class="title">${m.title}</p>` (no `<p slot="title">` ya que NES.css v2.3 usa `class="title"`). Las checklist items también usan el mismo patrón.

### OQ-5: Progress bar color theming — RESUELTO

Se usan clases CSS `.progress-success`, `.progress-warning`, `.progress-error` con la propiedad `accent-color` para colorear las barras de progreso semánticamente.
