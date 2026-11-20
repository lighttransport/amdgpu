#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Guard MES queue teardown bookkeeping after firmware removal failures."""
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1]) / 'drivers/gpu/drm/amd/amdkfd'
source = (root / 'kfd_device_queue_manager.c').read_text()


def function(name):
    match = re.search(r'^(?:static )?int ' + name + r'\([^;]+?\)\n\{', source, re.M)
    assert match, f'missing {name}'
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


reset = function('reset_queue_mes')
assert re.search(r'r\s*=\s*remove_queue_mes_on_reset_option\([^;]+;\s*'
                  r'if\s*\(r\)\s*\{[^}]*return r;', reset, re.S)
assert reset.index('if (r)') < reset.index('set_queue_as_reset')

remove = function('remove_queue_mes_on_reset_option')
assert 'pid=%d pasid=%u queue=%u doorbell=0x%x' in remove

# A failed MES removal must return before doorbell/MQD/list/accounting teardown.
destroy = function('destroy_queue_cpsch')
failed_remove = destroy.index('retval = remove_queue_mes(dqm, q, qpd)')
failed_return = destroy.index('return retval;', failed_remove)
resource_release = destroy.index('deallocate_doorbell(qpd, q)')
queue_unlink = destroy.index('list_del(&q->list)')
assert failed_remove < failed_return < resource_release < queue_unlink
assert 'q->properties.is_being_destroyed = false;' in destroy[failed_remove:failed_return]

suspend = function('suspend_single_queue')
failed_suspend = suspend.index('int r = remove_queue_mes(dqm, q, &pdd->qpd)')
rollback = suspend.index('q->properties.is_suspended = false;', failed_suspend)
return_error = suspend.index('return r;', rollback)
assert failed_suspend < rollback < return_error
assert suspend.index('decrement_queue_count', failed_suspend) > return_error
print('PASS: MES removal acknowledgement gates reset marking, suspension and queue teardown')
