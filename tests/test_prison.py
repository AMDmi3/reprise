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

import os
import sys
from pathlib import Path

import pytest

from reprise.prison import NetworkingIsolationMode, start_prison


@pytest.mark.skipif(not sys.platform.startswith('freebsd'), reason='prison tests only supported on FreeBSD')
@pytest.mark.skipif(os.getuid() != 0, reason='prison tests must be run as root')
@pytest.mark.skipif('IM_OK_WITH_LEFTOVERS' not in os.environ, reason='please set IM_OK_WITH_LEFTOVERS env var if you acknowledge that these tests may produce leftover prisons')
async def test_prison():
    prison = await start_prison(Path('/'), hostname='reprise_test_prison')
    assert await prison.is_running()
    assert prison.get_path() == Path('/')
    assert await prison.execute('hostname') == ['reprise_test_prison']
    await prison.destroy()
    assert not await prison.is_running()


@pytest.mark.skipif(not sys.platform.startswith('freebsd'), reason='prison tests only supported on FreeBSD')
@pytest.mark.skipif(os.getuid() != 0, reason='prison tests must be run as root')
@pytest.mark.skipif('IM_OK_WITH_LEFTOVERS' not in os.environ, reason='please set IM_OK_WITH_LEFTOVERS env var if you acknowledge that these tests may produce leftover prisons')
async def test_nonetwork():
    prison = await start_prison(Path('/'), hostname='reprise_test_prison_nonetwork', networking=NetworkingIsolationMode.DISABLED)

    # expected to die with "Non-recoverable resolver failure"
    with pytest.raises(RuntimeError):
        await prison.execute('fetch', 'http://example.com/')

    # expected to die with "Protocol not supported"
    with pytest.raises(RuntimeError):
        await prison.execute('fetch', 'http://127.0.0.1/')

    with pytest.raises(RuntimeError):
        await prison.execute('fetch', 'http://[::1]/')

    await prison.destroy()
