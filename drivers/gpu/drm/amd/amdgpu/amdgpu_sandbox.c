// SPDX-License-Identifier: MIT
/* Experimental cgroup-owned GPU resource policy. Unmanaged clients stay native. */
#include <linux/capability.h>
#include <linux/cgroup.h>
#include <linux/compat.h>
#include <linux/fs.h>
#include <linux/kref.h>
#include <linux/jiffies.h>
#include <linux/miscdevice.h>
#include <linux/mm.h>
#include <linux/moduleparam.h>
#include <linux/overflow.h>
#include <linux/pci.h>
#include <linux/poll.h>
#include <linux/rculist.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <drm/drm_drv.h>
#include "amdgpu.h"
#include "amdgpu_sandbox.h"

#define SB_EVENTS 256
#define SB_MAX_POLICIES 1024
#define SB_FAULT_HISTORY 64

struct sb_fault_record {
	u64 context, sequence, time;
};
/* Connected ABI hooks, available only with the explicit sandbox=1 opt-in.
 * Feature availability does not imply hardware/runtime validation.
 */
#define SB_FEATURES AMDGPU_SB_F_ALL
static bool sandbox;
module_param(sandbox, bool, 0444);
MODULE_PARM_DESC(sandbox, "Enable experimental host-managed GPU sandbox controls (default off)");

struct amdgpu_sb_client {
	struct list_head node;
	struct kref ref;
	struct mutex lock;
	wait_queue_head_t idle;
	unsigned int active;
	bool evicted;
	struct amdgpu_sandbox *sb;
	void *data;
	bool (*get)(void *data);
	void (*put)(void *data);
	int (*evict)(void *data);
};

struct amdgpu_sandbox {
	struct list_head node, gc_node;
	struct kref ref;
	struct rcu_head rcu;
	struct cgroup *cgroup;
	struct drm_device *drm;
	struct amdgpu_device *adev;
	u64 id, limit[AMDGPU_SB_RESOURCE_COUNT];
	u64 usage[AMDGPU_SB_RESOURCE_COUNT], peak[AMDGPU_SB_RESOURCE_COUNT];
	u64 violations, incidents, last_context, last_sequence;
	u64 window_start_ns;
	struct sb_fault_record history[SB_FAULT_HISTORY];
	unsigned int history_next;
	u32 window_count, threshold, window_ms;
	u32 state, mode;
	spinlock_t lock;
	struct mutex ranges_lock;
	struct list_head ranges;
	struct mutex clients_lock;
	struct list_head clients;
	struct delayed_work quarantine_work;
};

static LIST_HEAD(sb_policies);
static DEFINE_MUTEX(sb_registry_lock);
static u64 sb_next_id;
static unsigned int sb_policy_count;
static struct workqueue_struct *sb_wq;
static bool sb_stopping;
static DEFINE_SPINLOCK(sb_event_lock);
static DECLARE_WAIT_QUEUE_HEAD(sb_event_wait);
static struct amdgpu_sb_event sb_events[SB_EVENTS];
static u64 sb_event_sequence;

static void sb_event(struct amdgpu_sandbox *sb, u32 type, u32 resource,
		     u64 value, u64 limit)
{
	struct amdgpu_sb_event event = {
		.id = sb->id, .monotonic_ns = ktime_get_ns(), .type = type,
		.resource = resource, .value = value, .limit = limit,
	};
	unsigned long flags;

	spin_lock_irqsave(&sb_event_lock, flags);
	event.sequence = ++sb_event_sequence;
	sb_events[event.sequence % SB_EVENTS] = event;
	spin_unlock_irqrestore(&sb_event_lock, flags);
	wake_up_interruptible(&sb_event_wait);
}

static void sb_release(struct kref *ref)
{
	struct amdgpu_sandbox *sb = container_of(ref, struct amdgpu_sandbox, ref);

	WARN_ON(!list_empty(&sb->clients));
	WARN_ON(!list_empty(&sb->ranges));
	cgroup_put(sb->cgroup);
	drm_dev_put(sb->drm);
	kfree_rcu(sb, rcu);
}

struct amdgpu_sandbox *amdgpu_sb_get(struct amdgpu_sandbox *sb)
{
	if (sb)
		kref_get(&sb->ref);
	return sb;
}

void amdgpu_sb_put(struct amdgpu_sandbox *sb)
{
	if (sb)
		kref_put(&sb->ref, sb_release);
}

struct amdgpu_sandbox *amdgpu_sb_current(struct amdgpu_device *adev)
{
	struct amdgpu_sandbox *sb, *found = NULL;
	struct cgroup *cg;

	if (!sandbox || !current->mm)
		return NULL;
	rcu_read_lock();
	cg = task_dfl_cgroup(current);
	list_for_each_entry_rcu(sb, &sb_policies, node) {
		if (!cgroup_is_descendant(cg, sb->cgroup))
			continue;
		if (adev && sb->adev != adev) {
			found = ERR_PTR(-EPERM);
			break;
		}
		if (kref_get_unless_zero(&sb->ref))
			found = sb;
		break;
	}
	rcu_read_unlock();
	return found;
}

bool amdgpu_sb_allows(struct amdgpu_sandbox *sb, struct amdgpu_device *adev)
{
	return !sb || sb->adev == adev;
}

int amdgpu_sb_check(struct amdgpu_sandbox *sb)
{
	if (!sb)
		return 0;
	if (READ_ONCE(sb->state) == AMDGPU_SB_DEVICE_GONE)
		return -ENODEV;
	if (READ_ONCE(sb->state) != AMDGPU_SB_ACTIVE)
		return -EACCES;
	return 0;
}

int amdgpu_sb_identity(struct amdgpu_sandbox *sb, struct amdgpu_device *adev)
{
	struct amdgpu_sandbox *current_sb = amdgpu_sb_current(adev);
	int ret;

	if (IS_ERR(current_sb))
		return PTR_ERR(current_sb);
	ret = current_sb == sb ? 0 : -EXDEV;
	amdgpu_sb_put(current_sb);
	return ret;
}

int amdgpu_sb_check_current(struct amdgpu_sandbox *sb, struct amdgpu_device *adev)
{
	int ret = amdgpu_sb_identity(sb, adev);

	return ret ? ret : amdgpu_sb_check(sb);
}

int amdgpu_sb_charge(struct amdgpu_sandbox *sb, unsigned int resource, u64 amount)
{
	unsigned long flags;
	u64 next;
	int ret;

	if (!sb || !amount)
		return 0;
	if (WARN_ON(resource >= AMDGPU_SB_RESOURCE_COUNT))
		return -EINVAL;
	spin_lock_irqsave(&sb->lock, flags);
	ret = amdgpu_sb_check(sb);
	/* Placement of an already admitted BO is also needed by native eviction
	 * and recovery. Quarantine blocks object/submission admission, not these
	 * moves; retain the numeric VRAM ceiling and reject device removal.
	 */
	if (ret && !(ret == -EACCES && resource == AMDGPU_SB_VRAM))
		goto out;
	if (check_add_overflow(sb->usage[resource], amount, &next)) {
		ret = -EOVERFLOW;
		goto out;
	}
	if (next > sb->limit[resource]) {
		sb->violations++;
		sb_event(sb, AMDGPU_SB_EVENT_LIMIT, resource, next, sb->limit[resource]);
		if (sb->mode == AMDGPU_SB_ENFORCE) {
			ret = -EDQUOT;
			goto out;
		}
	}
	sb->usage[resource] = next;
	sb->peak[resource] = max(sb->peak[resource], next);
	ret = 0;
out:
	spin_unlock_irqrestore(&sb->lock, flags);
	return ret;
}

/* TTM must be able to try another placement (e.g. GTT) at the VRAM ceiling. */
int amdgpu_sb_charge_vram(struct amdgpu_sandbox *sb, u64 amount)
{
	int ret = amdgpu_sb_charge(sb, AMDGPU_SB_VRAM, amount);

	return ret == -EDQUOT ? -ENOSPC : ret;
}

void amdgpu_sb_uncharge(struct amdgpu_sandbox *sb, unsigned int resource, u64 amount)
{
	unsigned long flags;

	if (!sb || !amount)
		return;
	if (WARN_ON(resource >= AMDGPU_SB_RESOURCE_COUNT))
		return;
	spin_lock_irqsave(&sb->lock, flags);
	if (!WARN_ON(amount > sb->usage[resource]))
		sb->usage[resource] -= amount;
	spin_unlock_irqrestore(&sb->lock, flags);
}

/* Sorted reservation ledger. Distinct mm owners are charged independently;
 * overlapping userptr/SVM registrations within an mm contribute their union.
 */
struct amdgpu_sb_range {
	struct list_head node;
	struct amdgpu_sandbox *sb;
	struct mm_struct *mm;
	u64 start, end;
};

static u64 sb_uncovered(struct amdgpu_sandbox *sb, struct mm_struct *mm,
		       u64 start, u64 end, struct amdgpu_sb_range *skip)
{
	struct amdgpu_sb_range *range;
	u64 cursor = start, bytes = 0;

	lockdep_assert_held(&sb->ranges_lock);
	list_for_each_entry(range, &sb->ranges, node) {
		if (range == skip || range->mm != mm || range->end <= cursor)
			continue;
		if (range->start >= end)
			break;
		if (range->start > cursor)
			bytes += range->start - cursor;
		cursor = max(cursor, range->end);
		if (cursor >= end)
			return bytes;
	}
	return bytes + end - cursor;
}

static void sb_range_insert(struct amdgpu_sandbox *sb, struct amdgpu_sb_range *range)
{
	struct amdgpu_sb_range *other;

	list_for_each_entry(other, &sb->ranges, node) {
		if (other->start > range->start) {
			list_add_tail(&range->node, &other->node);
			return;
		}
	}
	list_add_tail(&range->node, &sb->ranges);
}

struct amdgpu_sb_range *amdgpu_sb_range_add(struct amdgpu_sandbox *sb,
		struct mm_struct *mm, u64 start, u64 size)
{
	struct amdgpu_sb_range *range;
	u64 end, delta;
	int ret;

	if (!sb)
		return NULL;
	if (!mm || !size || (start | size) & ~PAGE_MASK ||
	    check_add_overflow(start, size, &end))
		return ERR_PTR(-EINVAL);
	range = kzalloc(sizeof(*range), GFP_KERNEL);
	if (!range)
		return ERR_PTR(-ENOMEM);
	mutex_lock(&sb->ranges_lock);
	delta = sb_uncovered(sb, mm, start, end, NULL);
	/* Registration nodes share the BO metadata budget to bound zero-delta overlaps. */
	ret = amdgpu_sb_charge(sb, AMDGPU_SB_BOS, 1);
	if (ret)
		goto error;
	ret = amdgpu_sb_charge(sb, AMDGPU_SB_PINNED, delta);
	if (ret) {
		amdgpu_sb_uncharge(sb, AMDGPU_SB_BOS, 1);
		goto error;
	}
	range->sb = amdgpu_sb_get(sb);
	range->mm = mm;
	mmgrab(mm);
	range->start = start;
	range->end = end;
	sb_range_insert(sb, range);
	mutex_unlock(&sb->ranges_lock);
	return range;
error:
	mutex_unlock(&sb->ranges_lock);
	kfree(range);
	return ERR_PTR(ret);
}

void amdgpu_sb_range_free(struct amdgpu_sb_range *range)
{
	struct amdgpu_sandbox *sb;
	u64 delta;

	if (!range)
		return;
	sb = range->sb;
	mutex_lock(&sb->ranges_lock);
	delta = sb_uncovered(sb, range->mm, range->start, range->end, range);
	list_del(&range->node);
	amdgpu_sb_uncharge(sb, AMDGPU_SB_PINNED, delta);
	amdgpu_sb_uncharge(sb, AMDGPU_SB_BOS, 1);
	mutex_unlock(&sb->ranges_lock);
	mmdrop(range->mm);
	amdgpu_sb_put(sb);
	kfree(range);
}

/* SVM splitting only shrinks an existing range. The new child registration
 * is already present, so this operation never needs additional reservation.
 */
void amdgpu_sb_range_shrink(struct amdgpu_sb_range *range, u64 start, u64 size)
{
	struct amdgpu_sandbox *sb;
	u64 end, before, after;

	if (!range)
		return;
	if (WARN_ON(!size || check_add_overflow(start, size, &end) ||
		    start < range->start || end > range->end))
		return;
	sb = range->sb;
	mutex_lock(&sb->ranges_lock);
	before = sb_uncovered(sb, range->mm, range->start, range->end, range);
	after = sb_uncovered(sb, range->mm, start, end, range);
	if (WARN_ON(after > before))
		goto out;
	list_del(&range->node);
	range->start = start;
	range->end = end;
	sb_range_insert(sb, range);
	amdgpu_sb_uncharge(sb, AMDGPU_SB_PINNED, before - after);
out:
	mutex_unlock(&sb->ranges_lock);
}

static void sb_client_release(struct kref *ref)
{
	struct amdgpu_sb_client *client = container_of(ref, struct amdgpu_sb_client, ref);

	amdgpu_sb_put(client->sb);
	kfree(client);
}

/* Client registrations contain weak owner pointers. Snapshot and pin owners
 * under the registration lock; never hold registry locks during GPU eviction.
 */
static void sb_quarantine_work(struct work_struct *work)
{
	struct amdgpu_sandbox *sb = container_of(to_delayed_work(work),
					       struct amdgpu_sandbox, quarantine_work);
	struct amdgpu_sb_client *client, **snapshot;
	unsigned int count = 0, n = 0, i;
	void *data;
	bool retry;
	unsigned long flags;

	if (READ_ONCE(sb_stopping) ||
	    READ_ONCE(sb->state) != AMDGPU_SB_QUARANTINED)
		goto done;

	mutex_lock(&sb->clients_lock);
	list_for_each_entry(client, &sb->clients, node)
		count++;
	snapshot = kcalloc(count, sizeof(*snapshot), GFP_KERNEL);
	if (snapshot) {
		list_for_each_entry(client, &sb->clients, node) {
			kref_get(&client->ref);
			snapshot[n++] = client;
		}
	}
	mutex_unlock(&sb->clients_lock);
	retry = count && !snapshot;
	if (retry)
		sb_event(sb, AMDGPU_SB_EVENT_QUARANTINE, 0, ENOMEM, 0);
	for (i = 0; i < n; i++) {
		int ret = 0;

		client = snapshot[i];
		mutex_lock(&client->lock);
		data = client->evicted ? NULL : client->data;
		if (data && !client->get(data))
			data = NULL;
		if (data)
			client->active++;
		mutex_unlock(&client->lock);
		if (data) {
			ret = client->evict(data);
			client->put(data);
			mutex_lock(&client->lock);
			client->active--;
			if (!ret)
				client->evicted = true;
			wake_up_all(&client->idle);
			mutex_unlock(&client->lock);
			/* put must defer final teardown beyond this callback. */
		}
		if (ret) {
			sb_event(sb, AMDGPU_SB_EVENT_QUARANTINE, 0, -ret, 0);
			if (ret != -ENODEV && ret != -EXDEV)
				retry = true;
		}
		kref_put(&client->ref, sb_client_release);
	}
	kfree(snapshot);
	/* Transfer this work reference to the next attempt. Serialize the final
	 * state check and enqueue with shutdown's per-policy state transition.
	 * Completed clients are skipped, and weak pointers are re-pinned afresh.
	 */
	spin_lock_irqsave(&sb->lock, flags);
	if (retry && !READ_ONCE(sb_stopping) &&
	    sb->state == AMDGPU_SB_QUARANTINED &&
	    queue_delayed_work(sb_wq, &sb->quarantine_work, msecs_to_jiffies(100))) {
		spin_unlock_irqrestore(&sb->lock, flags);
		return;
	}
	spin_unlock_irqrestore(&sb->lock, flags);
done:
	amdgpu_sb_put(sb);
}

static void sb_quarantine_locked(struct amdgpu_sandbox *sb)
{
	if (READ_ONCE(sb_stopping) || sb->state != AMDGPU_SB_ACTIVE)
		return;
	sb->state = AMDGPU_SB_QUARANTINED;
	sb_event(sb, AMDGPU_SB_EVENT_QUARANTINE, 0, 0, 0);
	amdgpu_sb_get(sb);
	if (!queue_delayed_work(sb_wq, &sb->quarantine_work, 0))
		amdgpu_sb_put(sb);
}

struct amdgpu_sb_client *amdgpu_sb_client_add(struct amdgpu_sandbox *sb, void *data,
	bool (*get)(void *data), void (*put)(void *data), int (*evict)(void *data))
{
	struct amdgpu_sb_client *client;
	unsigned long flags;
	int ret;

	if (!sb)
		return NULL;
	ret = amdgpu_sb_charge(sb, AMDGPU_SB_CONTEXTS, 1);
	if (ret)
		return ERR_PTR(ret);
	client = kzalloc(sizeof(*client), GFP_KERNEL);
	if (!client) {
		amdgpu_sb_uncharge(sb, AMDGPU_SB_CONTEXTS, 1);
		return ERR_PTR(-ENOMEM);
	}
	kref_init(&client->ref);
	mutex_init(&client->lock);
	init_waitqueue_head(&client->idle);
	client->sb = amdgpu_sb_get(sb);
	client->data = data;
	client->get = get;
	client->put = put;
	client->evict = evict;
	mutex_lock(&sb->clients_lock);
	spin_lock_irqsave(&sb->lock, flags);
	ret = amdgpu_sb_check(sb);
	if (!ret)
		list_add_tail(&client->node, &sb->clients);
	spin_unlock_irqrestore(&sb->lock, flags);
	mutex_unlock(&sb->clients_lock);
	if (ret) {
		amdgpu_sb_uncharge(sb, AMDGPU_SB_CONTEXTS, 1);
		kref_put(&client->ref, sb_client_release);
		return ERR_PTR(ret);
	}
	return client;
}

void amdgpu_sb_client_quiesce(struct amdgpu_sb_client *client)
{
	if (!client)
		return;
	mutex_lock(&client->lock);
	client->data = NULL;
	mutex_unlock(&client->lock);
	wait_event(client->idle, !READ_ONCE(client->active));
}

void amdgpu_sb_client_del(struct amdgpu_sb_client *client)
{
	if (!client)
		return;
	amdgpu_sb_client_quiesce(client);
	mutex_lock(&client->sb->clients_lock);
	list_del(&client->node);
	mutex_unlock(&client->sb->clients_lock);
	amdgpu_sb_uncharge(client->sb, AMDGPU_SB_CONTEXTS, 1);
	kref_put(&client->ref, sb_client_release);
}

void amdgpu_sb_fault(struct amdgpu_sandbox *sb, u64 context, u64 sequence)
{
	unsigned long flags;
	u64 now = ktime_get_ns(), window;
	unsigned int i, count = 0;

	if (!sb)
		return;
	spin_lock_irqsave(&sb->lock, flags);
	window = (u64)sb->window_ms * NSEC_PER_MSEC;
	for (i = 0; i < SB_FAULT_HISTORY; i++) {
		struct sb_fault_record *record = &sb->history[i];

		if (!record->time || now - record->time >= window)
			continue;
		if (record->context == context && record->sequence == sequence)
			goto out;
		count++;
	}
	sb->history[sb->history_next] = (struct sb_fault_record) {
		.context = context, .sequence = sequence, .time = now,
	};
	sb->history_next = (sb->history_next + 1) % SB_FAULT_HISTORY;
	sb->incidents++;
	count = min_t(unsigned int, count + 1, SB_FAULT_HISTORY);
	sb_event(sb, AMDGPU_SB_EVENT_FAULT, 0, count, sb->threshold);
	if (sb->mode == AMDGPU_SB_ENFORCE && count >= sb->threshold)
		sb_quarantine_locked(sb);
out:
	spin_unlock_irqrestore(&sb->lock, flags);
}

void amdgpu_sb_device_gone(struct amdgpu_device *adev)
{
	struct amdgpu_sandbox *sb;
	unsigned long flags;

	mutex_lock(&sb_registry_lock);
	list_for_each_entry(sb, &sb_policies, node) {
		if (sb->adev != adev)
			continue;
		spin_lock_irqsave(&sb->lock, flags);
		sb->state = AMDGPU_SB_DEVICE_GONE;
		sb_event(sb, AMDGPU_SB_EVENT_DEVICE_GONE, 0, 0, 0);
		spin_unlock_irqrestore(&sb->lock, flags);
	}
	mutex_unlock(&sb_registry_lock);
}

static struct amdgpu_sandbox *sb_find(u64 id)
{
	struct amdgpu_sandbox *sb;

	list_for_each_entry(sb, &sb_policies, node)
		if (sb->id == id)
			return sb;
	return NULL;
}

static void sb_stats(struct amdgpu_sandbox *sb, struct amdgpu_sb_ctl *ctl)
{
	unsigned long flags;

	spin_lock_irqsave(&sb->lock, flags);
	ctl->id = sb->id;
	ctl->cgroup_id = cgroup_id(sb->cgroup);
	ctl->mode = sb->mode;
	ctl->state = sb->state;
	ctl->fault_threshold = sb->threshold;
	ctl->fault_window_ms = sb->window_ms;
	ctl->violations = sb->violations;
	ctl->incidents = sb->incidents;
	memcpy(ctl->limit, sb->limit, sizeof(ctl->limit));
	memcpy(ctl->usage, sb->usage, sizeof(ctl->usage));
	memcpy(ctl->peak, sb->peak, sizeof(ctl->peak));
	ctl->pci_domain = pci_domain_nr(sb->adev->pdev->bus);
	ctl->pci_bus = sb->adev->pdev->bus->number;
	ctl->pci_devfn = sb->adev->pdev->devfn;
	spin_unlock_irqrestore(&sb->lock, flags);
}

static int sb_create(struct amdgpu_sb_ctl *ctl)
{
	struct amdgpu_sandbox *sb, *other;
	struct pci_dev *pdev;
	struct drm_device *drm;
	struct cgroup *cg;
	unsigned int i;
	int ret = 0;

	if (ctl->mode > AMDGPU_SB_ENFORCE || ctl->pci_bus > U8_MAX ||
	    ctl->pci_devfn > U8_MAX || ctl->pci_domain > U16_MAX ||
	    !ctl->fault_threshold || ctl->fault_threshold > 64 ||
	    ctl->fault_window_ms < 1000 || ctl->fault_window_ms > 3600000)
		return -EINVAL;
	if (ctl->mode == AMDGPU_SB_ENFORCE && SB_FEATURES != AMDGPU_SB_F_ALL)
		return -EOPNOTSUPP;
	for (i = 0; i < AMDGPU_SB_RESOURCE_COUNT; i++)
		if (!ctl->limit[i] || ctl->limit[i] > BIT_ULL(60))
			return -EINVAL;
	cg = cgroup_get_from_fd(ctl->cgroup_fd);
	if (IS_ERR(cg))
		return PTR_ERR(cg);
	if (!cgroup_parent(cg)) {
		cgroup_put(cg);
		return -EINVAL;
	}
	pdev = pci_get_domain_bus_and_slot(ctl->pci_domain, ctl->pci_bus, ctl->pci_devfn);
	if (!pdev) {
		cgroup_put(cg);
		return -ENODEV;
	}
	device_lock(&pdev->dev);
	if (!pdev->driver || strcmp(pdev->driver->name, "amdgpu") ||
	    !pci_get_drvdata(pdev)) {
		ret = -ENODEV;
		goto out_device;
	}
	drm = pci_get_drvdata(pdev);
	drm_dev_get(drm);
	if (drm_dev_is_unplugged(drm)) {
		drm_dev_put(drm);
		ret = -ENODEV;
		goto out_device;
	}
	sb = kzalloc(sizeof(*sb), GFP_KERNEL);
	if (!sb) {
		drm_dev_put(drm);
		ret = -ENOMEM;
		goto out_device;
	}
	kref_init(&sb->ref);
	spin_lock_init(&sb->lock);
	mutex_init(&sb->clients_lock);
	mutex_init(&sb->ranges_lock);
	INIT_LIST_HEAD(&sb->ranges);
	INIT_LIST_HEAD(&sb->clients);
	INIT_DELAYED_WORK(&sb->quarantine_work, sb_quarantine_work);
	sb->cgroup = cg;
	sb->drm = drm;
	sb->adev = drm_to_adev(drm);
	sb->mode = ctl->mode;
	sb->threshold = ctl->fault_threshold;
	sb->window_ms = ctl->fault_window_ms;
	memcpy(sb->limit, ctl->limit, sizeof(sb->limit));
	mutex_lock(&sb_registry_lock);
	if (sb_policy_count >= SB_MAX_POLICIES || sb_next_id == U64_MAX) {
		ret = -ENOSPC;
		goto out_registry;
	}
	list_for_each_entry(other, &sb_policies, node) {
		if (cgroup_is_descendant(cg, other->cgroup) ||
		    cgroup_is_descendant(other->cgroup, cg)) {
			ret = -EEXIST;
			goto out_registry;
		}
	}
	sb->id = ++sb_next_id;
	sb_policy_count++;
	list_add_tail_rcu(&sb->node, &sb_policies);
	sb_stats(sb, ctl);
	sb_event(sb, AMDGPU_SB_EVENT_CREATE, 0, 0, 0);
	mutex_unlock(&sb_registry_lock);
	device_unlock(&pdev->dev);
	pci_dev_put(pdev);
	return 0;
out_registry:
	mutex_unlock(&sb_registry_lock);
	/* cg and drm belong to the policy even on this failure path. */
	amdgpu_sb_put(sb);
	device_unlock(&pdev->dev);
	pci_dev_put(pdev);
	return ret;
out_device:
	device_unlock(&pdev->dev);
	pci_dev_put(pdev);
	cgroup_put(cg);
	return ret;
}

static long sb_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct amdgpu_sb_ctl ctl;
	struct amdgpu_sandbox *sb, *candidate;
	unsigned long flags;
	unsigned int i;
	int ret = 0;

	if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))
		return -EPERM;
	if (cmd != AMDGPU_SB_IOCTL)
		return -ENOTTY;
	if (copy_from_user(&ctl, (void __user *)arg, sizeof(ctl)))
		return -EFAULT;
	if (ctl.size != sizeof(ctl) || ctl.version != AMDGPU_SB_VERSION || ctl.reserved)
		return -EINVAL;
	ctl.features = SB_FEATURES;
	if (ctl.op == AMDGPU_SB_CAPS)
		goto copy;
	if (ctl.op == AMDGPU_SB_CREATE) {
		ret = sb_create(&ctl);
		if (ret)
			return ret;
		/* On copy failure the policy remains enumerable, never unprotected. */
		goto copy;
	}
	mutex_lock(&sb_registry_lock);
	sb = sb_find(ctl.id);
	if (ctl.op == AMDGPU_SB_NEXT) {
		sb = NULL;
		list_for_each_entry(candidate, &sb_policies, node)
			if (candidate->id > ctl.id && (!sb || candidate->id < sb->id))
				sb = candidate;
	}
	if (!sb) {
		ret = -ENOENT;
		goto out;
	}
	switch (ctl.op) {
	case AMDGPU_SB_STATS:
	case AMDGPU_SB_NEXT:
		sb_stats(sb, &ctl);
		break;
	case AMDGPU_SB_QUARANTINE:
		spin_lock_irqsave(&sb->lock, flags);
		sb_quarantine_locked(sb);
		spin_unlock_irqrestore(&sb->lock, flags);
		sb_stats(sb, &ctl);
		break;
	case AMDGPU_SB_RETIRE:
		/* Remove the empty cgroup directory before retiring its policy. A
		 * dying cgroup cannot admit new tasks, unlike a merely empty one.
		 * This avoids depending on the unexported core cgroup mutex and
		 * closes task migration racing a populated-state snapshot.
		 * Client/allocation/job/work references also prevent retirement.
		 */
		if (!(READ_ONCE(sb->cgroup->self.flags) & CSS_DYING) ||
		    refcount_read(&sb->ref.refcount) != 1 ||
		    cgroup_is_populated(sb->cgroup)) {
			ret = -EBUSY;
			break;
		}
		spin_lock_irqsave(&sb->lock, flags);
		for (i = 0; i < AMDGPU_SB_RESOURCE_COUNT; i++)
			if (sb->usage[i])
				ret = -EBUSY;
		spin_unlock_irqrestore(&sb->lock, flags);
		if (ret)
			break;
		list_del_rcu(&sb->node);
		sb_policy_count--;
		/* Prevent concurrent RCU lookups acquiring a new reference. */
		synchronize_rcu();
		if (refcount_read(&sb->ref.refcount) != 1) {
			list_add_tail_rcu(&sb->node, &sb_policies);
			sb_policy_count++;
			ret = -EBUSY;
			break;
		}
		sb_event(sb, AMDGPU_SB_EVENT_RETIRE, 0, 0, 0);
		amdgpu_sb_put(sb);
		break;
	default:
		ret = -EINVAL;
	}
out:
	mutex_unlock(&sb_registry_lock);
	if (ret)
		return ret;
copy:
	spin_lock_irqsave(&sb_event_lock, flags);
	ctl.sequence = sb_event_sequence;
	spin_unlock_irqrestore(&sb_event_lock, flags);
	return copy_to_user((void __user *)arg, &ctl, sizeof(ctl)) ? -EFAULT : 0;
}

struct sb_reader {
	struct mutex lock;
	u64 cursor;
};

static int sb_open(struct inode *inode, struct file *file)
{
	struct sb_reader *reader;
	unsigned long flags;

	if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))
		return -EPERM;
	reader = kmalloc(sizeof(*reader), GFP_KERNEL);
	if (!reader)
		return -ENOMEM;
	spin_lock_irqsave(&sb_event_lock, flags);
	reader->cursor = sb_event_sequence + 1;
	spin_unlock_irqrestore(&sb_event_lock, flags);
	mutex_init(&reader->lock);
	file->private_data = reader;
	return stream_open(inode, file);
}

static int sb_close(struct inode *inode, struct file *file)
{
	kfree(file->private_data);
	return 0;
}

static ssize_t sb_read(struct file *file, char __user *buf, size_t size, loff_t *offset)
{
	struct amdgpu_sb_event event;
	struct sb_reader *reader = file->private_data;
	unsigned long flags;
	int ret;

	if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))
		return -EPERM;
	if (size < sizeof(event))
		return -EINVAL;
	ret = mutex_lock_interruptible(&reader->lock);
	if (ret)
		return ret;
	for (;;) {
		spin_lock_irqsave(&sb_event_lock, flags);
		if (reader->cursor <= sb_event_sequence)
			break;
		spin_unlock_irqrestore(&sb_event_lock, flags);
		if (file->f_flags & O_NONBLOCK) {
			ret = -EAGAIN;
			goto out;
		}
		ret = wait_event_interruptible(sb_event_wait,
			READ_ONCE(sb_event_sequence) >= reader->cursor);
		if (ret)
			goto out;
	}
	if (sb_event_sequence - reader->cursor >= SB_EVENTS)
		reader->cursor = sb_event_sequence - SB_EVENTS + 1;
	event = sb_events[reader->cursor % SB_EVENTS];
	spin_unlock_irqrestore(&sb_event_lock, flags);
	if (copy_to_user(buf, &event, sizeof(event))) {
		ret = -EFAULT;
		goto out;
	}
	WRITE_ONCE(reader->cursor, reader->cursor + 1);
	ret = sizeof(event);
out:
	mutex_unlock(&reader->lock);
	return ret;
}

static __poll_t sb_poll(struct file *file, poll_table *wait)
{
	struct sb_reader *reader = file->private_data;

	poll_wait(file, &sb_event_wait, wait);
	return READ_ONCE(sb_event_sequence) >= READ_ONCE(reader->cursor) ?
		EPOLLIN | EPOLLRDNORM : 0;
}

static const struct file_operations sb_fops = {
	.owner = THIS_MODULE, .open = sb_open, .release = sb_close,
	.unlocked_ioctl = sb_ioctl, .compat_ioctl = compat_ptr_ioctl,
	.read = sb_read, .poll = sb_poll,
};
static struct miscdevice sb_misc = {
	.minor = MISC_DYNAMIC_MINOR, .name = "amdgpu-sandbox", .mode = 0600,
	.fops = &sb_fops,
};

int amdgpu_sb_init(void)
{
	int ret;

	BUILD_BUG_ON(sizeof(struct amdgpu_sb_ctl) != 264);
	BUILD_BUG_ON(sizeof(struct amdgpu_sb_event) != 48);
	if (!sandbox)
		return 0;
	sb_wq = alloc_workqueue("amdgpu-sandbox", WQ_UNBOUND | WQ_MEM_RECLAIM, 0);
	if (!sb_wq)
		return -ENOMEM;
	ret = misc_register(&sb_misc);
	if (ret)
		destroy_workqueue(sb_wq);
	return ret;
}

void amdgpu_sb_fini(void)
{
	struct amdgpu_sandbox *sb, *tmp;
	LIST_HEAD(retired);

	if (!sandbox)
		return;
	WRITE_ONCE(sb_stopping, true);
	misc_deregister(&sb_misc);
	mutex_lock(&sb_registry_lock);
	list_for_each_entry_safe(sb, tmp, &sb_policies, node) {
		unsigned long flags;

		/* No initial enqueue or worker requeue can pass this transition. */
		spin_lock_irqsave(&sb->lock, flags);
		sb->state = AMDGPU_SB_DEVICE_GONE;
		spin_unlock_irqrestore(&sb->lock, flags);
		list_del_rcu(&sb->node);
		list_add_tail(&sb->gc_node, &retired);
	}
	mutex_unlock(&sb_registry_lock);
	synchronize_rcu();
	list_for_each_entry_safe(sb, tmp, &retired, gc_node) {
		list_del(&sb->gc_node);
		/* A canceled pending attempt still owns its transferred reference. */
		if (cancel_delayed_work_sync(&sb->quarantine_work))
			amdgpu_sb_put(sb);
		amdgpu_sb_put(sb);
	}
	destroy_workqueue(sb_wq);
}
