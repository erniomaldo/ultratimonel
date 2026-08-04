# checklist-markdown-sync — Reactivar fallback de parseo markdown de checklists

## Problema

`sync_tasks` en `ultratimonel/server.py` no extrae los checklists de las cards
porque estos viven como **markdown** en el campo `description` (no en un campo
separado `checklistItems`). La cadena de fallos:

1. L926: `description = card.get("description", "")` lee del response de
   `deck_get_stacks`, que NO incluye `description` (solo `descriptionPreview`
   truncado) → queda `""`.
2. L948: `card_detail.get("checklistItems", [])` — el server no devuelve
   `checklistItems` → lista vacía.
3. L972: fallback markdown `if checklist_total == 0 and description:` — como
   `description` es `""`, la condición falla y el parseo nunca corre, aunque
   `card_detail["description"]` contiene el checklist completo en markdown.

Resultado: todas las misiones con `checklist_total == 0` van al dashboard sin
progreso de checklist. Evidencia del Hermes hermano: card 106 (6 items - [ ]),
card 99 (13 items [x]/[ ]) — los checklists SÍ están en Nextcloud, en el
markdown de la descripción.

## Scope

- **In scope**: Fix en `sync_tasks` para que el fallback markdown se ejecute;
  tests unitarios que cubran ambos casos (stacks sin description, stacks con
  description).
- **Out of scope**: Cambiar la API de Deck, agregar campo `checklistItems` al
  response de stacks, modificar el parseo de `- [ ]` / `- [x]`.

## Enfoque propuesto

Agregar un fallback después de obtener `card_detail` y ANTES del parseo markdown:
si `description` está vacío, usar la descripción completa del detalle. Esto
reactiva el fallback existente en L972 sin alterar ninguna otra lógica.
