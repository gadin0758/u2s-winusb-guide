"""Local F50 workflow. Firmware and private backup images never leave this PC."""
import argparse
import ctypes as c
import json
import pathlib
import shutil
import struct
import time
import hashlib
from f50lib import USB, Device, check, frame, partition_payload, parse_gpt, save_json, sha256

SYSTEM = ('trustos_a','sml_a','teecfg_a','boot_a','vendor_boot_a','dtbo_a','common_rs1_a',
          'vbmeta_a','vbmeta_system_a','vbmeta_vendor_a','vbmeta_system_ext_a',
          'vbmeta_product_a','vbmeta_odm_a','super')
PROTECTED = {'prodnv','miscdata','calinv','persist','ztecfg','ztepersist',
             'splloader','uboot_a','uboot_b','pm_sys_a','pm_sys_b'}

def protected(name):
    return name.startswith(('nr_','l_')) or name in PROTECTED

def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))

def verify_backup(folder):
    folder=pathlib.Path(folder);manifest=load(folder/'verified-manifest.json')
    check(manifest.get('complete') is True, 'Backup must be complete')
    check(manifest.get('gpt_header_crc_valid') and manifest.get('gpt_entries_crc_valid'), 'Backup GPT not validated')
    check(sha256(folder/'pgpt.bin')==manifest['gpt_sha256'], 'Backup GPT hash mismatch')
    gpt=parse_gpt((folder/'pgpt.bin').read_bytes())
    names={p['name'] for p in manifest['partitions']}
    check(len(names)==len(manifest['partitions']), 'Duplicate backup manifest names')
    check(names=={p['name'] for p in gpt}|{'splloader'}, 'Incomplete full backup manifest')
    specs={p['name']:p for p in gpt}
    specs['splloader']={'expected_size':262144, 'offset':0, 'source':'splloader'}
    for p in manifest['partitions']:
        spec=specs[p['name']]
        for key in ('expected_size','offset','source'):
            check(p.get(key)==spec[key], 'Backup range mismatch: '+p['name'])
        if p['name']!='splloader':
            check(p.get('start_sector')==spec['start_sector'] and p.get('end_sector')==spec['end_sector'], 'Backup sector mismatch')
        path=folder/p['file']
        check(path.resolve().parent==folder.resolve(), 'Unsafe backup file path')
        check(path.stat().st_size==p['expected_size'] and sha256(path)==p['sha256'], 'Backup invalid: '+p['name'])
    return manifest

def connect(args):
    # The probe is separate from FDL loading and leaves the download version packet unread.
    api=USB(args.dll);check(api.init(c.byref(api.ctx))==0,'libusb init failed')
    old=None;wait_remove=False;previous=None;switched=False;deadline=time.monotonic()+args.wait
    print('READY: unplug, power off F50, then insert into the same PC USB port.',flush=True)
    try:
        while time.monotonic()<deadline:
            devices=c.POINTER(c.c_void_p)();count=api.getlist(api.ctx,c.byref(devices));keys=[]
            try:
                for i in range(max(count,0)):
                    d=Device()
                    if api.desc(devices[i],c.byref(d))==0 and (d.vid,d.pid)==(0x1782,0x4d00):
                        keys.append((int(api.bus(devices[i])),int(api.address(devices[i]))))
            finally:
                if devices:api.freelist(devices,1)
            check(len(keys)<=1,'Disconnect additional matching devices')
            state=tuple(keys)
            if old is None and state:wait_remove=True;previous=state[0]
            if state!=old:print('Target present:',bool(state),flush=True);old=state
            if wait_remove and previous not in state:wait_remove=False
            if state and not wait_remove:
                if switched:
                    print('HANDOFF READY: start LibUSB spd_dump; do not unplug.',flush=True);return
                with USB(args.dll) as usb:
                    result=usb.control(usb.handle,0x21,34,0x601,0,None,0,1000)
                    check(result>=0,'USB line-state control failed')
                    usb.send(bytes.fromhex('7e 00 00 00 00 08 00 fe 82 7e'),1500)
                    try:usb.receive(1000)
                    except RuntimeError:pass  # Device may disconnect immediately after mode change.
                switched=True;wait_remove=True;previous=state[0]
                print('Mode 2 requested; waiting for USB re-enumeration.',flush=True)
            time.sleep(0.08)
        raise RuntimeError('Timed out without a download-mode handoff')
    finally:
        api.exit(api.ctx)

def backup(args):
    out=pathlib.Path(args.out).resolve();check(not out.exists(),'Choose a new backup directory')
    out.mkdir(parents=True)
    manifest={'complete':False,'partitions':[]}
    with USB(args.dll) as usb:
        check(usb.read_command(0x12)[0]==0x80,'Not an existing raw-frame FDL2 session')
        pgpt=usb.read_range({'name':'pgpt','source':'user_partition','offset':0,'expected_size':32768,'file':'pgpt.bin'},out)
        parts=parse_gpt((out/'pgpt.bin').read_bytes())
        parts.append({'name':'splloader','source':'splloader','offset':0,'expected_size':262144,'file':'splloader.bin'})
        total=sum(p['expected_size'] for p in parts)
        check(total<128*1024**3,'Unexpected F50 storage capacity')
        check(shutil.disk_usage(out).free>total+1024**3,'Insufficient free disk space for a complete backup')
        manifest.update(gpt_header_crc_valid=True,gpt_entries_crc_valid=True,gpt_sha256=pgpt['sha256'])
        save_json(out/'verified-manifest.json',manifest)
        for p in parts:
            print('BACKUP',p['name'],p['expected_size'],flush=True)
            manifest['partitions'].append(usb.read_range(p,out))
            save_json(out/'verified-manifest.json',manifest)
        manifest['complete']=True;save_json(out/'verified-manifest.json',manifest)
    (out/'SHA256SUMS.txt').write_text(''.join(p['sha256']+'  '+p['file']+'\n' for p in manifest['partitions']),encoding='ascii')
    print('COMPLETE',len(parts),'files,',total,'bytes; excludes inaccessible RPMB/eFuse areas.')

def validate_super(path):
    with path.open('rb') as f:
        geometries=[]
        for off in (4096,8192):
            f.seek(off);g=f.read(52)
            check(struct.unpack_from('<II',g)==(0x616c4467,52),'Invalid super geometry')
            check(hashlib.sha256(g[:8]+bytes(32)+g[40:]).digest()==g[8:40],'Invalid super geometry checksum')
            geometries.append(g)
        check(geometries[0]==geometries[1],'Super geometry copies differ')
        f.seek(12288);h=f.read(256);magic,major,minor,hs=struct.unpack_from('<IHHI',h)
        check(magic==0x414c5030 and 128<=hs<=256,'Invalid super metadata header')
        check(hashlib.sha256(h[:12]+bytes(32)+h[44:hs]).digest()==h[12:44],'Invalid metadata header checksum')
        size=struct.unpack_from('<I',h,44)[0];check(size<=1024*1024,'Unexpected metadata table size')
        f.seek(12288+hs);table=f.read(size)
        check(hashlib.sha256(table).digest()==h[48:80],'Invalid metadata table checksum')
        off,count,width=struct.unpack_from('<III',h,80)
        check(width>=36 and off+count*width<=len(table),'Invalid logical partition table')
        names=[table[off+i*width:off+i*width+36].split(b'\0')[0].decode() for i in range(count)]
        check('system_a' in names and 'vendor_a' in names,'Required logical partitions absent')
        return names

def plan(args):
    backup_dir=pathlib.Path(args.backup).resolve();manifest=verify_backup(backup_dir)
    out=pathlib.Path(args.out).resolve();check(not out.exists(),'Choose a new plan directory')
    check(str(out).isascii(),'Use an ASCII staging path for upstream Windows spd_dump')
    package=pathlib.Path(args.package).resolve();parts={p['name']:p for p in manifest['partitions']}
    check(all(name in parts for name in SYSTEM),'Unsupported partition layout')
    for name in ('nr_modem_a','nr_phy_a'):
        check(sha256(package/'data'/(name+'.bin'))==parts[name]['sha256'],
              'Package modem/PHY differs from this B15 backup: '+name)
    out.mkdir(parents=True);(out/'images').mkdir();(out/'readback').mkdir();records=[]
    for name in SYSTEM:
        check(not protected(name),'Refuse protected target')
        src=package/'data'/(name+'.bin')
        # The author's batch explicitly writes this trustos image after write_parts.
        if name=='trustos_a' and (package/'bin'/'f50b09_t.bin').exists():src=package/'bin'/'f50b09_t.bin'
        check(0<src.stat().st_size<=parts[name]['expected_size'],'Image does not fit: '+name)
        dst=out/'images'/(name+'.bin');shutil.copyfile(src,dst);h=sha256(src)
        check(sha256(dst)==h,'Staged image differs')
        records.append({'name':name,'staged':str(dst),'size':dst.stat().st_size,
                        'partition_size':parts[name]['expected_size'],'sha256':h})
    logical=validate_super(out/'images'/'super.bin')
    commands=['timeout 30000','blk_size 65024']
    commands += ['w '+r['name']+' "'+r['staged']+'"' for r in records]
    commands += ['e metadata','e cache','set_active a']
    commands += ['read_part '+r['name']+' 0 '+str(r['partition_size'])+' "'+str(out/'readback'/(r['name']+'.bin'))+'"' for r in records]
    report={'backup':str(backup_dir),'backup_gpt_sha256':manifest['gpt_sha256'],'active_slot':'a',
            'images':records,'logical_partitions':logical,'commands':commands,
            'protected':[p for p in manifest['partitions'] if protected(p['name'])]}
    save_json(out/'plan.json',report)
    (out/'reviewed-commands.txt').write_text('\n'.join(commands)+'\n',encoding='ascii')
    print('PLAN ONLY: no device operations. Review images and commands before executing.')

def verify_system(args):
    out=pathlib.Path(args.plan).resolve();p=load(out/'plan.json');records=[]
    check(tuple(r['name'] for r in p['images'])==SYSTEM,'Unexpected write list')
    for r in p['images']:
        path=out/'readback'/(r['name']+'.bin')
        check(path.stat().st_size==r['partition_size'],'Incomplete readback: '+r['name'])
        check(sha256(path,r['size'])==r['sha256'],'Readback differs: '+r['name'])
        records.append({'name':r['name'],'sha256':sha256(path),'source_prefix_matches':True})
        print('VERIFIED',r['name'],flush=True)
    save_json(out/'system-verification.json',{'all_match':True,'images':records})

def snapshot(args,post=False):
    out=pathlib.Path(args.plan).resolve();plan=load(out/'plan.json')
    folder=out/('post-protected' if post else 'pre-protected')
    check(not folder.exists(),'Choose a fresh snapshot; never overwrite the baseline')
    folder.mkdir();records=[]
    baseline={p['name']:p for p in load(out/'pre-protected'/'manifest.json')} if post else {}
    with USB(args.dll) as usb:
        check(usb.read_command(0x12)[0]==0x80,'FDL2 read interface not ready')
        g=usb.read_range({'name':'pgpt','source':'user_partition','offset':0,'expected_size':32768,'file':'pgpt.bin'},folder)
        check(g['sha256']==plan['backup_gpt_sha256'],'Connected device GPT differs from backup')
        for p in plan['protected']:
            spec={**p,'source':'splloader' if p['name']=='splloader' else 'user_partition',
                  'offset':0 if p['name']=='splloader' else p['start_sector']*512,'file':p['name']+'.bin'}
            record=usb.read_range(spec,folder)
            if post:check(record['sha256']==baseline[p['name']]['sha256'],'Protected partition changed: '+p['name'])
            elif p['name'] in ('nr_modem_a','nr_phy_a','splloader','uboot_a','uboot_b'):
                check(record['sha256']==p['sha256'],'Immutable partition differs from backup: '+p['name'])
            records.append(record);save_json(folder/'manifest.json',records)
    if post:save_json(out/'protected-verification.json',{'all_unchanged':True,'count':len(records)})
    print('PROTECTED', 'UNCHANGED' if post else 'SNAPSHOT COMPLETE',len(records))

def restricted_action(args):
    out=pathlib.Path(args.plan).resolve();plan=load(out/'plan.json');system=load(out/'system-verification.json')
    check(system['all_match'] and tuple(r['name'] for r in system['images'])==SYSTEM,'System readback required')
    baseline=load(out/'pre-protected'/'manifest.json')
    check({r['name'] for r in baseline}=={p['name'] for p in plan['protected']},'Complete protected baseline required')
    if args.action=='erase-userdata':
        check(args.confirm=='ERASE_USERDATA','Pass --confirm ERASE_USERDATA after reviewing data loss')
        folder=out/'erasure-samples'
        check(not folder.exists() and not (out/'userdata-verification.json').exists(),'Refuse re-erasing this run')
        parts=load(pathlib.Path(plan['backup'])/'verified-manifest.json')['partitions']
        p=next(p for p in parts if p['name']=='userdata')
        check(p['expected_size']>=65536,'Unexpected userdata size')
        folder.mkdir()
    elif args.action=='reset':
        v=load(out/'protected-verification.json')
        check(v['all_unchanged'] and v['count']==len(plan['protected']),'Protected comparison required')
        v=load(out/'userdata-verification.json')
        check(v['acknowledged'] and v['samples_blank'] and len(v['samples'])==3,'Userdata erasure verification required')
        check(args.confirm=='REBOOT','Pass --confirm REBOOT')
    with USB(args.dll) as usb:
        # Check the connected layout before any destructive operation.
        check(usb.read_command(0x12)[0]==0x80,'FDL2 read interface not ready')
        guard=out/('erase-preflight' if args.action=='erase-userdata' else 'reset-preflight')
        check(not guard.exists(),'Choose a fresh run; this action was already attempted')
        guard.mkdir()
        g=usb.read_range({'name':'pgpt','source':'user_partition','offset':0,'expected_size':32768,'file':'pgpt.bin'},guard)
        check(g['sha256']==plan['backup_gpt_sha256'],'Connected GPT differs')
        for r in baseline:
            current=usb.read_range(r,guard)
            check(current['sha256']==r['sha256'],'Protected data changed before action: '+r['name'])
        if args.action=='erase-userdata':
            misc=next(q for q in parts if q['name']=='misc')
            usb.read_range({'name':'misc-command','source':'user_partition','offset':misc['start_sector']*512,
                            'expected_size':2048,'file':'misc-command.bin'},guard)
            check(not (guard/'misc-command.bin').read_bytes().startswith(b'boot-recovery'), 'Recovery wipe command present; stop and inspect misc')
            usb.send(frame(0x0a,partition_payload('userdata',0)))
            check(usb.receive()[0]==0x80,'Named userdata erasure not acknowledged')
            samples=[]
            for label,rel in [('start',0),('middle',p['expected_size']//2//4096*4096),('end',p['expected_size']-65536)]:
                r=usb.read_range({'name':label,'source':'user_partition','offset':p['start_sector']*512+rel,
                                 'expected_size':65536,'file':label+'.bin'},folder)
                data=(folder/r['file']).read_bytes()
                check(data==bytes(len(data)) or data==b'\xff'*len(data),'Erasure sample not blank')
                samples.append(r)
            save_json(out/'userdata-verification.json',{'acknowledged':True,'samples_blank':True,'samples':samples})
        elif args.action=='reset':
            usb.send(frame(0x05))
            check(usb.receive()[0]==0x80,'Reset not acknowledged; inspect device manually')
            print('RESET acknowledged; runtime version/network still need separate verification.')

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    for action in ('connect','backup','snapshot','audit','erase-userdata','reset'):
        a=sub.add_parser(action);a.add_argument('--dll',required=True)
        if action=='connect':a.add_argument('--wait',type=int,default=300)
        elif action=='backup':a.add_argument('--out',required=True)
        else:a.add_argument('--plan',required=True)
        if action in ('erase-userdata','reset'):a.add_argument('--confirm',required=True)
    a=sub.add_parser('plan');a.add_argument('--backup',required=True);a.add_argument('--package',required=True);a.add_argument('--out',required=True)
    a=sub.add_parser('verify-system');a.add_argument('--plan',required=True)
    a=sub.add_parser('verify-backup');a.add_argument('--backup',required=True)
    args=p.parse_args()
    if args.action=='connect':connect(args)
    elif args.action=='backup':backup(args)
    elif args.action=='plan':plan(args)
    elif args.action=='verify-system':verify_system(args)
    elif args.action=='verify-backup':verify_backup(args.backup);print('BACKUP VERIFIED')
    elif args.action in ('snapshot','audit'):snapshot(args,args.action=='audit')
    else:restricted_action(args)

if __name__=='__main__':
    try:main()
    except (RuntimeError,OSError,KeyError,ValueError,StopIteration) as e:
        raise SystemExit('STOPPED: '+str(e))
