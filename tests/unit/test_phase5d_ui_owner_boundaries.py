"""Permanent regressions for explicit owner opt-in and slot containment."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from businessos_metadata.ui_composition import apply_overlay, compose
from businessos_metadata.ui_contracts import UIConflict, UIOverlayDocument, UIOverlayScope
from businessos_party.ui_declarations import ui_id

from tests.unit.test_phase5d_ui import extension, sources


@pytest.mark.parametrize("parent", ["detail.v1", "detail.summary", "detail.display_name"])
def test_external_contribution_cannot_attach_to_owner_private_nodes(parent: str) -> None:
    contribution = extension()
    raw = json.loads(contribution.document_json)
    raw["nodes"][0]["parent_id"] = str(ui_id(parent))
    with pytest.raises(UIConflict):
        compose((*sources(), replace(contribution, document_json=json.dumps(raw))))


@pytest.mark.parametrize("scope", list(UIOverlayScope))
def test_owner_private_field_cannot_be_hidden(scope: UIOverlayScope) -> None:
    result = compose(sources())
    patch = UIOverlayDocument.model_validate(
        {"patches": [{"target_id": str(ui_id("detail.display_name")), "visible": False}]}
    )
    with pytest.raises(UIConflict):
        apply_overlay(result.view, patch, scope, result.capabilities)


@pytest.mark.parametrize("target", ["missing", "other_extension", "foreign_owner_slot"])
def test_external_roots_cannot_enter_non_owner_slots(target: str) -> None:
    first, second = extension(), extension()
    first_raw, second_raw = json.loads(first.document_json), json.loads(second.document_json)
    second_raw["nodes"][0]["parent_id"] = (
        first_raw["nodes"][0]["node_id"] if target == "other_extension" else str(uuid4())
    )
    declarations = sources()
    if target == "foreign_owner_slot":
        # Even an owner capability naming a real slot in another view cannot
        # expose that slot in this base. A stable ID alone is not authority.
        foreign_slot = str(uuid4())
        caps = json.loads(declarations[1].document_json)
        caps["extension_slots"][0]["slot_id"] = foreign_slot
        declarations = (
            declarations[0],
            replace(declarations[1], document_json=json.dumps(caps)),
            *declarations[2:],
        )
        second_raw["nodes"][0]["parent_id"] = foreign_slot
    with pytest.raises(UIConflict):
        compose((*declarations, first, replace(second, document_json=json.dumps(second_raw))))


def test_subtree_every_primitive_is_bound_to_explicit_owner_slot() -> None:
    contribution = extension()
    raw = json.loads(contribution.document_json)
    raw["nodes"].append(
        {
            "node_id": str(uuid4()),
            "parent_id": raw["nodes"][0]["node_id"],
            "kind": "field",
            "primitive": "TextInput",
            "field_id": str(ui_id("field.preferred_locale")),
            "presentation": {"label_key": "extension.private"},
        }
    )
    with pytest.raises(UIConflict):
        compose((*sources(), replace(contribution, document_json=json.dumps(raw))))
    assert compose((*sources(), contribution)).view.nodes


@pytest.mark.parametrize("scope", list(UIOverlayScope))
@pytest.mark.parametrize("omission", ["all", "scope", "target", "property"])
def test_customization_requires_complete_owner_opt_in(scope: UIOverlayScope, omission: str) -> None:
    declarations = sources()
    raw = json.loads(declarations[1].document_json)
    if omission == "all":
        del raw["customization"]
    elif omission == "scope":
        raw["customization"][0]["scopes"] = [x.value for x in UIOverlayScope if x != scope]
    elif omission == "target":
        raw["customization"][0]["target_id"] = str(ui_id("detail.summary"))
    else:
        raw["customization"][0]["properties"] = ["density"]
    result = compose((declarations[0], replace(declarations[1], document_json=json.dumps(raw))))
    patch = UIOverlayDocument.model_validate(
        {
            "patches": [{"target_id": str(result.view.view_id), "order": 23}],
        }
    )
    with pytest.raises(UIConflict):
        apply_overlay(result.view, patch, scope, result.capabilities)
    allowed = compose(declarations)
    assert apply_overlay(allowed.view, patch, scope, allowed.capabilities).presentation.order == 23
