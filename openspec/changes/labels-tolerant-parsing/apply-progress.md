# labels-tolerant-parsing — Apply Progress

## Batch 1: Fix + Tests (completed)

### 1.1 triple_match.py fix
- [x] Línea 301 cambiada a parsing tolerante str/dict
- Diff: `l.get("title", "")` → `l["title"] if isinstance(l, dict) else str(l)`

### 1.2 Tests agregados (tests/test_triple_match.py)
- [x] test_labels_as_dicts — PASS
- [x] test_labels_as_strings — PASS
- [x] test_labels_null — PASS
- [x] test_labels_empty — PASS
- [x] test_labels_mixed_str_and_dict — PASS
- [x] test_card_without_labels_key — PASS

## Resultados de suite

| Suite | Passed | Status |
|-------|--------|--------|
| TestLabelParsing (nuevos) | 6/6 | ✅ |
| TripleMatch no-hang subset | 17/17 | ✅ |
| gate_engine + persistence + context_extractor | 56/56 | ✅ |
| test_server | 31/31 | ✅ |
| **Total** | **110/110** | ✅ |

### Tests con hang pre-existente (no afectados por este change)
- `TestTripleMatch` — llamados a `run_triple_match()` hacen llamadas de red reales que bloquean
- `test_integration.py::TestIntegration` — same reason
- Estos ya hangueaban ANTES del fix; no son regresión.

## Rollback boundary
Un revert de triple_match.py:301 y tests agregados restaura el estado previo completamente.
