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

import logging
import platform
from collections import defaultdict
from typing import Iterable

from reprise.helpers import unicalize
from reprise.jail import JailSpec


class JailManager:
    _logger = logging.getLogger('JailMgr')

    _jails: list[JailSpec]
    _sets: dict[str, list[JailSpec]]

    def __init__(self) -> None:
        self._jails = []
        self._sets = defaultdict(list)

        # in order preferred for default
        versions = ['13.0-RELEASE', '12.3-RELEASE']

        machine = platform.machine()

        if machine == 'amd64':
            archs = ['amd64', 'i386']
        else:
            # XXX: this it not tested on different archs, may it need more
            # complex handling with aarch64 vs. arm.aarch64?
            archs = [machine]

        for version in versions:
            for arch in archs:
                branch = version.split('.')[0]
                name = f'{branch}-{arch}'

                spec = JailSpec(name, version, arch)

                self._jails.append(spec)
                self._logger.debug(f'registered jail spec {spec}')

                self._sets[branch].append(spec)
                self._sets[arch].append(spec)
                self._sets['all'].append(spec)
                self._sets[name] = [spec]

                if not self._sets['default']:
                    self._sets['default'] = [spec]

    def get_specs(self, names: Iterable[str]) -> list[JailSpec]:
        return unicalize(
            sum(
                (
                    self._sets[name]
                    for name in names
                    if name in self._sets
                ),
                []
            )
        )
