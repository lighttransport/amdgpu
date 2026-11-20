/* SPDX-License-Identifier: MIT */
#ifndef AMDGPU_SANDBOX_ABI_H
#define AMDGPU_SANDBOX_ABI_H
#include <linux/types.h>
#include <linux/ioctl.h>

#define AMDGPU_SB_VERSION 1
#define AMDGPU_SB_RESOURCE_COUNT 7
/* Experimental driver-private ABI; not an upstream cgroup interface. */
enum amdgpu_sb_op {
	AMDGPU_SB_CAPS = 0, AMDGPU_SB_CREATE, AMDGPU_SB_STATS,
	AMDGPU_SB_NEXT, AMDGPU_SB_QUARANTINE, AMDGPU_SB_RETIRE
};
enum amdgpu_sb_resource {
	AMDGPU_SB_VRAM = 0, AMDGPU_SB_BUFFER, AMDGPU_SB_PINNED,
	AMDGPU_SB_BOS, AMDGPU_SB_CONTEXTS, AMDGPU_SB_QUEUES, AMDGPU_SB_JOBS
};
enum amdgpu_sb_mode { AMDGPU_SB_OBSERVE = 0, AMDGPU_SB_ENFORCE = 1 };
enum amdgpu_sb_state { AMDGPU_SB_ACTIVE = 0, AMDGPU_SB_QUARANTINED, AMDGPU_SB_DEVICE_GONE };
#define AMDGPU_SB_F_OWNERSHIP (1ULL << 0)
#define AMDGPU_SB_F_BO (1ULL << 1)
#define AMDGPU_SB_F_VRAM (1ULL << 2)
#define AMDGPU_SB_F_PINNED (1ULL << 3)
#define AMDGPU_SB_F_CONTEXTS (1ULL << 4)
#define AMDGPU_SB_F_LEGACY (1ULL << 5)
#define AMDGPU_SB_F_USERQ (1ULL << 6)
#define AMDGPU_SB_F_KFD (1ULL << 7)
#define AMDGPU_SB_F_FAULTS (1ULL << 8)
#define AMDGPU_SB_F_ALL ((1ULL << 9) - 1)
struct amdgpu_sb_ctl {
	__u32 size, version, op, mode;
	__s32 cgroup_fd;
	__u32 pci_domain, pci_bus, pci_devfn;
	__u64 id, features;
	__u64 limit[AMDGPU_SB_RESOURCE_COUNT];
	__u64 usage[AMDGPU_SB_RESOURCE_COUNT];
	__u64 peak[AMDGPU_SB_RESOURCE_COUNT];
	__u64 violations, incidents, sequence;
	__u32 state, fault_threshold, fault_window_ms, reserved;
	__u64 cgroup_id;
};
#define AMDGPU_SB_IOCTL _IOWR('S', 0xa0, struct amdgpu_sb_ctl)
enum amdgpu_sb_event_type {
	AMDGPU_SB_EVENT_CREATE = 1, AMDGPU_SB_EVENT_LIMIT, AMDGPU_SB_EVENT_FAULT,
	AMDGPU_SB_EVENT_QUARANTINE, AMDGPU_SB_EVENT_RETIRE, AMDGPU_SB_EVENT_DEVICE_GONE
};
struct amdgpu_sb_event {
	__u64 sequence, id, monotonic_ns;
	__u32 type, resource;
	__u64 value, limit;
};
#endif
