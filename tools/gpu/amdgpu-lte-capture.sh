#!/bin/bash
# SPDX-License-Identifier: MIT
# Capture only: never change GPU power settings or install/load modules.
set -euo pipefail

tracing_root=${TRACING_ROOT:-/sys/kernel/tracing}
param_root=${MODULE_PARAM_ROOT:-/sys/module/amdgpu/parameters}
instance=$tracing_root/instances/amdgpu-lte-170w
events=(amdgpu_lte_smu amdgpu_lte_pm amdgpu_lte_ppt)

fail() { echo "amdgpu-lte-capture: $*" >&2; exit 1; }
usage() {
    echo "Usage: $0 start | status | mark LABEL | stop OUTPUT_DIRECTORY" >&2
    echo "start: BUFFER_KB=256 per CPU; FREEZE_ON_TIMEOUT=1 optionally freezes on SMU -62/-121" >&2
    exit 2
}

case ${1:-} in
start)
    [[ $# == 1 ]] || usage
    [[ -r $param_root/lte_debug ]] || fail 'driver lacks lte_debug; load the patched driver first'
    mask=$(cat "$param_root/lte_debug")
    (( mask & 7 )) || fail 'lte_debug is disabled (load with lte_debug=7 for all three features)'
    size=${BUFFER_KB:-256}
    [[ $size =~ ^[0-9]{1,5}$ ]] && (( 10#$size >= 1 && 10#$size <= 16384 )) ||
        fail 'invalid BUFFER_KB (1..16384)'
    size=$((10#$size))
    freeze=${FREEZE_ON_TIMEOUT:-0}
    [[ $freeze == 0 || $freeze == 1 ]] || fail 'FREEZE_ON_TIMEOUT must be 0 or 1'
    for event in "${events[@]}"; do
        [[ -e $tracing_root/events/amdgpu_lte/$event/id ]] || fail "missing trace event $event"
    done
    if [[ -d $instance ]]; then
        [[ $(cat "$instance/tracing_on") == 0 ]] ||
            fail 'capture already running; stop it before restarting'
    else
        mkdir "$instance"
    fi
    echo 0 > "$instance/tracing_on"
    : > "$instance/set_event"
    echo "$size" > "$instance/buffer_size_kb"
    echo mono > "$instance/trace_clock"
    echo 1 > "$instance/options/overwrite"
    trigger=$instance/events/amdgpu_lte/amdgpu_lte_smu/trigger
    if grep -q '^traceoff' "$trigger"; then
        echo '!traceoff' > "$trigger"
    fi
    if [[ $freeze == 1 ]]; then
        echo 'traceoff:1 if ret == -62 || ret == -121' > "$trigger"
    fi
    : > "$instance/trace"
    for event in "${events[@]}"; do
        echo 1 > "$instance/events/amdgpu_lte/$event/enable"
    done
    echo 1 > "$instance/tracing_on"
    echo "Capture started in $instance (lte_debug=$mask; buffer=$size KiB/CPU; freeze=$freeze)"
    ;;
mark)
    [[ $# == 2 ]] || usage
    [[ -d $instance ]] || fail 'no capture instance'
    [[ $(cat "$instance/tracing_on") == 1 ]] || fail 'capture stopped or frozen'
    printf '%s\n' "$2" > "$instance/trace_marker"
    ;;
status)
    [[ $# == 1 ]] || usage
    [[ -d $instance ]] || fail 'no capture instance'
    echo "tracing_on=$(cat "$instance/tracing_on")"
    echo "buffer_size_kb_per_cpu=$(cat "$instance/buffer_size_kb")"
    cat "$instance/events/amdgpu_lte/amdgpu_lte_smu/trigger"
    ;;
stop)
    [[ $# == 2 ]] || usage
    [[ -d $instance ]] || fail 'no capture instance'
    echo 0 > "$instance/tracing_on"
    mkdir -p -- "$2"
    cat "$instance/trace" > "$2/trace.txt"
    {
        date -Ins
        uname -a
        for name in lte_debug min_power_cap smu_etime_streak runpm ppfeaturemask; do
            if [[ -r $param_root/$name ]]; then
                echo "$name=$(cat "$param_root/$name")"
            fi
        done
    } > "$2/context.txt"
    for cpu in "$instance"/per_cpu/cpu*; do
        [[ -r $cpu/stats ]] || continue
        echo "${cpu##*/}"
        cat "$cpu/stats"
    done > "$2/buffer-stats.txt"
    dmesg --color=never > "$2/dmesg.txt" 2> "$2/dmesg-error.txt" || true
    echo "Saved trace, context, buffer statistics and kernel log to $2"
    ;;
*) usage ;;
esac
