# Dashboard Refactor — NES.css components, light/dark theme, layout fix, remove emojis

## Problema
El dashboard de Ultratimonel (`/dashboard/`) fue desarrollado como prueba de concepto sin seguir principios de UI/UX. Actualmente presenta tres problemas fundamentales que afectan la experiencia de usuario:

1. **CSS artesanal insostenible**: ~550 líneas de CSS con colores dark-mode hardcodeados (`#1a1a2e`, `#16213e`, `#0f3460`, `#e94560`). Sin sistema de diseño, sin variables, sin tema claro. Cualquier cambio requiere modificar CSS a mano en múltiples lugares.

2. **Ilegibilidad**: Fuentes en 6-10px que hacen el contenido difícil de leer. Sin jerarquía tipográfica, sin contraste adecuado, sin soporte para temas claros.

3. **Layout defectuoso**: Al hacer scroll vertical, el header y sidebar se desplazan junto con el contenido. El usuario pierde contexto de navegación (¿qué proyecto estoy viendo? ¿en qué pantalla estoy?).

Estos problemas no son cosméticos: un dashboard ilegible con navegación rota reduce la utilidad operativa de Ultratimonel como herramienta de monitoreo de gates y misiones.

## Summary
Reingeniería completa del frontend del dashboard. Reemplazar el CSS artesanal por componentes reales de **NES.css** v2.3.0 (framework CSS con estética pixel-art NES), implementar tema claro/oscuro con tokens de diseño CSS custom properties, eliminar todos los emojis del HTML reemplazándolos por componentes nativos del framework (`.nes-badge`, `.nes-container`, `.nes-btn`, `.nes-icon`), y corregir el layout para que header y sidebar queden fijos con scroll solo en el área de contenido.

## Definiciones
- **NES.css**: Framework CSS con estética pixel-art inspirada en Nintendo Entertainment System. v2.3.0 incluye componentes como botones, contenedores, badges, tablas y barras de progreso con temas claro/oscuro.
- **CSS** (Cascading Style Sheets): Lenguaje de estilos visuales para documentos HTML.
- **UI** (User Interface): Interfaz de usuario con la que interactúa la persona operando el dashboard.
- **API** (Application Programming Interface): Interfaz de comunicación entre el frontend del dashboard y el backend Python (`dashboard_server.py`).
- **SDD** (Spec-Driven Development): Metodología de desarrollo donde los cambios se especifican formalmente antes de implementarse.

## Proposed Solution

### Reactivo 1 — Componentes NES.css reales (no CSS artesanal)
Eliminar ~550 líneas de CSS custom y reemplazar por clases nativas de NES.css v2.3.0:
- `.nes-btn` con variantes `is-primary`, `is-success`, `is-error`, `is-warning`
- `.nes-container` con `with-title`, `is-dark`
- `.nes-badge` con `is-splited`, `is-icon`, colores semánticos
- `.nes-table` / `.nes-table.is-bordered`
- `.nes-progress.is-rounded`
- `.nes-balloon` para tooltips/info flotante
- `.nes-text` con semántica `is-primary`, `is-error`, `is-warning`
- `.nes-input` / `.nes-select` / `.nes-textarea`
- `.nes-icon` (trophy, star, heart, github, etc.)

### Reactivo 2 — Tema Light/Dark con tokens de diseño
Definir CSS custom properties:

```css
:root {
  /* Light (default) */
  --bg-primary: #ffffff;
  --bg-sidebar: #f0f0f0;
  --text-primary: #212529;
  --text-secondary: #636e72;
  --accent: #209cee;
  --border: #d3d3d3;
}
[data-theme="dark"] {
  --bg-primary: #1a1a2e;
  --bg-sidebar: #16213e;
  --text-primary: #e0e0e0;
  --text-secondary: #7f8c8d;
  --accent: #e94560;
  --border: #0f3460;
}
```

Toggle con `<input type="checkbox" class="nes-checkbox">`, clases `.is-dark` de NES.css, persistencia en localStorage.

### Reactivo 3 — Eliminar emojis, usar componentes NES.css
- `GATE_ICONS` → colores de border/background con `.nes-badge` + colores semánticos
- `STATUS_LABEL` → `.nes-badge.is-success` (completada), `.nes-badge.is-warning` (pendiente), `.nes-badge.is-error` (bloqueada)
- Sidebar projects → quitar 📁, usar `.nes-badge` con contador
- Breadcrumbs → texto sin emoji, separadores con CSS `::before`
- Cuadros de misiones → `.nes-container.with-title`

### Reactivo 4 — Layout con scroll fijo
Header con `position: sticky; top: 0; z-index: 100`.
Sidebar con `position: sticky; top: 0; height: 100vh; overflow-y: auto`.
Content con `overflow-y: auto; max-height: calc(100vh - header-height)`.
Solo el main content hace scroll vertical.

## Impact
- Breaking changes: No — solo UI, no cambia API ni lógica de negocio
- Database migrations: No
- API changes: No
- Dependencies: NES.css v2.3.0 ya incluida vía CDN (unpkg.com/nes.css@2.3.0/css/nes.min.css). No hay dependencias nuevas.
- Archivos afectados: `ultratimonel/dashboard/index.html` (reescritura completa ~460 líneas, de 551 originales), `ultratimonel/dashboard/app.js` (modificaciones en render functions ~652 líneas, de 573 originales)
- Fuera de alcance: Backend Python (`dashboard_server.py`), lógica de app.js, nuevas dependencias npm, migrar de NES.css, docs/SDD, MCP server

## Seguridad

El dashboard opera en un entorno controlado con las siguientes características de seguridad:

- **Network binding**: El servidor se enlaza a `127.0.0.1` (localhost) por defecto, configurable vía `ULTRATIMONEL_DASHBOARD_HOST`. No hay exposición a red externa.
- **Sin autenticación**: El dashboard es una herramienta operativa local sin usuarios ni sesiones. No maneja datos personales ni requiere control de acceso.
- **Sin autorización**: No hay operaciones de escritura desde el frontend — solo consulta (GET). Los datos se sirven desde la base de datos SQLite local del servidor MCP.
- **No hay PII**: Los datos mostrados son técnicos: estado de gates, misiones, checklists e intentos de ejecución. No hay información personal identificable.
- **CORS**: No se exponen cabeceras `Access-Control-Allow-Origin: *` (restringido a same-origin SPA).

**Riesgo aceptado**: Al ser una herramienta local sin exposición externa ni datos sensibles, no se requiere autenticación, cifrado adicional ni auditoría de acceso. Si en el futuro el dashboard se expone a red, se deberá agregar autenticación (ej: token-based o SSO vía Nextcloud).

## Fases de implementación
| Fase | Tema | Archivos | Esfuerzo |
|------|------|----------|----------|
| 1 | Layout + scroll fijo (reactivo 4) | index.html CSS + app.js | 15 min |
| 2 | Tema light/dark + tokens (reactivo 2) | index.html CSS | 20 min |
| 3 | Reemplazar emojis por NES.css (reactivo 3) | app.js, index.html | 25 min |
| 4 | Componentes NES.css reales (reactivo 1) | index.html (reescritura) | 30 min |
| 5 | Verificación + ajustes finos | Dashboard server + frontend | 15 min |
| **Total** | | | **~105 minutos** |