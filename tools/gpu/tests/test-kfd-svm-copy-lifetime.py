#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile the real copy producer, completion wait and per-VMA caller together."""
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
struct amdgpu_device { struct device *dev; };
struct kfd_node { struct amdgpu_device *adev; };
struct kfd_process { int svms;void *lead_thread; };
struct kfd_process_device { unsigned long page_out; };
struct svm_range { int *svms;unsigned long start,last,prefetch_loc,preferred_loc;void *ttm_res; };
struct page { unsigned pfn,refs;bool zone,locked,mapped,cpu; };
struct vm_area_struct { int unused; };
struct migrate_vma {
    unsigned long *src,*dst,start,end,npages,cpages;
    struct vm_area_struct *vma;struct page *fault_page;
};
struct dma_fence { unsigned seq,refs; };
enum MIGRATION_COPY_DIR { FROM_VRAM_TO_RAM,FROM_RAM_TO_VRAM };
struct amdgpu_res_cursor { u64 start,size; };
static struct page pages[256];
static struct dma_fence fences[16];
static struct kfd_process process;
static struct kfd_process_device pdd;
static unsigned allocs,maps,submits,completed,waits,fence_puts,sleeps,unmaps,frees,finalizes;
static unsigned fail_alloc,fail_map,fail_submit;
static bool partial_submit_failure,immediate,wait_faults,hold_forever,vram_mode;
static unsigned vram_allocs;
static jmp_buf retained_wait;
static void *buffer;
static unsigned page_count;
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
static bool dma_fence_is_signaled(struct dma_fence *f) { assert(f->refs);return completed>=f->seq; }
static int dma_fence_wait(struct dma_fence *f,bool intr) {
    assert(f->refs && !intr && ++waits<10);
    if(hold_forever)return -EIO;
    if(wait_faults && waits==1)return -EIO;
    if(wait_faults && waits==2)return 0; /* Spurious success is not a drain. */
    completed=f->seq;return 0;
}
static void dma_fence_put(struct dma_fence *f) { assert(f && f->refs);f->refs--;fence_puts++; }
static void msleep(unsigned ms) {
    assert(ms==20 && pending());sleeps++;
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
    if(hold_forever && sleeps==3)longjmp(retained_wait,1);
}
static int svm_migrate_copy_memory_gart(struct amdgpu_device *a,dma_addr_t *sys,
    u64 *vram,u64 n,enum MIGRATION_COPY_DIR dir,struct dma_fence **f) {
    (void)a;(void)vram;(void)dir;assert(n==1 && *sys);
    unsigned call=submits+1;
    if(call==fail_submit && !partial_submit_failure)return -ENOMEM;
    if(*f)dma_fence_put(*f); /* Replacement fence covers the same ordered queue. */
    submits++;assert(submits<16);
    fences[submits]=(struct dma_fence){.seq=submits,.refs=1};*f=&fences[submits];
    if(immediate)completed=submits;
    return call==fail_submit?-ENOMEM:0;
}
static int migrate_vma_setup(struct migrate_vma *m) {
    m->npages=page_count;m->cpages=page_count;
    for(unsigned i=0;i<page_count;i++) {
        unsigned pfn=2+2*i;pages[pfn]=(struct page){.pfn=pfn,.zone=true};
        m->src[i]=migrate_pfn(pfn)|MIGRATE_PFN_MIGRATE;
    }
    return 0;
}
static void migrate_vma_pages(struct migrate_vma *m) { (void)m; }
static void migrate_vma_finalize(struct migrate_vma *m) {
    assert(!pending());finalizes++;
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
    'static unsigned long svm_migrate_successful_pages(') + extract(
    'static int\nsvm_migrate_copy_to_ram(') + extract(
    'static int\nsvm_migrate_vma_to_ram(') + extract(
    'static int\nsvm_migrate_copy_to_vram(') + r'''
static void reset(void) {
    memset(pages,0,sizeof(pages));memset(fences,0,sizeof(fences));
    allocs=maps=submits=completed=waits=fence_puts=sleeps=unmaps=frees=finalizes=0;
    fail_alloc=fail_map=fail_submit=0;
    partial_submit_failure=immediate=wait_faults=hold_forever=vram_mode=false;vram_allocs=0;
    page_count=3;pdd.page_out=0;
}
static void run(int expected) {
    struct device dev={0};struct amdgpu_device adev={.dev=&dev};
    struct kfd_node node={.adev=&adev};struct vm_area_struct vma={0};
    struct svm_range range={.svms=&process.svms,.last=page_count-1};
    unsigned long migrated=999;
    int r=svm_migrate_vma_to_ram(&node,&range,&vma,0,page_count*PAGE_SIZE,0,NULL,&migrated);
    assert(r==expected && !pending() && finalizes==1 && fence_puts==submits);
    for(unsigned i=1;i<=submits;i++)assert(!fences[i].refs);
    for(unsigned i=1;i<=allocs;i++)assert(!pages[100+i].mapped);
    if(expected) {
        assert(!migrated && !pdd.page_out);
        for(unsigned i=1;i<=allocs;i++)assert(!pages[100+i].refs && !pages[100+i].locked);
    } else {
        assert(migrated==page_count && pdd.page_out==page_count);
        for(unsigned i=1;i<=allocs;i++)assert(pages[100+i].refs==1 && pages[100+i].cpu);
    }
}
static void run_vram(int expected) {
    vram_mode=true;
    struct device dev={0};struct amdgpu_device adev={.dev=&dev};
    struct kfd_node node={.adev=&adev};struct svm_range range={0};
    unsigned long src[3],dst[3]={0};dma_addr_t scratch[6]={0};struct dma_fence *last=NULL;
    struct migrate_vma m={.src=src,.dst=dst,.npages=3,.cpages=3};
    for(unsigned i=0;i<3;i++) {
        unsigned pfn=2+2*i;pages[pfn]=(struct page){.pfn=pfn,.refs=1,.locked=true};
        src[i]=migrate_pfn(pfn)|MIGRATE_PFN_MIGRATE;
    }
    assert(svm_migrate_copy_to_vram(&node,&range,&m,&last,scratch,0)==expected);
    if(expected)assert(!last); /* Producer consumed its error-path fence. */
    svm_migrate_copy_done(&adev,last); /* Same fence ownership convention as the caller. */
    assert(!pending() && fence_puts==submits);
    for(unsigned i=0;i<vram_allocs;i++) {
        if(expected)assert(!pages[150+i].refs && !dst[i]);
        else svm_migrate_put_vram_page(&adev,i*PAGE_SIZE);
    }
    for(unsigned i=0;i<3;i++) {
        if(scratch[i])dma_unmap_page(&dev,scratch[i],PAGE_SIZE,0);
        unlock_page(&pages[2+2*i]);put_page(&pages[2+2*i]);
    }
}
int main(void) {
    reset();run(0);assert(submits==3 && waits==1);
    reset();fail_alloc=2;run(-ENOMEM); /* Baseline must fail the actual pending-DMA assertion. */
    reset();immediate=true;run(0);
    reset();wait_faults=true;run(0);assert(waits==3 && sleeps==2);
    for(unsigned at=1;at<=3;at++) {
        reset();fail_alloc=at;run(-ENOMEM);assert(submits==at-1);
        reset();fail_map=at;run(-EIO);assert(submits==at-1);
        reset();fail_submit=at;run(-ENOMEM);assert(submits==at-1);
        reset();fail_submit=at;partial_submit_failure=true;run(-ENOMEM);assert(submits==at);
    }
    reset();fail_alloc=3;wait_faults=true;run(-ENOMEM);
    assert(submits==2 && waits==3 && sleeps==2);
    reset();fail_map=3;wait_faults=true;run(-EIO);
    assert(submits==2 && waits==3 && sleeps==2);
    reset();fail_submit=3;partial_submit_failure=true;wait_faults=true;run(-ENOMEM);
    assert(submits==3 && waits==3 && sleeps==2);
    reset();fail_alloc=3;immediate=true;run(-ENOMEM);
    reset();run_vram(0);
    reset();wait_faults=true;run_vram(0);assert(waits==3 && sleeps==2);
    for(unsigned at=1;at<=3;at++) {
        reset();fail_map=at;run_vram(-EIO);
        reset();fail_submit=at;run_vram(-ENOMEM);
        reset();fail_submit=at;partial_submit_failure=true;run_vram(-ENOMEM);
    }
    reset();fail_map=3;wait_faults=true;run_vram(-EIO);assert(sleeps==2);
    reset();fail_alloc=3;hold_forever=true;
    if(!setjmp(retained_wait)) {
        run(-ENOMEM);assert(!"permanently pending fence unexpectedly returned");
    }
    assert(pending() && submits==2 && fences[2].refs==1);
    assert(!unmaps && !frees && !finalizes && sleeps==3);
    assert(pages[101].refs==1 && pages[102].refs==1);
    free(buffer); /* Harness exits the modeled blocked call after verifying retention. */
    reset();fail_map=3;hold_forever=true;
    if(!setjmp(retained_wait)) {
        run_vram(-EIO);assert(!"permanently pending VRAM fence unexpectedly returned");
    }
    assert(pending() && submits==2 && fences[2].refs==1 && vram_allocs==3);
    assert(!unmaps && !frees && sleeps==3);
    for(unsigned i=0;i<3;i++)assert(pages[150+i].refs==1 && pages[150+i].locked);
    puts("PASS: both actual copy producers drain before cleanup; allocation/map/partial/final errors, wait failures, permanent retention and fence ownership");
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
