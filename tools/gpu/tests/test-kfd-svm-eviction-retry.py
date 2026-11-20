#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile the real SVM BO eviction callback with fault-injected migration."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / 'work/amdgpu'
source = (root / 'drivers/gpu/drm/amd/amdkfd/kfd_svm.c').read_text()
start = source.index('int svm_range_evict_svm_bo(')
end = source.index('\nstatic bool svm_range_needs_unmap', start)
callback = source[start:end]
free_body = source.split('static void svm_range_free(', 1)[1]
free_body = free_body[free_body.index('\tpr_debug("svms'):]
free_body = free_body.split('prange->start, prange->last);', 1)[1]
free_body = free_body.split('\n\tif (do_unmap)\n', 1)[0]
program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <stdio.h>
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
struct list_head { struct list_head *next, *prev; };
static void init(struct list_head *h) { h->next = h->prev = h; }
static bool list_empty(struct list_head *h) { return h->next == h; }
static void list_del_init(struct list_head *h) {
    h->next->prev = h->prev; h->prev->next = h->next; init(h);
}
static void list_add(struct list_head *h, struct list_head *head) {
    assert(list_empty(h));
    h->next = head->next; h->prev = head;
    head->next->prev = h; head->next = h;
}
#define list_first_entry(h, t, m) container_of((h)->next, t, m)
struct mutex { bool held; };
static int spin_held, mmap_held, mmrefs, unrefs, calls, warnings;
static void spin_lock(int *p) { (void)p; assert(!spin_held); spin_held = 1; }
static void spin_unlock(int *p) { (void)p; assert(spin_held); spin_held = 0; }
static int mutex_trylock(struct mutex *p) {
    if (p->held) return 0;
    p->held = true; return 1;
}
static void complete_inflight_eviction(void);
static bool free_wait;
static void mutex_lock(struct mutex *p) {
    if (free_wait) { free_wait = false; complete_inflight_eviction(); }
    assert(!p->held); p->held = true;
}
static void mutex_unlock(struct mutex *p) { assert(p->held); p->held = false; }
struct mm_struct { bool live, available; };
struct amdgpu_bo { int unused; };
struct svm_range_bo {
    struct amdgpu_bo bo; struct mm_struct *mm;
    int kref, evicting, list_lock; struct list_head range_list;
};
struct svm_range {
    struct list_head svm_bo_list; struct mutex migrate_mutex, lock;
    struct svm_range_bo *svm_bo; unsigned long actual_loc, start, last;
    int mode, attempts;
};
#define to_svm_range_bo(p) container_of(p, struct svm_range_bo, bo)
#define WRITE_ONCE(x, v) ((x) = (v))
#define pr_debug(...) ((void)0)
#define pr_info_once(...) ((void)0)
#define WARN_ONCE(c, ...) do { if (c) warnings++; } while (0)
#define KFD_MIGRATE_TRIGGER_TTM_EVICTION 0
static int kref_read(int *p) { return *p; }
static bool svm_bo_ref_unless_zero(struct svm_range_bo *b) {
    if (!b->kref) return false;
    b->kref++; return true;
}
static void svm_range_bo_unref(struct svm_range_bo *b) { b->kref--; unrefs++; }
static bool mmget_not_zero(struct mm_struct *m) {
    if (!m->live) return false;
    mmrefs++; return true;
}
static int mmap_read_trylock(struct mm_struct *m) {
    if (!m->available) return 0;
    assert(!mmap_held); mmap_held = 1; return 1;
}
static void mmap_read_unlock(struct mm_struct *m) {
    (void)m; assert(mmap_held); mmap_held = 0;
}
static void mmput_async(struct mm_struct *m) { (void)m; assert(!mmap_held); mmrefs--; }
/* mode: 0 complete; 1 no progress; 2 hard error; 3 complete on third call;
 * 4 an error despite fully draining the range. */
static int svm_migrate_vram_to_ram(struct svm_range *p, struct mm_struct *m,
        unsigned long s, unsigned long e, int trigger, void *page) {
    (void)m; (void)s; (void)e; (void)trigger; (void)page;
    assert(mmap_held && !spin_held && p->migrate_mutex.held);
    assert(list_empty(&p->svm_bo_list));
    calls++; p->attempts++;
    if (p->mode == 1) return 0;
    if (p->mode == 2) return -ENOMEM;
    if (p->mode == 3 && p->attempts < 3) return 0;
    p->actual_loc = 0; p->svm_bo->kref--;
    return p->mode == 4 ? -EIO : 0;
}
static struct svm_range *free_range;
static void complete_inflight_eviction(void) {
    struct svm_range *p = free_range;
    /* A migration fails while free waits; eviction relinks before unlock. */
    assert(p->migrate_mutex.held);
    list_add(&p->svm_bo_list, &p->svm_bo->range_list);
    p->migrate_mutex.held = false;
}
static void svm_range_vram_node_free(struct svm_range *p) {
    assert(p->migrate_mutex.held && list_empty(&p->svm_bo_list));
    p->svm_bo->kref--; p->svm_bo = NULL;
}
static void free_backing(struct svm_range *prange) {
''' + free_body + '\n}\n' + callback + r'''
static void setup(struct svm_range_bo *b, struct svm_range *p,
                  struct mm_struct *m, int mode) {
    *m = (struct mm_struct){true, true};
    *b = (struct svm_range_bo){.mm=m, .kref=1};
    *p = (struct svm_range){.svm_bo=b, .actual_loc=1, .mode=mode};
    init(&b->range_list); init(&p->svm_bo_list);
    list_add(&p->svm_bo_list, &b->range_list);
    calls = warnings = unrefs = mmrefs = spin_held = mmap_held = 0;
}
static void clean(void) { assert(!spin_held && !mmap_held && !mmrefs); }
int main(void) {
    struct svm_range_bo b; struct svm_range p, q; struct mm_struct m;
    for (int mode=0; mode<=4; mode++) {
        setup(&b, &p, &m, mode);
        int ret = svm_range_evict_svm_bo(&b.bo);
        clean(); assert(!p.migrate_mutex.held && !p.lock.held && !warnings);
        if (mode == 1 || mode == 2) {
            assert(ret == (mode == 1 ? -EBUSY : -ENOMEM));
            assert(calls == (mode == 1 ? 3 : 1));
            assert(!list_empty(&b.range_list) && !list_empty(&p.svm_bo_list));
            assert(p.svm_bo == &b && p.actual_loc && b.kref == 1 && !b.evicting);
            /* Retrying must see the failed range, not report empty success. */
            p.mode = 0;
            assert(!svm_range_evict_svm_bo(&b.bo));
            assert(!p.svm_bo && !p.actual_loc && list_empty(&b.range_list));
        } else {
            assert(ret == (mode == 4 ? -EIO : 0));
            assert(calls == (mode == 3 ? 3 : 1));
            assert(!p.svm_bo && !p.actual_loc && list_empty(&b.range_list));
            assert(b.evicting == (mode != 4));
        }
        clean(); assert(!warnings && b.kref == 0);
    }
    /* One drained range followed by a failing one: retain only the latter. */
    setup(&b, &p, &m, 2);
    q = (struct svm_range){.svm_bo=&b, .actual_loc=1};
    init(&q.svm_bo_list); list_add(&q.svm_bo_list, &b.range_list); b.kref++;
    assert(svm_range_evict_svm_bo(&b.bo) == -ENOMEM);
    assert(!q.svm_bo && list_empty(&q.svm_bo_list));
    assert(p.svm_bo == &b && b.range_list.next == &p.svm_bo_list);
    assert(!b.evicting && b.kref == 1); clean();
    p.mode=0; assert(!svm_range_evict_svm_bo(&b.bo)); clean();
    /* Lock contention does not detach a range or leave evicting asserted. */
    setup(&b, &p, &m, 0); p.migrate_mutex.held=true;
    assert(svm_range_evict_svm_bo(&b.bo) == -EBUSY);
    assert(!calls && !b.evicting && !list_empty(&p.svm_bo_list)); clean();
    setup(&b, &p, &m, 0); m.available=false;
    assert(svm_range_evict_svm_bo(&b.bo) == -EBUSY);
    assert(!calls && b.kref == 1 && !b.evicting); clean();
    setup(&b, &p, &m, 0); m.live=false;
    assert(!svm_range_evict_svm_bo(&b.bo)); assert(!calls && b.kref == 1); clean();
    setup(&b, &p, &m, 0); b.kref=0;
    assert(!svm_range_evict_svm_bo(&b.bo)); assert(!unrefs && !calls); clean();
    setup(&b, &p, &m, 0);
    free_backing(&p); assert(list_empty(&b.range_list) && !p.migrate_mutex.held);
    /* Simulate free racing eviction while its range is detached. */
    setup(&b, &p, &m, 0); list_del_init(&p.svm_bo_list);
    p.migrate_mutex.held = true; free_range = &p; free_wait = true;
    free_backing(&p);
    assert(list_empty(&b.range_list) && !p.svm_bo && !p.migrate_mutex.held);
    puts("PASS: SVM eviction errors, partial migration, retry, multiple ranges and contention");
}
'''
with tempfile.TemporaryDirectory() as temp:
    c = Path(temp) / 'test.c'
    c.write_text(program)
    exe = Path(temp) / 'test'
    subprocess.run([os.environ.get('CC', 'gcc'), '-std=gnu11', '-Wall', '-Wextra',
                    '-Werror', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
