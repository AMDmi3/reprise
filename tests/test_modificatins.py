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

import shutil

import pytest

from reprise.jail import JailSpec
from reprise.jail.prepare import _update_login_conf

_LOGIN_CONF = """
default:\\
    :welcome=/var/run/motd:\\
    :setenv=BLOCKSIZE=K:\\
    :mail=/var/mail/$:

russian:\\
    :welcome=/var/run/motd:\\
    :setenv=BLOCKSIZE=K:\\
    :mail=/var/mail/$:
"""

_PARAM_H = """
/*
 * __FreeBSD_version numbers are documented in the Porter's Handbook.
 */
#undef __FreeBSD_version
#define __FreeBSD_version 1300139   /* Master, propagated to newvers */
"""


@pytest.fixture
def test_jail_path(tmp_path):
    (tmp_path / 'etc').mkdir(parents=True)
    (tmp_path / 'usr/include/sys').mkdir(parents=True)

    with open(tmp_path / 'etc/login.conf', 'x') as f:
        f.write(_LOGIN_CONF)

    with open(tmp_path / 'usr/include/sys/param.h', 'x') as f:
        f.write(_PARAM_H)

    return tmp_path


@pytest.mark.skipif(not shutil.which('cap_mkdb'), reason='cap_mkdb binary required')
async def test_login_conf(test_jail_path):
    spec = JailSpec(
        name='13-ame64',
        version='13.0-RELEASE',
        arch='amd64',
    )

    await _update_login_conf(test_jail_path, spec)

    with open(test_jail_path / 'etc/login.conf') as f:
        login_conf = f.read()

    assert 'UNAME_m=amd64' in login_conf
    assert 'OSVERSION=1300139' in login_conf
