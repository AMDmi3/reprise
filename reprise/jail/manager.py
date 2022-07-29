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
import platform
import re
from collections import defaultdict
from typing import Iterable

from reprise.helpers import unicalize
from reprise.jail import JailSpec


class JailManager:
    _logger = logging.getLogger('JailManager')

    _jails: list[JailSpec]
    _tags: dict[str, list[JailSpec]]

    def __init__(self) -> None:
        self._jails = []
        self._tags = defaultdict(list)

    def register_jail(self, name: str, version: str, arch: str, tags: list[str] | None = None) -> None:
        spec = JailSpec(name, version, arch)

        self._jails.append(spec)
        self._tags[name].append(spec)
        if tags:
            for tag in tags:
                self._tags[tag].append(spec)

        self._logger.debug(f'registered jail {spec}')

    def register_host_jail(self) -> None:
        arch = platform.machine()
        version = platform.release()

        if not re.fullmatch(r'[0-9]+\.[0-9]+-RELEASE', version):
            version = '13.1'
            self._logger.error(f'unable to detect FreeBSD release from host version (is host STABLE or CURRENT?), falling back to hardcoded default {version}')

        self.register_jail('default', version=version, arch=arch)

    def finalize_tags(self) -> None:
        self._tags['all'] = self._jails
        if 'default' not in self._tags:
            self._tags['default'] = self._jails

    def get_specs(self, names: Iterable[str]) -> list[JailSpec]:
        return unicalize(
            sum(
                (
                    self._tags[name]
                    for name in names
                    if name in self._tags
                ),
                []
            )
        )
