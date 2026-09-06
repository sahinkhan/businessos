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
python -m pip wheel --no-deps --wheel-dir "$artifact_dir" "$repository_root/examples/proof_module"
python -m venv "$environment_dir"
"$environment_dir/bin/python" -m pip install \
    --constraint "$repository_root/requirements/constraints-py313.txt" \
    "$artifact_dir"/businessos-*.whl \
    "$artifact_dir"/businessos_phase1_proof-*.whl

cd "$outside_dir"
"$environment_dir/bin/businessos" migrate plan
"$environment_dir/bin/python" -c \
    "from importlib.resources import files; assert files('businessos').joinpath('migration_assets', 'env.py').is_file(); assert files('businessos_proof').joinpath('migrations', 'versions', '0003_proof_atomic_state.py').is_file()"
