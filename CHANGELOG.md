# Change Log

## unreleased

* Added ccache support (enabled by default, disabled by `--no-ccache`)
* Added build as user support (enabled by default, disabled by
  `--build-as-root`)
* Switched package management from `pkg` to our own repository
  metadata handler, removing the need for slow pkg bootstrap and
  update on each build and speeding up dependency graph calculation.

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
