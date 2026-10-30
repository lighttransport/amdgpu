===================
 Module Parameters
===================

The amdgpu driver supports the following module parameters:

.. kernel-doc:: drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c

Experimental Navi 48 PPT floor override (LTE fork)
------------------------------------------------

``min_power_cap`` (uint, watts, default 0, read-only after module load)
lowers the driver-side minimum PPT0 limit on discrete Navi 48 GPUs with
GC IP 12.0.1 and SMU IP 14.0.2, including the RX 9070 XT. It does not apply
to APUs, SR-IOV virtual functions, other IP versions, or PPT1. A value of
zero preserves the SKU minimum. A nonzero value can lower the selected
AC/DC and overdrive minimum, but cannot raise it. Upper limits and the
existing firmware read-back check remain in effect.

For example, loading the driver with ``amdgpu.min_power_cap=150`` on the
kernel command line exposes a 150 W ``power1_cap_min`` when the stock floor
is 212 W. A later 170 W ``power1_cap`` write (170000000 microwatts) then
passes the driver range check. When loading through modprobe, use the
module option ``min_power_cap=150``. The option changes the accepted floor;
it does not set the operating power cap. Remove the option or set it to
zero on the next module load to restore the SKU floor.

.. warning::

   This is an unsupported experiment, not a validated low-power mode.
   A previous RX 9070 XT test at 170 W below the 212 W SKU minimum caused
   compute-oracle failures and an SMU/PMFW hang requiring a cold boot.
   Firmware accepting or reading back a limit does not establish stability;
   the read-back guard does not undo the write or recover hung firmware.
   Keep voltage at stock for any separately authorized runtime validation.
