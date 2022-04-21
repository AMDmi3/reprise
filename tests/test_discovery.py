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

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from reprise.commands import MAKE_CMD
from reprise.jobs.generate.discovery import Defaults, discover_defaults


@dataclass
class _FakePortsTree:
    portsdir: Path
    distdir: Path
    port_path: Path


@pytest.fixture
def portstree(tmp_path) -> _FakePortsTree:
    port_path = tmp_path / 'catname' / 'portname'
    distdir = Path('/distfiles')

    port_path.mkdir(parents=True)

    with open(port_path / 'Makefile', 'w') as fd:
        fd.write(f"""
            PORTNAME=portname

            PORTSDIR={tmp_path}  # set by ports framework in real life
            DISTDIR={distdir}  # set by ports framework in real life
        """)

    # root portstree Makefile
    with open(tmp_path / 'Makefile', 'w') as fd:
        fd.write(f"""
            PORTSDIR={tmp_path}  # set by ports framework in real life
            DISTDIR={distdir}  # set by ports framework in real life
        """)

    return _FakePortsTree(
        portsdir=tmp_path,
        distdir=distdir,
        port_path=port_path
    )


@pytest.mark.skipif(not shutil.which(MAKE_CMD), reason=f'{MAKE_CMD} command required')
async def test_in_port(portstree):
    os.chdir(portstree.port_path)

    assert await discover_defaults(argparse.Namespace(portsdir=None, distdir=None)) == Defaults(
        portsdir=portstree.portsdir,
        distdir=portstree.distdir,
        current_port='catname/portname',
    )


@pytest.mark.skipif(not shutil.which(MAKE_CMD), reason=f'{MAKE_CMD} command required')
@pytest.mark.skipif(not os.path.exists('/usr/ports/Makefile'), reason='needs portstree available in /usr/ports')
async def test_in_nowhere(portstree):
    os.chdir('/')

    res = await discover_defaults(argparse.Namespace(portsdir=None, distdir=None))

    assert res.portsdir == Path('/usr/ports')
    # since this looks into host portstree, DISTDIR may vary
    assert res.current_port is None


@pytest.mark.skipif(not shutil.which(MAKE_CMD), reason=f'{MAKE_CMD} command required')
async def test_explicit_portsdir(portstree):
    os.chdir('/')

    assert await discover_defaults(argparse.Namespace(portsdir=str(portstree.portsdir), distdir=None)) == Defaults(
        portsdir=portstree.portsdir,
        distdir=portstree.distdir,
        current_port=None,
    )


@pytest.mark.skipif(not shutil.which(MAKE_CMD), reason=f'{MAKE_CMD} command required')
async def test_explicit_portsdir_distdir(portstree):
    os.chdir('/')

    distdir = Path('/foo')

    assert await discover_defaults(argparse.Namespace(portsdir=str(portstree.portsdir), distdir=str(distdir))) == Defaults(
        portsdir=portstree.portsdir,
        distdir=distdir,
        current_port=None,
    )
