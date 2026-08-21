from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.authoring.presets import BUILTIN_PRESET_IDS, PresetCatalog


ROOT = Path(__file__).resolve().parents[2]
PRESET_ROOT = ROOT / "examples" / "p0c"
DIGEST_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "authoring"
    / "library"
    / "preset-digests.json"
)


def test_five_builtin_presets_match_complete_frozen_digest_fixture() -> None:
    expected = json.loads(DIGEST_FIXTURE.read_text(encoding="utf-8"))
    catalog = PresetCatalog(PRESET_ROOT)

    assert list(BUILTIN_PRESET_IDS) == [
        "brake_lead",
        "construction_merge",
        "dangerous_cut_in",
        "highway_merge",
        "unprotected_left_turn",
    ]
    assert expected == {
        "brake_lead": "869395138f08635711887cc47a419c2ca7ed50e18c3cc8af305fa23c2ff110c9",
        "construction_merge": "37da2a170e417e2f13994d1bc6919e589d792f0f4c246e4b8b0cc6e184dd2923",
        "dangerous_cut_in": "0ababb69c9d7b072f0484741b10b5052e2d40e65b7d4a6d6dede59bc36770871",
        "highway_merge": "5649b78a4ff3250230c96363418e1299e3fbac8536f943b1e64f258d60d0e2a4",
        "unprotected_left_turn": "518f9846a6c68149993b00b400f322c85b8f35a98144588de35d7cfbe558d9ff",
    }
    assert catalog.template_ids == BUILTIN_PRESET_IDS

    for template_id in BUILTIN_PRESET_IDS:
        raw = (PRESET_ROOT / f"{template_id}.json").read_bytes()
        template = catalog.get(template_id)
        assert template.to_dict() == {
            "template_id": template_id,
            "template_digest": expected[template_id],
            "schema_version": "scenarioforge.scenario/v2",
            "content": json.loads(raw),
        }
        assert hashlib.sha256(raw).hexdigest() == expected[template_id]
        assert isinstance(template.content, MappingProxyType)
        with pytest.raises(TypeError):
            template.content["seed"] = 0  # type: ignore[index]


@pytest.mark.parametrize("template_id", BUILTIN_PRESET_IDS)
def test_editing_preset_forks_independent_revision_without_writing_fixture(
    tmp_path: Path,
    template_id: str,
) -> None:
    catalog = PresetCatalog(PRESET_ROOT)
    library = LocalScenarioLibrary(tmp_path, preset_catalog=catalog)
    fixture_path = PRESET_ROOT / f"{template_id}.json"
    before = fixture_path.read_bytes()
    editable = catalog.editable_copy(template_id)
    editable["seed"] += 1000

    revision = library.fork_preset(
        template_id,
        editable,
        actor="local_operator",
    )

    assert revision.scenario_id != template_id
    assert revision.parent_revision_id is None
    assert revision.revision_number == 1
    assert revision.content["seed"] == json.loads(before)["seed"] + 1000
    assert revision.provenance == {
        "kind": "preset_fork",
        "actor": "local_operator",
        "created_at": revision.created_at,
        "draft_generation": 0,
        "template_id": template_id,
        "template_digest": hashlib.sha256(before).hexdigest(),
    }
    assert library.get_draft(revision.scenario_id).provenance == {
        "kind": "preset_fork",
        "actor": "local_operator",
        "created_at": revision.created_at,
        "template_id": template_id,
        "template_digest": hashlib.sha256(before).hexdigest(),
    }
    assert library.latest_revision(revision.scenario_id).revision_id == (
        revision.revision_id
    )
    assert fixture_path.read_bytes() == before
    assert catalog.get(template_id).content["seed"] == json.loads(before)["seed"]


def test_preset_fork_owns_a_separate_followup_chain(tmp_path: Path) -> None:
    catalog = PresetCatalog(PRESET_ROOT)
    library = LocalScenarioLibrary(tmp_path, preset_catalog=catalog)
    editable = catalog.editable_copy("brake_lead")
    first = library.fork_preset("brake_lead", editable)
    editable["seed"] = 999

    draft = library.get_draft(first.scenario_id)
    library.update_draft(
        first.scenario_id,
        editable,
        expected_generation=draft.generation,
    )
    second = library.save_draft(first.scenario_id)

    assert second.parent_revision_id == first.revision_id
    assert second.scenario_id == first.scenario_id
    assert second.revision_id != first.revision_id
    assert first.content["seed"] != second.content["seed"]
    assert second.provenance["template_id"] == "brake_lead"
    assert second.provenance["template_digest"] == first.provenance[
        "template_digest"
    ]
