"""Quest 9 (#218): replica-only ``mission_delete`` and ``deck_stack_id`` exposure.

Pieza 1 — ``mission_delete(mission_id)`` deletes the mission and its dependent
replica rows atomically, requires ``confirm`` + ``reason``, writes an audit row
to ``mission_deletions``, and NEVER touches Deck.

Pieza 2 — ``mission_get`` / ``mission_list`` expose ``deck_stack_id`` so
``card_update_description(mission_id=...)`` can resolve board+stack without a
``deck_get_stacks`` lookup when the value is present, falling back to the
existing lookup when it is NULL.

All tests use an in-memory/temporary replica and a fake Deck: no live MCP call
is ever made and no production row is touched.
"""

import json
import tempfile
from contextlib import ExitStack
from unittest.mock import patch

from ultratimonel.persistence import Persistence

PROJECT = "testproj"
BOARD = 21

COUNTED_TABLES = (
    "missions",
    "checklist_items",
    "intentos",
    "attempt_grants",
    "turn_bitacora",
)


def _counts(persistence):
    with persistence._conn() as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in COUNTED_TABLES
        }


def _seed_mission(persistence, deck_task_id, title, stack_id=None):
    mission_id = persistence.upsert_mission(
        deck_task_id=deck_task_id, project=PROJECT, title=title
    )
    if stack_id is not None:
        persistence.set_mission_deck_stack_id(mission_id, stack_id)
    q1 = persistence.upsert_checklist_item(mission_id, 0, "alpha")
    q2 = persistence.upsert_checklist_item(mission_id, 1, "beta")
    intento_id = persistence.create_intento("sess", PROJECT, mission_id, q1)
    persistence.grant_attempts(mission_id, q1, 2, "pm")
    persistence.append_bitacora(
        intento_id, "sess", PROJECT, mission_id, q1, "success", 4, "done"
    )
    persistence.append_bitacora(
        intento_id + 1000, "sess", PROJECT, mission_id, q2, "fail", 0, "nope"
    )
    return {
        "mission_id": mission_id,
        "quest_ids": [q1, q2],
        "intento_id": intento_id,
    }


def _check_deck_untouched(mock_call):
    """No Deck write/delete tool was ever invoked by mission_delete."""
    forbidden = {"deck_delete_card", "deck_archive_card", "deck_move_card"}
    names = [call.args[1] for call in mock_call.call_args_list if len(call.args) > 1]
    assert forbidden.isdisjoint(names)


# ── mission_delete: validation and guards ─────────────────────────────────


class TestMissionDeleteGuards:
    def test_mission_delete_requires_confirm(self):
        persistence = Persistence(":memory:")
        try:
            seeded = _seed_mission(persistence, 10, "Guarded")
            before = _counts(persistence)

            from ultratimonel.server import mission_delete

            with patch("ultratimonel.server.persistence", persistence):
                result = json.loads(mission_delete(seeded["mission_id"]))

            assert "error" in result
            assert "confirm" in result["error"]
            assert _counts(persistence) == before
            assert persistence.get_mission(seeded["mission_id"]) is not None
        finally:
            persistence.close()

    def test_mission_delete_requires_non_empty_reason(self):
        persistence = Persistence(":memory:")
        try:
            seeded = _seed_mission(persistence, 11, "Needs reason")
            before = _counts(persistence)

            from ultratimonel.server import mission_delete

            with patch("ultratimonel.server.persistence", persistence):
                result = json.loads(
                    mission_delete(seeded["mission_id"], confirm=True, reason="   ")
                )

            assert "error" in result
            assert "reason" in result["error"]
            assert _counts(persistence) == before
            assert persistence.get_mission(seeded["mission_id"]) is not None
        finally:
            persistence.close()

    def test_mission_delete_unknown_mission_errors_with_id(self):
        persistence = Persistence(":memory:")
        try:
            from ultratimonel.server import mission_delete

            with patch("ultratimonel.server.persistence", persistence):
                result = json.loads(
                    mission_delete(9999, confirm=True, reason="cleanup")
                )

            assert "error" in result
            assert "9999" in result["error"]
            with persistence._conn() as conn:
                assert conn.execute(
                    "SELECT COUNT(*) FROM mission_deletions"
                ).fetchone()[0] == 0
        finally:
            persistence.close()


# ── mission_delete: happy path, isolation and audit ───────────────────────


class TestMissionDeleteHappyPath:
    def test_mission_delete_removes_only_target_and_reports_counts(self):
        persistence = Persistence(":memory:")
        try:
            target = _seed_mission(persistence, 20, "Delete me")
            survivor = _seed_mission(persistence, 21, "Keep me")
            before = _counts(persistence)

            from ultratimonel.server import mission_delete

            with patch("ultratimonel.server.persistence", persistence) as _p:
                result = json.loads(
                    mission_delete(
                        target["mission_id"],
                        confirm=True,
                        reason="duplicate replica row",
                        requested_by="tester",
                    )
                )

            assert result["status"] == "deleted"
            assert result["mission_id"] == target["mission_id"]
            assert result["deck_task_id"] == 20
            assert result["replica_only"] is True
            assert result["deck_untouched"] is True
            assert result["deleted"] == {
                "quests": 2,
                "intentos": 1,
                "attempt_grants": 1,
                "turn_bitacora": 2,
            }

            after = _counts(persistence)
            assert after["missions"] == before["missions"] - 1
            assert after["checklist_items"] == before["checklist_items"] - 2
            assert after["intentos"] == before["intentos"] - 1
            assert after["attempt_grants"] == before["attempt_grants"] - 1
            assert after["turn_bitacora"] == before["turn_bitacora"] - 2

            # The other mission and every row that belongs to it survived.
            assert persistence.get_mission(target["mission_id"]) is None
            assert persistence.get_mission(survivor["mission_id"]) is not None
            assert [
                ci["id"] for ci in persistence.list_checklist_items(
                    survivor["mission_id"]
                )
            ] == survivor["quest_ids"]
            assert persistence.get_intento(survivor["intento_id"]) is not None
            with persistence._conn() as conn:
                assert conn.execute(
                    "SELECT COUNT(*) FROM attempt_grants WHERE mission_id = ?",
                    (survivor["mission_id"],),
                ).fetchone()[0] == 1
                assert conn.execute(
                    "SELECT COUNT(*) FROM turn_bitacora WHERE mission_id = ?",
                    (survivor["mission_id"],),
                ).fetchone()[0] == 2
        finally:
            persistence.close()

    def test_mission_delete_writes_audit_event_read_from_replica(self):
        persistence = Persistence(":memory:")
        try:
            seeded = _seed_mission(persistence, 30, "Audited")

            from ultratimonel.server import mission_delete

            with patch("ultratimonel.server.persistence", persistence):
                result = json.loads(
                    mission_delete(
                        seeded["mission_id"],
                        confirm=True,
                        reason="obsolete replica row",
                        requested_by="hermes-agent",
                    )
                )

            # Read the audit event from the replica, never from the payload.
            with persistence._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM mission_deletions WHERE id = ?",
                    (result["audit_id"],),
                ).fetchone()

            assert row is not None
            assert row["mission_id"] == seeded["mission_id"]
            assert row["deck_task_id"] == 30
            assert row["project"] == PROJECT
            assert row["title"] == "Audited"
            assert row["reason"] == "obsolete replica row"
            assert row["requested_by"] == "hermes-agent"
            assert row["quests_deleted"] == 2
            assert row["intentos_deleted"] == 1
            assert row["grants_deleted"] == 1
            assert row["bitacora_deleted"] == 2
            assert row["created_at"]
            ids = json.loads(row["deleted_ids"])
            assert ids["mission_ids"] == [seeded["mission_id"]]
            assert ids["checklist_item_ids"] == seeded["quest_ids"]
        finally:
            persistence.close()

    def test_mission_delete_never_calls_deck(self):
        persistence = Persistence(":memory:")
        try:
            seeded = _seed_mission(persistence, 31, "Replica only")

            from ultratimonel.server import mission_delete

            with patch("ultratimonel.mcp_client.call_mcp_tool") as mock_call:
                with patch("ultratimonel.server.persistence", persistence):
                    json.loads(
                        mission_delete(
                            seeded["mission_id"], confirm=True, reason="cleanup"
                        )
                    )

            mock_call.assert_not_called()
            _check_deck_untouched(mock_call)
        finally:
            persistence.close()


# ── schema v8: idempotent migration + downgrade ───────────────────────────


class TestMissionDeletionsMigration:
    def test_v7_to_v8_is_idempotent(self):
        from ultratimonel.persistence import _migrate_v7_to_v8

        persistence = Persistence(":memory:")
        try:
            with persistence._conn() as conn:
                _migrate_v7_to_v8(conn)
                _migrate_v7_to_v8(conn)
                assert conn.execute(
                    "SELECT COUNT(*) FROM schema_version WHERE version = 8"
                ).fetchone()[0] == 1
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                assert "mission_deletions" in tables
        finally:
            persistence.close()

    def test_downgrade_v8_db_opens_under_v7_code(self):
        """A newer file stays readable/usable by v7-era code (SCHEMA_AHEAD).

        The v7 runtime is simulated by pinning ``SCHEMA_VERSION`` back to 7, so
        the unknown newer version falls through every migration branch exactly
        as v7 code would.
        """
        import ultratimonel.persistence as persistence_mod

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            p = persistence_mod.Persistence(db_path=db_path)
            seeded = _seed_mission(p, 40, "Future DB")
            p.close()

            with patch.object(persistence_mod, "SCHEMA_VERSION", 7), patch.object(
                persistence_mod, "SCHEMA_DESCRIPTION", "v7"
            ):
                v7_runtime = persistence_mod.Persistence(db_path=db_path)
                try:
                    assert v7_runtime.get_mission(seeded["mission_id"]) is not None
                    mid = v7_runtime.upsert_mission(
                        deck_task_id=41, project=PROJECT, title="v7 write"
                    )
                    assert v7_runtime.get_mission(mid)["title"] == "v7 write"
                    with v7_runtime._conn() as conn:
                        assert conn.execute(
                            "SELECT MAX(version) FROM schema_version"
                        ).fetchone()[0] >= 8
                finally:
                    v7_runtime.close()
        finally:
            import os

            try:
                os.unlink(db_path)
            except OSError:
                pass


# ── pieza 2: deck_stack_id exposed and used ──────────────────────────────


class TestDeckStackIdExposure:
    def test_mission_get_exposes_deck_stack_id_value_and_null(self):
        persistence = Persistence(":memory:")
        try:
            with_stack = _seed_mission(persistence, 50, "With stack", stack_id=111)
            without_stack = _seed_mission(persistence, 51, "No stack")

            from ultratimonel.server import mission_get

            with patch("ultratimonel.server.persistence", persistence):
                present = json.loads(mission_get(with_stack["mission_id"]))
                missing = json.loads(mission_get(without_stack["mission_id"]))

            assert present["deck_stack_id"] == 111
            assert missing["deck_stack_id"] is None
        finally:
            persistence.close()

    def test_mission_list_exposes_deck_stack_id_value_and_null(self):
        persistence = Persistence(":memory:")
        try:
            with_stack = _seed_mission(persistence, 60, "With stack", stack_id=222)
            without_stack = _seed_mission(persistence, 61, "No stack")

            from ultratimonel.server import mission_list

            with patch("ultratimonel.server.persistence", persistence):
                compact = json.loads(mission_list(PROJECT))
                full = json.loads(mission_list(PROJECT, include_description=True))

            by_id = {m["id"]: m for m in compact["missions"]}
            assert by_id[with_stack["mission_id"]]["deck_stack_id"] == 222
            assert by_id[without_stack["mission_id"]]["deck_stack_id"] is None

            full_by_id = {m["id"]: m for m in full["missions"]}
            assert full_by_id[with_stack["mission_id"]]["deck_stack_id"] == 222
            assert full_by_id[without_stack["mission_id"]]["deck_stack_id"] is None
        finally:
            persistence.close()

    def test_card_update_description_uses_deck_stack_id_without_lookup(self):
        persistence = Persistence(":memory:")
        try:
            seeded = _seed_mission(persistence, 70, "Stacked", stack_id=333)
            events = []

            def fake_call(server_name, tool_fn, params, **kwargs):
                events.append(tool_fn)
                if tool_fn == "deck_get_card":
                    return ({"id": 70, "title": "Original", "description": "old"}, None)
                if tool_fn == "deck_update_card":
                    return ({"id": 70}, None)
                if tool_fn == "deck_get_stacks":
                    return ({"stacks": [{"id": 1, "title": "Backlog"}]}, None)
                return (None, "unavailable")

            from ultratimonel.server import card_update_description

            with ExitStack() as stack:
                stack.enter_context(
                    patch("ultratimonel.mcp_client.call_mcp_tool", side_effect=fake_call)
                )
                stack.enter_context(
                    patch(
                        "ultratimonel.context_extractor.get_project_maps",
                        return_value={PROJECT: {"deck_board_id": BOARD}},
                    )
                )
                stack.enter_context(patch("ultratimonel.server.persistence", persistence))
                result = json.loads(
                    card_update_description(
                        description="new prose", mission_id=seeded["mission_id"]
                    )
                )

            assert result["status"] == "ok"
            assert "deck_get_stacks" not in events
            assert "deck_update_card" in events
        finally:
            persistence.close()

    def test_card_update_description_falls_back_when_stack_is_null(self):
        persistence = Persistence(":memory:")
        try:
            seeded = _seed_mission(persistence, 71, "No stack")
            events = []
            stacks_params = {}
            update_params = {}

            def fake_call(server_name, tool_fn, params, **kwargs):
                events.append(tool_fn)
                if tool_fn == "deck_get_card":
                    return ({"id": 71, "title": "Original", "description": "old"}, None)
                if tool_fn == "deck_update_card":
                    update_params.update(params)
                    return ({"id": 71}, None)
                if tool_fn == "deck_get_stacks":
                    stacks_params.update(params)
                    return ({"stacks": [{"id": 1, "title": "Backlog"}]}, None)
                return (None, "unavailable")

            from ultratimonel.server import card_update_description

            with ExitStack() as stack:
                stack.enter_context(
                    patch("ultratimonel.mcp_client.call_mcp_tool", side_effect=fake_call)
                )
                stack.enter_context(
                    patch(
                        "ultratimonel.context_extractor.get_project_maps",
                        return_value={PROJECT: {"deck_board_id": BOARD}},
                    )
                )
                stack.enter_context(patch("ultratimonel.server.persistence", persistence))
                result = json.loads(
                    card_update_description(
                        description="new prose", mission_id=seeded["mission_id"]
                    )
                )

            assert result["status"] == "ok"
            assert events.count("deck_get_stacks") == 1
            assert stacks_params["board_id"] == BOARD
            assert update_params["board_id"] == BOARD
            assert update_params["stack_id"] == 1
        finally:
            persistence.close()

    def test_card_update_description_keeps_explicit_board_and_stack(self):
        """The pre-existing explicit board+stack call shape is untouched."""
        stack_calls = []

        def fake_call(server_name, tool_fn, params, **kwargs):
            if tool_fn == "deck_get_stacks":
                stack_calls.append(params)
            if tool_fn == "deck_get_card":
                return ({"id": 99, "title": "T", "description": "old"}, None)
            if tool_fn == "deck_update_card":
                return ({"id": 99}, None)
            return (None, "unavailable")

        from ultratimonel.server import card_update_description

        with patch("ultratimonel.mcp_client.call_mcp_tool", side_effect=fake_call):
            result = json.loads(
                card_update_description(
                    99, "new", board_id=1, stack_id=2
                )
            )

        assert result["status"] == "ok"
        assert result["title_preserved"] == "T"
        assert stack_calls == []
