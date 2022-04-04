from dataclasses import dataclass
from pathlib import Path
import asyncio


@dataclass
class JailSpec:
    version: str
    architecture: str


async def populate_jail(spec: JailSpec, target_path: Path) -> None:
    if spec.version not in ['12.3-RELEASE', '13.0-RELEASE']:
        raise RuntimeError('unsupported version')

    if spec.architecture not in ['amd64', 'i386']:
        raise RuntimeError('unsupported architecture')

    url_prefix = f'https://download.freebsd.org/ftp/releases/{spec.architecture}/{spec.version}/'

    for tarball in ['base.txz']:
        command = f'fetch -o- {url_prefix}/{tarball} | tar -C {target_path} -x -f- -z'

        proc = await asyncio.create_subprocess_shell(command, stderr=asyncio.subprocess.PIPE)

        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError('failed to populate jail ' + stderr.decode('utf-8'))
