# Delta Spec — Dashboard UI Refactor

## ADDED Requirements

### Requirement: NES.css Component System

The dashboard MUST use NES.css v2.3.0 components for all UI elements instead of custom CSS. The following component classes SHALL be used throughout the interface:

- Buttons → `.nes-btn` with semantic variants (`is-primary`, `is-success`, `is-error`, `is-warning`)
- Containers → `.nes-container.with-title` and `.nes-container.is-dark`
- Badges → `.nes-badge.is-splited`, `.nes-badge.is-icon` with semantic colors
- Tables → `.nes-table.is-bordered`
- Progress bars → `.nes-progress.is-rounded`
- Tooltips → `.nes-balloon` for info overlays
- Text → `.nes-text.is-primary/error/warning` for semantic coloring
- Inputs → `.nes-input`, `.nes-select`, `.nes-textarea`
| Icons → `.nes-icon` (trophy, star, heart, github, etc.)

**OUT_OF_SCOPE** (not implemented — frontend no usa tablas, formularios ni tooltips): `.nes-table.is-bordered`, `.nes-input`, `.nes-select`, `.nes-textarea`, `.nes-balloon`, `.nes-text`

The font-size base MUST be 16px as defined by NES.css defaults.

#### Scenario: All interactive elements use NES.css buttons

- GIVEN the user is on any dashboard page (gates, missions, checklists)
- WHEN the UI renders action buttons (start mission, toggle gate, etc.)
- THEN all buttons use `.nes-btn` class with appropriate semantic variant
- AND no custom button CSS remains in the stylesheet

#### Scenario: Data displays use NES.css containers and tables

- GIVEN a page showing structured data (gate list, mission detail)
- WHEN the UI renders cards or data sections
- THEN containers use `.nes-container.with-title` for titled sections
- AND tabular data uses `.nes-table.is-bordered`
- And progress indicators use `.nes-progress.is-rounded`

#### Scenario: Icons use NES.css icon components

- GIVEN a list of gates or missions on the dashboard
- WHEN status icons are rendered next to items
- THEN all icons use `.nes-icon` elements from NES.css
- And zero emoji characters exist in the rendered HTML output

### Requirement: Light/Dark Theme System

The dashboard MUST support light and dark themes using CSS custom properties (design tokens). The system SHALL define theme tokens as follows:

**Light theme (default):** `--bg-primary: #ffffff`, `--bg-sidebar: #f0f0f0`, `--text-primary: #212529`, `--text-secondary: #636e72`, `--accent: #209cee`, `--border: #d3d3d3`

**Dark theme:** `--bg-primary: #1a1a2e`, `--bg-sidebar: #16213e`, `--text-primary: #e0e0e0`, `--text-secondary: #7f8c8d`, `--accent: #e94560`, `--border: #0f3460`

The user SHALL be able to toggle between themes via a `.nes-checkbox` input. The selected theme MUST persist across page reloads using localStorage. Light theme is the default when no preference exists.

#### Scenario: User toggles dark theme and it persists

- GIVEN the dashboard is loaded in light theme (default)
- WHEN the user clicks the theme toggle checkbox
- THEN the `[data-theme="dark"]` attribute is applied to `<html>` or `<body>`
- AND the page re-renders with dark color tokens
- AND refreshing the page restores the dark theme from localStorage

#### Scenario: Light theme is default on first visit

- GIVEN no localStorage theme preference exists
- WHEN the dashboard loads for the first time
- THEN the `[data-theme]` attribute defaults to light (absent or `light`)
- AND all elements render with light color tokens

### Requirement: Fixed Layout with Independent Scroll

The dashboard layout MUST have a fixed header and sidebar with independent content scroll. The system SHALL implement the following positioning:

- Header → `position: sticky; top: 0; z-index: 100`
- Sidebar → `position: sticky; top: 0; height: 100vh; overflow-y: auto`
- Content area → `overflow-y: auto; max-height: calc(100vh - header-height)`

Only the main content area SHALL scroll vertically. The header and sidebar MUST remain visible at all times during scrolling.

#### Scenario: Header stays fixed on scroll

- GIVEN the user is on a dashboard page with enough content to overflow
- WHEN the user scrolls down the content area
- THEN the header remains pinned at the top of the viewport
- And the sidebar remains visible along the left edge

#### Scenario: Sidebar has independent vertical scroll

- GIVEN the project list in the sidebar overflows vertically
- WHEN the user scrolls within the sidebar
- THEN only the sidebar content scrolls, not the main area
- AND the header stays fixed above both regions

## REMOVED Requirements

### Requirement: Custom dark-mode color scheme (hardcoded)

The hardcoded dark-mode palette (`#1a1a2e`, `#16213e`, `#0f3460`, `#e94560`) applied ad-hoc across ~550 lines of custom CSS SHALL be removed and replaced with the tokenized theme system.

(Reason: Hardcoded colors prevent light theme support and make maintenance difficult)
(Migration: All color references are replaced by CSS custom properties defined in `:root` and `[data-theme="dark"]`)

### Requirement: Emoji-based iconography

All emoji characters used as visual indicators throughout the dashboard (🔷, 📁, ✅, ⏳, etc.) SHALL be removed from HTML templates.

(Reason: Emojis are not accessible, don't scale well, and conflict with NES.css component system)
(Migration: Each emoji is replaced by its corresponding NES.css component — `.nes-icon`, `.nes-badge`, or colored border/background patterns)

### Requirement: Scrollable header and sidebar

The previous layout where the entire page scrolls (including header and sidebar) SHALL be removed. The header and sidebar MUST remain fixed while only content scrolls.

(Reason: Users lose navigation context when scrolling, making it hard to understand which project/page they're viewing)
(Migration: CSS positioning changes — sticky header, sticky sidebar, scrollable content area)
