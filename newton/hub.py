"""Single-instance local hub launcher. Opening it never starts an AI worker."""
from argparse import ArgumentParser
import ctypes
import http.client
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import webbrowser
from .api import NewtonAPI, LocalServer
from .observability import storage, safe_file

PROJECT=Path(__file__).resolve().parents[1]

def process_exists(pid):
    if type(pid) is not int or pid<=0:return False
    if sys.platform=='win32':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.get_last_error()==5
        try:
            code=ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True

def existing_link(path,root,mode):
    if not path.is_file() or path.stat().st_size>4000:return None
    try:
        d=json.loads(path.read_text(encoding='utf-8'))
        if d.get('project')!=str(Path(root).resolve()) or d.get('mode')!=mode or not process_exists(d.get('pid')):return None
        u=urlsplit(d['origin'])
        if u.scheme!='http' or u.hostname!='127.0.0.1' or not u.port or u.username or u.password or u.path or u.query or u.fragment:return None
        if not isinstance(d.get('token'),str) or not 16<=len(d['token'])<=100:return None
        conn=http.client.HTTPConnection('127.0.0.1',u.port,timeout=.5)
        try:
            conn.request('GET','/api/info',headers={'Authorization':'Bearer '+d['token']})
            response=conn.getresponse();data=json.loads(response.read(16000))
            if response.status!=200 or data.get('project_root')!=d['project'] or data.get('mode')!=mode:return None
        finally:conn.close()
        return d['origin']+'/#token='+d['token']
    except (OSError,ValueError,KeyError,http.client.HTTPException):return None

def launch(root=PROJECT,mode='codex',open_browser=True):
    root=Path(root).resolve();base=storage(root)
    lock=safe_file(base,'launcher-'+mode+'.lock');manifest=safe_file(base,'launcher-'+mode+'.json')
    for attempt in range(2):
        try:
            fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd);break
        except FileExistsError:
            for _ in range(8):
                link=existing_link(manifest,root,mode)
                if link:
                    if open_browser:webbrowser.open(link)
                    return 'reused'
                time.sleep(.25)
            try:owner=int(lock.read_text(encoding='utf-8'))
            except (ValueError,OSError):raise RuntimeError('launcher_lock_needs_inspection') from None
            if process_exists(owner):raise RuntimeError('existing_hub_not_responding')
            lock.unlink(missing_ok=True);manifest.unlink(missing_ok=True)
    else:raise RuntimeError('hub_launch_conflict')
    application=None;server=None
    try:
        application=NewtonAPI(root,mode);server=LocalServer(application,0)
        manifest.write_text(json.dumps({'project':str(root),'mode':mode,'pid':os.getpid(),'origin':server.origin,'token':server.token}),encoding='utf-8')
        link=server.origin+'/#token='+server.token
        if sys.stdout:print('Newton Hub | '+mode+'\n'+link+'\nNo worker started. Use Stop hub in the app to close.',flush=True)
        if open_browser:webbrowser.open(link)
        server.serve_forever(poll_interval=.2)
    finally:
        if server:server.server_close()
        if application:application.close()
        manifest.unlink(missing_ok=True);lock.unlink(missing_ok=True)
    return 'stopped'

def main():
    parser=ArgumentParser(description='Open Newton Hub without terminal setup')
    parser.add_argument('--mode',choices=('codex','mock'),default='codex')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    try:launch(mode=args.mode,open_browser=not args.no_browser)
    except KeyboardInterrupt:pass
    except Exception as error:
        base=storage(PROJECT);message='Newton could not open: '+type(error).__name__+'. See docs/NEWTON_HUB.md. No AI worker was launched by opening the hub.'
        safe_file(base,'launcher-error.txt').write_text(message,encoding='utf-8')
        if sys.stderr:print(message,file=sys.stderr)
        elif sys.platform=='win32':ctypes.windll.user32.MessageBoxW(None,message,'Newton Hub',0x10)
        raise SystemExit(1)

if __name__=='__main__':main()
