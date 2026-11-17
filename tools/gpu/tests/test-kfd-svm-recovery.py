#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise actual SVM migration accounting, eviction and BO reuse helpers."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / 'work/amdgpu'


def extract(path, signature):
    source = (root / path).read_text()
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


svm = 'drivers/gpu/drm/amd/amdkfd/kfd_svm.c'
migrate = 'drivers/gpu/drm/amd/amdkfd/kfd_migrate.c'
header = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define pr_debug(...) ((void)0)
#define WARN_ONCE(c,...) do { assert(!(c)); } while (0)
struct mutex { bool held; };
static int spin_held;
static void mutex_lock(struct mutex *m) { assert(!m->held);m->held=true; }
static void mutex_unlock(struct mutex *m) { assert(m->held);m->held=false; }
static int mutex_trylock(struct mutex *m) {
    if (m->held) return 0;
    m->held=true;return 1;
}
static void spin_lock(int *m) { (void)m;assert(!spin_held);spin_held=1; }
static void spin_unlock(int *m) { (void)m;assert(spin_held);spin_held=0; }
struct list_head { struct list_head *next,*prev; };
static void init(struct list_head *h) { h->next=h->prev=h; }
static bool list_empty(struct list_head *h) { return h->next==h; }
static bool list_empty_careful(struct list_head *h) { return list_empty(h); }
static void list_del_init(struct list_head *h) {
    h->next->prev=h->prev;h->prev->next=h->next;init(h);
}
static void list_add(struct list_head *h,struct list_head *head) {
    assert(list_empty(h));h->next=head->next;h->prev=head;
    head->next->prev=h;head->next=h;
}
#define list_first_entry(h,t,m) container_of((h)->next,t,m)
'''

accounting = header + r'''
#define PAGE_SHIFT 12
#define GFP_KERNEL 0
#define KFD_MIGRATE_TRIGGER_TTM_EVICTION 0
#define HAVE_MIGRATE_VMA_FAULT_PAGE 1
#define min(a,b) ((a)<(b)?(a):(b))
#define dev_err(...) ((void)0)
#define kfd_smi_event_migration_start(n,t,s,e,a,b,c,d,reason) ((void)(n),(void)(t),(void)(reason))
#define kfd_smi_event_migration_end(n,t,s,e,a,b,reason,result) ((void)(n),(void)(t),(void)(reason))
typedef uint64_t u64;
typedef unsigned long dma_addr_t;
struct device { int unused; };
struct amdgpu_device { struct device *dev; };
struct kfd_node { struct amdgpu_device *adev; };
struct vm_area_struct { unsigned long vm_end; int index; };
struct mm_struct { bool live; };
struct page { int unused; };
struct dma_fence { int unused; };
struct kfd_process { int svms; void *lead_thread; };
struct amdgpu_bo { int unused; };
struct svm_range_bo {
    struct amdgpu_bo bo;struct mm_struct *mm;
    int kref,evicting,list_lock;struct list_head range_list;
};
struct svm_range {
    unsigned long start,last,actual_loc,vram_pages,prefetch_loc,preferred_loc;
    void *ttm_res;int *svms;struct svm_range_bo *svm_bo;
    struct list_head svm_bo_list;struct mutex migrate_mutex,lock;
};
struct kfd_process_device { unsigned long page_out; };
struct migrate_vma {
    struct vm_area_struct *vma;unsigned long start,end,cpages,npages;
    unsigned long *src,*dst;struct page *fault_page;
};
static struct amdgpu_device adev;
static struct kfd_node node={.adev=&adev};
static struct kfd_process process;
static struct kfd_process_device pdd;
static struct vm_area_struct vmas[]={{2UL<<PAGE_SHIFT,0},{4UL<<PAGE_SHIFT,1}};
static unsigned remaining[2],mode,allocations,finalizes,mmrefs,backing_drops;
static int mmap_held;
static unsigned last_moved;
/* Modes: 1 later VMA copy error, 2 allocation failure in later VMA,
 * 3 later VMA missing, 4 copy error with committed progress,
 * 5 setup failure, 6 successful calls without progress,
 * 7 positive DMA mapping error predicate, 0 success. */
static void *kvcalloc(size_t n,size_t size,int flags) {
    (void)flags;allocations++;
    if (mode==2 && allocations==2) return NULL;
    return calloc(n,size);
}
#define kvfree(p) free(p)
static struct vm_area_struct *vma_lookup(struct mm_struct *m,unsigned long addr) {
    (void)m;if (mode==3 && addr>=vmas[0].vm_end) return NULL;
    return addr<vmas[0].vm_end?&vmas[0]:&vmas[1];
}
static struct kfd_node *svm_range_get_node_by_id(struct svm_range *p,unsigned long id)
    { (void)p;(void)id;return &node; }
static struct kfd_process_device *svm_range_get_pdd_by_node(struct svm_range *p,
                                                         struct kfd_node *n)
    { (void)p;(void)n;return &pdd; }
static int migrate_vma_setup(struct migrate_vma *m) {
    if (mode==5) return -EIO;
    m->npages=(m->end-m->start)>>PAGE_SHIFT;
    m->cpages=remaining[m->vma->index];return 0;
}
static int svm_migrate_copy_to_ram(struct amdgpu_device *a,struct svm_range *p,
    struct migrate_vma *m,struct dma_fence **f,dma_addr_t *scratch,u64 n) {
    (void)a;(void)p;(void)f;(void)scratch;(void)n;
    assert(!spin_held && mmap_held && p->migrate_mutex.held);
    if (m->vma->index==1 && mode==7) return 1;
    return (m->vma->index==1 && (mode==1 || mode==4))?-ENOMEM:0;
}
static void migrate_vma_pages(struct migrate_vma *m) {
    unsigned i=m->vma->index;
    last_moved=(mode==6 || (i==1 && (mode==1 || mode==7)))?0:remaining[i];
    remaining[i]-=last_moved;
}
static unsigned long svm_migrate_successful_pages(struct migrate_vma *m)
    { (void)m;return last_moved; }
static void svm_migrate_copy_done(struct amdgpu_device *a,struct dma_fence *f)
    { (void)a;(void)f; }
static void migrate_vma_finalize(struct migrate_vma *m) { (void)m;finalizes++; }
static void svm_range_dma_unmap_dev(struct device *d,dma_addr_t *s,int off,u64 n)
    { (void)d;(void)s;(void)off;(void)n; }
static void svm_range_vram_node_free(struct svm_range *p) {
    assert(p->migrate_mutex.held && !p->vram_pages && p->ttm_res);
    p->ttm_res=NULL;p->svm_bo->kref--;backing_drops++;
    /* Real node-free leaves the BO association for later release cleanup. */
}
#define to_svm_range_bo(p) container_of(p,struct svm_range_bo,bo)
static bool svm_bo_ref_unless_zero(struct svm_range_bo *b)
    { if (!b->kref)return false;b->kref++;return true; }
static int kref_read(int *p) { return *p; }
static void svm_range_bo_unref(struct svm_range_bo *b) { assert(b->kref>0);b->kref--; }
static bool mmget_not_zero(struct mm_struct *m)
    { if (!m->live)return false;mmrefs++;return true; }
static int mmap_read_trylock(struct mm_struct *m)
    { (void)m;assert(!mmap_held);mmap_held=1;return 1; }
static void mmap_read_unlock(struct mm_struct *m)
    { (void)m;assert(mmap_held);mmap_held=0; }
static void mmput_async(struct mm_struct *m) { (void)m;assert(!mmap_held);mmrefs--; }
''' + extract(migrate, 'static int\nsvm_migrate_vma_to_ram(') + extract(
    migrate, 'int svm_migrate_vram_to_ram(') + extract(svm, 'int svm_range_evict_svm_bo(') + r'''
static void setup(struct svm_range *p,struct svm_range_bo *b,struct mm_struct *m) {
    *m=(struct mm_struct){true};*b=(struct svm_range_bo){.mm=m,.kref=1};
    *p=(struct svm_range){.start=0,.last=3,.actual_loc=1,.vram_pages=4,
                         .ttm_res=b,.svms=&process.svms,.svm_bo=b};
    init(&b->range_list);init(&p->svm_bo_list);list_add(&p->svm_bo_list,&b->range_list);
    remaining[0]=remaining[1]=2;pdd.page_out=0;
    allocations=finalizes=backing_drops=mmrefs=0;spin_held=mmap_held=0;
}
int main(void) {
    struct svm_range p;struct svm_range_bo b;struct mm_struct mm;
    for (mode=1;mode<=7;mode++) {
        unsigned fault=mode;setup(&p,&b,&mm);
        int result=svm_range_evict_svm_bo(&b.bo);
        assert(result==(fault==3?-EFAULT:(fault==5 || fault==7)?-EIO:fault==6?-EBUSY:-ENOMEM));
        assert(!mmap_held && !spin_held && !mmrefs && !p.migrate_mutex.held);
        if (fault==4) {
            assert(!remaining[0] && !remaining[1] && pdd.page_out==4);
            assert(!p.vram_pages && !p.actual_loc && !p.ttm_res && !p.svm_bo);
            assert(backing_drops==1 && !b.kref && !b.evicting);
            assert(!svm_range_evict_svm_bo(&b.bo));
        } else {
            unsigned expected=(fault==5 || fault==6)?4:2;
            assert(p.vram_pages==expected && remaining[0]+remaining[1]==expected);
            assert(pdd.page_out==4-expected && p.actual_loc && p.ttm_res);
            assert(p.svm_bo==&b && !list_empty(&p.svm_bo_list));
            assert(b.kref==1 && !b.evicting && !backing_drops);
            mode=0;
            assert(!svm_range_evict_svm_bo(&b.bo));
            assert(!remaining[0] && !remaining[1] && pdd.page_out==4);
            assert(!p.vram_pages && !p.actual_loc && !p.ttm_res && !p.svm_bo);
            assert(list_empty(&b.range_list) && backing_drops==1 && !b.kref);
            mode=fault;
        }
    }
    puts("PASS: actual per-VMA + range migration + eviction compose across partial errors and retries");
}
'''

reuse = header + r'''
struct kfd_node { int unused; };
struct svm_range_bo {
    struct kfd_node *node;int refs,evicting,list_lock;
    struct { struct { void *resource; } tbo; } bo;
};
struct svm_range {
    struct mutex lock;struct svm_range_bo *svm_bo;
    struct list_head svm_bo_list;void *ttm_res;
};
static int acquisitions,drops,yields,action;
static struct svm_range *waiting;
static bool svm_bo_ref_unless_zero(struct svm_range_bo *b) {
    if (!b->refs) return false;
    b->refs++;acquisitions++;return true;
}
static void svm_range_bo_unref(struct svm_range_bo *b) { assert(b->refs>0);b->refs--;drops++; }
static void cond_resched(void) {
    assert(!waiting->lock.held && !spin_held);assert(++yields<8);
    struct svm_range_bo *b=waiting->svm_bo;
    if (action==1) { assert(b->refs==1);b->evicting=0; }
    else if (action==2) {
        /* Final release first unlinks, then clears the association. */
        b->refs=0;list_del_init(&waiting->svm_bo_list);
        if (yields>=2) waiting->svm_bo=NULL;
    } else if (action==3) {
        /* Clearing evicting must never resurrect a zero-reference BO. */
        assert(!b->refs);b->evicting=0;
        if (yields>=2) { list_del_init(&waiting->svm_bo_list);waiting->svm_bo=NULL; }
    } else assert(!"unexpected wait");
}
''' + extract(svm, 'static bool\nsvm_range_validate_svm_bo(') + r'''
static void setup(struct svm_range *p,struct svm_range_bo *b,struct kfd_node *node) {
    *b=(struct svm_range_bo){.node=node,.refs=1};b->bo.tbo.resource=b;
    *p=(struct svm_range){.svm_bo=b};init(&p->svm_bo_list);
    static struct list_head head;init(&head);list_add(&p->svm_bo_list,&head);
    waiting=p;acquisitions=drops=yields=action=0;
}
int main(void) {
    struct kfd_node node,other;struct svm_range_bo b;struct svm_range p;
    setup(&p,&b,&node);p.svm_bo=NULL;
    assert(!svm_range_validate_svm_bo(&node,&p) && !yields && !acquisitions);
    setup(&p,&b,&node);p.ttm_res=&b;
    assert(svm_range_validate_svm_bo(&node,&p) && b.refs==1 && !acquisitions);
    setup(&p,&b,&node);
    assert(svm_range_validate_svm_bo(&node,&p) && p.ttm_res==&b && b.refs==2);
    setup(&p,&b,&node);b.evicting=1;action=1;
    assert(svm_range_validate_svm_bo(&node,&p));
    assert(yields==1 && acquisitions==2 && drops==1 && b.refs==2 && p.ttm_res==&b);
    setup(&p,&b,&node);b.evicting=1;action=2;
    assert(!svm_range_validate_svm_bo(&node,&p));
    assert(yields==2 && !b.refs && acquisitions==1 && drops==1 && !p.ttm_res);
    setup(&p,&b,&node);b.refs=0;b.evicting=1;action=3;
    assert(!svm_range_validate_svm_bo(&node,&p));
    assert(yields==2 && !acquisitions && !drops && !p.svm_bo && !p.ttm_res);
    setup(&p,&b,&other);
    assert(!svm_range_validate_svm_bo(&node,&p));
    assert(list_empty(&p.svm_bo_list) && b.refs==1 && acquisitions==1 && drops==1 && !yields);
    puts("PASS: actual BO reuse recovers after abort, waits for final release and never resurrects zero refs");
}
'''

with tempfile.TemporaryDirectory(prefix='kfd-svm-recovery-') as temp:
    for name, program in [('accounting-eviction', accounting), ('reuse', reuse)]:
        c = Path(temp) / (name + '.c')
        exe = Path(temp) / name
        c.write_text(program)
        subprocess.run([os.environ.get('CC', 'gcc'), '-std=gnu11', '-Wall', '-Wextra',
                        '-Werror', '-Wno-unused-function', '-fsanitize=undefined',
                        '-fno-sanitize-recover=all', str(c), '-o', str(exe)],
                       check=True, timeout=30)
        subprocess.run([str(exe)], check=True, timeout=10)
