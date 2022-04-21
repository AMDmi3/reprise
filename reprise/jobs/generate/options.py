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

import logging
from pathlib import Path
from typing import Iterator

from reprise.commands import MAKE_CMD
from reprise.execute import execute


async def get_port_options_vars(path_to_port: Path) -> dict[str, set[str]]:
    var_names = ['OPTIONS_DEFAULT', 'OPTIONS_DEFINE', 'OPTIONS_GROUP', 'OPTIONS_SINGLE', 'OPTIONS_MULTI', 'OPTIONS_RADIO']

    lines = await execute(MAKE_CMD, '-C', str(path_to_port), *(f'-V{var}' for var in var_names))
    if len(lines) != len(var_names):
        raise RuntimeError(f'failed to read option variables for {path_to_port}')

    res = dict(zip(var_names, (set(line.split()) for line in lines)))

    var_names = [
        f'{var}_{sub}'
        for var in ['OPTIONS_GROUP', 'OPTIONS_SINGLE', 'OPTIONS_MULTI', 'OPTIONS_RADIO']
        for sub in res[var]
    ]

    if var_names:
        lines = await execute(MAKE_CMD, '-C', str(path_to_port), *(f'-V{var}' for var in var_names))
        if len(lines) != len(var_names):
            raise RuntimeError(f'failed to read option variables for {path_to_port}')

        res.update(zip(var_names, (set(line.split()) for line in lines)))

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

        for choice in sorted(options):
            logger.debug(f'considering variant with single {single} set to to {choice}')
            yield {option: option == choice for option in options}

    # RADIO is the same as single with additional variant of none
    for radio in variables['OPTIONS_RADIO']:
        options = variables[f'OPTIONS_RADIO_{radio}']

        for choice in sorted(options):
            logger.debug(f'considering variant with radio {radio} set to {choice}')
            yield {option: option == choice for option in options}

        logger.debug(f'considering variant with radio {radio} fully disabled')
        yield {option: False for option in options}

    # MULTI is the mix of GROUP without all-off variant and SINGLE
    for multi in variables['OPTIONS_MULTI']:
        options = variables[f'OPTIONS_MULTI_{multi}']
        default = options & enabled

        for choice in sorted(options):
            logger.debug(f'considering variant with multi {multi} set to {choice}')
            yield {option: option == choice for option in options}

        for option in sorted(options):
            # be sure not to produce combination with no options enabled by toggling
            if {option} != default:
                logger.debug(f'considering variant with multi {multi} option {option} toggled')
                yield from ({option: True}, {option: False})

        logger.debug(f'considering variant with multi {multi} fully enabled')
        yield {option: True for option in options}


def generate_options_combinations(
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
