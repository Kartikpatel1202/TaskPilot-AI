"""Malware scanning interface. With no scanner configured the result is SCAN_UNAVAILABLE — a file is
never reported as clean unless a scanner actually said so. ClamAV is supported via clamd (INSTREAM)."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path


class ScanResult:
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    UNAVAILABLE = "SCAN_UNAVAILABLE"
    ERROR = "SCAN_ERROR"


class NullScanner:
    async def scan(self, path: Path) -> str:
        return ScanResult.UNAVAILABLE


class ClamAVScanner:
    def __init__(self, host: str, port: int, timeout: float = 30) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    async def scan(self, path: Path) -> str:
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_connection(self.host, self.port)
                writer.write(b"zINSTREAM\0")
                with open(path, "rb") as fh:
                    while chunk := fh.read(65536):
                        writer.write(struct.pack(">I", len(chunk)) + chunk)
                        await writer.drain()
                writer.write(struct.pack(">I", 0))
                await writer.drain()
                reply = (await reader.read(4096)).decode(errors="replace")
                writer.close()
        except (OSError, asyncio.TimeoutError):
            return ScanResult.UNAVAILABLE
        if reply.rstrip("\0").endswith("OK"):
            return ScanResult.CLEAN
        if "FOUND" in reply:
            return ScanResult.INFECTED
        return ScanResult.ERROR
