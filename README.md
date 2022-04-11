# reprise

[![CI](https://github.com/AMDmi3/reprise/actions/workflows/ci.yml/badge.svg)](https://github.com/AMDmi3/reprise/actions/workflows/ci.yml)

reprise is a tool primarily designed to test package production
on FreeBSD.

Its goals are to use modern facilities present in FreeBSD (such as
ZFS, jails), to be easy to use and to depend only on base.

Unlike [poudriere](https://github.com/freebsd/poudriere), it is
focused on port testing only, without support for repository
production, and has important features still lacking in poudriere,
such as `make test` support, and more eager use of prebuilt packages.
As a result, with reprise you test your ports, not rebuild llvm
and other heavy dependencies over and over again.

## Features against poudriere

- **Automatic jail management**
  Jails are created on demand, no preparation steps are needed
  to run a first build.
- **Any number of simultaneous runs**
  No `jail is already running` errors, run any number of builds
  at a time.
- **Uses prebuilt packages**
  By default uses only prebuilt packages for all dependencies.
- **Convenient adhoc runs**
  Run without arguments in a port directory to test it in its ports
  tree.
- **`make test` support**
  Running upstream unit and integration tests is crucial for providing
  high quality software through the Ports Tree, and this tool allows
  to do it without polluting the host system. It also properly supports
  `TEST_DEPENDS`, even when they create dependency loops.

## Current drawbacks compared to poudriere

Most of these will hopefully be solved at some point.

- Much slower dependency graph calculation.
- Not currently able to build and reuse packages, so dependencies
  which are set to be rebuilt are rebuilt for every run that need
  them.
- Not completely clean builds because of that: jail is polluted
  by build-time dependencies of many ports.
- No timeout support.
- No sanity checking (stage Q/A, shlibs and plist problem detection).
- No automatic rebuilds of dependencies.
- No support for workdir preservation and interactive mode.
- No support for custom `make.conf` injection.
- No support for options.
- No support for ccache.
- No support for build as user.

## Requirements

- Python 3.10
- Python modules: `jsonslicer`
- ZFS
- Root permissions

## Usage

```shell
# cd /usr/ports/category/port && reprise
```

This command builds and tests the given port in its portstree.
At the first run, it creates ZFS hierarchy for itself at
`$ZPOOL/reprise` (currently requires single zpool to be present
in the system and uses it), and prepares FreeBSD 13.0-RELEASE amd64
jail by fetching tarballs from FreeBSD https.

You may specify `--portsdir` and a list of ports explicitly:

```shell
# reprise --portsdir /usr/ports cat1/port1 cat2/port2
```

Additionally, you may specify a list of dependencies which need to
be rebuilt from ports. These will only be built if actually needed
for any other port.

```shell
# cd /usr/ports/category/port && reprise --rebuild category/dependency
```
```shell
# reprise --portsdir /usr/ports -r cat/dep1 cat/dep2 -- cat/port1 cat/port2
```

Note that you need `--` to separate lists of ports.

## Author

  - [Dmitry Marakasov](https://github.com/AMDmi3) <amdmi3@amdmi3.ru>

## License

GPLv3 or later, see [COPYING](COPYING).
