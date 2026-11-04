#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile real PPT get/set functions with mocked firmware; pass fork root."""
import pathlib
import re
import subprocess
import sys
import tempfile

source = (pathlib.Path(sys.argv[1]) /
          'drivers/gpu/drm/amd/pm/swsmu/amdgpu_smu.c').read_text()


def function(name):
    match = re.search(r'(?:static )?(?:int|u32) ' + name + r'\([^;]+?\)\n\{', source)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define min_t(t,a,b) ((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define IP_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define GC_HWIP 0
#define MP1_HWIP 1
#define ENOTSUPP 524
#define SMU_DPM_USER_PROFILE_RESTORE 1
#define U32_MAX UINT32_MAX
#define amdgpu_lte_ppt_trace(...) ((void)0)
#define dev_err(d,...) ((void)(d))
enum smu_power_src_type { SMU_POWER_SOURCE_AC, SMU_POWER_SOURCE_DC, SMU_POWER_SOURCE_COUNT };
enum smu_ppt_limit_type { SMU_DEFAULT_PPT_LIMIT, SMU_FAST_PPT_LIMIT, SMU_LIMIT_TYPE_COUNT, SMU_SLOW_PPT_LIMIT = SMU_DEFAULT_PPT_LIMIT };
enum smu_ppt_limit_level { SMU_PPT_LIMIT_MIN = -1, SMU_PPT_LIMIT_CURRENT, SMU_PPT_LIMIT_DEFAULT, SMU_PPT_LIMIT_MAX };
enum pp_power_limit_level { PP_PWR_LIMIT_CURRENT, PP_PWR_LIMIT_DEFAULT, PP_PWR_LIMIT_MAX, PP_PWR_LIMIT_MIN };
enum pp_power_type { PP_PWR_TYPE_SUSTAINED, PP_PWR_TYPE_FAST };
struct smu_ppt_limit_range { u32 default_value, min, max, od_min, od_max; };
struct amdgpu_device { void *dev; struct { bool dpm_enabled, ac_power; } pm; bool vf; int gc, mp1; };
struct smu_context;
struct pptable_funcs {
 int (*set_ppt_limit)(struct smu_context *, enum smu_ppt_limit_type, u32);
 int (*get_ppt_limit)(struct smu_context *, enum smu_ppt_limit_type, u32 *);
};
struct smu_context {
 struct amdgpu_device *adev;
 bool is_apu, pm_enabled, od_enabled;
 struct { struct smu_ppt_limit_range range[SMU_POWER_SOURCE_COUNT][SMU_LIMIT_TYPE_COUNT]; u32 supported_mask; } ppt_limits;
 struct { u32 flags, ppt_limits[SMU_POWER_SOURCE_COUNT][SMU_LIMIT_TYPE_COUNT], ppt_limit_user_mask[SMU_POWER_SOURCE_COUNT]; } user_dpm_profile;
 struct pptable_funcs *ppt_funcs;
};
#define amdgpu_sriov_vf(a) ((a)->vf)
#define amdgpu_ip_version(a,which,n) ((void)(n), (which) == GC_HWIP ? (a)->gc : (a)->mp1)
#define smu_get_asic_ppt_limit(s,t,p) ((s)->ppt_funcs->get_ppt_limit((s),(t),(p)))
static unsigned int amdgpu_smu_min_power_cap;
static unsigned int writes, reads;
static u32 held, clamped_held = 212;
static int set_ret, get_ret;
static bool clamp;
static int set(struct smu_context *s, enum smu_ppt_limit_type t, u32 v) {
 (void)s; (void)t; ++writes; if (set_ret) return set_ret; held = clamp ? clamped_held : v; return 0;
}
static int get(struct smu_context *s, enum smu_ppt_limit_type t, u32 *v) {
 (void)s; (void)t; ++reads; if (get_ret) return get_ret; *v = held; return 0;
}
static struct amdgpu_device adev;
static struct smu_context smu;
static struct pptable_funcs funcs;
static void init(void) {
 adev = (struct amdgpu_device){ .pm = { .dpm_enabled = true, .ac_power = true }, .gc = IP_VERSION(12,0,1), .mp1 = IP_VERSION(14,0,2) };
 funcs = (struct pptable_funcs){ .set_ppt_limit = set, .get_ppt_limit = get };
 smu = (struct smu_context){ .adev = &adev, .pm_enabled = true, .ppt_funcs = &funcs, .ppt_limits.supported_mask = 3 };
 for (int p = 0; p < 2; p++) for (int t = 0; t < 2; t++)
  smu.ppt_limits.range[p][t] = (struct smu_ppt_limit_range){304,212,304,200,374};
 amdgpu_smu_min_power_cap = writes = reads = set_ret = get_ret = 0;
 clamp = false; clamped_held = 212; held = 304;
}
'''
main = r'''
int main(void) {
 u32 v;
 for (int mp1 = 2; mp1 <= 3; mp1++)
 for (int power = 0; power < 2; power++) for (int od = 0; od < 2; od++) {
  init(); adev.mp1 = IP_VERSION(14,0,mp1); adev.pm.ac_power = power == SMU_POWER_SOURCE_AC; smu.od_enabled = od;
  assert(smu_get_ppt_limit(&smu, &v, PP_PWR_LIMIT_MIN, PP_PWR_TYPE_SUSTAINED) == 0 && v == (od ? 200U : 212U));
  assert(smu_set_ppt_limit(&smu, SMU_DEFAULT_PPT_LIMIT, 170) == -EINVAL && writes == 0);
  amdgpu_smu_min_power_cap = 150;
  assert(smu_get_ppt_limit(&smu, &v, PP_PWR_LIMIT_MIN, PP_PWR_TYPE_SUSTAINED) == 0 && v == 150);
  assert(smu_set_ppt_limit(&smu, SMU_DEFAULT_PPT_LIMIT, 170) == 0 && held == 170);
  assert(smu.user_dpm_profile.ppt_limits[power][SMU_DEFAULT_PPT_LIMIT] == 170);
  assert(smu.user_dpm_profile.ppt_limit_user_mask[power] == BIT(SMU_DEFAULT_PPT_LIMIT));
  unsigned saved = writes;
  assert(smu_set_ppt_limit(&smu, SMU_DEFAULT_PPT_LIMIT, 149) == -EINVAL && writes == saved);
  assert(smu_set_ppt_limit(&smu, SMU_DEFAULT_PPT_LIMIT, od ? 375 : 305) == -EINVAL && writes == saved);
  assert(smu_set_ppt_limit(&smu, SMU_DEFAULT_PPT_LIMIT, 150) == 0 && held == 150);
  assert(smu_get_ppt_limit(&smu, &v, PP_PWR_LIMIT_MAX, PP_PWR_TYPE_SUSTAINED) == 0 && v == (od ? 374U : 304U));
  assert(smu_get_ppt_limit(&smu, &v, PP_PWR_LIMIT_DEFAULT, PP_PWR_TYPE_SUSTAINED) == 0 && v == 304);
  assert(smu_get_ppt_limit(&smu, &v, PP_PWR_LIMIT_MIN, PP_PWR_TYPE_FAST) == 0 && v == (od ? 200U : 212U));
 }
 /* The knob can lower the floor but never raise or overflow it. */
 init(); amdgpu_smu_min_power_cap = UINT32_MAX;
 assert(smu_min_ppt_limit(&smu, 0, 212) == 212);
 amdgpu_smu_min_power_cap = 212; assert(smu_min_ppt_limit(&smu, 0, 212) == 212);
 amdgpu_smu_min_power_cap = 1; assert(smu_min_ppt_limit(&smu, 0, 212) == 1);
 /* Other IPs, APUs, virtual functions and PPT1 retain stock policy. */
 for (int other = 0; other < 4; other++) {
  init(); amdgpu_smu_min_power_cap = 150;
  if (other == 0) adev.gc = IP_VERSION(12,0,0);
  if (other == 1) adev.mp1 = IP_VERSION(14,0,4);
  if (other == 2) smu.is_apu = true;
  if (other == 3) adev.vf = true;
  assert(smu_get_ppt_limit(&smu, &v, PP_PWR_LIMIT_MIN, PP_PWR_TYPE_SUSTAINED) == 0 && v == 212);
  assert(smu_set_ppt_limit(&smu, 0, 170) == -EINVAL && writes == 0);
 }
 init(); amdgpu_smu_min_power_cap = 150;
 assert(smu_min_ppt_limit(&smu, SMU_FAST_PPT_LIMIT, 212) == 212);
 assert(smu_set_ppt_limit(&smu, SMU_FAST_PPT_LIMIT, 170) == -EINVAL && writes == 0);
 /* Preserve validation, error propagation, read-back and restore behavior. */
 smu.ppt_limits.supported_mask = 0;
 assert(smu_set_ppt_limit(&smu, 0, 170) == -EOPNOTSUPP && writes == 0);
 init(); amdgpu_smu_min_power_cap = 150;
 set_ret = -EBUSY; assert(smu_set_ppt_limit(&smu, 0, 170) == -EBUSY && reads == 0);
 assert(smu.user_dpm_profile.ppt_limit_user_mask[0] == 0);
 init(); amdgpu_smu_min_power_cap = 150; clamp = true;
 assert(smu_set_ppt_limit(&smu, 0, 170) == -EIO);
 assert(smu.user_dpm_profile.ppt_limit_user_mask[0] == 0);
 /* Firmware read-back is untrusted u32; comparison must not overflow signed int. */
 u32 corrupt[] = {0, 0x80000000U, UINT32_MAX};
 for (unsigned i = 0; i < sizeof(corrupt)/sizeof(corrupt[0]); i++) {
  init(); amdgpu_smu_min_power_cap = 150; clamp = true; clamped_held = corrupt[i];
  assert(smu_set_ppt_limit(&smu, 0, 170) == -EIO);
  assert(smu.user_dpm_profile.ppt_limit_user_mask[0] == 0);
 }
 init(); amdgpu_smu_min_power_cap = 150; get_ret = -ETIME;
 assert(smu_set_ppt_limit(&smu, 0, 170) == -EIO);
 init(); amdgpu_smu_min_power_cap = 150; smu.user_dpm_profile.flags = SMU_DPM_USER_PROFILE_RESTORE;
 assert(smu_set_ppt_limit(&smu, 0, 170) == 0 && held == 170);
 assert(smu.user_dpm_profile.ppt_limit_user_mask[0] == 0);
 init(); amdgpu_smu_min_power_cap = 150;
 assert(smu_set_ppt_limit(&smu, SMU_LIMIT_TYPE_COUNT, 170) == -EINVAL);
 assert(smu_set_ppt_limit(&smu, 0, 0) == 0 && held == 304);
 adev.pm.dpm_enabled = false;
 assert(smu_set_ppt_limit(&smu, 0, 170) == -EOPNOTSUPP);
 assert(smu_get_ppt_limit(&smu, &v, PP_PWR_LIMIT_MIN, PP_PWR_TYPE_SUSTAINED) == -EOPNOTSUPP);
 puts("PASS: floor opt-in, AC/DC, OD, ASIC/type scope, bounds, read-back, errors, restore");
}
'''
code = prefix + '\n'.join(function(n) for n in (
    'smu_min_ppt_limit', 'smu_get_ppt_limit', 'smu_set_ppt_limit')) + main
with tempfile.TemporaryDirectory(prefix='smu-power-test-') as tmp:
    path = pathlib.Path(tmp)
    (path / 'test.c').write_text(code)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=undefined', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
