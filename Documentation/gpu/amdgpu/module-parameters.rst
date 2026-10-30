===================
 Module Parameters
===================

The amdgpu driver supports the following module parameters:

.. kernel-doc:: drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c

Experimental Navi 48 PPT floor override (LTE fork)
------------------------------------------------

``min_power_cap`` (uint, watts, default 0, read-only after module load)
lowers the driver-side minimum PPT0 limit on discrete Navi 48 GPUs with
GC IP 12.0.1 and SMU IP 14.0.2, including the RX 9070 XT. It does not apply
to APUs, SR-IOV virtual functions, other IP versions, or PPT1. A value of
zero preserves the SKU minimum. A nonzero value can lower the selected
AC/DC and overdrive minimum, but cannot raise it. Upper limits and the
existing firmware read-back check remain in effect.

For example, loading the driver with ``amdgpu.min_power_cap=150`` on the
kernel command line exposes a 150 W ``power1_cap_min`` when the stock floor
is 212 W. A later 170 W ``power1_cap`` write (170000000 microwatts) then
passes the driver range check. When loading through modprobe, use the
module option ``min_power_cap=150``. The option changes the accepted floor;
it does not set the operating power cap. Remove the option or set it to
zero on the next module load to restore the SKU floor.

.. warning::

   This is an unsupported experiment, not a validated low-power mode.
   A previous RX 9070 XT test at 170 W below the 212 W SKU minimum caused
   compute-oracle failures and an SMU/PMFW hang requiring a cold boot.
   Firmware accepting or reading back a limit does not establish stability;
   the read-back guard does not undo the write or recover hung firmware.
   Keep voltage at stock for any separately authorized runtime validation.

LTE failure diagnostics
-----------------------

``amdgpu.lte_debug`` is a read-only-at-load bitmask, default 0. Enable
individual features or use ``amdgpu.lte_debug=7`` for all three:

* 1: ``amdgpu_lte:amdgpu_lte_smu`` records SMU pre-poll begin/end,
  submission, post-poll result, split wait begin/end and fail-fast blocks.
  Fields include PCI device name, message name/index, first input parameter
  for submissions, observed response, errno, firmware state, timeout streak
  and effective timeout in microseconds. Pre-polls identify the previous
  submitted message, not the new unsent request. State/streak are the
  software values at that event; post-poll records precede escalation.
* 2: ``amdgpu_lte:amdgpu_lte_pm`` records begin/end for individual IP
  suspend/resume callbacks, runtime prepare/suspend/resume and BACO entry/
  exit. Fields include errno, IP hardware status, DPM enabled, runpm, S0ix,
  system-suspend and MP1 state. A begin without an end identifies the last
  entered callback. ``hw`` is meaningful for IP callbacks only, not the
  ``runtime`` component. BACO-entry errors are observed without changing
  the existing entry-error handling policy.
* 4: ``amdgpu_lte:amdgpu_lte_ppt`` records cap requests/effective bounds,
  range rejection, firmware-set begin/end, read-back begin/end and mismatch.
  Units are watts; ``held=4294967295`` means no valid read-back value at
  that phase. Only successful read-back has a valid held value.

The module bit and trace event must both be enabled. The trace buffer is
bounded and supplies timestamps; no per-message printk flood is added.
The diagnostics perform no extra register reads, firmware queries, resets
or power-setting writes. State snapshots are observational, not atomic
across subsystems. Trace overhead can alter timing; compare with tracing
disabled. This is not the existing ``smu_debug_mask`` halt-on-error option.

The standalone ``tools/gpu/amdgpu-lte-capture.sh`` helper configures a
private tracefs instance, without accessing GPU sensor files or changing
GPU settings. Run as root after separately arranging to load the patched
driver with the requested module arguments::

    sudo tools/gpu/amdgpu-lte-capture.sh start
    sudo tools/gpu/amdgpu-lte-capture.sh mark before-170W
    # Run the separately authorized experiment, with stock voltage.
    sudo tools/gpu/amdgpu-lte-capture.sh stop /tmp/amdgpu-170w-capture

``BUFFER_KB`` sets KiB **per CPU** (default 256). To retain the history at
the first SMU response timeout/fatal response, start with::

    sudo env FREEZE_ON_TIMEOUT=1 tools/gpu/amdgpu-lte-capture.sh start

This installs an instance-local, one-shot ``traceoff`` trigger for
``ret == -62 || ret == -121``. Freezing intentionally excludes subsequent
unwind events; use a separate capture without freezing to inspect the
cascade. ``status`` reports tracing state/trigger. ``mark`` adds an operator
label only while recording. An active capture cannot be silently restarted;
stop and save it first. Restarting a stopped/frozen instance clears its old
buffer, so save it before starting the next experiment.

``stop`` exports the trace, per-CPU overrun statistics, kernel log and a
small allowlist of module parameters. It works after a GPU failure without
issuing GPU queries. Existing VM-fault messages remain in the kernel log;
no new per-fault interrupt logging is enabled. Tracefs must be mounted and
kernel tracing supported. ``TRACING_ROOT`` can select an existing tracefs
mount; the default is ``/sys/kernel/tracing``. A full machine lockup or
reboot loses the RAM trace; external streaming/persistent kernel logging
must be arranged separately when that is the failure mode.

For the RX 9070 XT investigation, capture the stock 212 W baseline and any
separately authorized 170 W run into different output directories. Use
stock voltage and retain startup/periodic compute-oracle checks. Separate
awake-only load from runtime-PM cycling to distinguish compute corruption
from a transition failure. Do not combine undervolting and recovery tests.
