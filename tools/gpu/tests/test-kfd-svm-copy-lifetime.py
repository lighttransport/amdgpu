#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile real batch submission, completion and both migration callers."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / 'work/amdgpu'
source = (root / 'drivers/gpu/drm/amd/amdkfd/kfd_migrate.c').read_text()


def extract(signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <setjmp.h>
typedef uint64_t u64;
typedef unsigned long dma_addr_t;
#define PAGE_SIZE 4096
#define PAGE_SHIFT 12
#define GFP_KERNEL 0
#define DMA_BIDIRECTIONAL 0
#define MIGRATE_PFN_VALID 1UL
#define MIGRATE_PFN_MIGRATE 2UL
#define MIGRATE_PFN_LOCKED 4UL
#define HAVE_MIGRATE_VMA_FAULT_PAGE 1
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define WRITE_ONCE(x,v) ((x)=(v))
#define pr_debug(...) ((void)0)
#define pr_debug_ratelimited(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_err_ratelimited(...) ((void)0)
#define kfd_smi_event_migration_start(n,t,s,e,a,b,c,d,reason) ((void)(n),(void)(t),(void)(reason))
#define kfd_smi_event_migration_end(n,t,s,e,a,b,reason,result) ((void)(n),(void)(t),(void)(reason))
struct device { int unused; };
struct mutex { bool held; };
struct drm_sched_entity { int unused; };
struct amdgpu_ttm_buffer_entity { struct mutex lock;struct drm_sched_entity base;u64 gart_window_offs[1]; };
struct amdgpu_ring { struct amdgpu_device *adev; };
struct copy_ops { unsigned copy_num_dw; };
struct amdgpu_device { struct device *dev;int gmc;struct {void *bo;u64 gart_pte_flags;} gart;struct {
    struct copy_ops *buffer_funcs;
    void *buffer_funcs_scheds[1];struct amdgpu_ttm_buffer_entity move_entities[1];
} mman; };
struct kfd_node { struct amdgpu_device *adev; };
struct kfd_process { int svms;void *lead_thread; };
struct kfd_process_device { unsigned long page_out,page_in; };
struct svm_range { int *svms;unsigned long start,last,prefetch_loc,preferred_loc;void *ttm_res; };
struct page { unsigned pfn,refs;bool zone,locked,mapped,cpu; };
struct vm_area_struct { int unused; };
struct migrate_vma {
    unsigned long *src,*dst,start,end,npages,cpages;
    struct vm_area_struct *vma;struct page *fault_page;
};
struct dma_fence { unsigned seq,refs;int error;bool mapping,signaled; };
struct mock_ib { u64 gpu_addr;unsigned length_dw;uint32_t *ptr; };
struct amdgpu_job { struct mock_ib ibs[1]; };
enum MIGRATION_COPY_DIR { FROM_VRAM_TO_RAM,FROM_RAM_TO_VRAM };
struct amdgpu_res_cursor { u64 start,size; };
static struct page pages[256];
static struct dma_fence fences[16];
static struct dma_fence map_fences[16];
static struct amdgpu_device *active_adev;
static struct copy_ops copy_ops={8};
static struct kfd_process process;
static struct kfd_process_device pdd;
static unsigned allocs,maps,submits,completed,waits,fence_puts,sleeps,unmaps,frees,finalizes;
static unsigned fail_alloc,fail_map,fail_submit;
static bool immediate,wait_faults,hold_forever,vram_mode;
static unsigned vram_allocs;
static jmp_buf retained_wait;
static void *buffer;
static unsigned page_count;
static unsigned completion_error,commit_calls,submit_attempts;
static unsigned restored_pages;
static int completion_errno;
static bool expect_failure,contiguous;
static unsigned map_submits,map_waits,map_puts,map_status_queries,map_allocs;
static unsigned map_completion_error,fail_map_job_alloc;
static bool map_immediate,map_wait_faults,map_hold_forever,waiting_mapping,window_checked;
#define AMDGPU_GTT_MAX_TRANSFER_SIZE PAGE_SIZE
#define KFD_IOCTL_SVM_FLAG_GPU_RO 1
#define min(a,b) ((a)<(b)?(a):(b))
#define ALIGN(v,a) (((v)+(a)-1)&~((a)-1))
#define AMDGPU_GPU_PAGES_IN_CPU_PAGE 1
#define AMDGPU_GPU_PAGE_SHIFT PAGE_SHIFT
#define AMDGPU_FENCE_OWNER_UNDEFINED 0
#define AMDGPU_IB_POOL_DELAYED 0
#define AMDGPU_KERNEL_JOB_ID_KFD_GART_MAP 0
#define AMDGPU_PTE_VALID 1
#define AMDGPU_PTE_READABLE 2
#define AMDGPU_PTE_SYSTEM 4
#define AMDGPU_PTE_SNOOPED 8
#define AMDGPU_PTE_WRITEABLE 16
#define WARN_ON(c) assert(!(c))
#define lockdep_assert_held(m) assert((m)->held)
static int entity_held;
static void mutex_lock(struct mutex *m) { assert(!m->held && !entity_held);m->held=true;entity_held=1; }
static void mutex_unlock(struct mutex *m) { assert(m->held && entity_held);m->held=false;entity_held=0; }
static bool mutex_trylock(struct mutex *m) { if(m->held)return false;mutex_lock(m);return true; }
static struct amdgpu_ring *to_amdgpu_ring(void *s) {
    (void)s;static struct amdgpu_ring ring;ring.adev=active_adev;return &ring;
}
static u64 svm_migrate_direct_mapping_addr(struct amdgpu_device *a,u64 addr) { (void)a;return addr; }
static u64 amdgpu_compute_gart_address(int *g,struct amdgpu_ttm_buffer_entity *e,int i)
    { (void)g;(void)e;(void)i;return 0x10000; }
static int amdgpu_job_alloc_with_ib(struct amdgpu_device *a,struct drm_sched_entity *e,
    int owner,unsigned size,int pool,int id,struct amdgpu_job **out) {
    (void)a;(void)e;(void)owner;(void)size;(void)pool;(void)id;map_allocs++;
    if(map_allocs==fail_map_job_alloc)return -ENOMEM;
    static uint32_t words[64];static struct amdgpu_job job;
    memset(&job,0,sizeof(job));job.ibs[0].ptr=words;*out=&job;return 0;
}
static u64 amdgpu_bo_gpu_offset(void *p) { (void)p;return 0x20000; }
static void amdgpu_emit_copy_buffer(struct amdgpu_device *a,struct mock_ib *ib,u64 s,u64 d,unsigned n,int f)
    { (void)a;(void)ib;(void)s;(void)d;(void)n;(void)f; }
static void amdgpu_ring_pad_ib(struct amdgpu_ring *r,struct mock_ib *ib) { (void)r;(void)ib; }
static void amdgpu_gart_map(struct amdgpu_device *a,int off,u64 n,dma_addr_t *p,u64 flags,void *cpu)
    { (void)a;(void)off;(void)n;(void)p;(void)flags;(void)cpu; }
static struct dma_fence *amdgpu_job_submit(struct amdgpu_job *j) {
    (void)j;assert(entity_held && map_submits+1<16);map_submits++;window_checked=false;
    map_fences[map_submits]=(struct dma_fence){.seq=map_submits,.refs=1,.mapping=true,
        .signaled=map_immediate,.error=map_submits==map_completion_error?completion_errno:0};
    return &map_fences[map_submits];
}
static bool pending(void) { return completed<submits; }
static unsigned long migrate_pfn(unsigned long pfn) { return (pfn<<6)|MIGRATE_PFN_VALID; }
static struct page *migrate_pfn_to_page(unsigned long entry)
    { return (entry&MIGRATE_PFN_VALID)?&pages[entry>>6]:NULL; }
static bool is_zone_device_page(struct page *p) { return p->zone; }
static unsigned long page_to_pfn(struct page *p) { return p->pfn; }
static unsigned long svm_migrate_addr(struct amdgpu_device *a,struct page *p)
    { (void)a;return p->pfn*PAGE_SIZE; }
static unsigned long svm_migrate_addr_to_pfn(struct amdgpu_device *a,unsigned long addr)
    { (void)a;return 150+addr/PAGE_SIZE; }
static void svm_migrate_get_vram_page(struct svm_range *r,unsigned long pfn) {
    (void)r;assert(pfn<256);vram_allocs++;
    pages[pfn]=(struct page){.pfn=pfn,.refs=1,.zone=true,.locked=true};
}
static void amdgpu_res_first(void *res,u64 off,u64 length,struct amdgpu_res_cursor *c)
    { (void)res;(void)length;c->start=off;c->size=PAGE_SIZE; }
static void amdgpu_res_next(struct amdgpu_res_cursor *c,u64 n) { c->start+=n; }
static void *kvcalloc(size_t n,size_t size,int flags) {
    (void)flags;buffer=calloc(n,size);return buffer;
}
#define kvfree(p) free(p)
static struct page *svm_migrate_get_sys_page(struct vm_area_struct *v,u64 addr) {
    (void)v;(void)addr;allocs++;
    if(allocs==fail_alloc)return NULL;
    pages[100+allocs]=(struct page){.pfn=100+allocs,.refs=1,.locked=true};
    return &pages[100+allocs];
}
static dma_addr_t dma_map_page(struct device *d,struct page *p,int off,int size,int dir) {
    (void)d;(void)off;(void)size;(void)dir;maps++;
    if(maps==fail_map)return 0;
    assert(p->refs && p->locked);p->mapped=true;return p->pfn*PAGE_SIZE;
}
static int dma_mapping_error(struct device *d,dma_addr_t addr) { (void)d;return !addr; }
static void dma_unmap_page(struct device *d,dma_addr_t addr,int size,int dir) {
    (void)d;(void)size;(void)dir;assert(!pending());
    struct page *p=&pages[addr/PAGE_SIZE];assert(p->mapped);p->mapped=false;unmaps++;
}
static void unlock_page(struct page *p) { assert(!pending() && p->locked);p->locked=false; }
static void put_page(struct page *p) {
    assert(!pending() && p->refs && !p->locked && !p->mapped);
    p->refs--;if(!p->refs)frees++;
}
static void svm_migrate_put_vram_page(struct amdgpu_device *a,unsigned long addr) {
    struct page *p=&pages[svm_migrate_addr_to_pfn(a,addr)];unlock_page(p);put_page(p);
}
static bool dma_fence_is_signaled(struct dma_fence *f) {
    assert(f->refs);return f->mapping?f->signaled:completed>=f->seq;
}
static int dma_fence_wait(struct dma_fence *f,bool intr) {
    if(f->mapping) {
        assert(entity_held && f->refs && !intr && ++map_waits<16);waiting_mapping=true;
        /* A competing client cannot replace this window during completion. */
        assert(!mutex_trylock(&active_adev->mman.move_entities[0].lock));
        if(map_hold_forever)return -EIO;
        if(map_wait_faults && map_waits==1)return -EIO;
        if(map_wait_faults && map_waits==2)return 0;
        f->signaled=true;waiting_mapping=false;return 0;
    }
    assert(!entity_held && f->refs && !intr && ++waits<16);
    if(hold_forever)return -EIO;
    if(wait_faults && waits==1)return -EIO;
    if(wait_faults && waits==2)return 0; /* Spurious success is not a drain. */
    completed=f->seq;return 0;
}
static int dma_fence_get_status(struct dma_fence *f) {
    if(f->mapping) {
        assert(entity_held && f->refs && f->signaled);map_status_queries++;
        window_checked=!f->error;waiting_mapping=false;return f->error?f->error:1;
    }
    assert(!entity_held && f->refs && completed>=f->seq);return f->error?f->error:1;
}
static void dma_fence_put(struct dma_fence *f) {
    assert(f && f->refs);f->refs--;
    if(f->mapping){assert(f->signaled);map_puts++;}else fence_puts++;
}
static void msleep(unsigned ms) {
    assert(ms==20 && (pending() || waiting_mapping));sleeps++;
    /* Every allocated page and successful DMA mapping must still be owned. */
    for(unsigned i=1;i<=allocs;i++) {
        struct page *p=&pages[100+i];
        if(i==fail_alloc)continue;
        assert(p->refs==1 && p->locked);
        if(i<=maps && i!=fail_map)assert(p->mapped);
    }
    if(vram_mode) {
        for(unsigned i=0;i<vram_allocs;i++)assert(pages[150+i].refs==1 && pages[150+i].locked);
        for(unsigned i=0;i<maps;i++)if(i+1!=fail_map)assert(pages[2+2*i].mapped);
    }
    if((hold_forever || map_hold_forever) && sleeps==3)longjmp(retained_wait,1);
}
static int amdgpu_copy_buffer(struct amdgpu_device *a,struct amdgpu_ttm_buffer_entity *e,
    u64 from,u64 to,u64 bytes,void *resv,struct dma_fence **f,bool direct,u64 flags) {
    (void)a;(void)e;(void)from;(void)to;(void)resv;(void)direct;(void)flags;
    assert(entity_held && bytes==PAGE_SIZE);
    assert(window_checked && map_submits && !map_fences[map_submits].error);
    assert(map_fences[map_submits].signaled && !map_fences[map_submits].refs);
    unsigned call=++submit_attempts;
    if(call==fail_submit)return -ENOMEM;
    submits++;assert(submits<16);
    fences[submits]=(struct dma_fence){.seq=submits,.refs=1,.error=submits==completion_error?completion_errno:0};
    *f=&fences[submits];
    if(immediate)completed=submits;
    return 0;
}
static int migrate_vma_setup(struct migrate_vma *m) {
    m->npages=page_count;m->cpages=page_count;
    for(unsigned i=0;i<page_count;i++) {
        unsigned pfn=2+(contiguous?i:2*i);
        pages[pfn]=(struct page){.pfn=pfn,.zone=!vram_mode,.refs=1,.locked=true};
        m->src[i]=migrate_pfn(pfn)|MIGRATE_PFN_MIGRATE;
    }
    return 0;
}
static void migrate_vma_pages(struct migrate_vma *m) {
    (void)m;assert(!pending() && !expect_failure);commit_calls++;
}
static void migrate_vma_finalize(struct migrate_vma *m) {
    assert(!pending());finalizes++;
    if(expect_failure) {
        for(unsigned i=0;i<page_count;i++)assert(!m->dst[i]);
        restored_pages=page_count; /* Missing destinations restore source PTEs. */
    }
    for(unsigned i=0;i<page_count;i++) {
        struct page *p=migrate_pfn_to_page(m->dst[i]);
        if(p){assert(p->refs==1 && p->locked);p->cpu=true;p->locked=false;}
    }
}
static void svm_range_dma_unmap_dev(struct device *d,dma_addr_t *s,unsigned off,u64 n) {
    assert(!pending());
    for(unsigned i=off;i<off+n;i++)if(s[i]){dma_unmap_page(d,s[i],PAGE_SIZE,0);s[i]=0;}
}
static struct kfd_process_device *svm_range_get_pdd_by_node(struct svm_range *p,struct kfd_node *n)
    { (void)p;(void)n;return &pdd; }
''' + extract('static int\nsvm_migrate_copy_done(') + extract(
    'static int\nsvm_migrate_gart_map(') + extract(
    'static int\nsvm_migrate_copy_memory_gart(') + extract(
    'static unsigned long svm_migrate_successful_pages(') + extract(
    'static int\nsvm_migrate_copy_to_ram(') + extract(
    'static int\nsvm_migrate_vma_to_ram(') + extract(
    'static int\nsvm_migrate_copy_to_vram(') + r'''
static bool svm_range_window_resident(struct kfd_node *n,struct svm_range *r,u64 s,u64 e)
    { (void)n;(void)r;(void)s;(void)e;return false; }
''' + extract('static long\nsvm_migrate_vma_to_vram(') + r'''
static void reset(void) {
    memset(pages,0,sizeof(pages));memset(fences,0,sizeof(fences));
    allocs=maps=submits=completed=waits=fence_puts=sleeps=unmaps=frees=finalizes=0;
    fail_alloc=fail_map=fail_submit=0;
    immediate=wait_faults=hold_forever=vram_mode=false;vram_allocs=0;
    page_count=3;pdd.page_out=0;
    pdd.page_in=completion_error=commit_calls=submit_attempts=0;
    restored_pages=0;completion_errno=-EIO;
    expect_failure=contiguous=false;entity_held=0;
    memset(map_fences,0,sizeof(map_fences));
    map_submits=map_waits=map_puts=map_status_queries=map_allocs=0;
    map_completion_error=fail_map_job_alloc=0;
    map_immediate=map_wait_faults=map_hold_forever=waiting_mapping=window_checked=false;
}
static void run(int expected) {
    expect_failure=expected!=0;
    struct device dev={0};struct amdgpu_device adev={.dev=&dev};
    active_adev=&adev;adev.mman.buffer_funcs=&copy_ops;
    struct kfd_node node={.adev=&adev};struct vm_area_struct vma={0};
    struct svm_range range={.svms=&process.svms,.last=page_count-1};
    unsigned long migrated=999;
    int r=svm_migrate_vma_to_ram(&node,&range,&vma,0,page_count*PAGE_SIZE,0,NULL,&migrated);
    assert(r==expected && !pending() && finalizes==1 && fence_puts==submits && !entity_held);
    assert(map_puts==map_submits && map_status_queries==map_submits);
    for(unsigned i=1;i<=map_submits;i++)assert(!map_fences[i].refs);
    for(unsigned i=1;i<=submits;i++)assert(!fences[i].refs);
    for(unsigned i=1;i<=allocs;i++)assert(!pages[100+i].mapped);
    if(expected) {
        assert(!migrated && !pdd.page_out && !commit_calls && restored_pages==page_count);
        for(unsigned i=1;i<=allocs;i++)assert(!pages[100+i].refs && !pages[100+i].locked);
    } else {
        assert(migrated==page_count && pdd.page_out==page_count && commit_calls==1);
        for(unsigned i=1;i<=allocs;i++)assert(pages[100+i].refs==1 && pages[100+i].cpu);
    }
}
static void run_vram(int expected) {
    vram_mode=true;expect_failure=expected!=0;
    struct device dev={0};struct amdgpu_device adev={.dev=&dev};
    active_adev=&adev;adev.mman.buffer_funcs=&copy_ops;
    struct kfd_node node={.adev=&adev};struct svm_range range={0};
    struct vm_area_struct vma={0};range.svms=&process.svms;range.last=2;
    long r=svm_migrate_vma_to_vram(&node,&range,&vma,0,3*PAGE_SIZE,0,0);
    assert(r==(expected?expected:3) && !pending() && fence_puts==submits && finalizes==1);
    assert(commit_calls==(expected?0U:1U) && pdd.page_in==(expected?0UL:3UL));
    assert(restored_pages==(expected?page_count:0));
    assert(map_puts==map_submits && map_status_queries==map_submits && !entity_held);
    for(unsigned i=0;i<vram_allocs;i++) {
        if(expected)assert(!pages[150+i].refs);
        else assert(pages[150+i].refs==1 && !pages[150+i].locked);
    }
}
int main(void) {
    reset();run(0);assert(submits==3 && waits==3);
    reset();fail_alloc=2;run(-ENOMEM); /* Baseline must fail the actual pending-DMA assertion. */
    reset();immediate=true;run(0);
    reset();wait_faults=true;run(0);assert(waits==5 && sleeps==2);
    for(unsigned at=1;at<=3;at++) {
        reset();fail_alloc=at;run(-ENOMEM);assert(submits==at-1);
        reset();fail_map=at;run(-EIO);assert(submits==at-1);
        reset();fail_submit=at;run(-ENOMEM);assert(submits==at-1);
    }
    reset();fail_alloc=3;wait_faults=true;run(-ENOMEM);
    assert(submits==2 && waits==4 && sleeps==2);
    reset();fail_map=3;wait_faults=true;run(-EIO);
    assert(submits==2 && waits==4 && sleeps==2);
    reset();contiguous=true;fail_submit=3;run(-ENOMEM);assert(submits==2);
    reset();fail_alloc=3;immediate=true;run(-ENOMEM);
    reset();run_vram(0);
    reset();wait_faults=true;run_vram(0);assert(waits==5 && sleeps==2);
    for(unsigned at=1;at<=3;at++) {
        reset();fail_map=at;run_vram(-EIO);
        reset();fail_submit=at;run_vram(-ENOMEM);
    }
    reset();fail_map=3;wait_faults=true;run_vram(-EIO);assert(sleeps==2);
    for(unsigned at=1;at<=3;at++)for(unsigned pre=0;pre<2;pre++)for(unsigned err=0;err<2;err++) {
        int status=err?-ECANCELED:-EIO;
        reset();completion_error=at;completion_errno=status;immediate=pre;
        run(status);assert(submits==at);
        reset();completion_error=at;completion_errno=status;immediate=pre;
        run_vram(status);assert(submits==at);
        reset();contiguous=true;completion_error=at;completion_errno=status;immediate=pre;
        run(status);assert(submits==at);
    }
    reset();fail_alloc=3;completion_error=2;completion_errno=-ECANCELED;run(-ENOMEM);
    for(unsigned at=1;at<=3;at++)for(unsigned pre=0;pre<2;pre++)for(unsigned err=0;err<2;err++) {
        int status=err?-ECANCELED:-EIO;
        reset();map_completion_error=at;map_immediate=pre;completion_errno=status;
        run(status);assert(submits==at-1 && map_submits==at);
        reset();map_completion_error=at;map_immediate=pre;completion_errno=status;
        run_vram(status);assert(submits==at-1 && map_submits==at);
        reset();contiguous=true;map_completion_error=at;map_immediate=pre;completion_errno=status;
        run(status);assert(submits==at-1 && map_submits==at);
    }
    for(unsigned at=1;at<=3;at++) {
        reset();fail_map_job_alloc=at;run(-ENOMEM);assert(map_submits==at-1 && submits==at-1);
        reset();fail_map_job_alloc=at;run_vram(-ENOMEM);assert(map_submits==at-1 && submits==at-1);
    }
    reset();map_wait_faults=true;run(0);assert(sleeps==2);
    reset();map_wait_faults=true;run_vram(0);assert(sleeps==2);
    reset();fail_alloc=3;hold_forever=true;
    if(!setjmp(retained_wait)) {
        run(-ENOMEM);assert(!"permanently pending fence unexpectedly returned");
    }
    assert(pending() && submits==1 && fences[1].refs==1);
    assert(!unmaps && !frees && !finalizes && sleeps==3);
    assert(pages[101].refs==1 && pages[102].refs==1);
    free(buffer); /* Harness exits the modeled blocked call after verifying retention. */
    reset();fail_map=3;hold_forever=true;
    if(!setjmp(retained_wait)) {
        run_vram(-EIO);assert(!"permanently pending VRAM fence unexpectedly returned");
    }
    assert(pending() && submits==1 && fences[1].refs==1 && vram_allocs==2);
    assert(!unmaps && !frees && sleeps==3);
    for(unsigned i=0;i<vram_allocs;i++)assert(pages[150+i].refs==1 && pages[150+i].locked);
    reset();map_hold_forever=true;
    if(!setjmp(retained_wait)) { run(-EIO);assert(!"pending mapping unexpectedly returned"); }
    assert(entity_held && !submits && map_submits==1 && map_fences[1].refs==1);
    assert(!frees && !unmaps && !commit_calls && !finalizes && sleeps==3);
    free(buffer);
    puts("PASS: actual GART/data producers and both callers validate mapping/copy outcomes, preserve window ownership and retain pending backing");
}
'''

with tempfile.TemporaryDirectory(prefix='svm-copy-lifetime-') as temp:
    c = Path(temp) / 'test.c'
    exe = Path(temp) / 'test'
    c.write_text(program)
    subprocess.run([os.environ.get('CC', 'gcc'), '-std=gnu11', '-Wall', '-Wextra',
                    '-Werror', '-Wno-unused-parameter', '-Wno-unused-function', '-fsanitize=undefined',
                    '-fno-sanitize-recover=all', str(c), '-o', str(exe)],
                   check=True, timeout=30)
    subprocess.run([str(exe)], check=True, timeout=10)
