import asyncio
import logging
import os
import signal
from contextlib import AsyncExitStack
from pathlib import Path

from porttester.jail import Jail, start_jail
from porttester.jail.populate import JailSpec, populate_jail
from porttester.mount import Mountpoint
from porttester.mount.filesystems import mount_devfs, mount_nullfs, mount_tmpfs
from porttester.resources.enumerate import enumerate_resources
from porttester.workdir import Workdir
from porttester.zfs import ZFS

_JAIL_SPECS = {
    '12-i386': JailSpec(version='12.3-RELEASE', architecture='i386'),
    '12-amd64': JailSpec(version='12.3-RELEASE', architecture='amd64'),
    '13-i386': JailSpec(version='13.0-RELEASE', architecture='i386'),
    '13-amd64': JailSpec(version='13.0-RELEASE', architecture='amd64'),
}


_USE_JAILS = ['13-amd64']


_PORTSTREE = '/usr/ports'


_DISTFILES = '/usr/distfiles'


_PORT = 'www/py-yarl'


def replace_in_file(path: Path, pattern: str, replacement: str) -> None:
    with open(path, 'r') as fd:
        data = fd.read().replace(pattern, replacement)

    with open(path, 'w') as fd:
        fd.write(data)


class PortTester:
    workdir: Workdir

    def __init__(self, workdir: Workdir) -> None:
        self.workdir = workdir

    async def _get_prepared_jail(self, name: str) -> ZFS:
        jail = self.workdir.get_jail_master(name)
        spec = _JAIL_SPECS[name]

        if await jail.exists() and not (jail.get_path() / 'usr').exists():
            logging.debug(f'jail {name} is incomplete, destroying')
            await jail.destroy(recursive=True)

        if not await jail.exists():
            logging.debug(f'creating jail {name}')
            await jail.create(parents=True)

            logging.debug(f'populating jail {name}')
            await populate_jail(spec, jail.mountpoint)

            await jail.snapshot('clean')

        logging.debug(f'jail {name} is ready')

        return jail

    async def _cleanup_jail(self, path: Path) -> None:
        for resource in await enumerate_resources(path):
            logging.debug(f'cleaning up jail resource: {resource}')
            await resource.destroy()

    async def run(self):
        for jail_name in _USE_JAILS:
            master_zfs = await self._get_prepared_jail(jail_name)

            instance_name = f'{jail_name}-default'

            instance_zfs = self.workdir.get_jail_instance(instance_name)

            packages_zfs = self.workdir.get_jail_packages(jail_name)

            if not await packages_zfs.exists():
                await packages_zfs.create(parents=True)

            await self._cleanup_jail(instance_zfs.get_path())

            try:
                logging.debug(f'cloning instance')
                await instance_zfs.clone_from(master_zfs, 'clean', parents=True)

                logging.debug(f'creating directories')
                ports_path = instance_zfs.get_path() / 'usr' / 'ports'
                distfiles_path = instance_zfs.get_path() / 'distfiles'
                work_path = instance_zfs.get_path() / 'work'
                packages_path = instance_zfs.get_path() / 'packages'

                for path in [ports_path, distfiles_path, work_path, packages_path]:
                    path.mkdir(parents=True, exist_ok=True)

                logging.debug(f'installing resolv.conf')
                with open(instance_zfs.get_path() / 'etc' / 'resolv.conv', 'w') as fd:
                    fd.write('nameserver 8.8.8.8\n')

                logging.debug(f'fixing pkg config')
                replace_in_file(instance_zfs.get_path() / 'etc' / 'pkg'/ 'FreeBSD.conf', 'quarterly', 'latest')

                logging.debug(f'mounting filesystems')
                await asyncio.gather(
                    mount_devfs(instance_zfs.get_path() / 'dev'),
                    mount_nullfs(Path(_PORTSTREE), ports_path),
                    mount_nullfs(Path(_DISTFILES), distfiles_path, readonly=False),
                    mount_nullfs(packages_zfs.get_path(), packages_path, readonly=False),
                    mount_tmpfs(work_path),
                )

                logging.debug(f'starting jail')
                jail = await start_jail(instance_zfs.get_path(), networking=True)

                def printline(line: str):
                    print(line)

                logging.debug(f'installing pkg')

                returncode = await jail.execute_by_line(
                    printline,
                    'pkg', 'bootstrap', '-y',
                )

                logging.debug(f'gathering depends')

                depend_vars = await jail.execute(
                    'make', '-C', str(Path('/usr/ports') / _PORT),
                    '-V', 'BUILD_DEPENDS',
                    '-V', 'RUN_DEPENDS',
                    '-V', 'LIB_DEPENDS',
                    '-V', 'TEST_DEPENDS',
                )

                depends = set()

                for depend in ' '.join(depend_vars).split():
                    test, port = depend.split(':', 1)

                    flavor_args = []
                    if '@' in port:
                        port, flavor = port.split('@', 1)
                        flavor_args = ['FLAVOR=' + flavor]

                    pkgname = (await jail.execute(
                        'env', *flavor_args, 'make', '-C', f'/usr/ports/{port}', '-V', 'PKGNAME'
                    ))[0]

                    depends.add(pkgname.rsplit('-', 1)[0])

                print(depends)

                logging.debug(f'installing depends')

                returncode = await jail.execute_by_line(
                    printline,
                    'env', 'PKG_CACHEDIR=/packages', 'pkg', 'install', '-y', *depends
                )

                logging.debug(f'force-removing the package')

                returncode = await jail.execute_by_line(
                    printline,
                    'env', 'PKG_CACHEDIR=/packages', 'pkg', 'delete', '-f', _PORT
                )

                logging.debug(f'running make install')

                returncode = await jail.execute_by_line(
                    printline,
                    'env', 'DISTDIR=/distfiles', 'WRKDIRPREFIX=/work', 'make', '-C', f'/usr/ports/{_PORT}', 'install'
                )

                if returncode != 0:
                    print(f'failed')
                    return

                returncode = await jail.execute_by_line(
                    printline,
                    'env', 'DISTDIR=/distfiles', 'WRKDIRPREFIX=/work', 'make', '-C', f'/usr/ports/{_PORT}', 'test'
                )

                if returncode != 0:
                    print(f'failure')
                    return

                print(f'done')
            finally:
                await self._cleanup_jail(instance_zfs.get_path())


def sig_handler():
    print('Interrupted')


async def main():
    logging.basicConfig(level=logging.DEBUG)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, sig_handler)

    workdir = await Workdir.initialize()
    await PortTester(workdir).run()


asyncio.run(main())
