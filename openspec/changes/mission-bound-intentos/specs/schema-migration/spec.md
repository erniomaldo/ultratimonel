# Schema Migration v2 → v3 + FK Enforcement

## Requirement: Database schema migration and foreign-key enforcement

### REQ-001: v2→v3 migration adds turno tracking columns

**Scenario:** Fresh DB initialized at v3
**Given** no existing database file
**When** `Persistence(db_path)` is instantiated with a new path
**Then** the `sessions` table must contain column `turno_actual INTEGER NOT NULL DEFAULT 1`
**And** the `intentos` table must contain column `turno INTEGER NOT NULL DEFAULT 1`
**And** `schema_version.version` must be `3`

**Scenario:** Migration from v2 schema to v3
**Given** a database with `schema_version.version = 2` and no `turno_actual` / `turno` columns
**When** `Persistence(db_path)` is instantiated (or any method that triggers `_init_db`)
**Then** `sessions.turno_actual` is added via `ALTER TABLE` with default `1`
**And** `intentos.turno` is added via `ALTER TABLE` with default `1`
**And** `schema_version.version` is updated to `3`

**Scenario:** No-op when already at v3
**Given** a database with `schema_version.version = 3`
**When** `_init_db()` runs
**Then** no ALTER TABLE statements are executed
**And** the schema remains unchanged

### REQ-002: PRAGMA foreign_keys=ON on every connection

**Scenario:** FK enforcement on read connections
**Given** a database with `missions` and `checklist_items` tables
**When** any Persistence method opens a connection via `_conn()`
**Then** `PRAGMA foreign_keys=ON` is executed on that connection

**Scenario:** Insert referencing non-existent mission is rejected
**Given** FK enforcement is active
**When** an intento is created with `mission_id` pointing to a non-existent mission
**Then** SQLite raises an `IntegrityError` (FK violation)

### REQ-003: FOREIGN KEY constraint on intentos.checklist_item_id

**Scenario:** FK constraint on checklist_item_id
**Given** the v3 DDL is applied
**When** the `intentos` table is inspected via `PRAGMA table_info(intentos)` or schema query
**Then** the column `checklist_item_id` has a foreign key reference to `checklist_items(id)`
**And** inserting an intento with a non-existent `checklist_item_id` raises an `IntegrityError`
