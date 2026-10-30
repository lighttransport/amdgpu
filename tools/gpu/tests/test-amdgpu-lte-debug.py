#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise real diagnostic gates/hooks and the capture tool without a GPU."""
import ast
import os
import pathlib
import re
import subprocess
import sys
import tempfile

root = pathlib.Path(sys.argv[1])
here = pathlib.Path(__file__).parent


def prefix(name):
    tree = ast.parse((here / name).read_text())
    return next(ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'prefix' for t in n.targets))


def function(path, name):
    source = (root / path).read_text()
    match = re.search(r'(?:static )?(?:inline )?(?:int|u32|void) ' + name + r'\([^;]+?\)\n\{', source)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


def run_c(code):
    with tempfile.TemporaryDirectory(prefix='lte-debug-test-') as tmp:
        path = pathlib.Path(tmp)
        (path / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-variable', '-Wno-unused-but-set-variable',
                        '-fsanitize=undefined', '-fno-sanitize-recover=undefined', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True)


base = 'drivers/gpu/drm/amd/'
common = r'''
#include <string.h>
#define U32_MAX UINT32_MAX
#define unlikely(x) (x)
#define AMDGPU_LTE_DEBUG_SMU 1
#define AMDGPU_LTE_DEBUG_PM 2
#define AMDGPU_LTE_DEBUG_PPT 4
static unsigned int amdgpu_lte_debug;
'''
smu = prefix('test-smu-etime.py').replace('#define smu_lte_trace(...) ((void)0)', '')
smu = smu.replace('u32 timeout_streak;', 'u32 timeout_streak, default_timeout;')
smu += common + r'''
static bool enabled = true;
static struct { const char *phase; u32 param, resp, timeout, index; int ret; } events[32];
static unsigned nevents;
#define trace_amdgpu_lte_smu_enabled() (enabled)
static void trace_amdgpu_lte_smu(struct amdgpu_device *a, const char *p, const char *m,
 u32 i, u32 v, u32 r, int ret, u32 state, u32 streak, u32 timeout) {
 (void)a; (void)m; (void)state; (void)streak; assert(nevents < 32);
 events[nevents++] = (typeof(events[0])){p,v,r,timeout,i,ret};
}
'''
smu += '\n'.join(function(base + 'pm/swsmu/smu_cmn.c', n) for n in (
    'smu_lte_trace', '__smu_msg_v1_send', '__smu_msg_v1_etime_track',
    'smu_msg_v1_send_msg', 'smu_msg_v1_wait_response'))
smu += r'''
int main(void) {
 struct amdgpu_device adev = {0};
 struct smu_context context = {.adev = &adev};
 struct cmn2asic_msg_mapping map[] = {{1,0,42}};
 struct smu_msg_ctl ctl = {.smu = &context, .message_map = map, .default_timeout = 123,
  .config = {.msg_reg = 42, .num_arg_regs = 1}};
 struct smu_msg_args args = {.msg = TEST_MSG, .num_args = 1, .args = {170}};
 for (int mode = 0; mode < 4; mode++) {
  context.smc_fw_state = SMU_FW_INIT; nevents = polls = sends = response_pos = 0;
  nresponses = 1; responses[0] = 1;
  amdgpu_lte_debug = mode == 0 ? 0 : mode == 1 ? 2 : 1; enabled = mode != 2;
  assert(smu_msg_v1_send_msg(&ctl, &args) == 0 && polls == 1 && sends == 1);
  if (mode != 3) { assert(nevents == 0); continue; }
  assert(nevents == 2 && !strcmp(events[0].phase, "send"));
  assert(events[0].param == 170 && events[0].index == 42 && events[0].timeout == 123);
  assert(!strcmp(events[1].phase, "post-end") && events[1].resp == 1 && events[1].ret == 0);
 }
 nevents = 0; response_pos = 0; responses[0] = 0;
 assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME && sends == 1);
 assert(nevents == 2 && !strcmp(events[0].phase,"pre-begin"));
 assert(!strcmp(events[1].phase,"pre-end") && events[1].ret == -ETIME);
 nevents = 0; response_pos = 0; responses[0] = 1;
 assert(smu_msg_v1_wait_response(&ctl, 99) == 0);
 assert(nevents == 2 && !strcmp(events[0].phase,"wait-begin") && events[0].timeout == 99);
 assert(!strcmp(events[1].phase,"wait-end"));
 puts("PASS: SMU gates, send/pre/wait ordering, original polls/writes and payload");
}
'''
run_c(smu)

ppt = prefix('test-smu-min-power-cap.py').replace('#define U32_MAX UINT32_MAX', '').replace('#define amdgpu_lte_ppt_trace(...) ((void)0)', '')
ppt += common + r'''
static struct {const char *phase; u32 min, max, held, requested; int ret;} events[16];
static unsigned nevents;
static void trace_amdgpu_lte_ppt(struct amdgpu_device *a, const char *p, u32 type,
 u32 req, u32 min, u32 max, u32 held, int ret) {
 (void)a; (void)type; assert(nevents < 16);
 events[nevents++] = (typeof(events[0])){p,min,max,held,req,ret};
}
'''
ppt += function(base + 'amdgpu/amdgpu_lte_debug.h', 'amdgpu_lte_ppt_trace')
ppt += '\n'.join(function(base + 'pm/swsmu/amdgpu_smu.c', n)
                 for n in ('smu_min_ppt_limit', 'smu_set_ppt_limit'))
ppt += r'''
int main(void) {
 for (int mode = 0; mode < 3; mode++) {
  init(); amdgpu_smu_min_power_cap = 150; nevents = 0;
  amdgpu_lte_debug = mode == 0 ? 0 : mode == 1 ? 1 : 4;
  assert(smu_set_ppt_limit(&smu,0,170) == 0 && writes == 1 && reads == 1);
  if (mode < 2) {assert(nevents == 0); continue;}
  assert(nevents == 5 && !strcmp(events[0].phase,"request"));
  assert(events[0].min == 150 && events[0].max == 304 && events[0].requested == 170);
  assert(!strcmp(events[4].phase,"readback-end") && events[4].held == 170 && events[4].ret == 0);
 }
 init(); amdgpu_smu_min_power_cap = 150; nevents = 0; clamp = true;
 assert(smu_set_ppt_limit(&smu,0,170) == -EIO && writes == 1 && reads == 1);
 assert(nevents == 6 && !strcmp(events[5].phase,"mismatch") && events[5].ret == -EIO);
 init(); amdgpu_smu_min_power_cap = 150; nevents = 0;
 assert(smu_set_ppt_limit(&smu,0,149) == -EINVAL && writes == 0 && reads == 0);
 assert(nevents == 2 && !strcmp(events[1].phase,"range-error"));
 puts("PASS: PPT gates, effective bounds, read-back/mismatch, no extra firmware calls");
}
'''
run_c(ppt)

pm = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define dev_err(...) ((void)0)
struct amdgpu_device {int unused;};
struct amdgpu_ip_block;
struct funcs {const char *name; int (*suspend)(struct amdgpu_ip_block *); int (*resume)(struct amdgpu_ip_block *);};
struct version {struct funcs *funcs;};
struct amdgpu_ip_block {struct amdgpu_device *adev; struct version *version; struct {bool hw;} status;};
static int result;
static int callback(struct amdgpu_ip_block *b) {(void)b; return result;}
static unsigned nevents;
static struct {const char *phase; int ret; bool hw;} events[4];
static void trace_amdgpu_lte_pm(struct amdgpu_device *a, const char *block, const char *phase, int ret, bool hw) {
 (void)a; (void)block; assert(nevents < 4); events[nevents++] = (typeof(events[0])){phase,ret,hw};
}
'''
pm += common + function(base + 'amdgpu/amdgpu_lte_debug.h', 'amdgpu_lte_pm_trace')
pm += '\n'.join(function(base + 'amdgpu/amdgpu_ip.c', n)
                for n in ('amdgpu_ip_block_suspend', 'amdgpu_ip_block_resume'))
pm += r'''
int main(void) {
 struct amdgpu_device a; struct funcs f = {"smu",callback,callback}; struct version v = {&f};
 struct amdgpu_ip_block b = {&a,&v,{true}};
 assert(amdgpu_ip_block_suspend(&b) == 0 && nevents == 0 && !b.status.hw);
 amdgpu_lte_debug = 2;
 assert(amdgpu_ip_block_resume(&b) == 0 && b.status.hw && nevents == 2);
 assert(!strcmp(events[0].phase,"resume-begin") && !events[0].hw);
 assert(!strcmp(events[1].phase,"resume-end") && events[1].hw);
 nevents = 0; result = -62;
 assert(amdgpu_ip_block_suspend(&b) == -62 && b.status.hw && nevents == 2);
 assert(events[1].ret == -62 && events[1].hw);
 f.suspend = 0; nevents = 0;
 assert(amdgpu_ip_block_suspend(&b) == 0 && !b.status.hw && nevents == 2);
 puts("PASS: PM gate, paired phases, original return values and IP status on failure");
}
'''
run_c(pm)

# Fake tracefs: check only our instance/configuration; never use live tracefs or dmesg.
with tempfile.TemporaryDirectory(prefix='lte-capture-test-') as tmp:
    path = pathlib.Path(tmp)
    trace = path / 'tracefs'
    instance = trace / 'instances/amdgpu-lte-170w'
    params = path / 'params'
    params.mkdir()
    (params / 'lte_debug').write_text('0\n')
    names = ('amdgpu_lte_smu', 'amdgpu_lte_pm', 'amdgpu_lte_ppt')
    for name in names:
        global_event = trace / 'events/amdgpu_lte' / name
        global_event.mkdir(parents=True)
        (global_event / 'id').write_text('1\n')
        event = instance / 'events/amdgpu_lte' / name
        event.mkdir(parents=True)
        (event / 'enable').write_text('0\n')
        (event / 'trigger').write_text('# triggers\n')
    (instance / 'tracing_on').write_text('0\n')
    (instance / 'options').mkdir()
    (instance / 'options/overwrite').write_text('0\n')
    (path / 'dmesg').write_text('#!/bin/sh\necho fixture-dmesg\n')
    (path / 'dmesg').chmod(0o755)
    env = dict(os.environ, TRACING_ROOT=str(trace), MODULE_PARAM_ROOT=str(params),
               PATH=str(path) + ':' + os.environ['PATH'], FREEZE_ON_TIMEOUT='1')
    script = root / 'tools/gpu/amdgpu-lte-capture.sh'
    def tool(*args):
        return subprocess.run(['bash', str(script), *args], env=env, capture_output=True, text=True)
    assert tool('start').returncode != 0
    (params / 'lte_debug').write_text('7\n')
    env['BUFFER_KB'] = '040000'
    assert tool('start').returncode != 0  # Decimal 40000 must not pass as octal 16384.
    env['BUFFER_KB'] = '00256'
    result = tool('start'); assert result.returncode == 0, result.stderr
    assert (instance / 'buffer_size_kb').read_text().strip() == '256'
    assert (instance / 'options/overwrite').read_text().strip() == '1'
    assert (instance / 'tracing_on').read_text().strip() == '1'
    assert 'ret == -62 || ret == -121' in (instance / 'events/amdgpu_lte/amdgpu_lte_smu/trigger').read_text()
    assert tool('start').returncode != 0  # Never clear an active capture.
    assert tool('mark', 'before-170W').returncode == 0
    assert (instance / 'trace_marker').read_text() == 'before-170W\n'
    (instance / 'trace').write_text('fixture-trace\n')
    result = tool('stop', str(path / 'out')); assert result.returncode == 0, result.stderr
    assert (path / 'out/trace.txt').read_text() == 'fixture-trace\n'
    assert (path / 'out/dmesg.txt').read_text() == 'fixture-dmesg\n'
    assert 'lte_debug=7' in (path / 'out/context.txt').read_text()
    assert (instance / 'tracing_on').read_text().strip() == '0'
    print('PASS: capture opt-in checks, instance isolation, freeze setup, active-capture guard, export')
