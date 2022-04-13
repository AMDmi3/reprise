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
import contextlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from reprise.execute import execute
from reprise.jobs import JobSpec

_FALLBACK_PORTSDIR = '/usr/ports'


_USE_JAILS = ['13-amd64']


@dataclass
class Defaults:
    portsdir: Path
    distdir: Path
    current_port: str | None


async def _discover_defaults(args: argparse.Namespace) -> Defaults:
    logger = logging.getLogger('Discover')

    portsdir = args.portsdir
    distdir = args.distdir
    current_port = None

    if not portsdir and os.path.exists('Makefile'):
        lines = await execute('make', '-V', 'PORTSDIR', '-V', 'PORTNAME', allow_failure=True)
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
        lines = await execute('make', '-C', portsdir, '-V', 'DISTDIR', allow_failure=True)
        if lines and lines[0]:
            distdir = lines[0]
            logger.debug(f'discovered default DISTDIR: {distdir}')

    return Defaults(
        portsdir=Path(portsdir),
        distdir=(distdir),
        current_port=current_port,
    )


async def generate_jobs(args: argparse.Namespace) -> list[JobSpec]:
    logger = logging.getLogger('Generate')

    defaults = await _discover_defaults(args)

    ports: set[str] = set()

    if args.file:
        with contextlib.ExitStack() as stack:
            fd = sys.stdin if args.file == '-' else stack.enter_context(open(args.file))

            ports.update(
                item
                for line in fd
                if (item := line.split('#')[0].strip())
            )

            logger.debug(f'added {len(ports)} port(s) from the file')

    if isinstance(args.ports, list):
        prev_ports_count = len(ports)

        for port in args.ports:
            if port == '.':
                if defaults.current_port is None:
                    raise RuntimeError('cannot use `.` as a port name when not in a port directory')
                ports.add(defaults.current_port)
            else:
                ports.add(port)

        logger.debug(f'adding {len(ports) - prev_ports_count} port(s) from the command line')

    if not ports and defaults.current_port is not None:
        ports = {defaults.current_port}
        logger.debug(f'assuming to build port {defaults.current_port}')

    rebuild = set(args.rebuild) if args.rebuild is not None else set()

    return [
        JobSpec(
            origin=port,
            portsdir=defaults.portsdir,
            distdir=defaults.distdir,
            jailname=jailname,
            origins_to_rebuild=rebuild,
            fail_fast=args.fail_fast,
        )
        for port in ports
        for jailname in _USE_JAILS
    ]
