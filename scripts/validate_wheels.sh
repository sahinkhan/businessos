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
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/tenant"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/identity"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/foundations/organization"
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/examples/proof_module"
python -m venv "$environment_dir"
"$environment_dir/bin/python" -m pip install \
    --constraint "$repository_root/requirements/constraints-py313.txt" \
    "$artifact_dir"/businessos-*.whl \
    "$artifact_dir"/businessos_foundation_tenant-*.whl \
    "$artifact_dir"/businessos_foundation_identity-*.whl \
    "$artifact_dir"/businessos_foundation_organization-*.whl \
    "$artifact_dir"/businessos_phase1_proof-*.whl

cd "$outside_dir"
"$environment_dir/bin/businessos" migrate plan
"$environment_dir/bin/python" -c \
    "from importlib.resources import files; from pathlib import Path; root=Path('$repository_root').resolve(); packages=('businessos','businessos_tenant','businessos_identity','businessos_organization','businessos_proof'); roots=[Path(str(files(name))).resolve() for name in packages]; assert all(root not in item.parents for item in roots); assert roots[0].joinpath('migration_assets','env.py').is_file(); assert roots[1].joinpath('migrations','versions','tenant_0001_foundation.py').is_file(); assert roots[2].joinpath('migrations','versions','identity_0001_foundation.py').is_file(); assert roots[3].joinpath('migrations','versions','organization_0001_foundation.py').is_file(); assert roots[4].joinpath('migrations','versions','0003_proof_atomic_state.py').is_file()"
"$environment_dir/bin/python" "$repository_root/scripts/migration_database_smoke.py" \
    --businessos "$environment_dir/bin/businessos"
