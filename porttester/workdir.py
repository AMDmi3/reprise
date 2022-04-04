from pathlib import Path
from porttester.execute import execute
from porttester.zfs import ZFS, get_zfs_pools
import logging


_PORTTESTER_HOME = 'porttester'


class AutocreateFailure(RuntimeError):
    pass


class Workdir:
    root: ZFS

    @staticmethod
    async def initialize(dataset: Path | None = None) -> ZFS:
        if dataset is None:
            pools = await get_zfs_pools()

            if not pools:
                raise AutocreateFailure('no ZFS pools detected')
            elif len(pools) > 1:
                raise AutocreateFailure('multiple ZFS pools detected, please specify manually')

            root = ZFS(Path(pools[0]) / _PORTTESTER_HOME)
        else:
            root = ZFS(dataset)

        if not await root.exists():
            try:
                logging.debug(f'creating main dataset at {root.dataset}')
                await root.create()
            except RuntimeError as e:
                raise AutocreateFailure('cannot create root dataset') from e

        try:
            await root.resolve_mountpoint()
        except RuntimeError as e:
            raise AutocreateFailure('cannot get root dataset mountpoint') from e

        return Workdir(root)

    def __init__(self, root: ZFS) -> None:
        self.root = root

    def get_jail_master(self, name: str) -> ZFS:
        return self.root.get_child(Path('jails') / name)

    def get_jail_instance(self, name: str) -> ZFS:
        return self.root.get_child(Path('instances') / name)

    def get_jail_packages(self, name: str) -> ZFS:
        return self.root.get_child(Path('packages') / name)
