# LTE driver regression tests

From any directory, run `tools/gpu/tests/run-tests.sh` in the fork.
Requires Bash, Python 3, a C compiler named `cc`, and its UBSan runtime.
No root permissions, kernel module loading, tracefs mount, or GPU are needed.
Tests compile actual source functions with mocked kernel/firmware dependencies
in temporary directories. UBSan violations are fatal.

- `test-gmc-fault-filter.py`: full 57-bit address/PASID/source key separation,
  forced hash collisions, source-domain expiration, stale faults and aging.
- `test-smu-etime.py`: sync/async protocol, no premature async output reads,
  busy retry bounds, timeout streak reset/escalation and reset ACK budgets.
- `test-smu-min-power-cap.py`: opt-in range policy, AC/DC and OD selection,
  SKU/type scope, limits, firmware errors, corrupt u32 read-back, and restore.
- `test-amdgpu-pm-failures.py`: DPM error propagation/RLC order, BACO exit
  failure, runtime-suspend state unwind and successful transitions.
- `test-amdgpu-lte-debug.py`: diagnostic gates/event order/payload, original
  firmware-call counts and callback status; capture tool with fake tracefs,
  decimal buffer bounds, overwrite policy, markers, freeze setup and export.

- `test-amdgpu-reset-guard.py`: PCI config errors/all-ones responses before
  dumps and after queue reset; real scheduler timeout/completion bookkeeping,
  pending-job ownership, retained callbacks/later cleanup, racing completion,
  a later bus drop, healthy-device
  recovery, and unchanged VF behavior. Workqueue stop/start and free-work
  gating now use extracted real helpers. Deterministic in-flight completion
  and timer requeue injections check stop-before-reinsertion and cancel
  ordering; a two-job case checks list order, callbacks and cleanup. The old driver fails the first
  assertion by entering hardware recovery against an inaccessible PF.

These tests do not validate kernel locking, real firmware/power sequencing,
trace trigger execution on a live kernel, or the stability of a 170 W setting.
A full build against the target DKMS package/kernel and separately scheduled
hardware tests are still required. Source layout is
`drivers/gpu/drm/amd/*`; the packaged DKMS build layout is `amd/*`.

The audit regressions fail on `32d19bf4c`: GMC key aliasing at address bit 56,
asynchronous SMU output reads before completion, and signed-overflow UBSan
failure when firmware returns PPT `0x80000000`. Capture tests also assert the
new explicit overwrite policy. Use individual Python tests with a source root
argument when comparing another revision.
