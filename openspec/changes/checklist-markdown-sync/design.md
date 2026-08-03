# Design: checklist-markdown-sync

## ADR-011: Fallback de descripción para parseo markdown de checklists

### Contexto

`sync_tasks` en `server.py` (L926-L972) sigue una cadena de extracción de
checklists que asume que el campo `description` proviene de `deck_get_stacks`.
Sin embargo, este endpoint no incluye la descripción completa — solo un preview
truncado. La descripción completa vive en `deck_get_card` (card_detail).

El fallback de parseo markdown (`- [ ]` / `- [x]`) en L972 está diseñado para
casos donde `checklistItems` no está disponible, pero la condición
`if checklist_total == 0 and description:` nunca se satisface porque
`description` ya es `""`.

### Decisión

Agregar un fallback de una línea después de obtener `card_detail` y antes del
bloque de parseo markdown:

```python
# Después de obtener card_detail, antes del parseo markdown
if not description and isinstance(card_detail, dict):
    description = card_detail.get("description", "") or ""
```

### Alternativas consideradas

| Alternativa | Pros | Contras |
|-------------|------|---------|
| Usar siempre `card_detail["description"]` | Siempre tiene el texto completo | Rompería regression si stacks trae description diferente |
| Agregar campo `checklistItems` al response de stacks | Solución más limpia a largo plazo | Requiere cambios en la API de Deck/Nextcloud |
| Fallback condicional (elegido) | Mínimo cambio, preserva comportamiento existente | Ninguno relevante |

### Consecuencias

- **Positivas**: Reactiva el fallback markdown sin cambiar el parsing existente;
  regresión protegida por tests.
- **Negativas**: Ninguna — el fallback solo ejecuta cuando `description` está vacío.
- **Riesgos**: Bajo. El cambio es una sola línea condicional que no altera los
  caminos existentes donde `description` ya tiene valor.

### Artefactos

- `ultratimonel/server.py` — fix en sync_tasks (~L971)
- `tests/test_server.py` — tests unitarios para ambos escenarios
