# labels-tolerant-parsing — Parsing tolerante de labels (str o dict) en triple_match

## Problema

El gate 1e (`_call_deck`) crashea con `AttributeError: 'str' object has no attribute 'get'`
cuando el MCP de Nextcloud devuelve labels como **strings** en lugar de dicts.

La línea crítica en `ultratimonel/triple_match.py:301`:

```python
"labels": [l.get("title", "") for l in (card.get("labels") or [])],
```

Un string no tiene `.get()` → crash → WARN 1e.

## Evidencia multi-deployment

| Deployment | Formato labels | Estado |
|------------|---------------|--------|
| `abec` (:2993, del Hermes hermano) | `['🚨 Crítica']` — strings | **CRASH** (card #96, board 13) |
| `agendasencilla` (mcpnextcloud.agendasencilla.com) | `[{'id', 'title', 'color', 'boardId', 'cardId'}]` — dicts | OK (card #133, board 20) |

El emoji NO es la causa; la causa es el **formato** (str vs dict), que difiere
entre deployments de Nextcloud Deck (multi-servidor).

## Scope

- Fix en `ultratimonel/triple_match.py` línea ~301: parsing tolerante str/dict.
- Tests unitarios en `tests/test_triple_match.py`.
- NO tocar el MCP ni normalizar en el servidor; tolerar en el consumidor (repo).

## Qué NO incluye

- Cambios en el plugin preflight.
- Normalización del formato labels en el MCP de Nextcloud.
- Cambios en otros gates (1a, 1b, 1c).
