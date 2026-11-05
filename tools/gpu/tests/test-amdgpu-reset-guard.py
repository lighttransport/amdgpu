#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the real timeout callback, PCI check and scheduler bookkeeping.

Usage: python3 test-amdgpu-reset-guard.py /path/to/amdgpu
Compiles extracted C functions with mocked PCI/fence/workqueue dependencies.
No root, kernel module loading, live reset, or GPU access is involved.
"""
import pathlib
import re
import subprocess
import sys
import tempfile


root = pathlib.Path(sys.argv[1])


def function(path, name):
    source = (root / path).read_text()
    match = re.search(r'^(?:static (?:inline )?)?(?:enum \w+|unsigned long|void|int|bool|struct drm_sched_job \*)\s+'
                      + name + r'\([^;]+?\)\n\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end] + '\n\n'


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
typedef uint32_t u32;
#define container_of(p,t,m) ((t *)((char *)(p) - offsetof(t,m)))
struct list_head { struct list_head *next, *prev; };
static void INIT_LIST_HEAD(struct list_head *h) { h->next=h->prev=h; }
static bool list_empty(struct list_head *h) { return h->next==h; }
static void list_add(struct list_head *n, struct list_head *h) {
 assert(n->next==n && n->prev==n); n->next=h->next; n->prev=h;
 h->next->prev=n; h->next=n;
}
static void list_del_init(struct list_head *n) {
 n->prev->next=n->next; n->next->prev=n->prev; INIT_LIST_HEAD(n);
}
#define list_first_entry_or_null(h,t,m) (list_empty(h) ? NULL : container_of((h)->next,t,m))
#define list_del(n) list_del_init(n)
#define list_for_each_entry_safe_reverse(pos,tmp,head,member) \
 for(pos=container_of((head)->prev,typeof(*pos),member), \
     tmp=container_of(pos->member.prev,typeof(*pos),member); \
     &pos->member!=(head); \
     pos=tmp,tmp=container_of(tmp->member.prev,typeof(*tmp),member))
enum drm_gpu_sched_stat { DRM_GPU_SCHED_STAT_RESET, DRM_GPU_SCHED_STAT_ENODEV, DRM_GPU_SCHED_STAT_NO_HANG };
struct work_struct { bool queued, free_worker; };
struct delayed_work { struct work_struct work; struct { unsigned long expires; } timer; bool pending; };
struct drm_sched_job;
struct dma_fence { uint64_t context, seqno; int status, error; bool callback; unsigned long flags, timestamp; int *lock; struct drm_sched_job *owner; };
struct drm_sched_fence { struct dma_fence finished, scheduled, *parent; struct drm_gpu_scheduler *sched; };
struct drm_sched_job;
struct drm_sched_backend_ops {
 enum drm_gpu_sched_stat (*timedout_job)(struct drm_sched_job *);
 void (*free_job)(struct drm_sched_job *);
 void (*cancel_job)(struct drm_sched_job *);
};
struct drm_gpu_scheduler {
 const char *name; int job_list_lock, credit_count, score_value, *score;
 struct list_head pending_list; struct delayed_work work_tdr;
 const struct drm_sched_backend_ops *ops; bool free_guilty, pause_submit;
 unsigned long timeout; void *timeout_wq, *submit_wq;
 struct work_struct work_run_job, work_free_job;
 bool ready, own_submit_wq; int job_scheduled; void *dev;
};
struct drm_sched_job {
 struct drm_gpu_scheduler *sched; struct drm_sched_fence *s_fence;
 struct list_head list; int credits, cb; bool freed;
};
struct device { int unused; };
struct pci_dev { int unused; };
struct rw_semaphore { unsigned readers; bool writer; };
struct amdgpu_reset_domain { struct rw_semaphore sem; };
struct drm_wedge_task_info { int unused; };
struct amdgpu_task_info { struct drm_wedge_task_info task; };
struct amdgpu_device {
 struct device *dev; struct pci_dev *pdev; bool vf;
 struct amdgpu_reset_domain *reset_domain;
 struct { bool tdr_debug; } virt; int gpu_reset_counter;
};
struct amdgpu_ring {
 struct drm_gpu_scheduler sched; struct amdgpu_device *adev;
 struct { int last_seq; unsigned sync_seq; } fence_drv;
 struct { int (*reset)(void); } *funcs;
};
struct amdgpu_job {
 void *sandbox;
 struct drm_sched_job base; int pasid, vmid; struct dma_fence *hw_fence;
};
struct amdgpu_reset_context {
 int method, src; struct amdgpu_device *reset_req_dev; unsigned long flags;
};
#define to_amdgpu_ring(s) container_of(s,struct amdgpu_ring,sched)
#define to_amdgpu_job(j) container_of(j,struct amdgpu_job,base)
#define adev_to_drm(a) (a)
#define amdgpu_sriov_vf(a) ((a)->vf)
#define PCI_COMMAND 4
#define PCI_POSSIBLE_ERROR(s) ((s)==UINT32_MAX)
#define AMDGPU_RESET_TYPE_SOFT_RECOVERY 1
#define AMDGPU_RESET_TYPE_PER_QUEUE 2
#define AMDGPU_RESET_TYPE_IP_BLOCK_SOFT_RESET 4
#define AMD_RESET_METHOD_NONE (-1)
#define AMDGPU_RESET_SRC_JOB 1
#define AMDGPU_NEED_FULL_RESET 0
#define AMDGPU_SKIP_COREDUMP 2
#define DRM_WEDGE_RECOVERY_NONE 0
#define MAX_SCHEDULE_TIMEOUT LONG_MAX
static unsigned long jiffies=1;
static int amdgpu_gpu_recovery=1, recovery_allowed=1, supported=3;
static int config_reads, missing_at, config_error, unplugged, soft_ok;
static int ring_ret, ip_ret, recover_ret;
static unsigned dumps, ring_resets, ip_resets, recovers, enters, exits;
static unsigned task_gets, task_puts, stops, starts, arms, cancels, frees, free_queues;
static unsigned read_attempts, read_locks, read_unlocks, reset_completions;
static unsigned teardown_warnings;
static bool reset_pending, reset_during_ring;
static struct amdgpu_reset_domain reset_domain;
static struct amdgpu_task_info task;
static void (*dump_hook)(void), (*stop_hook)(void), (*config_hook)(void), (*reset_resume_hook)(void);
int down_read_trylock(struct rw_semaphore *s) {
 read_attempts++;if(s->writer) return false;s->readers++;read_locks++;return true;
}
void up_read(struct rw_semaphore *s) {
 assert(s->readers==1 && !s->writer);s->readers--;read_unlocks++;
 if(reset_pending) {
  reset_pending=false;s->writer=true;reset_completions++;
  assert(reset_resume_hook);reset_resume_hook();s->writer=false;
 }
}
static void spin_lock(int *l) { assert(!*l); *l=1; }
static void spin_unlock(int *l) { assert(*l); *l=0; }
#define spin_lock_irqsave(l,f) do { (f)=0; spin_lock(l); } while(0)
#define spin_unlock_irqrestore(l,f) do { (void)(f); spin_unlock(l); } while(0)
#define lockdep_assert_held(l) assert(*(l))
#define atomic_read(p) (*(p))
#define atomic_inc(p) (++*(p))
#define atomic_dec(p) (--*(p))
#define atomic_sub(v,p) (*(p)-=(v))
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,n) ((v)=(n))
#define clear_bit(b,p) (*(p)&=~(1UL<<(b)))
#define set_bit(b,p) (*(p)|=(1UL<<(b)))
#define dev_info(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_warn(...) (teardown_warnings++)
#define EXPORT_SYMBOL(f)
static void wake_up_all(int *w) { (void)w; }
static void destroy_workqueue(void *q) { (void)q; }
#define trace_drm_sched_job_done(f) ((void)(f))
#define DMA_FENCE_FLAG_TIMESTAMP_BIT 0
#define test_bit(b,p) ((*(p)&(1UL<<(b)))!=0)
static unsigned long dma_fence_timestamp(struct dma_fence *f) { return f->timestamp; }
static int pci_read_config_dword(struct pci_dev *p, int reg, u32 *status) {
 (void)p; assert(reg==PCI_COMMAND); config_reads++;
 assert(reset_domain.sem.readers==1 && !reset_domain.sem.writer);
 if(config_hook) { void (*hook)(void)=config_hook;config_hook=NULL;hook(); }
 *status=missing_at && config_reads>=missing_at ? UINT32_MAX : 7;
 return config_error;
}
static bool drm_dev_enter(struct amdgpu_device *a,int *idx) {
 (void)a; enters++; *idx=9; return !unplugged;
}
static void drm_dev_exit(int idx) { assert(idx==9); exits++; }
static inline void amdgpu_sb_fault(void *p,uint64_t context,uint64_t sequence) { (void)p;(void)context;(void)sequence; }
static void amdgpu_job_core_dump(struct amdgpu_device *a,struct amdgpu_job *j) { (void)a;(void)j;assert(!reset_domain.sem.readers);dumps++;if(dump_hook) dump_hook(); }
static bool amdgpu_ring_is_reset_type_supported(struct amdgpu_ring *r,int t) { (void)r;return supported&t; }
static bool amdgpu_ring_soft_recovery(struct amdgpu_ring *r,int v,struct dma_fence *f) { (void)r;(void)v;(void)f;return soft_ok; }
static struct amdgpu_task_info *amdgpu_vm_get_task_info_pasid(struct amdgpu_device *a,int p) { (void)a;(void)p;task_gets++;return &task; }
static void amdgpu_vm_print_task_info(struct amdgpu_device *a,struct amdgpu_task_info *t) { (void)a;assert(t==&task); }
static void amdgpu_vm_put_task_info(struct amdgpu_task_info *t) { if(t) {assert(t==&task);task_puts++;} }
static void cancel_work_sync(struct work_struct *w) {
 w->queued=false;
 if(!w->free_worker) {
  stops++;
  if(stop_hook) { void (*hook)(void)=stop_hook;stop_hook=NULL;hook(); }
 }
}
static bool queue_work(void *q,struct work_struct *w) {
 (void)q;bool was_queued=w->queued;w->queued=true;
 if(w->free_worker) free_queues++;else starts++;
 return !was_queued;
}
static int amdgpu_ring_reset(struct amdgpu_ring *r,int v,struct dma_fence *f) { (void)r;(void)v;(void)f;assert(!reset_domain.sem.readers);if(reset_during_ring) reset_domain.sem.writer=true;ring_resets++;return ring_ret; }
static int amdgpu_device_ip_soft_reset(struct amdgpu_ring *r,struct dma_fence *f) { (void)r;(void)f;ip_resets++;return ip_ret; }
static void drm_dev_wedged_event(struct amdgpu_device *a,int reason,struct drm_wedge_task_info *t) { (void)a;(void)reason;(void)t; }
static int dma_fence_get_status(struct dma_fence *f) { return f->status; }
static void dma_fence_set_error(struct dma_fence *f,int e) { assert(!f->status);f->error=e; }
static bool amdgpu_device_should_recover_gpu(struct amdgpu_device *a) { (void)a;return recovery_allowed; }
static int amdgpu_device_gpu_recover(struct amdgpu_device *a,struct amdgpu_job *j,struct amdgpu_reset_context *c) {
 assert(c->reset_req_dev==a && c->src==AMDGPU_RESET_SRC_JOB);assert(!reset_domain.sem.readers && !reset_domain.sem.writer);(void)j;recovers++;return recover_ret;
}
static void dma_fence_put(struct dma_fence *f) { assert(f); }
static void dma_fence_get(struct dma_fence *f) { assert(f); }
static bool dma_fence_is_signaled(struct dma_fence *f) { return f->status!=0; }
static void drm_sched_job_done(struct drm_sched_job *, int);
static bool dma_fence_is_signaled_locked(struct dma_fence *f) { assert(*f->lock);return dma_fence_is_signaled(f); }
static void dma_fence_signal_locked(struct dma_fence *f) {
 assert(*f->lock && !f->status);f->status=f->error ? f->error : 1;
 if(f->callback) { f->callback=false;assert(f->owner);drm_sched_job_done(f->owner,f->error); }
}
static void drm_sched_fence_finished(struct drm_sched_fence *f,int result) { if(result) dma_fence_set_error(&f->finished,result);f->finished.status=result ? result : 1; }
static bool mod_delayed_work(void *q,struct delayed_work *w,unsigned long delay) { (void)q;bool was_pending=w->pending;w->pending=true;arms++;w->timer.expires=jiffies+delay;return was_pending; }
static void cancel_delayed_work(struct delayed_work *w) { w->pending=false;cancels++; }
static void cancel_delayed_work_sync(struct delayed_work *w) { cancel_delayed_work(w); }
#define time_after(a,b) ((long)((b)-(a))<0)
static void free_job(struct drm_sched_job *j) { assert(list_empty(&j->list));assert(!j->freed);j->freed=true;j->sched=NULL;j->s_fence=NULL;frees++; }
static unsigned long drm_sched_suspend_timeout(struct drm_gpu_scheduler *);
'''

driver = 'drivers/gpu/drm/amd/amdgpu/'
scheduler = 'drivers/gpu/drm/scheduler/sched_main.c'
code = prefix + function(scheduler, 'drm_sched_is_stopped')
code += function(scheduler, 'drm_sched_wqueue_stop')
code += function(scheduler, 'drm_sched_wqueue_start')
code += function(scheduler, 'drm_sched_run_free_queue')
code += function(driver + 'amdgpu.h', 'amdgpu_device_bus_status_check')
code += function(driver + 'amdgpu_job.c', 'amdgpu_job_timedout')
code += function(driver + 'amdgpu_job.c', 'amdgpu_job_cancel')
code += function(scheduler, 'drm_sched_start_timeout')
code += function(scheduler, 'drm_sched_start_timeout_unlocked')
code += function(scheduler, 'drm_sched_suspend_timeout')
code += function(scheduler, 'drm_sched_job_reinsert_on_false_timeout')
code += function(scheduler, 'drm_sched_job_timedout')
code += function(scheduler, 'drm_sched_job_done')
code += function(scheduler, 'drm_sched_get_finished_job')
code += function(scheduler, 'drm_sched_cancel_remaining_jobs')
code += function(scheduler, 'drm_sched_fini')
assert '.cancel_job = amdgpu_job_cancel' in (root / driver / 'amdgpu_job.c').read_text()

code += r'''
static struct amdgpu_device adev;
static struct amdgpu_ring ring;
static struct amdgpu_job job;
static struct drm_sched_fence sf;
static struct dma_fence hw;
static const struct drm_sched_backend_ops ops={amdgpu_job_timedout,free_job,amdgpu_job_cancel};
static int fence_lock;
static int reset_marker(void) { return 0; }
static void setup(void) {
 memset(&adev,0,sizeof(adev));memset(&ring,0,sizeof(ring));
 memset(&reset_domain,0,sizeof(reset_domain));adev.reset_domain=&reset_domain;
 memset(&job,0,sizeof(job));memset(&sf,0,sizeof(sf));memset(&hw,0,sizeof(hw));
 static typeof(*ring.funcs) funcs={reset_marker};ring.funcs=&funcs;
 ring.adev=&adev;ring.sched.name="gfx_0.0.0";ring.sched.ops=&ops;
 ring.sched.timeout=100;ring.sched.credit_count=1;
 ring.sched.work_free_job.free_worker=true;ring.sched.work_tdr.pending=true;
 ring.sched.score=&ring.sched.score_value;ring.sched.score_value=1;sf.sched=&ring.sched;
 INIT_LIST_HEAD(&ring.sched.pending_list);INIT_LIST_HEAD(&job.base.list);
 job.base.sched=&ring.sched;job.base.s_fence=&sf;job.base.credits=1;
 job.hw_fence=&hw;sf.parent=&hw;hw.callback=true;
 fence_lock=0;hw.lock=&fence_lock;hw.owner=&job.base;
 teardown_warnings=0;ring.sched.ready=true;
 list_add(&job.base.list,&ring.sched.pending_list);
 amdgpu_gpu_recovery=recovery_allowed=1;supported=3;
 config_reads=missing_at=config_error=unplugged=soft_ok=0;dump_hook=stop_hook=config_hook=NULL;
 read_attempts=read_locks=read_unlocks=reset_completions=0;
 reset_pending=reset_during_ring=false;reset_resume_hook=NULL;
 ring_ret=ip_ret=-EIO;recover_ret=0;
 dumps=ring_resets=ip_resets=recovers=enters=exits=0;
 task_gets=task_puts=stops=starts=arms=cancels=frees=free_queues=0;
}
static void timeout(void) {
 ring.sched.work_tdr.pending=false;drm_sched_job_timedout(&ring.sched.work_tdr.work);
 assert(!reset_domain.sem.readers && read_locks==read_unlocks);
}
static void pending_once(void) {
 assert(ring.sched.pending_list.next==&job.base.list);
 assert(ring.sched.pending_list.prev==&job.base.list);
 assert(job.base.list.next==&ring.sched.pending_list);
 assert(job.base.list.prev==&ring.sched.pending_list);
}
static void finish_while_stopping(void) {
 /* Model completion/free work already running when stop waits for it. */
 assert(ring.sched.pause_submit);drm_sched_job_done(&job.base,0);
 struct drm_sched_job *done=drm_sched_get_finished_job(&ring.sched);
 if(done) free_job(done);
 /* A timer queued by in-flight work must also be canceled by the guard. */
 mod_delayed_work(ring.sched.timeout_wq,&ring.sched.work_tdr,13);
}
static void fail_during_dump(void) { drm_sched_job_done(&job.base,-EIO); }
static void finish_during_config_read(void) { drm_sched_job_done(&job.base,0); }
static void resume_after_reset(void) {
 assert(reset_domain.sem.writer && !reset_domain.sem.readers);
 drm_sched_wqueue_start(&ring.sched);
}
static void request_reset_during_config_read(void) {
 assert(reset_domain.sem.readers==1 && !reset_domain.sem.writer);
 reset_pending=true;reset_resume_hook=resume_after_reset;
}
static void finish_parent(struct dma_fence *f,int error) {
 unsigned long flags;
 spin_lock_irqsave(f->lock,flags);dma_fence_set_error(f,error);
 dma_fence_signal_locked(f);spin_unlock_irqrestore(f->lock,flags);
}
static void resume_and_free_after_reset(void) {
 resume_after_reset();finish_parent(&hw,0);
 struct drm_sched_job *done=drm_sched_get_finished_job(&ring.sched);
 assert(done==&job.base);free_job(done);
}
static void request_reset_and_free(void) {
 request_reset_during_config_read();reset_resume_hook=resume_and_free_after_reset;
}
int main(void) {
 setup();dump_hook=fail_during_dump;timeout();
 assert(dumps==1 && !stops && !ring_resets && !ip_resets && !recovers);
 assert(sf.finished.status==-EIO && sf.finished.error==-EIO);
 pending_once();
 /* Completion during an IP dump is a false timeout, including errors. */
 setup();dump_hook=finish_during_config_read;timeout();
 assert(dumps==1 && !stops && !ring_resets && !ip_resets && !recovers);
 assert(sf.finished.status==1 && !sf.finished.error && !ring.sched.pause_submit);
 pending_once();
 struct drm_sched_job *dump_done=drm_sched_get_finished_job(&ring.sched);
 assert(dump_done==&job.base);free_job(dump_done);assert(frees==1);

 /* Parked jobs must be freed on teardown without resuming submission. */
 for(int completed=0;completed<3;completed++) {
  setup();missing_at=1;timeout();
  if(completed) finish_parent(&hw,completed==1 ? 0 : -EIO);
  assert(!ring.sched.work_free_job.queued && !frees);
  drm_sched_fini(&ring.sched);
  assert(frees==1 && list_empty(&ring.sched.pending_list) && !teardown_warnings);
  assert(!ring.sched.ready && ring.sched.pause_submit && !starts && !hw.callback);
  assert(ring.sched.credit_count==0 && ring.sched.score_value==0);
  assert(sf.finished.status==(completed==1 ? 1 : completed==2 ? -EIO : -ECANCELED));
 }
 /* Failed submission: the scheduler already finished it without a parent. */
 setup();sf.parent=NULL;hw.callback=false;drm_sched_job_done(&job.base,-EIO);
 drm_sched_fini(&ring.sched);
 assert(frees==1 && !teardown_warnings && sf.finished.status==-EIO);

 /* Teardown handles a mixed pending list and an already-empty scheduler. */
 setup();missing_at=1;
 struct amdgpu_job tail={0};struct drm_sched_fence tail_sf={0};struct dma_fence tail_hw={0};
 tail.base.sched=&ring.sched;tail.base.s_fence=&tail_sf;tail.base.credits=1;
 tail_sf.sched=&ring.sched;tail_sf.parent=&tail_hw;
 tail_hw.callback=true;tail_hw.owner=&tail.base;tail_hw.lock=&fence_lock;
 INIT_LIST_HEAD(&tail.base.list);list_add(&tail.base.list,&job.base.list);
 ring.sched.credit_count++;ring.sched.score_value++;timeout();finish_parent(&tail_hw,0);
 drm_sched_fini(&ring.sched);
 assert(frees==2 && !teardown_warnings && list_empty(&ring.sched.pending_list));
 assert(sf.finished.status==-ECANCELED && tail_sf.finished.status==1);
 assert(ring.sched.credit_count==0 && ring.sched.score_value==0 && !hw.callback && !tail_hw.callback);
 setup();finish_parent(&hw,0);
 struct drm_sched_job *empty_done=drm_sched_get_finished_job(&ring.sched);
 assert(empty_done==&job.base);free_job(empty_done);drm_sched_fini(&ring.sched);
 assert(frees==1 && !teardown_warnings && list_empty(&ring.sched.pending_list));

 /* AER may resume, complete and free the job as soon as the reader unlocks. */
 setup();missing_at=1;config_hook=request_reset_and_free;timeout();
 assert(frees==1 && !ring.sched.pause_submit && list_empty(&ring.sched.pending_list));
 assert(job.base.s_fence==NULL && job.base.sched==NULL && !ring.sched.work_tdr.pending);

 /* A vanished PF: no dump, MMIO recovery or rearm; job remains owned. */
 setup();missing_at=1;timeout();
 assert(config_reads==1 && !dumps && !ring_resets && !recovers);
 assert(stops==1 && ring.sched.pause_submit && !arms && !frees && cancels==1);
 assert(!ring.sched.work_tdr.pending && !ring.sched.work_run_job.queued && !ring.sched.work_free_job.queued);
 assert(sf.parent==&hw && hw.callback && ring.sched.credit_count==1);pending_once();
 assert(enters==1 && exits==1 && task_gets==task_puts);

 /* A later forced HW completion still reaches the real scheduler done path. */
 drm_sched_job_done(&job.base,-ENODEV);
 assert(sf.finished.status==-ENODEV && ring.sched.credit_count==0 && ring.sched.score_value==0);
 assert(!free_queues && !ring.sched.work_free_job.queued);
 drm_sched_wqueue_start(&ring.sched);
 struct drm_sched_job *done=drm_sched_get_finished_job(&ring.sched);
 assert(done==&job.base);free_job(done);
 assert(frees==1 && list_empty(&ring.sched.pending_list));

 /* A reset that owns the domain must not be waited on or followed by a park. */
 setup();missing_at=1;reset_domain.sem.writer=true;timeout();
 assert(read_attempts==1 && !read_locks && !config_reads && !stops);
 assert(!dumps && !ring_resets && !recovers && !ring.sched.pause_submit);pending_once();

 /* A writer arriving after the failed probe must resume only after parking. */
 setup();missing_at=1;config_hook=request_reset_during_config_read;timeout();
 assert(read_locks==1 && read_unlocks==1 && reset_completions==1 && !reset_pending);
 assert(stops==1 && starts==1 && !ring.sched.pause_submit);
 assert(!dumps && !ring_resets && !recovers && sf.parent==&hw);pending_once();

 /* Drop the read lock before a normal reset, and defer if AER starts later. */
 setup();reset_during_ring=true;timeout();
 assert(config_reads==1 && ring_resets==1 && !recovers && read_attempts==2);
 assert(read_locks==1 && read_unlocks==1 && stops==1 && task_gets==task_puts);pending_once();

 /* Wait for active work before reinserting; do not lose a newly queued timer. */
 setup();missing_at=1;stop_hook=finish_while_stopping;timeout();
 assert(!frees && !job.base.freed && !free_queues && !ring.sched.work_tdr.pending);
 assert(arms==1 && cancels==1 && sf.finished.status==1);pending_once();
 assert(sf.parent==&hw && ring.sched.credit_count==0 && ring.sched.score_value==0);

 /* More than one pending job: preserve order, callbacks and exactly-once cleanup. */
 setup();missing_at=1;
 struct amdgpu_job later={0};struct drm_sched_fence later_sf={0};struct dma_fence later_hw={0};
 later.base.sched=&ring.sched;later.base.s_fence=&later_sf;later.base.credits=1;
 later_sf.sched=&ring.sched;later_sf.parent=&later_hw;later_hw.callback=true;
 INIT_LIST_HEAD(&later.base.list);list_add(&later.base.list,&job.base.list);
 ring.sched.credit_count++;ring.sched.score_value++;timeout();
 assert(ring.sched.pending_list.next==&job.base.list && job.base.list.next==&later.base.list);
 assert(later.base.list.next==&ring.sched.pending_list && ring.sched.pending_list.prev==&later.base.list);
 assert(sf.parent==&hw && later_sf.parent==&later_hw && hw.callback && later_hw.callback);
 assert(!arms && !ring.sched.work_tdr.pending && !free_queues && !frees);
 drm_sched_job_done(&job.base,-ENODEV);drm_sched_job_done(&later.base,-ENODEV);
 assert(!free_queues && ring.sched.credit_count==0 && ring.sched.score_value==0);
 drm_sched_wqueue_start(&ring.sched);
 done=drm_sched_get_finished_job(&ring.sched);assert(done==&job.base);free_job(done);
 done=drm_sched_get_finished_job(&ring.sched);assert(done==&later.base);free_job(done);
 assert(frees==2 && list_empty(&ring.sched.pending_list) && !ring.sched.work_tdr.pending);

 /* PCI config access errors must be handled like all-ones responses. */
 setup();config_error=-EIO;timeout();
 assert(stops==1 && !dumps && !ring_resets && !arms);pending_once();

 /* A completed timeout must not probe or park an otherwise usable queue. */
 setup();missing_at=1;hw.callback=false;drm_sched_job_done(&job.base,0);timeout();
 assert(!config_reads && !stops && !ring.sched.pause_submit && !dumps && !ring_resets && !recovers);
 assert(!frees && !ring.sched.free_guilty && enters==exits);pending_once();
 assert(ring.sched.work_free_job.queued);
 done=drm_sched_get_finished_job(&ring.sched);assert(done==&job.base);free_job(done);
 assert(frees==1 && list_empty(&ring.sched.pending_list));

 /* Completion while the first config read fails must bypass the park too. */
 setup();missing_at=1;config_hook=finish_during_config_read;timeout();
 assert(config_reads==1 && !stops && !ring.sched.pause_submit && !dumps && !ring_resets && !recovers);
 assert(!frees && ring.sched.work_free_job.queued && enters==exits);pending_once();
 done=drm_sched_get_finished_job(&ring.sched);assert(done==&job.base);free_job(done);
 assert(frees==1 && list_empty(&ring.sched.pending_list));

 /* The already-completed fast path also avoids recovery on a present PF/VF. */
 for(int vf=0;vf<2;vf++) {
  for(int failed=0;failed<2;failed++) {
   setup();adev.vf=vf;drm_sched_job_done(&job.base,failed ? -EIO : 0);timeout();
   assert(!config_reads && !stops && !dumps && !ring_resets && !recovers);
   assert(!ring.sched.pause_submit && ring.sched.work_free_job.queued);pending_once();
  }
 }

 /* Link disappears during queue reset: keep the initial dump, skip full reset. */
 setup();missing_at=2;timeout();
 assert(config_reads==2 && dumps==1 && ring_resets==1 && !recovers);
 assert(stops==2 && !arms && task_gets==1 && task_puts==1);pending_once();

 /* A drop inside full recovery is caught before hardware on the next callback. */
 setup();missing_at=3;recover_ret=-ENODEV;timeout();
 assert(recovers==1 && arms==1);pending_once();timeout();
 assert(dumps==1 && ring_resets==1 && recovers==1 && arms==1);
 assert(task_gets==1 && task_puts==1 && enters==exits);pending_once();

 /* Normal success and errors on a present device retain the old retry policy. */
 int results[]={0,-EIO,-ETIME,-EBUSY,-ENODEV};
 for(unsigned i=0;i<sizeof(results)/sizeof(results[0]);i++) {
  setup();recover_ret=results[i];timeout();
  assert(config_reads==2 && dumps==1 && ring_resets==1 && recovers==1);
  assert(stops==1 && arms==1 && !cancels && !frees);pending_once();
  assert(sf.finished.error==-ETIME && task_gets==task_puts && enters==exits);
 }

 /* Successful soft, per-queue and IP reset paths are unchanged. */
 setup();soft_ok=1;timeout();
 assert(config_reads==1 && dumps==1 && !ring_resets && !recovers && arms==1);pending_once();
 setup();ring_ret=0;timeout();
 assert(config_reads==1 && ring_resets==1 && starts==1 && !recovers && arms==1);
 assert(adev.gpu_reset_counter==1);pending_once();
 setup();supported=AMDGPU_RESET_TYPE_IP_BLOCK_SOFT_RESET;ip_ret=0;timeout();
 assert(config_reads==1 && ip_resets==1 && !recovers && arms==1);pending_once();

 /* VF/host FLR behavior must not be replaced with a physical-device verdict. */
 setup();adev.vf=true;missing_at=1;timeout();
 assert(!config_reads && !dumps && ring_resets==1 && recovers==1 && arms==1);pending_once();

 /* Already unplugged remains the original early-exit path. */
 setup();unplugged=1;timeout();
 assert(!config_reads && !dumps && !stops && !arms && !exits);
 puts("PASS: parked-job teardown/cancellation, unlock-time free, completed-job bypass, reset-domain serialization, PCI loss, scheduler ownership, healthy recovery and VF bypass");
 return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='amdgpu-reset-guard-') as temporary:
    path = pathlib.Path(temporary)
    (path / 'test.c').write_text(code)
    subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=undefined',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
