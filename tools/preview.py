"""Local-only launcher; stores a private development key outside tracked code."""
import os
from pathlib import Path
from cryptography.fernet import Fernet
root=Path(__file__).resolve().parents[1]
os.umask(0o077)
key=root/'cloud-data'/'development.secret'
key.parent.mkdir(exist_ok=True,mode=0o700)
if not key.exists():
    with key.open('x') as f: f.write(Fernet.generate_key().decode())
os.environ['MAIL_MASTER_KEY']=key.read_text().strip()
os.environ['MAIL_DATA_DIR']=str(key.parent)
os.environ['MAIL_ORIGIN']='http://127.0.0.1:18744'
os.environ['MAIL_BIND']='127.0.0.1'
os.environ['PORT']='18744'
import runpy,sys
sys.argv=[str(root/'cloud.py'),'serve']
runpy.run_path(str(root/'cloud.py'),run_name='__main__')
