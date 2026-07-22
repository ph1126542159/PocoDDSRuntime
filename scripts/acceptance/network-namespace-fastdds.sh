#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <pdr-dds-probe> <dependency-prefix>" >&2
    exit 64
fi

probe=$(realpath "$1")
dependency_prefix=$(realpath "$2")
suffix=$$
namespace_a="pdr-a-${suffix}"
namespace_b="pdr-b-${suffix}"
bridge="pdr-br-${suffix}"
subscriber_marker="/tmp/pdr-subscriber-${suffix}.txt"
control_marker="/tmp/pdr-control-${suffix}.txt"
subscriber_log="/tmp/pdr-subscriber-${suffix}.log"
publisher_log="/tmp/pdr-publisher-${suffix}.log"
agent_log="/tmp/pdr-agent-${suffix}.log"
client_log="/tmp/pdr-client-${suffix}.log"
background_pid=""

cleanup()
{
    if [[ -n "$background_pid" ]]; then
        kill "$background_pid" 2>/dev/null || true
        wait "$background_pid" 2>/dev/null || true
    fi
    ip netns delete "$namespace_a" 2>/dev/null || true
    ip netns delete "$namespace_b" 2>/dev/null || true
    ip link delete "$bridge" 2>/dev/null || true
    rm -f "$subscriber_marker" "$control_marker" "$subscriber_log" "$publisher_log" \
        "$agent_log" "$client_log"
}
trap cleanup EXIT

ip netns add "$namespace_a"
ip netns add "$namespace_b"
ip link add "$bridge" type bridge
ip link set "$bridge" up
ip link add "pdr-a-${suffix}" type veth peer name "pdr-ab-${suffix}"
ip link add "pdr-b-${suffix}" type veth peer name "pdr-bb-${suffix}"
ip link set "pdr-ab-${suffix}" master "$bridge"
ip link set "pdr-bb-${suffix}" master "$bridge"
ip link set "pdr-ab-${suffix}" up
ip link set "pdr-bb-${suffix}" up
ip link set "pdr-a-${suffix}" netns "$namespace_a"
ip link set "pdr-b-${suffix}" netns "$namespace_b"
ip -n "$namespace_a" address add 10.203.1.2/24 dev "pdr-a-${suffix}"
ip -n "$namespace_b" address add 10.203.1.3/24 dev "pdr-b-${suffix}"
ip -n "$namespace_a" link set lo up
ip -n "$namespace_b" link set lo up
ip -n "$namespace_a" link set "pdr-a-${suffix}" up
ip -n "$namespace_b" link set "pdr-b-${suffix}" up

runtime_path="${dependency_prefix}/lib:${dependency_prefix}/lib64:${LD_LIBRARY_PATH:-}"
run_in()
{
    local namespace=$1
    shift
    ip netns exec "$namespace" env LD_LIBRARY_PATH="$runtime_path" "$@"
}

run_in "$namespace_a" timeout 30s "$probe" subscriber 167 network "$subscriber_marker" \
    >"$subscriber_log" 2>&1 &
background_pid=$!
run_in "$namespace_b" timeout 30s "$probe" publisher 167 network >"$publisher_log" 2>&1
wait "$background_pid"
background_pid=""
grep -Fxq FAST_DDS_TWO_PROCESS_PASS "$subscriber_marker"
grep -Fq FAST_DDS_DISCOVERY_PASS "$subscriber_log"
grep -Fq FAST_DDS_PUBLISH_PASS "$publisher_log"

run_in "$namespace_a" timeout 30s "$probe" control-agent 168 network >"$agent_log" 2>&1 &
background_pid=$!
run_in "$namespace_b" timeout 30s "$probe" control-client 168 network "$control_marker" \
    >"$client_log" 2>&1
wait "$background_pid"
background_pid=""
grep -Fxq FAST_DDS_CONTROL_PASS "$control_marker"
grep -Fq FAST_DDS_CONTROL_AGENT_PASS "$agent_log"

echo "FAST_DDS_ISOLATED_NETWORK_STACKS_PASS namespace_a=10.203.1.2 namespace_b=10.203.1.3"
