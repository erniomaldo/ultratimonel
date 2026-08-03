# labels-tolerant-parsing — Spec

## Req-1: Parsing tolerante de labels

El parse de labels en `_call_deck` **SHALL** aceptar tanto dicts como strings.

### Escenario 1: labels como dicts

GIVEN un card con `labels = [{"id": 1, "title": "Crítica", "color": "#ff0000"}]`
WHEN se ejecuta `_call_deck`
THEN los labels extraídos son `["Crítica"]`

### Escenario 2: labels como strings

GIVEN un card con `labels = ["🚨 Crítica", "Prioritaria"]`
WHEN se ejecuta `_call_deck`
THEN los labels extraídos son `["🚨 Crítica", "Prioritaria"]`

### Escenario 3: labels null/empty

GIVEN un card con `labels = None` o `labels = []`
WHEN se ejecuta `_call_deck`
THEN los labels extraídos son `[]`

### Escenario 4: mezcla str + dict

GIVEN un card con `labels = [{"title": "A"}, "B"]`
WHEN se ejecuta `_call_deck`
THEN los labels extraídos son `["A", "B"]`

## Req-2: No regressión

El fix **NO SHALL** cambiar el comportamiento para cards sin campo `labels`.

### Escenario 5: card sin labels

GIVEN un card sin clave `labels`
WHEN se ejecuta `_call_deck`
THEN los labels extraídos son `[]` (mismo que antes)
