/* SPDX-License-Identifier: MIT */
#undef TRACE_SYSTEM
#define TRACE_SYSTEM amdgpu_lte

#if !defined(_AMDGPU_LTE_TRACE_H_) || defined(TRACE_HEADER_MULTI_READ)
#define _AMDGPU_LTE_TRACE_H_

#include <linux/tracepoint.h>
#include <kcl/kcl_tracepoint.h>

TRACE_EVENT(amdgpu_lte_smu,
	    TP_PROTO(struct amdgpu_device *adev, const char *phase, const char *msg,
		     u32 index, u32 param, u32 resp, int ret, u32 state, u32 streak,
		     u32 timeout),
	    TP_ARGS(adev, phase, msg, index, param, resp, ret, state, streak, timeout),
	    TP_STRUCT__entry(
		__string(dev, dev_name(adev->dev))
		__string(phase, phase)
		__string(msg, msg)
		__field(u32, index)
		__field(u32, param)
		__field(u32, resp)
		__field(int, ret)
		__field(u32, state)
		__field(u32, streak)
		__field(u32, timeout)
	),
	    TP_fast_assign(
		__amdkcl_assign_str(dev, dev_name(adev->dev));
		__amdkcl_assign_str(phase, phase);
		__amdkcl_assign_str(msg, msg);
		__entry->index = index;
		__entry->param = param;
		__entry->resp = resp;
		__entry->ret = ret;
		__entry->state = state;
		__entry->streak = streak;
		__entry->timeout = timeout;
	),
	    TP_printk("dev=%s phase=%s msg=%s index=0x%x param=0x%x resp=0x%x ret=%d state=%u streak=%u timeout_us=%u",
		      __get_str(dev), __get_str(phase), __get_str(msg),
		      __entry->index, __entry->param, __entry->resp, __entry->ret,
		      __entry->state, __entry->streak, __entry->timeout)
);

TRACE_EVENT(amdgpu_lte_pm,
	    TP_PROTO(struct amdgpu_device *adev, const char *block,
		     const char *phase, int ret, bool hw),
	    TP_ARGS(adev, block, phase, ret, hw),
	    TP_STRUCT__entry(
		__string(dev, dev_name(adev->dev))
		__string(block, block)
		__string(phase, phase)
		__field(int, ret)
		__field(bool, hw)
		__field(bool, dpm)
		__field(bool, runpm)
		__field(bool, s0ix)
		__field(bool, suspend)
		__field(int, mp1)
	),
	    TP_fast_assign(
		__amdkcl_assign_str(dev, dev_name(adev->dev));
		__amdkcl_assign_str(block, block);
		__amdkcl_assign_str(phase, phase);
		__entry->ret = ret;
		__entry->hw = hw;
		__entry->dpm = adev->pm.dpm_enabled;
		__entry->runpm = adev->in_runpm;
		__entry->s0ix = adev->in_s0ix;
		__entry->suspend = adev->in_suspend;
		__entry->mp1 = adev->mp1_state;
	),
	    TP_printk("dev=%s block=%s phase=%s ret=%d hw=%d dpm=%d runpm=%d s0ix=%d suspend=%d mp1=%d",
		      __get_str(dev), __get_str(block), __get_str(phase),
		      __entry->ret, __entry->hw, __entry->dpm, __entry->runpm,
		      __entry->s0ix, __entry->suspend, __entry->mp1)
);

TRACE_EVENT(amdgpu_lte_ppt,
	    TP_PROTO(struct amdgpu_device *adev, const char *phase, u32 type,
		     u32 requested, u32 min, u32 max, u32 held, int ret),
	    TP_ARGS(adev, phase, type, requested, min, max, held, ret),
	    TP_STRUCT__entry(
		__string(dev, dev_name(adev->dev))
		__string(phase, phase)
		__field(u32, type)
		__field(u32, requested)
		__field(u32, min)
		__field(u32, max)
		__field(u32, held)
		__field(int, ret)
		__field(bool, ac)
	),
	    TP_fast_assign(
		__amdkcl_assign_str(dev, dev_name(adev->dev));
		__amdkcl_assign_str(phase, phase);
		__entry->type = type;
		__entry->requested = requested;
		__entry->min = min;
		__entry->max = max;
		__entry->held = held;
		__entry->ret = ret;
		__entry->ac = adev->pm.ac_power;
	),
	    TP_printk("dev=%s phase=%s type=%u requested_w=%u min_w=%u max_w=%u held_w=%u ret=%d ac=%d",
		      __get_str(dev), __get_str(phase), __entry->type,
		      __entry->requested, __entry->min, __entry->max,
		      __entry->held, __entry->ret, __entry->ac)
);
#endif

#undef TRACE_INCLUDE_PATH
#define TRACE_INCLUDE_PATH .
#undef TRACE_INCLUDE_FILE
#define TRACE_INCLUDE_FILE amdgpu_lte_trace
#include <trace/define_trace.h>
