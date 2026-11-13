#!/usr/bin/env python3
"""Compile the actual allocation preflight and test boundary intervals."""
from pathlib import Path
import subprocess
import sys
import tempfile
root = Path(sys.argv[1])
source = (root / 'drivers/gpu/drm/amd/amdkfd/kfd_chardev.c').read_text()
body = source.split('static int kfd_ioctl_alloc_memory_of_gpu(', 1)[1]
checks = body[body.index('\tif (args->size == 0)'):body.index('\tif (p->context_id !=')]
assert 'mmap_offset' in checks and 'U64_MAX' in checks
handle_check = body[body.index('\tif (idr_handle < 0)'):body.index('\n\t/* Update the VRAM usage count */')]
program = '''#include <stdint.h>
#include <errno.h>
#include <assert.h>
#define U64_MAX UINT64_MAX
#define KFD_IOC_ALLOC_MEM_FLAGS_USERPTR 1
struct args { uint64_t va_addr, size, mmap_offset; };
static int check(struct args *args, unsigned flags) {
''' + checks + '''return 0; }
static int check_handle(int idr_handle) {
int err = 0;
''' + handle_check + '''return 0;
err_free: return err;
}
int main(void) {
assert(check_handle(-ENOMEM) == -ENOMEM);
assert(check_handle(-ENOSPC) == -ENOSPC);
assert(check_handle(1) == 0);
struct args a = {0, 0, 0};
assert(check(&a, 0) == -EINVAL);
a.size = 1; a.va_addr = UINT64_MAX; a.mmap_offset = UINT64_MAX;
assert(check(&a, 1) == 0);
a.size = 2; assert(check(&a, 0) == -EINVAL);
a.va_addr = 0; assert(check(&a, 1) == -EINVAL);
assert(check(&a, 0) == 0);
a.mmap_offset = UINT64_MAX - 1; assert(check(&a, 1) == 0);
a.va_addr = 0x22838000; a.mmap_offset = 0x22838000; a.size = 4096;
assert(check(&a, 1) == 0);
}
'''
with tempfile.TemporaryDirectory() as temp:
    c = Path(temp) / 'test.c'; c.write_text(program)
    exe = Path(temp) / 'test'
    subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: extracted allocation preflight: zero, wrapping VA/USERPTR, exact end and ordinary intervals')
