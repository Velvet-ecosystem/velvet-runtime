# SPDX-License-Identifier: GPL-3.0-only

import os
import pty
import unittest

from services.read_only_nmea_serial import ReadOnlyNmeaSerial, ReadOnlySerialError


class ReadOnlyNmeaSerialTests(unittest.TestCase):
    def test_reads_one_line_from_posix_terminal_without_write_surface(self) -> None:
        master, slave = pty.openpty()
        reader = None
        try:
            reader = ReadOnlyNmeaSerial(os.ttyname(slave), baud=9600, timeout=0.5)
            self.assertFalse(hasattr(reader, "write"))
            os.write(master, b"$GPGGA,123519,,,,,0,00,99.9,,,,,,*00\r\n")
            self.assertTrue(reader.readline().startswith(b"$GPGGA"))
        finally:
            if reader is not None:
                reader.close()
            os.close(master)
            os.close(slave)

    def test_timeout_returns_empty_bytes(self) -> None:
        master, slave = pty.openpty()
        reader = None
        try:
            reader = ReadOnlyNmeaSerial(os.ttyname(slave), baud=9600, timeout=0.05)
            self.assertEqual(reader.readline(), b"")
        finally:
            if reader is not None:
                reader.close()
            os.close(master)
            os.close(slave)

    def test_rejects_unknown_baud_and_closed_reads(self) -> None:
        master, slave = pty.openpty()
        try:
            with self.assertRaises(ValueError):
                ReadOnlyNmeaSerial(os.ttyname(slave), baud=12345)
            reader = ReadOnlyNmeaSerial(os.ttyname(slave), baud=9600)
            reader.close()
            with self.assertRaises(ReadOnlySerialError):
                reader.readline()
        finally:
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
