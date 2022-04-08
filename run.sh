#!/bin/sh

sudo env PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python3 -m reprise "$@"
