#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tools_dir="${root_dir}/.tools"
version="3.29.6"
archive="cmake-${version}-linux-x86_64.tar.gz"
url="https://github.com/Kitware/CMake/releases/download/v${version}/${archive}"

mkdir -p "${tools_dir}"
if [[ ! -x "${tools_dir}/cmake/bin/cmake" ]]; then
    curl --fail --location --retry 3 "${url}" --output "${tools_dir}/${archive}"
    tar -xzf "${tools_dir}/${archive}" -C "${tools_dir}"
    mv "${tools_dir}/cmake-${version}-linux-x86_64" "${tools_dir}/cmake"
fi
"${tools_dir}/cmake/bin/cmake" --version
