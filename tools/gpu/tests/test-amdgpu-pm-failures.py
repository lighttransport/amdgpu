#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Failure-inject extracted driver PM functions; no kernel or GPU access."""
import pathlib
import re
import subprocess
import sys
import tempfile

root = pathlib.Path(sys.argv[1]) / 'drivers/gpu/drm/amd'


def function(path, name):
    source = (root / path).read_text()
    match = re.search(r'static int ' + name + r'\([^;]+?\)\n\{', source)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#define IP_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define IP_VERSION_MAJ(v) ((v)>>16)
#define MP1_HWIP 0
#define GC_HWIP 1
#define AMD_RESET_METHOD_BACO 1
#define AMD_IS_APU 1
#define SMU_FEATURE_BACO_BIT 1
#define PP_MP1_STATE_NONE 0
#define PP_MP1_STATE_UNLOAD 1
#define AMDGPU_MAX_RINGS 1
#define PCI_D0 0
#define PCI_D3cold 3
#define AMDGPU_RUNPM_NONE 0
#define AMDGPU_RUNPM_PX 1
#define AMDGPU_RUNPM_BOCO 2
#define AMDGPU_RUNPM_BACO 3
#define AMDGPU_RUNPM_BAMACO 4
struct device { int unused; };
struct amdgpu_device;
struct pci_dev { struct device dev; };
struct rlc_funcs { void (*stop)(struct amdgpu_device *); };
struct amdgpu_ring { struct { int ready; } sched; };
struct amdgpu_device {
 struct device *dev;
 struct pci_dev *pdev;
 struct { int rpm_mode; } pm;
 struct amdgpu_ring *rings[AMDGPU_MAX_RINGS];
 struct { struct { void *funcs; } imu; struct { struct rlc_funcs *funcs; } rlc; } gfx;
 bool in_runpm, in_s4, in_s0ix, scpm_enabled, no_hw_access;
 unsigned flags;
 int mp1_state;
};
enum switch_power_state { DRM_SWITCH_POWER_ON, DRM_SWITCH_POWER_CHANGING, DRM_SWITCH_POWER_DYNAMIC_OFF };
struct drm_device { enum switch_power_state switch_power_state; };
struct smu_context { struct amdgpu_device *adev; bool is_apu, uploading_custom_pp_table; };
static struct pci_dev pdev;
static struct amdgpu_device adev;
static struct drm_device drm;
static struct smu_context smu;
static struct amdgpu_ring ring;
static int mp1_version, gc_version, reset, supports_baco, baco_feature;
static int checks_ret, fence_ret, prepare_ret, suspend_ret, exit_ret, resume_ret;
static int feature_ret, notify_ret;
static unsigned prepares, suspends, exits, resumes, profiles, feature_calls, notifications, stops;
static struct pci_dev *to_pci_dev(struct device *d) { (void)d; return &pdev; }
#define pci_get_drvdata(p) (&drm)
static struct amdgpu_device *drm_to_adev(struct drm_device *d) { (void)d; return &adev; }
#define amdgpu_ip_version(a, which, n) ((void)(a), (void)(n), (which) == MP1_HWIP ? mp1_version : gc_version)
#define amdgpu_in_reset(a) ((void)(a), reset)
#define amdgpu_asic_reset_method(a) ((void)(a), AMD_RESET_METHOD_BACO)
#define amdgpu_asic_supports_baco(a) ((void)(a), supports_baco)
#define smu_feature_is_enabled(s,f) ((void)(s), (void)(f), baco_feature)
#define amdgpu_sriov_vf(a) ((void)(a), false)
#define smu_disable_all_features_with_exception(s,f) ((void)(s), (void)(f), ++feature_calls, feature_ret)
#define smu_system_features_control(s,e) ((void)(s), (void)(e), ++feature_calls, feature_ret)
#define smu_notify_rlc_state(s,e) ((void)(s), (void)(e), ++notifications, notify_ret)
static void stop_rlc(struct amdgpu_device *a) { (void)a; stops++; }
static struct rlc_funcs rlc = { .stop = stop_rlc };
#define amdgpu_pmops_runtime_checks(d) ((void)(d), checks_ret)
#define amdgpu_fence_wait_empty(r) ((void)(r), fence_ret)
#define amdgpu_device_prepare(d) ((void)(d), ++prepares, prepare_ret)
#define amdgpu_device_suspend(d,n) ((void)(d), (void)(n), ++suspends, suspend_ret)
#define amdgpu_device_resume(d,n) ((void)(d), (void)(n), ++resumes, resume_ret)
static int amdgpu_device_baco_exit(struct amdgpu_device *a) { (void)a; exits++; return exit_ret; }
#define amdgpu_restore_umd_profile_pstate_after_runpm(a) ((void)(a), ++profiles)
#define amdgpu_device_baco_enter(a) ((void)(a), 0)
#define amdgpu_device_cache_pci_state(p) ((void)(p))
#define amdgpu_device_load_pci_state(p) ((void)(p))
#define pci_disable_device(p) ((void)(p))
#define pci_ignore_hotplug(p) ((void)(p))
#define pci_set_power_state(p,s) ((void)(p), (void)(s))
#define pci_enable_device(p) ((void)(p), 0)
#define pci_set_master(p) ((void)(p))
#define pci_device_is_present(p) ((void)(p), true)
#define amdgpu_lte_pm_trace(...) ((void)0)
#define dev_err(d,...) ((void)(d))
#define dev_dbg(d,...) ((void)(d))
static void init(int mode) {
 adev = (struct amdgpu_device){ .dev = &pdev.dev, .pdev = &pdev,
   .pm.rpm_mode = mode, .gfx.rlc.funcs = &rlc };
 drm.switch_power_state = DRM_SWITCH_POWER_ON;
 smu = (struct smu_context){ .adev = &adev };
 mp1_version = IP_VERSION(12,0,0); gc_version = IP_VERSION(12,0,0);
 reset = supports_baco = baco_feature = 0;
 checks_ret = fence_ret = prepare_ret = suspend_ret = exit_ret = resume_ret = 0;
 feature_ret = notify_ret = 0;
 prepares = suspends = exits = resumes = profiles = feature_calls = notifications = stops = 0;
}
'''
main = r'''
int main(int argc, char **argv) {
 int group = argc > 1 ? atoi(argv[1]) : 0;
 assert(group >= 0 && group <= 3);
 int errors[] = {-ETIME, -EIO, -EBUSY, -EREMOTEIO};
 if (group == 0 || group == 1) {
 for (unsigned i = 0; i < sizeof(errors)/sizeof(errors[0]); i++) {
  for (int baco = 0; baco < 2; baco++) {
   init(AMDGPU_RUNPM_BACO);
   adev.in_runpm = baco; supports_baco = baco_feature = baco;
   feature_ret = errors[i];
   assert(smu_disable_dpms(&smu) == errors[i]);
   assert(feature_calls == 1 && notifications == 0 && stops == 0);
  }
 }
 init(AMDGPU_RUNPM_BACO);
 assert(smu_disable_dpms(&smu) == 0);
 assert(feature_calls == 1 && notifications == 1 && stops == 1);
 init(AMDGPU_RUNPM_BACO); notify_ret = -ETIME;
 assert(smu_disable_dpms(&smu) == -ETIME && stops == 0);
 /* The RX 9070 SMU 14.0.2 firmware-managed path must remain unchanged. */
 init(AMDGPU_RUNPM_BACO); mp1_version = IP_VERSION(14,0,2); feature_ret = -ETIME;
 assert(smu_disable_dpms(&smu) == 0 && feature_calls == 0 && stops == 0);
 init(AMDGPU_RUNPM_BACO); adev.scpm_enabled = true;
 assert(smu_disable_dpms(&smu) == 0 && feature_calls == 0 && stops == 1);
 }
 if (group == 0 || group == 2) {
 for (int mode = AMDGPU_RUNPM_BACO; mode <= AMDGPU_RUNPM_BAMACO; mode++) {
  for (unsigned i = 0; i < sizeof(errors)/sizeof(errors[0]); i++) {
   init(mode); adev.in_runpm = true; exit_ret = errors[i];
   assert(amdgpu_pmops_runtime_resume(&pdev.dev) == errors[i]);
   assert(exits == 1 && resumes == 0 && profiles == 0 && adev.in_runpm);
  }
  init(mode); adev.in_runpm = true;
  assert(amdgpu_pmops_runtime_resume(&pdev.dev) == 0);
  assert(exits == 1 && resumes == 1 && profiles == 1 && !adev.in_runpm);
  init(mode); adev.in_runpm = true; resume_ret = -EIO;
  assert(amdgpu_pmops_runtime_resume(&pdev.dev) == -EIO);
  assert(exits == 1 && resumes == 1 && profiles == 0 && adev.in_runpm);
 }
 }
 if (group == 0 || group == 3) {
 for (int mode = AMDGPU_RUNPM_PX; mode <= AMDGPU_RUNPM_BAMACO; mode++) {
  for (int stage = 0; stage < 2; stage++) {
   init(mode);
   if (stage) suspend_ret = -ETIME; else prepare_ret = -ENOMEM;
   assert(amdgpu_pmops_runtime_suspend(&pdev.dev) == (stage ? -ETIME : -ENOMEM));
   assert(prepares == 1 && suspends == (unsigned)stage);
   assert(!adev.in_runpm && adev.mp1_state == PP_MP1_STATE_NONE);
   assert(drm.switch_power_state == DRM_SWITCH_POWER_ON);
  }
  init(mode); checks_ret = -EBUSY;
  assert(amdgpu_pmops_runtime_suspend(&pdev.dev) == -EBUSY && prepares == 0);
  init(mode); ring.sched.ready = 1; adev.rings[0] = &ring; fence_ret = -ETIME;
  assert(amdgpu_pmops_runtime_suspend(&pdev.dev) == -EBUSY && prepares == 0);
  init(mode);
  assert(amdgpu_pmops_runtime_suspend(&pdev.dev) == 0);
  assert(adev.in_runpm && adev.mp1_state == PP_MP1_STATE_NONE);
  assert(drm.switch_power_state == (mode == AMDGPU_RUNPM_PX ? DRM_SWITCH_POWER_DYNAMIC_OFF : DRM_SWITCH_POWER_ON));
 }
 }
 puts("PASS: DPM disable errors, RLC ordering, BACO exit failure, runtime PM unwind and success");
}
'''
code = prefix + '\n'.join((
    function('pm/swsmu/amdgpu_smu.c', 'smu_disable_dpms'),
    function('amdgpu/amdgpu_drv.c', 'amdgpu_pmops_runtime_suspend'),
    function('amdgpu/amdgpu_drv.c', 'amdgpu_pmops_runtime_resume'),
)) + main
with tempfile.TemporaryDirectory(prefix='amdgpu-pm-test-') as tmp:
    path = pathlib.Path(tmp)
    (path / 'test.c').write_text(code)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=undefined', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test'), *sys.argv[2:]], check=True)
