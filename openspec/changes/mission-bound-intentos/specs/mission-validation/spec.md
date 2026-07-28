# Mission Validation — Spec

## Requirement: record_intento must reject mission_id=0

**Scenario:** Agent calls record_intento with mission_id=0
**Given** an active session with gates PASS
**When** record_intento(session_id, project, mission_id=0, checklist_item_id=0) is called
**Then** the response must contain `"status": "error"`
**And** the error message must mention that mission_id must be > 0
**And** the error message must suggest using sync_tasks() first

**Scenario:** Agent calls record_intento with valid mission_id
**Given** a synced mission exists with id=5 and checklist_item_id=10
**When** record_intento(session_id, project, mission_id=5, checklist_item_id=10) is called
**Then** the response must contain `"status": "ok"` and a valid intento_id

**Scenario:** Agent calls record_intento with checklist_item_id=0 but mission_id>0
**Given** an active session with gates PASS
**When** record_intento(session_id, project, mission_id=5, checklist_item_id=0) is called
**Then** the response must contain `"status": "error"`
**And** the error must mention checklist_item_id must be > 0

**Scenario:** Backward compatibility with mission_id>0, item_id>0
**Given** existing code that calls record_intento with valid parameters
**When** the same call is made after the change
**Then** it must work identically to before

**Scenario:** assert_gates accepts explicit project parameter
**Given** an active session
**When** assert_gates(message, session_id, project="ultratimonel") is called
**Then** the gates must run against project "ultratimonel"
**And** the context.project in the response must be "ultratimonel"

**Scenario:** assert_gates falls back to auto-detection without project param
**Given** an active session
**When** assert_gates(message, session_id) is called without project
**Then** the context.project must be auto-detected from the message
**And** backward compatibility must be preserved
