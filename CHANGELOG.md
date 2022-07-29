# Change Log

## 0.6.1

* Allow to specify jails to use by their individual names

## 0.6.0

* Fix incorrect handling of concurrent fetches
* Add DEVELOPER=1 to build environment to run stage-qa target for
  more sanity checking
* List shared libraries required by a just built package similar
  to how poudriere does
* Implement config and allow to specify jails in it
* Without the config, only generate single jail similar to the host

## 0.5.0

* Added support for interactive mode
* Added plist checking
* Enabled coredumps

## 0.4.0

* Fixed `--fail-fast` mode
* Added timeout support
* Fixed incorrect `$PATH` in the jails which led to attempts to
  read /root/bin by unprivileged processes which led to unexpected
  `EPERM` failures

## 0.3.2

* Fix error in option combinations generated for SINGLE groups

## 0.3.1

* Added compatibility with python 3.9 and python 3.8, so it's
  possible to build reprise from a FreeBSD port.

## 0.3.0

* Added ccache support (enabled by default, disabled by `--no-ccache`)
* Added build as user support (enabled by default, disabled by
  `--build-as-root`)
* Switched package management from `pkg` to our own repository
  metadata handler, removing the need for slow pkg bootstrap and
  update on each build and speeding up dependency graph calculation
* Allow to tune package compression level: disabling compression
  makes package generation way faster
* Added control on tmpfs usage, allow to enable tmpfs independently
  for workdirs and localbase, and allow to limit tmpfs size
* Imroved `--help` formatting
* Restricted list of devfs entries in the jails
* Added support for `BROKEN`/`IGNORE` ports - these now result in
  `SKIPPED` job status, distinguishable and not counted towards
  actual failures
* Improved logs readability

Overall, this release brings significant speedup, for instance with
warm package cache and ccache, `reprise games/xmoto` runs 2.6x faster
compared to 0.2.0 and 20% faster compared to poudriere with similar
settings (package compression, ccache, tmpfs). `reprise -O devel/sdl20`
is 3x faster compared to 0.2.0.

## 0.2.0

* Fixed `--rebuild` having no effect
* Added fail-fast mode which stops the job after the first failure
* Added more control over networking isolation
* Added passing custom `make.conf` variables to the build (`-V FOO=bar`)
* Added option combinations testing mode (`-O`)
* Added support for multiple jails (`-j`)
* Added automatic jail recreation on spec change
* Added summaries before and after the run

## 0.1.2

* Improve logging
* Fix FLAVOR handling

## 0.1.1

* Don't fail on licenses which needs acceptance

## 0.1.0

* Fixed issues with fetching from parallel builds
* Added support for `EXTRACT_DEPENDS`
* Added support for independent testing of multiple ports (specifying
  multiple ports on the command line no longer builds them in a
  single jail)
* Added support for storing build log
* Hid most of log output under `--debug` mode, cleaned up logging
* Add support for getting a list of ports to test from file with
  `--file` argument

## 0.0.1

* Initial release
