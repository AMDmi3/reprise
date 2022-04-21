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

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from reprise.jail import JailSpec
from reprise.prison import NetworkingMode

# assuming default is somewhere in between "fast" and "best"
PackageCompressionMode = Enum('PackageCompressionMode', 'NONE FAST DEFAULT BEST')


@dataclass
class JobSpec:
    origin: str
    portsdir: Path
    distdir: Path
    jailspec: JailSpec
    origins_to_rebuild: set[str]
    fail_fast: bool
    networking_build: NetworkingMode
    networking_test: NetworkingMode
    variables: dict[str, str]
    options: dict[str, bool]
    do_test: bool
    build_as_nobody: bool
    use_ccache: bool
    package_compression: PackageCompressionMode
    use_tmpfs_work: bool
    use_tmpfs_localbase: bool
    tmpfs_limit_bytes: int

    @property
    def all_variables(self) -> dict[str, str]:
        variables = dict(self.variables)

        if (options := [k for k, v in self.options.items() if v]):
            variables['WITH'] = ' '.join(options)

        if (options := [k for k, v in self.options.items() if not v]):
            variables['WITHOUT'] = ' '.join(options)

        if self.use_ccache:
            variables['WITH_CCACHE_BUILD'] = 'YES'
            variables['CCACHE_DIR'] = '/ccache'

        if self.package_compression == PackageCompressionMode.NONE:
            variables['PKG_NOCOMPRESS'] = 'yes'
        elif self.package_compression == PackageCompressionMode.FAST:
            variables['PKG_COMPRESSION_LEVEL'] = 'fast'
        elif self.package_compression == PackageCompressionMode.BEST:
            variables['PKG_COMPRESSION_LEVEL'] = 'best'

        return variables

    def __repr__(self) -> str:
        extra_components: list[str] = []

        extra_components.extend(f'{k}={v}' for k, v in self.variables.items())
        extra_components.extend(f'{"+" if v else "-"}{k}' for k, v in self.options.items())

        res = f'{self.origin} on {self.jailspec.name}'
        if extra_components:
            res += ' (' + ' '.join(extra_components) + ')'
        return res
