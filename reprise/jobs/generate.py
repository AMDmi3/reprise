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
from typing import Any, AsyncGenerator, Iterator

from reprise.execute import execute
from reprise.helpers import unicalize
from reprise.jail.manager import JailManager
from reprise.jobs import JobSpec
from reprise.prison import NetworkingIsolationMode

_FALLBACK_PORTSDIR = '/usr/ports'


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


async def _get_port_options_vars(path_to_port: Path) -> dict[str, set[str]]:
    var_names = ['OPTIONS_DEFAULT', 'OPTIONS_DEFINE', 'OPTIONS_GROUP', 'OPTIONS_SINGLE', 'OPTIONS_MULTI', 'OPTIONS_RADIO']

    lines = await execute('make', '-C', str(path_to_port), *(f'-V{var}' for var in var_names))
    if len(lines) != len(var_names):
        raise RuntimeError(f'failed to read option variables for {path_to_port}')

    res = dict(zip(var_names, (set(line.split()) for line in lines)))

    var_names = [
        f'{var}_{sub}'
        for var in ['OPTIONS_GROUP', 'OPTIONS_SINGLE', 'OPTIONS_MULTI', 'OPTIONS_RADIO']
        for sub in res[var]
    ]

    if var_names:
        lines = await execute('make', '-C', str(path_to_port), *(f'-V{var}' for var in var_names))
        if len(lines) != len(var_names):
            raise RuntimeError(f'failed to read option variables for {path_to_port}')

        res |= dict(zip(var_names, (set(line.split()) for line in lines)))

    return res


def _iterate_options_combinations(variables: dict[str, set[str]]) -> Iterator[dict[str, bool]]:
    logger = logging.getLogger('Options')

    always_enabled = {'DOCS', 'NLS', 'EXAMPLES', 'IPV6'}
    enabled = variables['OPTIONS_DEFAULT'] | always_enabled

    # toggle each plain option
    for option in sorted(variables['OPTIONS_DEFINE']):
        logger.debug(f'considering variant with option {option} toggled')
        yield from ({option: True}, {option: False})

    # group options are no different from single, toggle each
    # in addition, check all-enabled and all-disabled variants
    for group in variables['OPTIONS_GROUP']:
        options = variables[f'OPTIONS_GROUP_{group}']

        for option in sorted(options):
            logger.debug(f'considering variant with group {group} option {option} toggled')
            yield from ({option: True}, {option: False})

        logger.debug(f'considering variant with group {group} fully enabled')
        yield {option: True for option in options}

        logger.debug(f'considering variant with group {group} fully disabled')
        yield {option: False for option in options}

    # check each choice of SINGLE
    for single in variables['OPTIONS_SINGLE']:
        options = variables[f'OPTIONS_SINGLE_{single}']

        for option in sorted(options):
            logger.debug(f'considering variant with single {single} set to to {option}')
            yield {other: False for other in options} | {option: True}

    # RADIO is the same as single with additional variant of none
    for radio in variables['OPTIONS_RADIO']:
        options = variables[f'OPTIONS_RADIO_{radio}']

        for option in sorted(options):
            logger.debug(f'considering variant with radio {radio} set to {option}')
            yield {other: False for other in options} | ({option: True} if option else {})

        logger.debug(f'considering variant with radio {radio} fully disabled')
        yield {other: False for other in options}

    # MULTI is the mix of GROUP without all-off variant and SINGLE
    for multi in variables['OPTIONS_MULTI']:
        options = variables[f'OPTIONS_MULTI_{multi}']
        default = options & enabled

        for option in sorted(options):
            # be sure not to produce combination with no options enabled by toggling
            if {option} != default:
                logger.debug(f'considering variant with multi {multi} option {option} toggled')
                yield from ({option: True}, {option: False})

            logger.debug(f'considering variant with multi {multi} set to {option}')
            yield {other: False for other in options} | {option: True}

        logger.debug(f'considering variant with multi {multi} fully enabled')
        yield {option: True for option in options}


def _generate_options_combinations(
    variables: dict[str, set[str]],
    include_options: set[str] | None,
    exclude_options: set[str],
) -> Iterator[dict[str, bool]]:
    always_enabled = {'DOCS', 'NLS', 'EXAMPLES', 'IPV6'}
    enabled = variables['OPTIONS_DEFAULT'] | always_enabled

    def is_good_option(k: str, v: bool) -> bool:
        changed_from_default = v != (k in enabled)
        includes_passed = include_options is None or k in include_options
        excludes_passed = k not in exclude_options
        return changed_from_default and includes_passed and excludes_passed

    seen_keys = set()
    for options in _iterate_options_combinations(variables):
        # remove options not changed from default
        # and handle includes/excludes
        options = {
            k: v
            for k, v in options.items()
            if is_good_option(k, v)
        }

        if not options:
            continue

        # unicalize option sets
        key = ','.join(f'{k}={v}' for k, v in sorted(options.items()))

        if key not in seen_keys:
            seen_keys.add(key)
            yield options


async def generate_jobs(args: argparse.Namespace, jail_manager: JailManager) -> AsyncGenerator[Any, JobSpec]:
    logger = logging.getLogger('Generate')

    defaults = await _discover_defaults(args)

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
                    _generate_options_combinations(
                        await _get_port_options_vars(defaults.portsdir / port),
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
                    networking_isolation_build=NetworkingIsolationMode[args.networking_isolation_build],
                    networking_isolation_test=NetworkingIsolationMode[args.networking_isolation_test],
                    variables=variables,
                    options=options,
                    do_test=not args.no_test,
                )
