"""Execute reviewed system-only spd_dump commands; stop at the first bad completion."""
import argparse
import pathlib
import queue
import re
import subprocess
import threading
import time
from f50 import SYSTEM, load, verify_backup, verify_system
from f50lib import check, sha256

def checked_completion(text, operation, name, size=None):
    if operation=='erase':
        check(re.search(r'Erase Part Done: '+re.escape(name)+r'(?:\r?\n|$)',text),'Erase completion missing: '+name)
        return
    pattern=(r'Write Part Done: '+re.escape(name)+r', target: 0x([0-9a-f]+), written: 0x([0-9a-f]+)' if operation=='write'
             else r'Read Part Done: '+re.escape(name)+r'\+0x0, target: 0x([0-9a-f]+), read: 0x([0-9a-f]+)')
    matches=re.findall(pattern,text,re.I)
    check(matches and all(int(a,16)==int(b,16)==size for a,b in matches),'Incomplete '+operation+': '+name)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',required=True);p.add_argument('--tool',required=True)
    p.add_argument('--execute',action='store_true')
    args=p.parse_args();out=pathlib.Path(args.plan).resolve();plan=load(out/'plan.json')
    check(tuple(r['name'] for r in plan['images'])==SYSTEM,'Unexpected system targets')
    if not args.execute:
        print((out/'reviewed-commands.txt').read_text());print('DRY RUN: add --execute only after full backup and pre-protected snapshot.');return
    check(not (out/'system-verification.json').exists(),'Refuse re-executing a completed run')
    verify_backup(plan['backup'])
    baseline=load(out/'pre-protected'/'manifest.json')
    check({r['name'] for r in baseline}=={r['name'] for r in plan['protected']},'Incomplete protected baseline')
    for r in baseline:
        file=out/'pre-protected'/r['file']
        check(file.stat().st_size==r['expected_size'] and sha256(file)==r['sha256'],'Protected baseline file invalid')
    preflight=out/'live-preflight'
    check(not preflight.exists(),'A write attempt already exists; inspect it before making a new plan')
    preflight.mkdir()
    for r in plan['images']:check(sha256(r['staged'])==r['sha256'],'Staged image changed: '+r['name'])
    tool=pathlib.Path(args.tool).resolve()
    check(tool.name.lower()=='spd_dump.exe' and (tool.parent/'libusb-1.0.dll').exists(),'LibUSB upstream tool required')
    process=subprocess.Popen([str(tool),'--wait','30','--stage','99','--verbose','0'],cwd=out,
                             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    incoming=queue.Queue()
    def pump():
        while True:
            data=process.stdout.read(1)
            if not data:incoming.put(None);return
            incoming.put(data)
    threading.Thread(target=pump,daemon=True).start()
    log=(out/'spd-session.log').open('ab')
    def prompt(timeout=180):
        deadline=time.monotonic()+timeout;data=bytearray()
        while time.monotonic()<deadline:
            try:b=incoming.get(timeout=0.5)
            except queue.Empty:continue
            check(b is not None,'spd_dump exited before completion')
            data.extend(b);log.write(b)
            if data.endswith(b'FDL2 >'):
                text=data.decode('utf8','replace')
                print(text[-1000:],flush=True);log.flush();return text
        raise RuntimeError('Timed out; flash state may be incomplete. Do not reboot.')
    def command(s):
        check('\n' not in s and '\r' not in s,'Invalid command')
        process.stdin.write((s+'\n').encode('ascii'));process.stdin.flush();return prompt()
    try:
        prompt()
        command('timeout 30000');command('blk_size 65024')
        command('partition_list connected-gpt.xml')
        check(sha256(out/'pgpt.bin')==plan['backup_gpt_sha256'],'Connected GPT differs from backup')
        # Same GPT alone cannot identify a device. Compare all protected contents.
        for r in baseline:
            file=preflight/(r['name']+'.bin')
            source=r['source'];offset=r['offset'];size=r['expected_size']
            text=command('read_part '+source+' '+str(offset)+' '+str(size)+' "'+str(file)+'"')
            pattern=r'Read Part Done: '+re.escape(source)+r'\+0x([0-9a-f]+), target: 0x([0-9a-f]+), read: 0x([0-9a-f]+)'
            matches=re.findall(pattern,text,re.I)
            check(matches and all(int(a,16)==offset and int(b,16)==int(c,16)==size for a,b,c in matches),'Incomplete preflight read')
            check(file.stat().st_size==size and sha256(file)==r['sha256'],'Connected protected contents differ: '+r['name'])
        for r in plan['images']:
            text=command('w '+r['name']+' "'+r['staged']+'"')
            checked_completion(text,'write',r['name'],r['size'])
        for name in ('metadata','cache'):
            checked_completion(command('e '+name),'erase',name)
        text=command('set_active a')
        check('Write Part Done: misc' in text,'Slot control not written')
        for r in plan['images']:
            text=command('read_part '+r['name']+' 0 '+str(r['partition_size'])+' "'+str(out/'readback'/(r['name']+'.bin'))+'"')
            checked_completion(text,'read',r['name'],r['partition_size'])
        verify_system(argparse.Namespace(plan=str(out)))
        print('System verified. FDL2 stays loaded. No userdata wrapper or reboot executed.')
    finally:
        # Only a host-side process shutdown; never send device reset on error.
        if process.poll() is None:process.terminate()
        process.wait(timeout=10);log.close()

if __name__=='__main__':
    try:main()
    except (RuntimeError,OSError,KeyError,ValueError) as e:raise SystemExit('STOPPED: '+str(e))
