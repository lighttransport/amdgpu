============================================
 LTE fork pre-push audit, 2026-11-20 (31.70)
============================================

Scope
-----

Reviewed the single LTE port commit ``34dc8654`` on top of upstream
``amdgpu-31.70`` ``f818e1c3fa05eb652ece8680f63a5eae22daadba`` on branch
``releases/amd-31.70-lte-qtrace``. The patch set was replayed from the
31.60 fork tip ``fa4199e5c``; eight 3-way merge conflicts were resolved
in ``amdgpu_amdkfd_gpuvm.c``, ``amdgpu_drv.c``, ``amdgpu_gem.c``,
``amdgpu_userq.h``, ``amdgpu_vm_pt.c``, ``gmc_v12_1.c``,
``kfd_device.c`` and ``kfd_device_queue_manager.c``.

This is an experimental fork review, not upstream acceptance or a claim
that firmware/hardware failures cannot hang the GPU. No driver was
installed, loaded or tested against live hardware during this audit.

Findings and corrections
------------------------

* The 31.70 tree adds ``amdgpu_ualink.c``, which did not exist when the
  LTE sandbox ownership change was authored. It called the old
  3-argument ``amdgpu_vm_init()``; the build failed with "too few
  arguments". The device-owned NPA VM has no client policy owner, so the
  call now passes ``NULL`` as the sandbox argument. This was the only
  defect found by the full build.
* Upstream 31.70 superseded several older LTE edits; those hunks were
  dropped rather than force-reapplied: per-xcp ``vram_pinned`` accounting
  (the fork's old scalar form would not compile), the ``gmc_v12_1``
  retry-fault path (now centralized in ``amdgpu_gmc.c``, where the LTE
  hub-aware dedupe key was retained), and the KFD ``device_fini`` /
  ``device_exit`` split (LTE process teardown and global-reference drop
  were kept, with the state sampled before the device is freed).
* The compat-ioctl sandbox check was dropped because upstream removed
  ``amdgpu_ioc32.c``.
* The offline reset-guard harness needed the 31.70 scheduler fields
  (``num_rqs``, ``sched_rq``, ``DRM_SCHED_PRIORITY_KERNEL``); the SMU and
  LTE-debug harnesses needed the newer ``smu_msg_is_reset_ack`` helper.

Validation
----------

* ``tools/gpu/tests/run-tests.sh``: all 13 suites pass (15 PASS groups)
  with fatal UBSan. The suites compile extracted C functions against
  mocked hardware/PM dependencies; no root or GPU is required.
* ``git diff --check``: clean. No conflict markers remain in changed
  files. Bash syntax and Python byte-compilation of the test tools pass.
* ``scripts/checkpatch.pl`` on the cumulative diff: 0 errors, 17 warnings
  (new-file maintainer reminders, test-file SPDX/filename notes,
  allocation/spelling/style suggestions, and the intentional ENOTSUPP
  compatibility fallback). All reviewed.
* Build-only compile of the actual 31.70 DKMS package source
  (``amdgpu-dkms 1:7.2.3.31700000-2428518.26.04``) with all 71 changed
  fork files overlaid as ``amd/*``: EXIT 0 for both
  ``7.0.0-43-generic`` and ``7.0.0-44-generic``. Nine modules build;
  ``amdgpu.ko`` reports version ``7.2.3.31700000`` and exports
  ``lte_debug``, ``smu_etime_streak`` and ``min_power_cap``.
* All 71 built driver sources match the fork commit byte-for-byte after
  normalizing the vendor ``_AMDKCL`` CONFIG renames applied by the DKMS
  pre-build. The packaged ``include/kcl/kcl_version.h`` matches the
  fork's copy, so the installer's base-source drift check is meaningful.
* The Pearl installer pin is consistent with this commit:
  ``dkms_fork_commit`` = ``34dc8654...``, ``dkms_base_commit`` =
  ``f818e1c3...``, ``dkms_base_version`` = ``7.2.3-2428518.26.04``, and
  every changed DRM file is in ``dkms_overlay_files``. All 30 DKMS
  script tests pass; the installer dry run stops at the missing stock
  source because the 31.70 package is not installed on this machine.

Accepted shallow-history deviation
----------------------------------

This checkout was created with shallow fetches; ``.git/shallow`` lists
both ``f818e1c3`` and the old 31.60 base. The port branch therefore has
only a short local ancestry, with the 31.70 base as a parentless shallow
root. The lighttransport ``origin`` has neither the 31.70 tag nor a 31.70
branch, so publishing the branch makes ``f818e1c3`` a root commit on the
remote and truncates upstream history at that point. The operator
explicitly accepted this deviation for the experimental branch. If the
branch later becomes a canonical base, repair the history by fetching
full upstream 31.70 ancestry and rebasing/merging the LTE commits onto
it, then verify with ``git rev-list --count`` and
``git log --oneline origin/releases/amd-31.70..HEAD``.

Residual limits
---------------

No live GPU, reset, suspend/resume, thermal or power-limit test was run;
the below-212 W PPT option remains an explicitly failed experiment.
Concurrent firmware/PM race conditions and physical PCI recovery are
still unvalidated. Software tests and builds do not prove the absence
of latent defects.
