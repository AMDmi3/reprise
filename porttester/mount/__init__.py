from porttester.execute import execute
from porttester.commands import UMOUNT_CMD
from porttester.resources import Resource
from pathlib import Path
import asyncio


class Mountpoint(Resource):
    _path: Path

    def __init__(self, path: Path) -> None:
        self._path = path

    async def destroy(self) -> None:
        await execute(UMOUNT_CMD, '-f', self._path)

    def get_path(self) -> Path:
        return self._path

    def __repr__(self) -> str:
        return f'mountpoint at {self._path}'
