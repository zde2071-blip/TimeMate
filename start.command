#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -c 'import sys; assert sys.version_info >= (3,12), "请先安装 Python 3.12 或更高版本"'
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements/cloud.txt
fi
exec .venv/bin/python -m backend.local "$@"
