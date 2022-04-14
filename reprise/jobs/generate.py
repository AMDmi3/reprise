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
from reprise.jail import NetworkingIsolationMode
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

    for option in variables['OPTIONS_DEFINE']:
        target_state = option not in enabled
        logger.debug(f'considering variant with option {option} toggled to {"ON" if target_state else "OFF"}')
        yield {option: target_state}

    for group in variables['OPTIONS_GROUP']:
        options = variables[f'OPTIONS_GROUP_{group}']
        default_options = options & enabled

        for option in variables[f'OPTIONS_GROUP_{group}']:
            target_state = option not in enabled
            logger.debug(f'considering variant with group {group} option {option} toggled to {"ON" if target_state else "OFF"}')
            yield {option: target_state}

        if default_options != options:
            logger.debug(f'considering variant with group {group} fully enabled')
            yield {option: True for option in options}

        if default_options:
            logger.debug(f'considering variant with group {group} fully disabled')
            yield {option: False for option in options}

    for single in variables['OPTIONS_SINGLE']:
        choices = variables[f'OPTIONS_SINGLE_{single}']
        default_choices = choices & enabled

        if len(default_choices) != 1:
            logger.error(f'unexpected number of default choices for single {single}, ignoring')
            continue

        default_choice = next(iter(default_choices))

        for choice in choices - default_choices:
            logger.debug(f'considering variant with single {single} changed from {default_choice} to {choice}')
            yield {choice: True, default_choice: False}

    for radio in variables['OPTIONS_RADIO']:
        choices = variables[f'OPTIONS_RADIO_{radio}']
        default_choices = choices & enabled

        if len(default_choices) == 0:
            for choice in choices:
                logger.debug(f'considering variant with radio {radio} set to {choice}')
                yield {choice: True}
        elif len(default_choices) == 1:
            default_choice = next(iter(default_choices))
            for choice in choices:
                if choice == default_choice:
                    logger.debug(f'considering variant with radio {radio} reset from {default_choice}')
                    yield {default_choice: False}
                else:
                    logger.debug(f'considering variant with radio {radio} changed from {default_choice} to {choice}')
                    yield {choice: True, default_choice: False}
        else:
            logger.error(f'multiple default choices for radio {radio}, ignoring')
            continue

    for multi in variables['OPTIONS_MULTI']:
        choices = set(variables[f'OPTIONS_MULTI_{multi}'])
        default_choices = choices & enabled

        for choice in choices:
            if {choice} != default_choices:
                logger.debug(f'considering variant with multi {multi} set to (only) {choice}')
                yield {default_choice: False for default_choice in default_choices} | {choice: True}

        if default_choices != choices:
            logger.debug(f'considering variant with multi {multi} fully enabled')
            yield {choice: True for choice in choices}


async def generate_jobs(args: argparse.Namespace) -> AsyncGenerator[Any, JobSpec]:
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

    variables = {}
    if args.vars is not None:
        variables = dict(var.split('=', 1) for var in args.vars)

    for jailname in _USE_JAILS:
        for port in ports:
            options_combinations: list[dict[str, bool]] = [{}]

            # XXX: to be correct, options should be generated inside a jail
            if args.options:
                options_combinations.extend(
                    _iterate_options_combinations(
                        await _get_port_options_vars(defaults.portsdir / port)
                    )
                )
                logger.debug(f'{len(options_combinations) - 1} additional options combination(s) generated')

            for options in options_combinations:
                yield JobSpec(
                    origin=port,
                    portsdir=defaults.portsdir,
                    distdir=defaults.distdir,
                    jailname=jailname,
                    origins_to_rebuild=rebuild,
                    fail_fast=args.fail_fast,
                    networking_isolation_build=NetworkingIsolationMode[args.networking_isolation_build],
                    networking_isolation_test=NetworkingIsolationMode[args.networking_isolation_test],
                    variables=variables,
                    options=options,
                )
