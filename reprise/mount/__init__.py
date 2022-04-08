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

from pathlib import Path

from reprise.commands import UMOUNT_CMD
from reprise.execute import execute
from reprise.resources import Resource


class Mountpoint(Resource):
    _path: Path

    def __init__(self, path: Path) -> None:
        self._path = path

    async def destroy(self) -> None:
        await execute(UMOUNT_CMD, '-f', f'{self._path}')

    def get_path(self) -> Path:
        return self._path

    def __repr__(self) -> str:
        return f'mountpoint at {self._path}'
