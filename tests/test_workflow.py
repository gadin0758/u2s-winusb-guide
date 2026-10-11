import argparse
import hashlib
import pathlib
import struct
import sys
import contextlib
import shutil
import uuid
import unittest
import zlib
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import f50
from f50lib import USB, frame, parse_frame, parse_gpt, partition_payload, save_json, sha256
from run_spd_plan import checked_completion


@contextlib.contextmanager
def temporary_directory():
    # Inherit workspace ACLs: Windows sandbox tokens cannot reopen mkdtemp's
    # owner-only directory. Every test owns only its unique child of runs/.
    root = pathlib.Path(__file__).resolve().parents[1] / 'runs'
    root.mkdir(exist_ok=True)
    folder = root / ('test-' + uuid.uuid4().hex)
    folder.mkdir()
    try:
        yield str(folder)
    finally:
        if folder.resolve().parent != root.resolve():
            raise RuntimeError('Unsafe test cleanup path')
        shutil.rmtree(folder)


def gpt(names=('boot_a', 'userdata'), starts=None):
    data = bytearray(32768)
    starts = starts or [100 + i * 2 for i in range(len(names))]
    entries = bytearray(128 * len(names))
    for i, (name, start) in enumerate(zip(names, starts)):
        off = i * 128
        entries[off:off + 16] = b'1' * 16
        struct.pack_into('<QQ', entries, off + 32, start, start)
        encoded = name.encode('utf-16-le')
        entries[off + 56:off + 56 + len(encoded)] = encoded
    data[1024:1024 + len(entries)] = entries
    h = bytearray(512)
    h[:8] = b'EFI PART'
    struct.pack_into('<I', h, 12, 92)
    struct.pack_into('<QIII', h, 72, 2, len(names), 128, zlib.crc32(entries))
    struct.pack_into('<I', h, 16, zlib.crc32(h[:92]))
    data[512:1024] = h
    return bytes(data)


def complete_backup(folder):
    data = gpt()
    (folder / 'pgpt.bin').write_bytes(data)
    records = parse_gpt(data)
    records.append({'name': 'splloader', 'file': 'splloader.bin', 'source': 'splloader',
                    'offset': 0, 'expected_size': 262144})
    for r in records:
        file = folder / r['file']
        file.write_bytes(bytes(r['expected_size']))
        r['sha256'] = sha256(file)
    m = {'complete': True, 'gpt_header_crc_valid': True, 'gpt_entries_crc_valid': True,
         'gpt_sha256': sha256(folder / 'pgpt.bin'), 'partitions': records}
    save_json(folder / 'verified-manifest.json', m)
    return m


class ProtocolTests(unittest.TestCase):
    def test_known_read_end_frame(self):
        self.assertEqual(frame(0x12).hex(), '7e00120000ffed7e')

    def test_odd_and_even_payload(self):
        for payload in (b'', b'a', b'ab', b'\x7e\x7d\x00'):
            self.assertEqual(parse_frame(frame(0x93, payload)), (0x93, payload))

    def test_bad_checksum_rejected(self):
        data = bytearray(frame(0x93, b'data')); data[5] ^= 1
        with self.assertRaisesRegex(RuntimeError, 'checksum'): parse_frame(data)

    def test_short_frame_rejected(self):
        with self.assertRaises(RuntimeError): parse_frame(b'\x7e')

    def test_64bit_payload(self):
        total = (1 << 32) + 65536
        p = partition_payload('user_partition', total, True)
        self.assertEqual(len(p), 88)
        self.assertEqual(struct.unpack_from('<IIQ', p, 72), (65536, 1, 0))

    def test_read_policy_rejects_write_before_send(self):
        usb = object.__new__(USB)
        with patch.object(usb, 'send') as send:
            with self.assertRaisesRegex(RuntimeError, 'Read-only'): usb.read_command(0x0a)
            send.assert_not_called()

    def test_real_read_range_64bit_and_file_hash(self):
        class MockUSB:
            requests = []
            def read_command(self, code, payload=b''):
                self.requests.append((code, payload))
                if code == 0x11:
                    size, lo, hi = struct.unpack('<III', payload)
                    self.offset = (hi << 32) | lo
                    return 0x93, b'x' * size
                return 0x80, b''
        usb = MockUSB()
        with temporary_directory() as t:
            r = USB.read_range(usb, {'name':'test', 'source':'user_partition',
                              'offset':1 << 33, 'expected_size':512, 'file':'test.bin'}, t)
            self.assertEqual(usb.offset, 1 << 33)
            self.assertEqual(r['sha256'], hashlib.sha256(b'x' * 512).hexdigest())
            self.assertFalse((pathlib.Path(t) / 'test.bin.partial').exists())

    def test_partial_reply_never_becomes_complete_file(self):
        class MockUSB:
            def read_command(self, code, payload=b''):
                return (0x93, b'x') if code == 0x11 else (0x80, b'')
        with temporary_directory() as t:
            with self.assertRaises(RuntimeError):
                USB.read_range(MockUSB(), {'name':'test', 'offset':0, 'expected_size':512, 'file':'test.bin'}, t)
            self.assertFalse((pathlib.Path(t) / 'test.bin').exists())
            self.assertTrue((pathlib.Path(t) / 'test.bin.partial').exists())


class GPTTests(unittest.TestCase):
    def test_valid_ranges(self):
        p = parse_gpt(gpt())
        self.assertEqual((p[0]['offset'], p[0]['expected_size']), (51200, 512))

    def test_short_gpt(self):
        with self.assertRaises(RuntimeError): parse_gpt(b'')

    def test_header_crc(self):
        data = bytearray(gpt()); data[512 + 24] ^= 1
        with self.assertRaisesRegex(RuntimeError, 'header CRC'): parse_gpt(data)

    def test_entries_crc(self):
        data = bytearray(gpt()); data[1024 + 56] ^= 1
        with self.assertRaisesRegex(RuntimeError, 'entries CRC'): parse_gpt(data)

    def test_path_injection_name(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsafe'): parse_gpt(gpt(('..\\bad',)))

    def test_duplicate_names(self):
        with self.assertRaisesRegex(RuntimeError, 'Duplicate'): parse_gpt(gpt(('boot_a', 'boot_a')))

    def test_overlapping_ranges(self):
        with self.assertRaisesRegex(RuntimeError, 'Overlapping'): parse_gpt(gpt(starts=[100,100]))


class VerificationTests(unittest.TestCase):
    def test_complete_backup_passes(self):
        with temporary_directory() as t:
            complete_backup(pathlib.Path(t)); f50.verify_backup(t)

    def test_missing_partition_rejected(self):
        with temporary_directory() as t:
            folder = pathlib.Path(t); m = complete_backup(folder); m['partitions'].pop()
            save_json(folder / 'verified-manifest.json', m)
            with self.assertRaisesRegex(RuntimeError, 'Incomplete'): f50.verify_backup(t)

    def test_changed_backup_rejected(self):
        with temporary_directory() as t:
            folder = pathlib.Path(t); complete_backup(folder)
            (folder / 'boot_a.bin').write_bytes(b'x' * 512)
            with self.assertRaisesRegex(RuntimeError, 'Backup invalid'): f50.verify_backup(t)

    def test_manifest_wrong_physical_offset(self):
        with temporary_directory() as t:
            folder = pathlib.Path(t); m = complete_backup(folder); m['partitions'][0]['offset'] += 512
            save_json(folder / 'verified-manifest.json', m)
            with self.assertRaisesRegex(RuntimeError, 'range mismatch'): f50.verify_backup(t)

    def test_incomplete_manifest_rejected(self):
        with temporary_directory() as t:
            folder = pathlib.Path(t); m = complete_backup(folder); m['complete'] = False
            save_json(folder / 'verified-manifest.json', m)
            with self.assertRaisesRegex(RuntimeError, 'complete'): f50.verify_backup(t)

    def test_truncated_hash_prefix_rejected(self):
        with temporary_directory() as t:
            p = pathlib.Path(t) / 'file'; p.write_bytes(b'x')
            with self.assertRaisesRegex(RuntimeError, 'shorter'): sha256(p, 2)

    def test_exact_completion(self):
        checked_completion('Write Part Done: boot_a, target: 0x100, written: 0x100\n', 'write', 'boot_a', 256)

    def test_short_write_rejected(self):
        with self.assertRaises(RuntimeError):
            checked_completion('Write Part Done: boot_a, target: 0x100, written: 0xff\n', 'write', 'boot_a', 256)

    def test_wrong_partition_rejected(self):
        with self.assertRaises(RuntimeError):
            checked_completion('Read Part Done: boot_b+0x0, target: 0x100, read: 0x100\n', 'read', 'boot_a', 256)

    def test_erase_suffix_not_accepted(self):
        with self.assertRaises(RuntimeError): checked_completion('Erase Part Done: cache_bad\n', 'erase', 'cache')

    def test_repeated_erasure_blocked_before_usb(self):
        with temporary_directory() as t:
            out = pathlib.Path(t)
            save_json(out / 'plan.json', {'protected': [{'name':'persist'}]})
            save_json(out / 'system-verification.json', {'all_match':True, 'images':[{'name':n} for n in f50.SYSTEM]})
            (out / 'pre-protected').mkdir()
            save_json(out / 'pre-protected' / 'manifest.json', [{'name':'persist'}])
            (out / 'erasure-samples').mkdir()
            args = argparse.Namespace(plan=t, dll='unused', action='erase-userdata', confirm='ERASE_USERDATA')
            with patch.object(f50, 'USB') as usb:
                with self.assertRaisesRegex(RuntimeError, 're-erasing'): f50.restricted_action(args)
                usb.assert_not_called()

    def test_wrong_confirmation_blocked_before_usb(self):
        with temporary_directory() as t:
            out = pathlib.Path(t)
            save_json(out / 'plan.json', {'protected': [{'name':'persist'}]})
            save_json(out / 'system-verification.json', {'all_match':True, 'images':[{'name':n} for n in f50.SYSTEM]})
            (out / 'pre-protected').mkdir()
            save_json(out / 'pre-protected' / 'manifest.json', [{'name':'persist'}])
            args = argparse.Namespace(plan=t, dll='unused', action='erase-userdata', confirm='yes')
            with patch.object(f50, 'USB') as usb:
                with self.assertRaisesRegex(RuntimeError, 'ERASE_USERDATA'): f50.restricted_action(args)
                usb.assert_not_called()


if __name__ == '__main__': unittest.main()
