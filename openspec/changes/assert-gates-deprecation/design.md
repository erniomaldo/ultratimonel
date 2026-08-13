# Design: Assert Gates Deprecation (Card #150)

> **Change:** `assert-gates-deprecation` · **Date:** 2026-08-13 · **Capability:** `assert-gates-deprecation`
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/assert-gates-deprecation/spec.md)

---

## 1. Architecture Decision Records

### ADR-1: Deprecate `assert_gates` vs remove it

**Contexto:** Con el flujo consolidado `begin_turn` → trabajo → `end_turn`, `assert_gates` ya no es necesaria como paso de agente: `begin_turn` ejecuta los 4 gates internamente y persiste el snapshot en el intento. La pregunta es si deprecarla o eliminarla.

**Decisión:** Deprecar, no eliminar. `assert_gates` queda registrada con firma y comportamiento intactos, marcada `~~DEPRECATED~~` y movida a la sección "Legacy / archived tools".

**Justificación:**

| Criterio | Eliminar | Deprecar |
|----------|----------|----------|
| Compatibilidad con plugin | Rompe `on_session_start` / `pre_llm_call` (plugin_preflight.py líneas 243, 285) | Plugin sigue funcionando sin cambios |
| Riesgo de regresión | Alto (plugin es fuente de verdad del bouncer) | Cero (no cambia comportamiento) |
| Claridad para Hermes | Desaparece del surface | Se marca legacy: no usar como paso de agente |
| Trabajo futuro de remoción | Inmediato, sin migración previa | Requiere migrar plugin primero (fuera de alcance) |

**Riesgo aceptado:** El tool sigue siendo invocable por Hermes, que podría ignorar el deprecado. Mitigación: el plugin ejecuta los gates automáticamente en cada turno (`on_session_start` / `pre_llm_call`), así que un llamado manual solo duplica trabajo; el warning del docstring desincentiva el uso. Los mensajes del bouncer que aún instruyen al agente a llamar `assert_gates()` (líneas 103–155) quedan como deuda de coherencia — fuera de alcance.

### ADR-2: Docstring como contrato de deprecación

**Contexto:** El repositorio ya usa `~~DEPRECATED~~` como convención (record_intento, complete_intento). ¿Cómo comunicar la deprecación de `assert_gates`?

**Decisión:** Usar la misma convención: el docstring comienza con `~~DEPRECATED~~` seguido de instrucción explícita `use begin_turn() instead`, y explica por qué (el plugin ya ejecuta los gates en cada turno vía `on_session_start`/`pre_llm_call` y su bouncer instruye al agente a llamar `assert_gates()`; begin_turn ya los ejecuta internamente).

**Justificación:** Consistencia con las otras 2 legacy tools; el marker es grepeable (verificación F-AGD-05, S2); el README hereda la misma frase para trazabilidad.

### ADR-3: Sección física "Legacy / archived tools" para código deprecado

**Contexto:** `assert_gates` estaba al inicio de "Tool handlers". Con la deprecación, ¿dónde debe vivir el código?

**Decisión:** Mover el handler completo después de `end_turn`, bajo el header `# ── Legacy / archived tools ──` que ya agrupa `record_intento` y `complete_intento`.

**Justificación:** El header ya existe y documenta la política (deprecated in favor of the consolidated 2-call flow). Agrupa las 3 herramientas legacy en un solo lugar: mejora el scan visual, reduce el riesgo de que alguien use el tool pensando que es core, y hace la verificación S3 trivial. `card_update_description` y `delete_intento` no son legacy (sin DEPRECATED) — no se mueven; el README las lista como activas y eso es correcto.

### ADR-4: Documentación ES/EN consistente con inventario verificable

**Contexto:** Un hallazgo de judgment previo detectó que el conteo real de tools es 20, no 18. El README tenía "16 active + 2 legacy" con `mission_get` / `checklist_item_get` existiendo en el código pero sin documentar.

**Decisión:** Documentar el conteo **20 (17 activas + 3 legacy)** en todas las apariciones (diagrama, tabla de features, sección Tools, árbol de proyecto) y añadir filas para `mission_get` y `checklist_item_get` en Misiones/Deck Sync, en ambos idiomas.

**Justificación:** El conteo pasa de ser "hand-maintained" a verificable con `app.list_tools()` (NF-AGD-03). 20 = 17 activas + 3 legacy: se obtiene de `rg -c "@app\.tool\(\)"` = 20 y `rg -c "DEPRECATED"` = 3. Documentar las dos tools faltantes cierra el gap de cobertura que causó el desvío original.

---

## 2. Structure / Flow

```
server.py (sin cambios de comportamiento)
├── Tool handlers (activas, 17)
│   ├── check_gate / complete_gate / server / map_* / sync_* / mission_list
│   ├── mission_get (1088) / checklist_item_get (1102)   ← documentadas en README
│   ├── begin_turn (1111) → end_turn (1265)
│   └── card_update_description (1558) / delete_intento (1643)  ← activas, sin DEPRECATED
└── Legacy / archived tools (3, DEPRECATED)
    ├── assert_gates (1413)  ← movida aquí desde línea ~170
    ├── record_intento (1521)
    └── complete_intento (1664)

plugin_preflight.py (sin cambios)
├── _on_session_start → ultratimonel_client.assert_gates(...)  (línea 243)
├── _pre_llm_call     → ultratimonel_client.assert_gates(...)  (línea 285)
└── _gates_bouncer (pre_tool_call) → lee la caché llenada por los hooks; NO llama assert_gates
```

---

## 3. Component Impact

| Componente | Impacto | Detalle |
|------------|---------|---------|
| `ultratimonel/server.py` | Move + docstring | `assert_gates` reubicada sin tocar cuerpo ni firma; docstring deprecado |
| `README.md` / `README.en.md` | Docs | Conteo 20 (17+3), filas `mission_get` / `checklist_item_get`, `assert_gates` a legacy |
| `ultratimonel/plugin_preflight.py` | Ninguno | Sigue llamando a `assert_gates` — razón de la compatibilidad |
| `tests/*` | Ninguno | Tests existentes de assert_gates siguen válidos (comportamiento intacto) |

---

## 4. Verification Strategy

- **Inventario**: `rg -c "@app\.tool\(\)" ultratimonel/server.py` == 20; docstrings `DEPRECATED` == 3.
- **Ubicación**: header `Legacy / archived tools` seguido de `assert_gates`.
- **Docstring**: `~~DEPRECATED~~ ... use begin_turn() instead` en la línea 1419.
- **READMEs**: grep `20 MCP tools` y `17 active + 3 legacy` en ambos; `assert_gates` fuera de "Núcleo (Gates)".
- **Plugin**: `assert_gates(` presente en plugin_preflight.py (línea 243 `_on_session_start`, línea 285 `_pre_llm_call`).
- **Tests**: `pytest tests/test_server.py tests/test_integration.py -k "assert_gates"` en verde.
