# labels-tolerant-parsing — Tasks

## Fase 1: Implementación

### 1.1 Fix en triple_match.py
- [ ] Cambiar línea ~301 de `ultratimonel/triple_match.py`:
  - Antes: `"labels": [l.get("title", "") for l in (card.get("labels") or [])]`
  - Después: `"labels": [l["title"] if isinstance(l, dict) else str(l) for l in (card.get("labels") or [])]`

### 1.2 Tests unitarios
- [ ] Agregar tests en `tests/test_triple_match.py`:
  - labels como dicts → se extrae title
  - labels como strings → se usa el string
  - labels null/vacio → []
  - mezcla str+dict
  - card sin campo labels → []

## Fase 2: Verificación

### 2.1 Ejecutar suite
- [ ] Correr `.venv/bin/python -m pytest tests/test_triple_match.py` — todos los tests que pasan deben seguir pasando.
- [ ] Los nuevos tests deben pasar.
- [ ] Tests que llaman `run_triple_match()` (pre-existing hang) no deben afectar resultado.

### 2.2 Verificación manual
- [ ] Confirmar que el fix no rompe el flujo de `_call_deck` con datos reales (dict labels).
