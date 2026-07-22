#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <pdr-dds-probe> <dependency-prefix>" >&2
    exit 64
fi

workspace=$(pwd)
probe="/workspace/$(realpath --relative-to="$workspace" "$1")"
dependency_prefix="/workspace/$(realpath --relative-to="$workspace" "$2")"
suffix=$$
network="pdr-network-${suffix}"
subscriber="pdr-subscriber-${suffix}"
publisher="pdr-publisher-${suffix}"
agent="pdr-agent-${suffix}"
client="pdr-client-${suffix}"
evidence="${workspace}/build-network-evidence-${suffix}"
runtime_path="${dependency_prefix}/lib:${dependency_prefix}/lib64"

cleanup()
{
    docker rm -f "$subscriber" "$publisher" "$agent" "$client" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

report_failure()
{
    local status=$?
    echo "isolated Fast-DDS acceptance failed with exit code ${status}" >&2
    for log in "$evidence"/*.log; do
        if [[ -f "$log" ]]; then
            echo "===== $(basename "$log") =====" >&2
            sed -n '1,240p' "$log" >&2
        fi
    done
    exit "$status"
}
trap report_failure ERR

mkdir -p "$evidence"
docker network create --driver bridge --subnet 10.203.1.0/24 "$network" >/dev/null

run_probe()
{
    local name=$1
    local address=$2
    shift 2
    docker run --rm --name "$name" --hostname "$name" --network "$network" --ip "$address" \
        --volume "$workspace:/workspace" --workdir /workspace \
        --env LD_LIBRARY_PATH="$runtime_path" ubuntu:24.04 timeout 30s "$probe" "$@"
}

run_probe "$subscriber" 10.203.1.2 subscriber 167 network \
    "/workspace/build-network-evidence-${suffix}/subscriber.marker" \
    >"$evidence/subscriber.log" 2>&1 &
subscriber_pid=$!
run_probe "$publisher" 10.203.1.3 publisher 167 network >"$evidence/publisher.log" 2>&1
wait "$subscriber_pid"
grep -Fxq FAST_DDS_TWO_PROCESS_PASS "$evidence/subscriber.marker"
grep -Fq FAST_DDS_DISCOVERY_PASS "$evidence/subscriber.log"
grep -Fq FAST_DDS_PUBLISH_PASS "$evidence/publisher.log"

run_probe "$agent" 10.203.1.2 control-agent 168 network >"$evidence/agent.log" 2>&1 &
agent_pid=$!
run_probe "$client" 10.203.1.3 control-client 168 network \
    "/workspace/build-network-evidence-${suffix}/control.marker" >"$evidence/client.log" 2>&1
wait "$agent_pid"
grep -Fxq FAST_DDS_CONTROL_PASS "$evidence/control.marker"
grep -Fq FAST_DDS_CONTROL_AGENT_PASS "$evidence/agent.log"

echo "FAST_DDS_ISOLATED_NETWORK_STACKS_PASS container_a=10.203.1.2 container_b=10.203.1.3"
