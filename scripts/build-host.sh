#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cmake_bin="${root_dir}/.tools/cmake/bin/cmake"
jobs=${PDR_BUILD_JOBS:-2}
[[ -x "${cmake_bin}" ]] || { echo "Run scripts/bootstrap-cmake.sh first." >&2; exit 2; }

source_args=()
[[ -f "${root_dir}/sources/poco-1.15.3-release.tar.gz" ]] &&
    source_args+=("-DPDR_POCO_ARCHIVE=${root_dir}/sources/poco-1.15.3-release.tar.gz")
[[ -d "${root_dir}/sources/fastdds" ]] &&
    source_args+=("-DPDR_FASTDDS_SOURCE_DIR=${root_dir}/sources/fastdds")

"${cmake_bin}" -S "${root_dir}/cmake" -B "${root_dir}/build/dependencies" \
    -DCMAKE_BUILD_TYPE=Release \
    -DPDR_DEPENDENCY_INSTALL_PREFIX="${root_dir}/build/host-install" \
    "${source_args[@]}"
"${cmake_bin}" --build "${root_dir}/build/dependencies" --parallel "${jobs}"

"${cmake_bin}" -S "${root_dir}" -B "${root_dir}/build/host" \
    -DCMAKE_BUILD_TYPE=Release \
    -DPDR_INSTALL_PREFIX="${root_dir}/build/host-install" \
    -DCMAKE_INSTALL_PREFIX="${root_dir}/build/host-install"
"${cmake_bin}" --build "${root_dir}/build/host" --parallel "${jobs}"
"${cmake_bin}" --build "${root_dir}/build/host" --target test
"${cmake_bin}" --install "${root_dir}/build/host" \
    --prefix "${root_dir}/build/host-install"
