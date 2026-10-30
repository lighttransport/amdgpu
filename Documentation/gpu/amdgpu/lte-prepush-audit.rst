LTE fork pre-push audit, 2026-10-31
===================================

Scope
-----

Reviewed the ten LTE commits from packaged baseline
``820212794d184710298efcecce42c0215bfc9c6a`` through ``32d19bf4c``.
This is an experimental fork review, not upstream acceptance or a claim
that firmware/hardware failures cannot hang the GPU. No driver was loaded,
installed or tested against live hardware during this audit.

Corrected findings
------------------

* ``0e5882894`` packed four source bits into the fault key. GC 12.1 IVs
  carry up to 57 address bits, so shifting the page number by 20 discarded
  address bit 56. Distinct retry faults could deduplicate incorrectly.
  The IH decoder supplies a one-bit VMID source, not a physical VMHUB ID.
  Pack that bit, all 16 PASID bits and all 45 page-number bits; expiration
  now visits both source domains instead of sixteen buckets.
* ``a2bd71fb8`` replaced the asynchronous send's early exit with a loop
  break. That fell through to output-register reads despite not waiting
  for command completion. Restore the common unlock/return path immediately
  after asynchronous submission, preserving split send/wait semantics.
* ``0d4652c87`` cast the untrusted u32 PPT read-back to int before subtraction
  and abs(). A firmware value of 0x80000000 provokes signed-overflow UB.
  Compare the unsigned magnitude of the difference instead.
* The capture helper inherited tracefs overwrite policy. An instance set
  to stop-on-full could lose the actual hang evidence. Explicitly select
  overwrite mode and validate/normalize buffer sizes as bounded decimal
  input, including leading-zero inputs.
* Regression harnesses previously lived only in a separate workspace.
  Publish all five offline suites and a standalone runner in this fork.
  UBSan violations terminate the tests instead of merely printing warnings.

The first three regressions were each reproduced on ``32d19bf4c`` before
correction. The GMC test checks address bit 56 plus forced hash collisions
and expiration of both domains. The SMU test asserts no output reads on
an asynchronous request. The PPT test rejects corrupt 0, 0x80000000 and
0xffffffff read-backs; the old signed calculation fails UBSan.

Reproduce software validation
-----------------------------

From the checkout, run::

    tools/gpu/tests/run-tests.sh

Requires Python 3, Bash, cc and its UBSan runtime. The tests extract real
C routines and mock kernel/firmware dependencies. They need neither root
nor a GPU. Diagnostic tests check gates, event ordering/payload and unchanged
firmware-call counts. A fake tracefs test covers capture setup/export;
it does not execute a live kernel trace trigger.

The target build remains the matching ROCm 7.1.9 DKMS package and kernel
``7.0.0-38-generic``. Build a temporary package-source copy with the fork's
changed ``drivers/gpu/drm/amd/*`` files overlaid as ``amd/*``. Include the
new LTE headers, amdgpu.h, amdgpu_ip.c and amdgpu_trace_points.c as well as
the original GMC/SMU files. Never use an installed-driver tree as the
scratch build directory. The vendor pre-build renames selected CONFIG
symbols; that difference is expected, not a source correction.

Audit validation result
-----------------------

All five offline suites passed. The first three new regressions fail on
``32d19bf4c`` and pass with their corrections; the capture fixture also
verifies overwrite mode and decimal bounds. The full temporary DKMS build
exited 0 for ``7.0.0-38-generic``, producing nine modules. amdgpu retains
version ``7.1.9.31600000``. The corrected driver sources match their compiled
copies byte-for-byte. No compiler warnings originate in those files;
unrelated KCL/display/compiler notes remain, and BTF is skipped without
vmlinux. ``git diff --check`` and Bash syntax validation pass. Checkpatch
reports no errors; existing integer-type and trace-macro style checks and
the added-file maintainer reminder were reviewed.

Residual limits
---------------

* The below-SKU PPT override remains off by default. The earlier RX 9070 XT
  170 W run caused oracle failures and an SMU hang. Read-back verification
  detects some failures after a write; it neither rolls back that write
  nor establishes firmware stability. The default-on timeout policy has
  software tests but still needs hardware reset/suspend/resume validation.
* Partial SMU suspend and failed generic unwind still need coordinated
  device recovery. Do not simply restore software flags or issue blind
  MMIO to an unconfirmed power domain. Runtime BACO-entry errors are traced
  but retain the base driver's existing handling policy.
* The key distinguishes GFXHUB/MMHUB source domains, not every physical
  hub/XCC/node. It retains the base filter's timestamp/ring synchronization
  assumptions; the offline test is not a concurrent interrupt stress test.
* ``AMDGPU_GMC_FAULT_TIMEOUT`` is 5000 IH timestamp ticks. It must not be
  described as five seconds without establishing the hardware tick period.
* Trace buffers are RAM only and bounded. Reboot loses them; overwrites are
  reported in per-CPU statistics. A first-timeout freeze omits later unwind
  events. Hardware transition timing and live trace-trigger behavior remain
  unvalidated. Arrange external capture separately for a full host lockup.

The fork branch may be published for experimental review after the corrected
build/tests pass; that is not approval to install it or run the 170 W test.


Previous-boot PCI bus-loss guard, 2026-10-31
------------------------------------------

The 07:48:55 JST GFX timeout in the previous boot was followed by MES
queue-command timeouts and unavailable PCI configuration access. The
journal contains 155 bus-loss reports and 154 failed job recoveries with
``-ENODEV``. It establishes a recovery storm, not the initial hardware or
firmware cause; no contemporaneous AER, SMU timeout or VM fault was logged.

The timeout callback now checks physical-device PCI access before dumping
IP registers and again before full recovery after per-ring reset. A failed
check parks submission/free workers, restores the removed guilty job under
the scheduler list lock, cancels queued timeout work and returns
``DRM_GPU_SCHED_STAT_ENODEV``. The timeout wrapper skips duplicate insertion
and timer rearm. Parent-fence callbacks remain attached so later completion
and workqueue restart can release the job. Unlike the older
``drm_sched_stop()`` path, this does not detach callbacks that the current
full-reset workqueue restart would not reattach. VF/host FLR behavior
and present-device recovery paths are unchanged. The guard does not latch
a permanent unplug state, alter timeout values, or repair the link.

``test-amdgpu-reset-guard.py`` compiles the actual callback, PCI helper and
scheduler timeout/reinsertion/completion/cleanup functions with mocks and
fatal UBSan.
It covers PCI read errors/all-ones responses, early/late loss, completion
races, job ownership, retained callbacks/later cleanup, healthy-device
recoveries and VF bypass. The previous
``1636034a6`` callback fails the first assertion. Kernel concurrency and
physical recovery remain untested. Each ring is parked on its own timeout;
this is containment of repeated job recovery, not a device-wide stop of
all MMIO or a claim that userspace can continue without a reset/rebind.


The follow-up full temporary package-source build completed with exit 0
for ``7.0.0-42-generic``, producing nine modules and retaining amdgpu
version ``7.1.9.31600000``. The guarded amdgpu_job.c matches the compiled
copy byte-for-byte, with no compiler warnings in that file. All thirteen
overlay sources match after expected vendor CONFIG renaming in amdgpu.h
and amdgpu_drv.c. Existing unrelated warnings remain; BTF was skipped
without vmlinux. All six driver regression suites pass, including the new
scheduler/PCI test. No installed sources/modules, live resets, power
settings or reboot were changed during this follow-up.
