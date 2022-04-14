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

from dataclasses import dataclass
from pathlib import Path

from reprise.jail import JailSpec
from reprise.prison import NetworkingIsolationMode


@dataclass
class JobSpec:
    origin: str
    portsdir: Path
    distdir: Path
    jailspec: JailSpec
    origins_to_rebuild: set[str]
    fail_fast: bool
    networking_isolation_build: NetworkingIsolationMode
    networking_isolation_test: NetworkingIsolationMode
    variables: dict[str, str]
    options: dict[str, bool]

    @property
    def all_variables(self) -> dict[str, str]:
        extra_vars = {}

        if (options := [k for k, v in self.options.items() if v]):
            extra_vars['WITH'] = ' '.join(options)

        if (options := [k for k, v in self.options.items() if not v]):
            extra_vars['WITHOUT'] = ' '.join(options)

        return self.variables | extra_vars

    def __repr__(self) -> str:
        extra_components: list[str] = []

        extra_components.extend(f'{k}={v}' for k, v in self.all_variables.items())

        res = f'{self.origin} on {self.jailspec.name}'

        if extra_components:
            res += ' (' + ', '.join(extra_components) + ')'

        return res
