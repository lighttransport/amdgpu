/* SPDX-License-Identifier: MIT */
#ifndef _AMDGPU_LTE_DEBUG_H_
#define _AMDGPU_LTE_DEBUG_H_

#include "amdgpu_lte_trace.h"

static inline void amdgpu_lte_pm_trace(struct amdgpu_device *adev,
				       const char *block, const char *phase,
				       int ret, bool hw)
{
	if (unlikely(amdgpu_lte_debug & AMDGPU_LTE_DEBUG_PM))
		trace_amdgpu_lte_pm(adev, block, phase, ret, hw);
}

static inline void amdgpu_lte_ppt_trace(struct amdgpu_device *adev,
					const char *phase, u32 type,
					u32 requested, u32 min, u32 max,
					u32 held, int ret)
{
	if (unlikely(amdgpu_lte_debug & AMDGPU_LTE_DEBUG_PPT))
		trace_amdgpu_lte_ppt(adev, phase, type, requested, min, max,
				     held, ret);
}
#endif
