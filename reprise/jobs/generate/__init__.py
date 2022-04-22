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
import contextlib
import logging
import sys
from typing import Any, AsyncGenerator

from reprise.helpers import unicalize
from reprise.jail.manager import JailManager
from reprise.jobs import JobSpec, PackageCompressionMode
from reprise.jobs.generate.discovery import discover_defaults
from reprise.jobs.generate.options import (generate_options_combinations,
                                           get_port_options_vars)
from reprise.prison import NetworkingMode


async def generate_jobs(args: argparse.Namespace, jail_manager: JailManager) -> AsyncGenerator[Any, JobSpec]:
    logger = logging.getLogger('Generate')

    defaults = await discover_defaults(args)

    ports: list[str] = []

    if args.file:
        with contextlib.ExitStack() as stack:
            fd = sys.stdin if args.file == '-' else stack.enter_context(open(args.file))

            ports.extend(
                item
                for line in fd
                if (item := line.split('#')[0].strip())
            )

            ports = unicalize(ports)

            logger.debug(f'added {len(ports)} port(s) from the file')

    if args.ports:
        prev_ports_count = len(ports)

        for port in args.ports:
            if port == '.':
                if defaults.current_port is None:
                    raise RuntimeError('cannot use `.` as a port name when not in a port directory')
                ports.append(defaults.current_port)
            else:
                ports.append(port)

        ports = unicalize(ports)

        logger.debug(f'adding {len(ports) - prev_ports_count} port(s) from the command line')

    if not ports and defaults.current_port is not None:
        ports = [defaults.current_port]
        logger.debug(f'assuming to build port {defaults.current_port}')

    rebuild = set(args.rebuild)

    variables = dict(var.split('=', 1) for var in args.vars)

    if args.jails is None:
        jails = ['default']
    elif args.jails == []:
        jails = ['all']
    else:
        jails = args.jails

    jailspecs = jail_manager.get_specs(jails)

    for jailspec in jailspecs:
        for port in ports:
            options_combinations: list[dict[str, bool]] = [{}]

            # XXX: to be correct, options should be generated inside a jail
            if args.options:
                if args.exclude_default_options:
                    options_combinations = []

                options_combinations.extend(
                    generate_options_combinations(
                        await get_port_options_vars(defaults.portsdir / port),
                        include_options=set(args.include_options) if args.include_options else None,
                        exclude_options=set(args.exclude_options) if args.exclude_options else set(),
                    )
                )

                logger.debug(f'{len(options_combinations)} options combination(s) generated')

            for options in options_combinations:
                yield JobSpec(
                    origin=port,
                    portsdir=defaults.portsdir,
                    distdir=defaults.distdir,
                    jailspec=jailspec,
                    origins_to_rebuild=rebuild,
                    fail_fast=args.fail_fast,
                    networking_build=NetworkingMode[args.networking_build],
                    networking_test=NetworkingMode[args.networking_test],
                    variables=variables,
                    options=options,
                    do_test=not args.no_test,
                    build_as_nobody=not args.build_as_root,
                    use_ccache=not args.no_ccache,
                    package_compression=PackageCompressionMode[args.package_compression],
                    use_tmpfs_work=args.tmpfs_work,
                    use_tmpfs_localbase=args.tmpfs_localbase,
                    tmpfs_limit_bytes=args.tmpfs_limit_mb * 1024 * 1024,
                    fetch_timeout=args.timeout_fetch,
                    build_timeout=args.timeout_build,
                    test_timeout=args.timeout_test,
                )
