"""Single-user loopback launcher. No cloud account or mail-verification service."""
import argparse
import os
from pathlib import Path
import threading
import time
import webbrowser
from cryptography.fernet import Fernet
from backend.cloud import create_app


def load_key(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = directory / 'local.secret'
    if not key.exists():
        with key.open('xb') as handle:
            handle.write(Fernet.generate_key())
    return key.read_bytes().strip()


def main():
    parser = argparse.ArgumentParser(description='TimeMate 本地版')
    parser.add_argument('--port', type=int, default=18744)
    parser.add_argument('--data-dir', type=Path, default=Path.home()/'.timemate')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('端口需在 1–65535 之间')
    os.umask(0o077)
    directory = args.data_dir.expanduser().resolve()
    key = load_key(directory)
    # Reject concurrent launches sharing the same writable mail database.
    import fcntl
    lock = (directory/'server.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('此数据目录已有 TimeMate 在运行')
    origin = f'http://127.0.0.1:{args.port}'
    app = create_app(directory, key, origin, local=True)
    def scheduler():
        while True:
            app.store.tick()
            time.sleep(60)
    threading.Thread(target=scheduler, daemon=True).start()
    if not args.no_browser:
        threading.Timer(1, lambda: webbrowser.open(origin)).start()
    from waitress import serve
    print(f'TimeMate 本地版：{origin}\n数据目录：{directory}', flush=True)
    serve(app, host='127.0.0.1', port=args.port, threads=8)


if __name__ == '__main__':
    main()
