# Spec: checklist-markdown-sync

## Req-1: Fallback de descripción completa

**SHALL** `sync_tasks` usar la descripción completa del detalle de la card como
fallback cuando el response de `deck_get_stacks` no proporciona un campo
`description` no vacío.

### Escenario 1a: stacks sin description, card_detail con markdown checklist

**DADO QUE** `deck_get_stacks` devuelve una card sin campo `description` (o con
cadena vacía)
**Y QUE** `deck_get_card` devuelve un `card_detail` cuyo campo `description`
contiene checkboxes en markdown (`- [ ]`, `- [x]`)
**ENTONCES** `sync_tasks` SHALL parsear los checkboxes del markdown y calcular
`checklist_total` y `checklist_done` correctamente.

### Escenario 1b: stacks con description (regresión)

**DADO QUE** `deck_get_stacks` devuelve una card con campo `description` no vacío
**ENTONCES** `sync_tasks` SHALL usar la descripción de stacks (comportamiento
existente) y el fallback NO SHALL interferir.

### Escenario 1c: neither tiene description

**DADO QUE** ni `deck_get_stacks` ni `card_detail` proporcionan una descripción
no vacía
**ENTONCES** `sync_tasks` SHALL continuar con `description = ""` sin crash.
