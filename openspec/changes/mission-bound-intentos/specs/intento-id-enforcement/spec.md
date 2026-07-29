# Intento-ID Enforcement — Spec

## Requirement: complete_intento must enforce intento_id belongs to the current turn

**Scenario:** complete_intento rejects intento_id from different turn
**Given** a session with two distinct turns (turn A and turn B)
**When** `record_intento()` is called during turn A, producing intento_id=42
**And** during turn B, `complete_intento(session_id, project, intento_id=42)` is called
**Then** the response must contain `"status": "error"`
**And** the error message must state that intento_id=42 does not belong to the current turn

**Scenario:** complete_intento accepts intento_id from current turn
**Given** a session with one active turn
**When** `record_intento(session_id, project, mission_id=5, checklist_item_id=10)` is called during the turn and returns intento_id=42
**AND** `complete_intento(session_id, project, intento_id=42)` is called during the same turn
**Then** the response must contain `"status": "ok"`
**And** the intento with id=42 must be marked as completed in persistence
