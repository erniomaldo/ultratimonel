# Mission-Bound Intentos — Zero phantom intentos

## Problema
`record_intento()` acepta `mission_id=0` y `checklist_item_id=0`, lo que permite crear intentos sin vínculo a una misión real de Deck. En esta sesión se registraron 6 intentos fantasma (IDs #17-#22) sin misión, quemando tokens sin accountability.

## Summary
Las 3 capas de enforcement obligan a que todo intento esté atado a un checklist_item de una misión real. Sin misión no hay intento.

## Cambios

### Fase 1 — Protocolo (agente, SOUL.md)
- Nuevo **Paso 4b** en SOUL.md: obliga al agente a identificar misión antes de record_intento()
- Actualización del **Paso 5**: eliminar fallback `mission_id=0`

### Fase 2 — Tool validation (server.py, opencode)
- `record_intento()` rechaza `mission_id <= 0` o `checklist_item_id <= 0` con error explícito
- `create_intento()` en persistence valida los mismos constraints

### Fase 3 — Plugin bouncer (__init__.py, PR futuro)
- Bloqueo en pre_tool_call si record_intento no lleva mission_id > 0

## Checklist PAC

### Fase 1 — Definición (OpenSpec)
- [x] proposal.md
- [x] design.md (6 ADRs: 001–006)
- [x] tasks.md
- [x] specs/mission-validation/spec.md
- [x] specs/intento-id-enforcement/spec.md
- [x] specs/consolidated-intent-flow/spec.md

### Fase 2 — Implementación SDD
- [ ] `record_intento()` validación en server.py (opencode)
- [ ] Tests
- [ ] PR + push

### Fase 3 — Deploy
- [ ] Revisión PM
- [ ] Merge
