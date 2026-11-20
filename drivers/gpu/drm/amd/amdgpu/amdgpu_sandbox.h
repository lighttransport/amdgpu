/* SPDX-License-Identifier: MIT */
#ifndef AMDGPU_SANDBOX_H
#define AMDGPU_SANDBOX_H
#include <linux/types.h>
#include "amdgpu_sandbox_abi.h"
struct amdgpu_device;
struct amdgpu_sandbox;
struct amdgpu_sb_client;
struct amdgpu_sb_range;
struct mm_struct;

struct amdgpu_sb_range *amdgpu_sb_range_add(struct amdgpu_sandbox *sb,
	struct mm_struct *mm, u64 start, u64 size);
void amdgpu_sb_range_free(struct amdgpu_sb_range *range);
void amdgpu_sb_range_shrink(struct amdgpu_sb_range *range, u64 start, u64 size);
int amdgpu_sb_init(void);
void amdgpu_sb_fini(void);
struct amdgpu_sandbox *amdgpu_sb_current(struct amdgpu_device *adev);
struct amdgpu_sandbox *amdgpu_sb_get(struct amdgpu_sandbox *sb);
void amdgpu_sb_put(struct amdgpu_sandbox *sb);
bool amdgpu_sb_allows(struct amdgpu_sandbox *sb, struct amdgpu_device *adev);
int amdgpu_sb_check(struct amdgpu_sandbox *sb);
int amdgpu_sb_identity(struct amdgpu_sandbox *sb, struct amdgpu_device *adev);
int amdgpu_sb_check_current(struct amdgpu_sandbox *sb, struct amdgpu_device *adev);
int amdgpu_sb_charge(struct amdgpu_sandbox *sb, unsigned int resource, u64 amount);
int amdgpu_sb_charge_vram(struct amdgpu_sandbox *sb, u64 amount);
void amdgpu_sb_uncharge(struct amdgpu_sandbox *sb, unsigned int resource, u64 amount);
void amdgpu_sb_fault(struct amdgpu_sandbox *sb, u64 context, u64 sequence);
void amdgpu_sb_device_gone(struct amdgpu_device *adev);
/* get/put pin the owner; put must defer final teardown (fput/KFD release_work). */
struct amdgpu_sb_client *amdgpu_sb_client_add(struct amdgpu_sandbox *sb, void *data,
	bool (*get)(void *data), void (*put)(void *data), int (*evict)(void *data));
void amdgpu_sb_client_quiesce(struct amdgpu_sb_client *client);
void amdgpu_sb_client_del(struct amdgpu_sb_client *client);
#endif
