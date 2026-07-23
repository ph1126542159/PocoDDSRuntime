#!/usr/bin/env bash
set -eo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cmake_bin="${root_dir}/.tools/cmake/bin/cmake"
jobs=${PDR_BUILD_JOBS:-2}
sdk_env=${PDR_PETALINUX_SDK_ENV:-/data/petalinux/bin/petalinux-sdk-env.sh}
qemu_arm=${MYIOT_QEMU_ARM:-/home/arthur/Tools/petalinux_2022_1/components/yocto/buildtools/sysroots/x86_64-petalinux-linux/usr/bin/qemu-aarch64}

[[ -x "${cmake_bin}" ]] || { echo "Run scripts/bootstrap-cmake.sh first." >&2; exit 2; }
if [[ -z "${CC:-}" || -z "${CXX:-}" || -z "${SDKTARGETSYSROOT:-}" ]]; then
    [[ -r "${sdk_env}" ]] || { echo "Missing PetaLinux SDK: ${sdk_env}" >&2; exit 3; }
    # shellcheck disable=SC1090
    source "${sdk_env}"
fi
set -u
: "${CC:?PetaLinux SDK did not define CC}"
: "${CXX:?PetaLinux SDK did not define CXX}"
: "${SDKTARGETSYSROOT:?PetaLinux SDK did not define SDKTARGETSYSROOT}"
[[ -x "${qemu_arm}" ]] || { echo "Missing qemu-aarch64: ${qemu_arm}" >&2; exit 4; }

cc_bin=${CC%% *}
cxx_bin=${CXX%% *}
common_cross=(
    -DCMAKE_BUILD_TYPE=Release
    -DCMAKE_SYSTEM_NAME=Linux
    -DCMAKE_SYSTEM_PROCESSOR=aarch64
    "-DCMAKE_C_COMPILER=${cc_bin}"
    "-DCMAKE_CXX_COMPILER=${cxx_bin}"
    "-DCMAKE_SYSROOT=${SDKTARGETSYSROOT}"
)
source_args=()
[[ -f "${root_dir}/sources/poco-1.15.3-release.tar.gz" ]] &&
    source_args+=("-DPDR_POCO_ARCHIVE=${root_dir}/sources/poco-1.15.3-release.tar.gz")
[[ -d "${root_dir}/sources/fastdds" ]] &&
    source_args+=("-DPDR_FASTDDS_SOURCE_DIR=${root_dir}/sources/fastdds")
[[ -d "${root_dir}/sources/fastcdr" ]] &&
    source_args+=("-DPDR_FASTCDR_SOURCE_DIR=${root_dir}/sources/fastcdr")
[[ -d "${root_dir}/sources/foonathan_memory" ]] &&
    source_args+=("-DPDR_FOONATHAN_MEMORY_SOURCE_DIR=${root_dir}/sources/foonathan_memory")
[[ -d "${root_dir}/sources/paho_mqtt_c" ]] &&
    source_args+=("-DPDR_PAHO_MQTT_SOURCE_DIR=${root_dir}/sources/paho_mqtt_c")

"${cmake_bin}" -S "${root_dir}/cmake" \
    -B "${root_dir}/build/petalinux-dependencies" \
    "-DPDR_DEPENDENCY_INSTALL_PREFIX=${root_dir}/build/petalinux-install" \
    "${common_cross[@]}" "${source_args[@]}"
"${cmake_bin}" --build "${root_dir}/build/petalinux-dependencies" --parallel "${jobs}"

"${cmake_bin}" -S "${root_dir}" -B "${root_dir}/build/petalinux" \
    "${common_cross[@]}" \
    -DBUILD_TESTING=OFF \
    "-DPDR_INSTALL_PREFIX=${root_dir}/build/petalinux-install" \
    "-DCMAKE_INSTALL_PREFIX=${root_dir}/build/petalinux-install" \
    "-DMYIOT_QEMU_ARM=${qemu_arm}"
"${cmake_bin}" --build "${root_dir}/build/petalinux" --parallel "${jobs}"
"${cmake_bin}" --install "${root_dir}/build/petalinux" \
    --prefix "${root_dir}/build/petalinux-install"
