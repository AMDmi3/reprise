FLAKE8?=	flake8
MYPY?=		mypy
PYTEST?=	pytest
ISORT?=		isort
PYTHON?=	python3
TWINE?=		twine

lint:: test flake8 mypy isort-check

test::
	${PYTEST} ${PYTEST_ARGS} -v -rs

flake8::
	${FLAKE8} ${FLAKE8_ARGS} --application-import-names=reprise reprise tests

mypy::
	${MYPY} reprise tests

isort-check::
	${ISORT} ${ISORT_ARGS} --check $$(find . -name "*.py")

isort::
	${ISORT} ${ISORT_ARGS} $$(find . -name "*.py")

sdist::
	${PYTHON} setup.py sdist

release::
	rm -rf dist
	${PYTHON} setup.py sdist
	${TWINE} upload dist/*.tar.gz
