"""Quest 8 (#218): ``sync_tasks`` drift report and proven-orphan pruning.

The forum reproduction lives on the ``ajustes-en-diseno-actual`` board, which is
not reachable from this environment. These tests use synthetic fixtures (a real
in-memory replica + simulated Deck responses); the end-to-end check against the
real board is the PM's.

Covered:
- ``prune=False`` reports drift and deletes nothing.
- ``prune=True`` deletes only proven orphans.
- Failed / partial Deck reads prune nothing and report the error.
- Cards in Deck but not refreshed land in ``skipped`` with a cause.
- Idempotency: a second ``prune=True`` run reports ``pruned: []``.
- ``mission_list`` counts reflect the pruned row.
"""

import json
from contextlib import ExitStack
from unittest.mock import patch

from ultratimonel.persistence import Persistence

PROJECT = "testproj"
BOARD = 42
LIVE_CARD = 10
ORPHAN_CARD = 914


def _stack(cards, title="To Do", stack_id=1):
    return {"id": stack_id, "title": title, "cards": cards}


def _card(card_id, title="Card", description="", **extra):
    card = {"id": card_id, "title": title, "description": description}
    card.update(extra)
    return card


def _sync(persistence, stacks_payload, details=None, prune=False, maps=None):
    """Run ``sync_tasks`` against a real in-memory replica + fake Deck."""
    details = details if details is not None else {}

    def fake_call(server_name, tool_fn, params, **kwargs):
        if tool_fn == "deck_get_stacks":
            return stacks_payload, None
        if tool_fn == "deck_get_card":
            card_id = params.get("card_id")
            detail = details.get(card_id, {"id": card_id})
            return detail, None
        return None, f"unknown tool {tool_fn}"

    from ultratimonel.server import sync_tasks

    with ExitStack() as stack:
        stack.enter_context(
            patch("ultratimonel.mcp_client.call_mcp_tool", side_effect=fake_call)
        )
        stack.enter_context(
            patch(
                "ultratimonel.context_extractor.get_project_maps",
                return_value=maps or {PROJECT: {"deck_board_id": BOARD}},
            )
        )
        stack.enter_context(patch("ultratimonel.server.persistence", persistence))
        return json.loads(sync_tasks(PROJECT, prune=prune))


def _seed_orphan(persistence):
    return persistence.upsert_mission(
        deck_task_id=ORPHAN_CARD, project=PROJECT, title="Fantasma 914"
    )


def _seed_live(persistence):
    return persistence.upsert_mission(
        deck_task_id=LIVE_CARD, project=PROJECT, title="Viva"
    )


def _missing_ids(result):
    return [entry["mission_id"] for entry in result["missing_in_deck"]]


class TestDriftReport:
    def test_prune_false_reports_orphan_and_deletes_nothing(self):
        persistence = Persistence(":memory:")
        orphan_id = _seed_orphan(persistence)
        live_id = _seed_live(persistence)

        result = _sync(
            persistence,
            {"stacks": [_stack([_card(LIVE_CARD, "Viva")])]},
            details={LIVE_CARD: {"id": LIVE_CARD}},
        )

        assert result["synced"] == 1
        assert result["pruned"] == []
        assert _missing_ids(result) == [orphan_id]
        assert result["missing_in_deck"][0]["deck_task_id"] == ORPHAN_CARD
        # Nothing was deleted.
        assert persistence.get_mission(orphan_id) is not None
        assert persistence.get_mission(live_id) is not None
        assert result["read_complete"] is True

    def test_prune_true_deletes_only_the_proven_orphan(self):
        persistence = Persistence(":memory:")
        orphan_id = _seed_orphan(persistence)
        live_id = _seed_live(persistence)

        result = _sync(
            persistence,
            {"stacks": [_stack([_card(LIVE_CARD, "Viva")])]},
            details={LIVE_CARD: {"id": LIVE_CARD}},
            prune=True,
        )

        assert result["pruned"] == [orphan_id]
        assert _missing_ids(result) == [orphan_id]
        assert persistence.get_mission(orphan_id) is None
        assert persistence.get_mission(live_id) is not None
        assert result["total_pruned"] == 1

    def test_prune_is_idempotent(self):
        persistence = Persistence(":memory:")
        _seed_orphan(persistence)
        _seed_live(persistence)
        stacks_payload = {"stacks": [_stack([_card(LIVE_CARD, "Viva")])]}

        first = _sync(
            persistence,
            stacks_payload,
            details={LIVE_CARD: {"id": LIVE_CARD}},
            prune=True,
        )
        second = _sync(
            persistence,
            stacks_payload,
            details={LIVE_CARD: {"id": LIVE_CARD}},
            prune=True,
        )

        assert len(first["pruned"]) == 1
        assert second["pruned"] == []
        assert second["missing_in_deck"] == []

    def test_mission_list_count_reflects_prune(self):
        persistence = Persistence(":memory:")
        _seed_orphan(persistence)
        _seed_live(persistence)

        from ultratimonel.server import mission_list

        with patch("ultratimonel.server.persistence", persistence):
            before = json.loads(mission_list(PROJECT))["total"]

        _sync(
            persistence,
            {"stacks": [_stack([_card(LIVE_CARD, "Viva")])]},
            details={LIVE_CARD: {"id": LIVE_CARD}},
            prune=True,
        )

        with patch("ultratimonel.server.persistence", persistence):
            after = json.loads(mission_list(PROJECT))["total"]

        assert before == 2
        assert after == 1


class TestNeverPruneOnIncompleteRead:
    def test_failed_deck_read_prunes_nothing(self):
        persistence = Persistence(":memory:")
        orphan_id = _seed_orphan(persistence)

        # ``None`` stacks payload = the call failed.
        def fake_call(server_name, tool_fn, params, **kwargs):
            return None, "timeout"

        from ultratimonel.server import sync_tasks

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
            result = json.loads(sync_tasks(PROJECT, prune=True))

        assert result["pruned"] == []
        assert result["read_complete"] is False
        assert any("Cannot reach Deck" in err for err in result["errors"])
        assert persistence.get_mission(orphan_id) is not None

    def test_partial_shape_prunes_nothing(self):
        persistence = Persistence(":memory:")
        orphan_id = _seed_orphan(persistence)

        result = _sync(persistence, {"unexpected": "shape"}, prune=True)

        assert result["pruned"] == []
        assert result["read_complete"] is False
        assert any("incomplete" in err for err in result["errors"])
        assert persistence.get_mission(orphan_id) is not None

    def test_stack_without_id_prunes_nothing(self):
        persistence = Persistence(":memory:")
        orphan_id = _seed_orphan(persistence)

        result = _sync(
            persistence,
            {"stacks": [{"title": "To Do", "cards": [_card(99, "Sin stack")]}]},
            prune=True,
        )

        assert result["pruned"] == []
        assert result["read_complete"] is False
        assert persistence.get_mission(orphan_id) is not None

    def test_card_detail_failure_prunes_nothing_and_is_skipped(self):
        persistence = Persistence(":memory:")
        orphan_id = _seed_orphan(persistence)

        def fake_call(server_name, tool_fn, params, **kwargs):
            if tool_fn == "deck_get_stacks":
                return {"stacks": [_stack([_card(LIVE_CARD, "Sin detalle")])]}, None
            if tool_fn == "deck_get_card":
                return None, "detail read failed"
            return None, f"unknown tool {tool_fn}"

        from ultratimonel.server import sync_tasks

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
            result = json.loads(sync_tasks(PROJECT, prune=True))

        assert result["pruned"] == []
        assert result["read_complete"] is False
        assert result["skipped"][0]["deck_task_id"] == LIVE_CARD
        assert result["skipped"][0]["reason"].startswith("card_read_failed")
        assert persistence.get_mission(orphan_id) is not None


class TestSkippedWithReason:
    def test_unmapped_stack_is_skipped_with_reason(self):
        persistence = Persistence(":memory:")

        result = _sync(
            persistence,
            {"stacks": [_stack([_card(50, "Rara")], title="Stack desconocido")]},
        )

        assert result["synced"] == 0
        assert result["skipped"] == [
            {
                "deck_task_id": 50,
                "title": "Rara",
                "reason": "stack_unmapped: Stack desconocido",
            }
        ]
        assert result["total_skipped"] == 1

    def test_archived_card_is_skipped_with_reason(self):
        persistence = Persistence(":memory:")

        result = _sync(
            persistence,
            {"stacks": [_stack([_card(51, "Archivada", archived=True)])]},
        )

        assert result["synced"] == 0
        assert result["skipped"][0]["deck_task_id"] == 51
        assert result["skipped"][0]["reason"] == "archived"

    def test_skipped_card_is_not_reported_as_orphan(self):
        """A card in Deck but not refreshed is drift-free, not a false orphan."""
        persistence = Persistence(":memory:")
        mission_id = persistence.upsert_mission(
            deck_task_id=51, project=PROJECT, title="Archivada"
        )

        result = _sync(
            persistence,
            {"stacks": [_stack([_card(51, "Archivada", archived=True)])]},
            prune=True,
        )

        assert result["skipped"][0]["deck_task_id"] == 51
        assert result["missing_in_deck"] == []
        assert result["pruned"] == []
        assert persistence.get_mission(mission_id) is not None
