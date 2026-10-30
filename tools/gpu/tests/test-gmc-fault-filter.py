#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile real GMC key/filter/remove routines with a mocked IH ring."""
import pathlib
import re
import subprocess
import sys
import tempfile

source = (pathlib.Path(sys.argv[1]) / 'drivers/gpu/drm/amd/amdgpu/amdgpu_gmc.c').read_text()


def function(name):
    match = re.search(r'(?:static inline )?(?:uint64_t|bool|void) ' + name + r'\([^;]+?\)\n\{', source)
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
#define AMDGPU_GPU_PAGE_SHIFT 12
#define AMDGPU_GMC_FAULT_TIMEOUT 5000ULL
#define AMDGPU_GMC_FAULT_HASH_ORDER 8
#define max(a,b) ((a) > (b) ? (a) : (b))
#define rmb() ((void)0)
#define hash_64(k,b) ((void)(k), (void)(b), 0) /* Deliberately collide every hash. */
#define amdgpu_ih_ts_after(t1,t2) (((int64_t)((t2)<<16) - (int64_t)((t1)<<16)) > 0LL)
typedef struct {uint64_t value;} atomic64_t;
#define atomic64_read(p) ((p)->value)
#define atomic64_set(p,v) ((p)->value = (v))
struct amdgpu_ih_ring {uint64_t processed_timestamp; unsigned ring_size; bool enabled;};
struct amdgpu_gmc_fault {atomic64_t key; uint64_t timestamp, timestamp_expiry; uint8_t next;};
struct amdgpu_gmc {
 struct amdgpu_gmc_fault fault_ring[256];
 struct {uint8_t idx;} fault_hash[256];
 uint8_t last_fault;
};
struct amdgpu_device {
 struct amdgpu_gmc gmc;
 struct {bool retry_cam_enabled; struct amdgpu_ih_ring ih1, ih_soft;} irq;
};
static uint64_t last_ts;
static uint32_t amdgpu_ih_get_wptr(struct amdgpu_device *a, struct amdgpu_ih_ring *ih) {(void)a; (void)ih; return 0;}
static uint64_t amdgpu_ih_decode_iv_ts(struct amdgpu_device *a, struct amdgpu_ih_ring *ih, uint32_t w, int n) {
 (void)a; (void)ih; (void)w; (void)n; return last_ts;
}
'''
main = r'''
int main(void) {
 uint64_t high = 1ULL << 56;
 assert(amdgpu_gmc_fault_key(0,1,0) != amdgpu_gmc_fault_key(high,1,0));
 uint64_t addrs[] = {0,4096,1ULL<<47,1ULL<<48,1ULL<<55,1ULL<<56,(1ULL<<57)-4096};
 uint16_t pasids[] = {0,1,4095,65535};
 uint64_t keys[56]; unsigned n = 0;
 for (unsigned a = 0; a < 7; a++) for (unsigned p = 0; p < 4; p++) for (unsigned h = 0; h < 2; h++) {
  uint64_t key = amdgpu_gmc_fault_key(addrs[a],pasids[p],h);
  for (unsigned i = 0; i < n; i++) assert(keys[i] != key);
  keys[n++] = key;
 }
 struct amdgpu_device adev = {.irq.ih1.ring_size = 8};
 struct amdgpu_ih_ring *ih = &adev.irq.ih1;
 assert(!amdgpu_gmc_filter_faults(&adev,ih,4096,1,10000,0));
 assert(amdgpu_gmc_filter_faults(&adev,ih,4096,1,10000,0));
 assert(!amdgpu_gmc_filter_faults(&adev,ih,4096,1,10001,1));
 assert(!amdgpu_gmc_filter_faults(&adev,ih,4096,2,10002,0));
 assert(!amdgpu_gmc_filter_faults(&adev,ih,high+4096,1,10003,0));
 last_ts = 10010;
 amdgpu_gmc_filter_faults_remove(&adev,4096,1);
 assert(!amdgpu_gmc_filter_faults(&adev,ih,4096,1,10011,0));
 assert(!amdgpu_gmc_filter_faults(&adev,ih,4096,1,10012,1));
 assert(amdgpu_gmc_filter_faults(&adev,ih,4096,2,10013,0));
 assert(amdgpu_gmc_filter_faults(&adev,ih,high+4096,1,10013,0));
 ih->processed_timestamp = 10020;
 assert(amdgpu_gmc_filter_faults(&adev,ih,8192,3,10000,0));
 ih->processed_timestamp = 0;
 assert(!amdgpu_gmc_filter_faults(&adev,ih,4096,2,20000,0));
 puts("PASS: 57-bit key uniqueness, PASID/source isolation, hash collisions, remove-both, stale/expiry");
}
'''
code = prefix + '\n'.join(function(n) for n in (
    'amdgpu_gmc_fault_key', 'amdgpu_gmc_filter_faults', 'amdgpu_gmc_filter_faults_remove')) + main
with tempfile.TemporaryDirectory(prefix='gmc-filter-test-') as tmp:
    path = pathlib.Path(tmp)
    (path / 'test.c').write_text(code)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=undefined', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
