import asyncio


@staticmethod
async def execute(program: str, *args: list[str], allow_failure: bool = False) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        program, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL if allow_failure else asyncio.subprocess.PIPE,
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        if allow_failure:
            return []
        else:
            raise RuntimeError(stderr.decode('utf-8'))

    return stdout.decode('utf-8').split('\n')[:-1]
