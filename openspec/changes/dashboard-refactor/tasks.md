# Tasks — Dashboard Refactor

## Fase 1 — Layout + scroll fijo (Reactivo 4)

- [x] **1.1** Aplicar `position: sticky; top: 0; z-index: 100` al header en index.html
- [x] **1.2** Aplicar `position: sticky; top: 0; height: 100vh; overflow-y: auto` al sidebar
- [x] **1.3** Configurar content con `overflow-y: auto; max-height: calc(100vh - header-height)`
- [x] **1.4** Verificar que header y sidebar no se desplazan al scrollear

## Fase 2 — Tema Light/Dark + tokens (Reactivo 2)

- [x] **2.1** Definir CSS custom properties `:root` (light) y `[data-theme="dark"]` con los tokens especificados
- [x] **2.2** Agregar toggle switch con `<input type="checkbox" class="nes-checkbox">`
- [x] **2.3** Implementar persistencia en localStorage (guardar preferencia al toggle, leer al cargar)
- [x] **2.4** Aplicar clases `.is-dark` de NES.css donde corresponda
- [x] **2.5** Verificar que light es default y el toggle persiste entre recargas

## Fase 3 — Eliminar emojis (Reactivo 3)

- [x] **3.1** Reemplazar `GATE_ICONS` por colores de border/background con `.nes-badge`
- [x] **3.2** Reemplazar `STATUS_LABEL` por `.nes-badge.is-success/warning/error`
- [x] **3.3** Eliminar 📁 del sidebar, usar `.nes-badge` con contador
- [x] **3.4** Reemplazar breadcrumbs con texto + CSS `::before` para separadores
- [x] **3.5** Usar `.nes-container.with-title` para cuadros de misiones
- [x] **3.6** Verificar cero emojis en HTML renderizado

## Fase 4 — Componentes NES.css (Reactivo 1)

- [x] **4.1** Reemplazar botones artesanales por `.nes-btn` con variantes
- [x] **4.2** Reemplazar contenedores por `.nes-container.with-title` y `.is-dark`
- [x] **4.3** Reemplazar badges de estado por `.nes-badge.is-splited` e `.is-icon`
- [x] **4.4** Reemplazar tablas por `.nes-table.is-bordered`
- [x] **4.5** Reemplazar barras de progreso por `.nes-progress.is-rounded`
- [ ] **4.6** Reemplazar tooltips por `.nes-balloon` — NO IMPLEMENTADO (frontend no usa tooltips)
- [x] **4.7** Reemplazar textos semánticos por `.nes-text.is-primary/error/warning`
- [x] **4.8** Verificar font-size base 16px de NES.css en toda la UI

## Fase 5 — Verificación

- [x] **5.1** Verificar dashboard funcional en puerto 3005
- [x] **5.2** Verificar toggle light/dark funcional
- [x] **5.3** Verificar scroll fijo (header/sidebar no se mueven)
- [x] **5.4** Verificar cero emojis en toda la UI
- [x] **5.5** Verificar 74/74 tests pasan en el backend