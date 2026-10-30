#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile real V1 control flow with mocked hardware; pass the fork source root."""
import pathlib
import subprocess
import sys
import tempfile

source = (pathlib.Path(sys.argv[1]) /
          'drivers/gpu/drm/amd/pm/swsmu/smu_cmn.c').read_text()


def function(name):
    start = source.index('static ', source.index(name + '(') - 30)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
enum smu_message_type { TEST_MSG, SMU_MSG_DriverMode2Reset, SMU_MSG_GfxDeviceDriverReset, SMU_MSG_MAX_COUNT };
enum { SMU_FW_INIT, SMU_FW_RUNTIME, SMU_FW_HANG };
#define SMU_RESP_NONE 0
#define SMU_RESP_OK 1
#define SMU_MSG_FLAG_LOCK_HELD 1
#define SMU_MSG_FLAG_ASYNC 2
#define SMU_MSG_FLAG_FORCE_READ_ARG 4
#define SMU_MSG_VF_FLAG 8
#define SMU_DEBUG_HALT_ON_ERROR 1
#define SMU_MSG_V1_BUSY_RETRIES 3
#define SMU_MSG_V1_ETIME_STREAK_LIMIT 3
#define DUMP_PREFIX_NONE 0
struct amdgpu_device { int no_hw_access; void *dev; struct { int smu_debug_mask; } pm; };
struct smu_context { struct amdgpu_device *adev; int smc_fw_state; };
struct cmn2asic_msg_mapping { int valid_mapping, flags, map_to; };
struct smu_msg_args { enum smu_message_type msg; int num_args, num_out_args; u32 flags, timeout; u32 args[1], out_args[1]; };
struct smu_msg_config { u32 msg_reg, resp_reg; int num_arg_regs; u32 arg_regs[1]; };
struct smu_msg_ctl {
 struct smu_context *smu;
 struct smu_msg_config config;
 const struct cmn2asic_msg_mapping *message_map;
 u32 timeout_streak;
 enum smu_message_type last_msg;
 int lock;
};
static unsigned int smu_etime_streak = 3;
static unsigned int polls, sends, logs, nresponses, response_pos, out_reads;
static char last_log[512];
static const char *smu_get_message_name(struct smu_context *s, enum smu_message_type m) {
 (void)s; return m == TEST_MSG ? "TEST_MSG" : "unknown smu message";
}
static u32 responses[256];
static u32 __smu_msg_v1_poll_stat(struct smu_msg_ctl *c, u32 t) {
 (void)c; (void)t; polls++; assert(response_pos < nresponses);
 return responses[response_pos++];
}
static int smu_msg_v1_decode_response(u32 r) {
 return r == 0 ? -ETIME : r == 1 ? 0 : r == 2 ? -EBUSY : r == 3 ? -EIO : -EREMOTEIO;
}
#define RREG32(r) ((void)adev, (r))
#define WREG32(r,v) do { (void)adev; if ((r) == ctl->config.msg_reg) sends++; (void)(v); } while (0)
#define dev_err(dev, ...) do { (void)(dev); ++logs; snprintf(last_log, sizeof(last_log), __VA_ARGS__); } while (0)
#define dev_dbg(...) ((void)0)
#define print_hex_dump_debug(...) ((void)0)
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
#define amdgpu_sriov_vf(a) false
#define udelay(t) ((void)(t))
#define unlikely(x) (x)
#define amdgpu_device_halt(a) assert(0)
#define WARN_ON(x) assert(!(x))
#define smu_lte_trace(...) ((void)0)
#define __smu_msg_v1_print_error(c,r,a) ((void)0)
#define __smu_msg_v1_read_out_args(c,a) ((void)++out_reads)
static int __smu_msg_v1_ras_filter(struct smu_msg_ctl *c, enum smu_message_type m, u32 f, bool *s) {
 (void)c; (void)m; (void)f; (void)s; return 0;
}
'''
main = r'''
int main(void) {
 struct amdgpu_device adev = {0};
 struct smu_context smu = { .adev = &adev };
 struct cmn2asic_msg_mapping map[] = {{1, 0, 42}};
 struct smu_msg_ctl ctl = { .smu = &smu, .message_map = map,
  .config = { .msg_reg = 42, .num_arg_regs = 1 } };
 struct smu_msg_args args = { .msg = TEST_MSG };
 #define RESET() do { smu.smc_fw_state = SMU_FW_INIT; ctl.timeout_streak = 0; ctl.last_msg = TEST_MSG; polls = sends = logs = response_pos = nresponses = 0; smu_etime_streak = 3; args.flags = 0; } while (0)
 #define RESP(v) (responses[nresponses++] = (v))
 RESET();
 RESP(0); assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME);
 assert(ctl.timeout_streak == 1 && ctl.last_msg == TEST_MSG);
 /* Late completion followed by successful synchronous command clears streak. */
 RESP(1); RESP(1); assert(smu_msg_v1_send_msg(&ctl, &args) == 0);
 assert(ctl.timeout_streak == 0);
 RESP(1); RESP(0); assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME);
 RESP(0); assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME);
 RESP(0); assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME);
 assert(smu.smc_fw_state == SMU_FW_HANG && ctl.timeout_streak == 3);
 assert(strstr(last_log, "last message TEST_MSG, msg_reg: 0x2a"));
 unsigned int saved_polls = polls, saved_sends = sends;
 assert(smu_msg_v1_send_msg(&ctl, &args) == -EREMOTEIO);
 assert(smu_msg_v1_wait_response(&ctl, 0) == -EREMOTEIO);
 assert(polls == saved_polls && sends == saved_sends);
 /* Firmware restart must discard the prior streak. */
 smu.smc_fw_state = SMU_FW_INIT;
 RESP(0); assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME);
 assert(ctl.timeout_streak == 1);
 RESET(); smu_etime_streak = 1;
 RESP(0); assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME);
 assert(smu.smc_fw_state == SMU_FW_HANG);
 RESET(); smu_etime_streak = 0;
 for (int i = 0; i < 10; i++) RESP(0);
 for (int i = 0; i < 10; i++) assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME);
 assert(smu.smc_fw_state == SMU_FW_RUNTIME && ctl.timeout_streak == 0);
 /* Async submission is not a successful response; wait owns the result. */
 RESET(); args.flags = SMU_MSG_FLAG_ASYNC | SMU_MSG_FLAG_LOCK_HELD;
 assert(smu_msg_v1_send_msg(&ctl, &args) == 0 && polls == 0);
 RESP(0); assert(smu_msg_v1_wait_response(&ctl, 0) == -ETIME);
 RESP(1); assert(smu_msg_v1_wait_response(&ctl, 0) == 0);
 assert(ctl.timeout_streak == 0);
 RESP(0); RESP(0); RESP(0);
 for (int i = 0; i < 3; i++) assert(smu_msg_v1_wait_response(&ctl, 0) == -ETIME);
 assert(smu.smc_fw_state == SMU_FW_HANG);
 /* Reset ACK loops retain their own budget, even above the threshold. */
 for (int reset = SMU_MSG_DriverMode2Reset; reset <= SMU_MSG_GfxDeviceDriverReset; reset++) {
  RESET(); smu.smc_fw_state = SMU_FW_RUNTIME; ctl.last_msg = reset;
  for (int i = 0; i < 100; i++) RESP(0);
  for (int i = 0; i < 100; i++) assert(smu_msg_v1_wait_response(&ctl, 0) == -ETIME);
  assert(smu.smc_fw_state == SMU_FW_RUNTIME && ctl.timeout_streak == 0);
  RESP(1); assert(smu_msg_v1_wait_response(&ctl, 0) == 0);
  /* Once the reset caller gives up, normal send pre-polls still contain a wedged SMU. */
  RESP(0); RESP(0); RESP(0);
  for (int i = 0; i < 3; i++) assert(smu_msg_v1_send_msg(&ctl, &args) == -ETIME);
  assert(smu.smc_fw_state == SMU_FW_HANG);
 }
 /* ASYNC submission must not read output registers before completion. */
 RESET(); args.flags = SMU_MSG_FLAG_ASYNC | SMU_MSG_FLAG_LOCK_HELD;
 args.num_out_args = 1; out_reads = 0;
 assert(smu_msg_v1_send_msg(&ctl, &args) == 0);
 assert(polls == 0 && out_reads == 0);
 args.flags = 0; args.num_out_args = 0;
 /* Any defined non-timeout response breaks a timeout sequence. */
 RESET(); RESP(0); RESP(3);
 assert(smu_msg_v1_wait_response(&ctl, 0) == -ETIME);
 assert(smu_msg_v1_wait_response(&ctl, 0) == -EIO);
 assert(ctl.timeout_streak == 0);
 /* Largest uint threshold must reach hang without wrapping the counter. */
 RESET(); smu_etime_streak = UINT32_MAX;
 smu.smc_fw_state = SMU_FW_RUNTIME; ctl.timeout_streak = UINT32_MAX - 1;
 RESP(0); assert(smu_msg_v1_wait_response(&ctl, 0) == -ETIME);
 assert(smu.smc_fw_state == SMU_FW_HANG && ctl.timeout_streak == UINT32_MAX);
 RESET(); RESP(2); RESP(2); RESP(2); RESP(1);
 assert(smu_msg_v1_send_msg(&ctl, &args) == 0 && sends == 4);
 puts("PASS: sync/async streaks, late completion, restart, thresholds 0/1/3, fail-fast, reset ACK budgets, busy retry");
}
'''
code = prefix + '\n'.join(function(n) for n in (
    '__smu_msg_v1_send', '__smu_msg_v1_etime_track',
    'smu_msg_v1_send_msg', 'smu_msg_v1_wait_response')) + main
with tempfile.TemporaryDirectory(prefix='smu-etime-test-') as tmp:
    path = pathlib.Path(tmp)
    (path / 'test.c').write_text(code)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-variable', '-Wno-unused-but-set-variable',
                    '-fsanitize=undefined', '-fno-sanitize-recover=undefined', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
