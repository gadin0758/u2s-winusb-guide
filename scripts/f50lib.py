"""F50 FDL2 reads and WinUSB binding. Requires an existing raw-frame FDL2 session.

No CONNECT, FDL execution, partition-write or erase commands are exposed here.
Protocol reference: TomKing062/spreadtrum_flash, stable_20250726_0012.
"""
import ctypes as c
import hashlib
import json
import pathlib
import re
import struct
import sys
import time
import uuid
import zlib

READ_START, READ_MIDST, READ_END = 0x10, 0x11, 0x12

def check(condition, message):
    if not condition:
        raise RuntimeError(message)

def checksum(data):
    # Little-endian 16-bit ones-complement sum, with upstream's final swap.
    total = sum(int.from_bytes(data[i:i+2], 'little') for i in range(0, len(data), 2))
    total = (total >> 16) + (total & 0xffff)
    total += total >> 16
    total = ~total & 0xffff
    return ((total >> 8) | ((total & 255) << 8)) if len(data) % 2 == 0 else total

def frame(code, payload=b''):
    check(len(payload) <= 0xffff, 'Packet payload too large')
    body = struct.pack('>HH', code, len(payload)) + payload
    return b'\x7e' + body + struct.pack('>H', checksum(body)) + b'\x7e'

def parse_frame(packet):
    check(len(packet) >= 8 and packet[0] == packet[-1] == 0x7e, 'Bad frame markers')
    code, length = struct.unpack_from('>HH', packet, 1)
    check(len(packet) == length + 8, 'Bad frame length')
    check(checksum(packet[1:-3]) == struct.unpack_from('>H', packet, len(packet)-3)[0], 'Bad frame checksum')
    return code, packet[5:-3]

def partition_payload(name, total, mode64=False):
    check(len(name.encode('utf-16-le')) < 72 and total >= 0, 'Invalid partition request')
    return name.encode('utf-16-le').ljust(72, b'\0') + (
        struct.pack('<IIQ', total & 0xffffffff, total >> 32, 0) if mode64 else struct.pack('<I', total))

def sha256(path, limit=None):
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        while limit is None or limit > 0:
            chunk = f.read(8*1024*1024 if limit is None else min(limit, 8*1024*1024))
            if not chunk:
                break
            h.update(chunk)
            if limit is not None:
                limit -= len(chunk)
    check(limit is None or limit == 0, 'File is shorter than expected')
    return h.hexdigest()

def save_json(path, value):
    pathlib.Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')

def parse_gpt(data, sector=512):
    check(sector == 512 and len(data) >= 1024, 'Expected a complete 512-byte-sector GPT')
    header = data[sector:sector*2]
    check(header[:8] == b'EFI PART', 'Not the expected 512-byte-sector GPT')
    size = struct.unpack_from('<I', header, 12)[0]
    check(92 <= size <= sector, 'Invalid GPT header size')
    expected = struct.unpack_from('<I', header, 16)[0]
    cleared = bytearray(header[:size]); cleared[16:20] = bytes(4)
    check(zlib.crc32(cleared) == expected, 'GPT header CRC mismatch')
    lba, count, width, crc = struct.unpack_from('<QIII', header, 72)
    check(width >= 128 and count*width <= len(data), 'GPT entry bounds invalid')
    entries = data[lba*sector:lba*sector+count*width]
    check(len(entries) == count*width and zlib.crc32(entries) == crc, 'GPT entries CRC mismatch')
    records = []
    for i in range(count):
        entry = entries[i*width:(i+1)*width]
        if entry[:16] == bytes(16):
            continue
        start, end = struct.unpack_from('<QQ', entry, 32)
        name = entry[56:128].decode('utf-16-le').split('\0')[0]
        check(re.fullmatch(r'[a-zA-Z0-9_]+', name), 'Unsafe GPT name')
        check(end >= start, 'Invalid GPT range')
        records.append({'name': name, 'file': name+'.bin', 'start_sector': start,
                        'end_sector': end, 'offset': start*sector,
                        'expected_size': (end-start+1)*sector, 'source': 'user_partition'})
    check(len({p['name'] for p in records}) == len(records), 'Duplicate GPT names')
    ranges = sorted((p['start_sector'], p['end_sector']) for p in records)
    check(all(a[1] < b[0] for a, b in zip(ranges, ranges[1:])), 'Overlapping GPT ranges')
    return records

class Device(c.Structure):
    _fields_ = [('length',c.c_uint8),('type',c.c_uint8),('usb',c.c_uint16),
        ('cls',c.c_uint8),('sub',c.c_uint8),('protocol',c.c_uint8),('packet',c.c_uint8),
        ('vid',c.c_uint16),('pid',c.c_uint16),('version',c.c_uint16),
        ('manufacturer',c.c_uint8),('product',c.c_uint8),('serial',c.c_uint8),('configs',c.c_uint8)]

class USB:
    def __init__(self, dll):
        check(sys.platform == 'win32', 'Live USB operations require Windows')
        self.dll = c.WinDLL(str(pathlib.Path(dll).resolve()))
        self.ctx=c.c_void_p(); self.handle=c.c_void_p(); self.devices=c.POINTER(c.c_void_p)()
        self.claimed=False
        def bind(name, result, *args):
            fn=getattr(self.dll, 'libusb_'+name); fn.restype=result; fn.argtypes=list(args);return fn
        p=c.c_void_p
        self.init=bind('init',c.c_int,c.POINTER(p)); self.exit=bind('exit',None,p)
        self.getlist=bind('get_device_list',c.c_ssize_t,p,c.POINTER(c.POINTER(p)))
        self.freelist=bind('free_device_list',None,c.POINTER(p),c.c_int)
        self.desc=bind('get_device_descriptor',c.c_int,p,c.POINTER(Device))
        self.open=bind('open',c.c_int,p,c.POINTER(p));self.close=bind('close',None,p)
        self.claim=bind('claim_interface',c.c_int,p,c.c_int);self.release=bind('release_interface',c.c_int,p,c.c_int)
        self.bulk=bind('bulk_transfer',c.c_int,p,c.c_uint8,p,c.c_int,c.POINTER(c.c_int),c.c_uint)
        self.control=bind('control_transfer',c.c_int,p,c.c_uint8,c.c_uint8,c.c_uint16,c.c_uint16,p,c.c_uint16,c.c_uint)
        self.bus=bind('get_bus_number',c.c_uint8,p);self.address=bind('get_device_address',c.c_uint8,p)
    def __enter__(self):
        try:
            check(self.init(c.byref(self.ctx))==0, 'libusb initialization failed')
            count=self.getlist(self.ctx,c.byref(self.devices));targets=[]
            for i in range(max(count,0)):
                d=Device()
                if self.desc(self.devices[i],c.byref(d))==0 and (d.vid,d.pid)==(0x1782,0x4d00):
                    targets.append(self.devices[i])
            check(len(targets)==1, 'Expected exactly one F50 1782:4d00 download device')
            check(self.open(targets[0],c.byref(self.handle))==0, 'USB open failed; check driver/busy process')
            check(self.claim(self.handle,0)==0, 'USB interface claim failed')
            self.claimed=True
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise
    def __exit__(self,*args):
        if self.claimed:self.release(self.handle,0)
        if self.handle:self.close(self.handle)
        if self.devices:self.freelist(self.devices,1)
        if self.ctx:self.exit(self.ctx)
    def send(self, data, timeout=30000):
        buf=c.create_string_buffer(data); n=c.c_int()
        result=self.bulk(self.handle,0x01,buf,len(data),c.byref(n),timeout)
        check(result==0 and n.value==len(data), 'USB send failed: '+str(result))
    def receive(self, timeout=30000):
        packet=bytearray()
        while True:
            buf=c.create_string_buffer(1024*1024); n=c.c_int()
            result=self.bulk(self.handle,0x81,buf,len(buf),c.byref(n),timeout)
            check(result==0, 'USB receive failed: '+str(result))
            packet.extend(buf.raw[:n.value])
            if len(packet)>=5 and len(packet)>=struct.unpack_from('>H',packet,3)[0]+8:break
            check(len(packet)<1024*1024, 'Oversized USB reply')
        return parse_frame(packet)
    def read_command(self, code, payload=b''):
        check(code in (READ_START,READ_MIDST,READ_END), 'Read-only command policy')
        self.send(frame(code,payload));return self.receive()
    def read_range(self, spec, directory):
        directory=pathlib.Path(directory);directory.mkdir(parents=True,exist_ok=True)
        target=directory/spec['file'];partial=directory/(spec['file']+'.partial')
        check(not target.exists() and not partial.exists(), 'Refuse overwrite: '+str(target))
        start=spec.get('offset',spec.get('start_sector',0)*512);length=spec['expected_size']
        mode64=start+length>0xffffffff
        code,_=self.read_command(READ_START,partition_payload(spec.get('source','user_partition'),start+length,mode64))
        check(code==0x80,'READ_START not acknowledged')
        digest=hashlib.sha256();done=0;begin=time.monotonic();last=begin
        try:
            with partial.open('xb') as f:
                while done<length:
                    size=min(65024,length-done);off=start+done
                    payload=struct.pack('<III',size,off&0xffffffff,off>>32) if mode64 else struct.pack('<II',size,off)
                    code,data=self.read_command(READ_MIDST,payload)
                    check(code==0x93 and len(data)==size,'READ_MIDST failed')
                    f.write(data);digest.update(data);done+=size
                    now=time.monotonic()
                    if now-last>=30:
                        print(f'{spec["name"]}: {done/length:.1%}, {done/(now-begin)/1048576:.1f} MiB/s',flush=True);last=now
            check(self.read_command(READ_END)[0]==0x80,'READ_END not acknowledged')
            check(sha256(partial)==digest.hexdigest(),'Saved file hash differs from USB stream')
            partial.rename(target)
            return {**spec,'actual_size':done,'sha256':digest.hexdigest(),'size_valid':True}
        except BaseException:
            try:self.read_command(READ_END)
            except Exception:pass
            raise
