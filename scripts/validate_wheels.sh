#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
artifact_dir=$(mktemp -d)
environment_dir=$(mktemp -d)
outside_dir=$(mktemp -d)

cleanup() {
    rm -rf "$artifact_dir" "$environment_dir" "$outside_dir"
}
trap cleanup EXIT INT TERM

export PIP_CONSTRAINT="$repository_root/requirements/constraints-py313.txt"
python "$repository_root/scripts/migration_database_smoke.py" \
    --write-graph "$artifact_dir/migration-graph.json"
# The artifact environment must resolve the built wheels, never source paths
# inherited from the caller's development container.
unset PYTHONPATH
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/tenant"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/identity"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/organization"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/currency"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/geography"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/reference_data"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/uom"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/party"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/policy"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/audit"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/data_governance"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/metadata"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/examples/proof_module"

python -m venv "$environment_dir"
"$environment_dir/bin/python" -m pip install \
    --constraint "$repository_root/requirements/constraints-py313.txt" \
    "$artifact_dir"/businessos-*.whl \
    "$artifact_dir"/businessos_foundation_tenant-*.whl \
    "$artifact_dir"/businessos_foundation_identity-*.whl \
    "$artifact_dir"/businessos_foundation_organization-*.whl \
    "$artifact_dir"/businessos_foundation_currency-*.whl \
    "$artifact_dir"/businessos_foundation_geography-*.whl \
    "$artifact_dir"/businessos_foundation_reference_data-*.whl \
    "$artifact_dir"/businessos_foundation_uom-*.whl \
    "$artifact_dir"/businessos_foundation_party-*.whl \
    "$artifact_dir"/businessos_foundation_policy-*.whl \
    "$artifact_dir"/businessos_foundation_audit-*.whl \
    "$artifact_dir"/businessos_foundation_data_governance-*.whl \
    "$artifact_dir"/businessos_foundation_metadata-*.whl \
    "$artifact_dir"/businessos_phase1_proof-*.whl

cd "$outside_dir"
"$environment_dir/bin/python" - <<'PY'
from importlib.resources import files
from pathlib import Path

from businessos_metadata import (
    ArchiveCustomEntity, CreateCustomEntity, CustomEntityExport,
    CustomEntityIdentity, CustomEntityLifecycle, CustomEntityLimits,
    CustomEntityPage, CustomEntityQueryCapabilities, CustomEntityRecord,
    CustomEntityScopeKind, ExportCustomEntity, ListCustomEntities,
    MetadataModule, ReadCustomEntity, UpdateCustomEntity,
    CreateCustomEntityDefinition, EditCustomEntityDraft, ReadCustomEntityDraft,
    ReadActiveCustomEntityRevision, RetireCustomEntityDefinition,
    CustomEntityDefinitionSnapshot, CustomEntityDefinitionRecord,
    CreateUIOverlay, EditUIOverlay, PublishUIOverlay, ReactivateUIOverlay,
    ReadUIOverlay, ResolvePublishedUI, RetireUIOverlay, ResolvedUISchema,
    UIOverlayDocument, UIOverlayMutationResult, UIOverlayRecord, UIOverlayScope,
    UIResolution, UIViewSchema,
)
from businessos_metadata.contracts import DefinitionKind
from businessos_metadata.custom_entity_store import CustomEntityStore

package = Path(str(files('businessos_metadata'))).resolve()
assert Path('/app') not in package.parents
assert files('businessos_metadata').joinpath(
    'migrations', 'versions', 'metadata_0002_custom_entities.py'
).is_file()
assert package.joinpath('custom_entities.py').is_file()
assert package.joinpath('custom_entity_store.py').is_file()
assert package.joinpath('custom_entity_definitions.py').is_file()
assert {kind.value for kind in DefinitionKind} == {'field_set', 'reference_set'}
contracts = {(c.contract_id, c.version) for c in MetadataModule().manifest.public_contracts}
assert {
    ('foundation.metadata.custom-entity.v1', '1.0'),
    ('foundation.metadata.custom-entity-query.v1', '1.0'),
    ('foundation.metadata.custom-entity-definition.v1', '1.0'),
} <= contracts
assert CustomEntityQueryCapabilities().version == '1.0'
assert not CustomEntityQueryCapabilities().custom_field_filter
assert CustomEntityStore.__module__ == 'businessos_metadata.custom_entity_store'
print('PHASE5C_INSTALLED_PUBLIC_SURFACES_PASS — runtime/contracts/migration packaged; no source shadowing')
from businessos.sdk import METADATA_CATALOG, MetadataCatalog
from businessos_metadata.ui_runtime import PublishedUIRuntime
from businessos_metadata.ui_composition import compose
from businessos_party.ui_declarations import published_ui_declarations, ui_id

assert files('businessos_metadata').joinpath(
    'migrations', 'versions', 'metadata_0003_ui_overlays.py'
).is_file()
assert files('businessos_metadata').joinpath(
    'migrations', 'versions', 'metadata_0004_ui_bindings.py'
).is_file()
assert files('businessos_metadata').joinpath(
    'migrations', 'versions', 'metadata_0005_ui_binding_seals.py'
).is_file()
assert 'draft_document' not in UIOverlayMutationResult.model_fields
assert 'draft_document' in UIOverlayRecord.model_fields
from businessos.sdk import defer_handler_completion, retain_handler_resource
from businessos.security import FencedPolicyEvaluator
assert callable(defer_handler_completion) and callable(retain_handler_resource)
assert ('foundation.metadata.published-ui.v1', '1.0') in contracts
assert PublishedUIRuntime.version == MetadataCatalog.version == '1.0'
assert ResolvePublishedUI(view_id=ui_id('detail.v1'), locale='ar').contract_version == '1.0'
assert UIOverlayDocument(patches=()).contract_version == '1.0'
assert len(published_ui_declarations()) == 5
assert METADATA_CATALOG.name == 'businessos.metadata_catalog.v1'
assert package.joinpath('ui_contracts.py').is_file()
assert package.joinpath('ui_runtime.py').is_file()
assert Path(str(files('businessos_party'))).resolve().joinpath('ui_declarations.py').is_file()
print('PHASE5D_INSTALLED_PUBLIC_SURFACES_PASS — UI v1/catalog/declarations/migration; no source shadowing')
PY
"$environment_dir/bin/businessos" migrate plan
"$environment_dir/bin/python" -c \
    "from importlib.resources import files; from pathlib import Path; root=Path('$repository_root').resolve(); package=Path(str(files('businessos_metadata'))).resolve(); assert root not in package.parents; assert package.joinpath('migrations','versions','metadata_0001_definition_foundation.py').is_file()"
"$environment_dir/bin/python" -c \
    "from importlib.resources import files; from pathlib import Path; root=Path('$repository_root').resolve(); packages=('businessos','businessos_tenant','businessos_identity','businessos_organization','businessos_currency','businessos_geography','businessos_reference_data','businessos_uom','businessos_party','businessos_policy','businessos_audit','businessos_data_governance','businessos_proof'); roots=[Path(str(files(name))).resolve() for name in packages]; assert all(root not in item.parents for item in roots); assert roots[0].joinpath('migration_assets','env.py').is_file(); assert roots[0].joinpath('migration_assets','versions','0006_governance_outbox.py').is_file(); assert roots[1].joinpath('migrations','versions','tenant_0001_foundation.py').is_file(); assert roots[2].joinpath('migrations','versions','identity_0001_foundation.py').is_file(); assert roots[2].joinpath('migrations','versions','identity_0002_device_principal_integrity.py').is_file(); assert roots[2].joinpath('migrations','versions','identity_0004_workload_identity.py').is_file(); assert roots[2].joinpath('migrations','versions','identity_0005_worker_admission_role.py').is_file(); assert roots[3].joinpath('migrations','versions','organization_0001_foundation.py').is_file(); assert roots[3].joinpath('migrations','versions','organization_0002_typed_principals.py').is_file(); assert roots[4].joinpath('migrations','versions','currency_0001_foundation.py').is_file(); assert roots[5].joinpath('migrations','versions','geography_0001_foundation.py').is_file(); assert roots[5].joinpath('migrations','versions','geography_0003_currency_authority.py').is_file(); assert roots[6].joinpath('migrations','versions','reference_0001_foundation.py').is_file(); assert roots[7].joinpath('migrations','versions','uom_0001_foundation.py').is_file(); assert roots[8].joinpath('migrations','versions','party_0001_foundation.py').is_file(); assert roots[9].joinpath('migrations','versions','policy_0001_foundation.py').is_file(); assert roots[9].joinpath('migrations','versions','policy_0002_certification.py').is_file(); assert roots[9].joinpath('migrations','versions','policy_0004_typed_support_access.py').is_file(); assert roots[10].joinpath('migrations','versions','audit_0001_foundation.py').is_file(); assert roots[10].joinpath('migrations','versions','audit_0002_immutability.py').is_file(); assert roots[10].joinpath('migrations','versions','audit_0004_governance_append.py').is_file(); assert roots[11].joinpath('migrations','versions','gov_0001_foundation.py').is_file(); assert roots[11].joinpath('migrations','versions','gov_0002_runtime_access.py').is_file(); assert roots[11].joinpath('migrations','versions','gov_0003_classification_v2.py').is_file(); assert roots[11].joinpath('migrations','versions','gov_0004_module_db_authority.py').is_file(); assert roots[12].joinpath('migrations','versions','0003_proof_atomic_state.py').is_file()"

"$environment_dir/bin/python" "$repository_root/scripts/migration_database_smoke.py" \
    --businessos "$environment_dir/bin/businessos" \
    --expected-graph "$artifact_dir/migration-graph.json"
