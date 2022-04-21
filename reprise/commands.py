# Copyright (C) 2022 Dmitry Marakasov <amdmi3@amdmi3.ru>
#
# This file is part of reprise
#
# reprise is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# reprise is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with reprise.  If not, see <http://www.gnu.org/licenses/>.

import sys

MOUNT_CMD = 'mount'
UMOUNT_CMD = 'umount'
ZFS_CMD = 'zfs'
ZPOOL_CMD = 'zpool'
JAIL_CMD = 'jail'
JEXEC_CMD = 'jexec'
JLS_CMD = 'jls'

if sys.platform.startswith('freebsd'):
    MAKE_CMD = 'make'
else:
    # on Linux, make is usually GNU make, while we need BSD make
    MAKE_CMD = 'bmake'
