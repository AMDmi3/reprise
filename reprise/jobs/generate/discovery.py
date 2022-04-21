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

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from reprise.commands import MAKE_CMD
from reprise.execute import execute

_FALLBACK_PORTSDIR = '/usr/ports'


@dataclass
class Defaults:
    portsdir: Path
    distdir: Path
    current_port: str | None


async def discover_defaults(args: argparse.Namespace) -> Defaults:
    logger = logging.getLogger('Discover')

    portsdir = args.portsdir
    distdir = args.distdir
    current_port = None

    if not portsdir and os.path.exists('Makefile'):
        lines = await execute(MAKE_CMD, '-V', 'PORTSDIR', '-V', 'PORTNAME', allow_failure=True)
        if len(lines) == 2 and all(lines):
            logger.debug('we seem to be in a port directory, using it')

            portsdir = lines[0]
            logger.debug(f'discovered default PORTSDIR: {portsdir}')

            current_port = '/'.join(os.getcwd().rsplit('/', 2)[-2:])
            logger.debug(f'current port: {current_port}')

    if not portsdir:
        portsdir = _FALLBACK_PORTSDIR
        logger.debug(f'assumed default PORTSDIR: {portsdir}')

    if not distdir:
        lines = await execute(MAKE_CMD, '-C', portsdir, '-V', 'DISTDIR', allow_failure=True)
        if lines and lines[0]:
            distdir = lines[0]
            logger.debug(f'discovered default DISTDIR: {distdir}')

    return Defaults(
        portsdir=Path(portsdir),
        distdir=Path(distdir),
        current_port=current_port,
    )
