#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -c 'import sys; assert sys.version_info >= (3,12), "请先安装 Python 3.12 或更高版本"'
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import flask, waitress, cryptography, certifi, jsonschema, charset_normalizer" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements/cloud.txt
fi
exec .venv/bin/python -m backend.local "$@"
