# endTurn Bouncer — Validación server-side en complete_intento()

## Problema
`complete_intento()` acepta cualquier `gates_passed` sin verificar el estado real de las gates en SQLite. El plugin preflight bloquea en Hermes, pero no hay segundo candado server-side.

## Summary
Agregar validación server-side en `complete_intento()` que consulte `gate_state` antes de permitir la completación. Con `session_id`+`project`, verifica que las 4 gates mandatory estén PASS/SKIP. Si no, rechaza con `status=blocked`. Patrón endTurn de Nikhil Verma.

## Cambios
- `server.py`: `complete_intento()` modificado con 2 parámetros nuevos (`session_id`, `project`) + lógica bouncer
- `server.py`: Nueva tool `card_update_description()` para actualizar descripción de cards Deck sin pisar título
- `persistence.py`: `list_gate_states()` corregido para devolver solo la última entrada por gate (vía `MAX(id)`), evitando WARN fantasma por entradas duplicadas del plugin

## Checklist PAC

### Fase 1 — Definición (OpenSpec)
- [x] proposal.md
- [ ] tasks.md
- [ ] specs/endturn-validation/spec.md
- [ ] design.md

### Fase 2 — Implementación (SDD)
- [x] Código implementado en working tree
- [ ] judgment-day
- [ ] PR + push

### Fase 3 — Deploy
- [ ] Revisión PM
- [ ] Merge
