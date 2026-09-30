"""Connect-on-demand mesh session for the Skylight, over any bleak client.

This is the Home Assistant flavor of the stack in the repo's ``meshlib/``: the
protocol (crypto, network/transport encoding, the Generic OnOff quirk) is
identical, but instead of owning a persistent proxy connection it operates on a
bleak client that the caller connects and disconnects per command. That keeps
an ESPHome Bluetooth proxy's limited connection slots free between commands.

The lamp only reliably speaks Generic OnOff, and SET is inverted (wire 0x00 =
ON). See the repo README, "What works (and what doesn't)".
"""

from __future__ import annotations

import asyncio
import logging

from . import network

_LOGGER = logging.getLogger(__name__)

PROXY_DATA_IN = "00002add-0000-1000-8000-00805f9b34fb"    # write-without-response
PROXY_DATA_OUT = "00002ade-0000-1000-8000-00805f9b34fb"   # notify

OP_ONOFF_GET = 0x8201
OP_ONOFF_SET = 0x8202
OP_ONOFF_STATUS = 0x8204

# Firmware quirk (see meshlib/skylight.py): SET is inverted, GET is standard.
ONOFF_SET_INVERTED = True

STATUS_TIMEOUT = 3.0   # seconds per attempt
STATUS_ATTEMPTS = 3    # sends before we give up


def onoff_wire(on: bool) -> int:
    """Parameter byte for an OnOff SET (inverted)."""
    return int(on ^ ONOFF_SET_INVERTED)


def onoff_echo(wire: int) -> bool:
    """Status reply to a SET -- echoed wire byte, so inverted."""
    return bool(wire) ^ ONOFF_SET_INVERTED


def onoff_phys(wire: int) -> bool:
    """Status reply to a GET -- real state, standard-compliant."""
    return bool(wire)


class _SarReassembler:
    """Proxy PDU reassembly: byte0 = (SAR<<6)|msgtype, rest = payload."""

    def __init__(self) -> None:
        self.buf = b""

    def feed(self, frame: bytes):
        sar, payload = frame[0] >> 6, frame[1:]
        if sar == 0:                       # complete
            return payload
        if sar == 1:                       # first segment
            self.buf = payload
            return None
        self.buf += payload
        if sar == 3:                       # last segment
            out, self.buf = self.buf, b""
            return out
        return None                        # middle segment


class MeshSession:
    """One command session over an already-connected bleak client.

    ``cfg`` is a mutable dict holding the mesh keys and the ``seq``/``tid``
    counters; ``seq`` is advanced in place as messages are sent and must be
    persisted by the caller afterwards (replay protection).
    """

    def __init__(self, client, cfg: dict) -> None:
        self.client = client
        self.cfg = cfg
        self.ctx = network.NetContext(
            bytes.fromhex(cfg["net_key"]), cfg["iv_index"])
        self.app_key = bytes.fromhex(cfg["app_key"])
        self.src = cfg["src"]
        self.dst = cfg["unicast"]
        self._sar = _SarReassembler()
        self._rx: asyncio.Queue = asyncio.Queue()

    async def start(self) -> None:
        await self.client.start_notify(PROXY_DATA_OUT, self._on_notify)

    async def stop(self) -> None:
        try:
            await self.client.stop_notify(PROXY_DATA_OUT)
        except Exception:  # noqa: BLE001 - best effort on teardown
            pass

    def _on_notify(self, _char, data: bytearray) -> None:
        frame = self._sar.feed(bytes(data))
        if frame is None or (data[0] & 0x3F) != 0x00:
            return
        decoded = network.decode_network_pdu(self.ctx, frame)
        if decoded:
            self._rx.put_nowait(decoded)

    def _next_tid(self) -> int:
        self.cfg["tid"] = (self.cfg["tid"] + 1) & 0xFF
        return self.cfg["tid"]

    async def _send_access(self, opcode: int, params: bytes, ttl: int = 5) -> None:
        access = network.encode_access(opcode, params)
        seq = self.cfg["seq"]
        pdus = network.build_transport_pdus(
            self.ctx, self.app_key, True, seq, self.src, self.dst, access)
        for i, transport in enumerate(pdus):
            net = network.encode_network_pdu(
                self.ctx, 0, ttl, seq + i, self.src, self.dst, transport)
            await self.client.write_gatt_char(
                PROXY_DATA_IN, bytes([0x00]) + net, response=False)
            await asyncio.sleep(0.05)
        self.cfg["seq"] = seq + len(pdus)

    async def _wait_status(self, expect_opcode: int, timeout: float) -> bytes:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"no response 0x{expect_opcode:04x} after {timeout}s")
            ctl, _ttl, seq, src, dst, transport = await asyncio.wait_for(
                self._rx.get(), timeout=remaining)
            if ctl:
                continue
            access = network.decrypt_access(
                self.ctx, self.app_key, True, seq, src, dst, transport)
            if access is None:
                continue
            opcode, params = network.parse_access(access)
            if opcode == expect_opcode:
                return params

    async def _request(self, opcode: int, params: bytes) -> bytes:
        last_err: Exception | None = None
        for _ in range(STATUS_ATTEMPTS):
            await self._send_access(opcode, params)
            try:
                return await self._wait_status(
                    OP_ONOFF_STATUS, timeout=STATUS_TIMEOUT)
            except TimeoutError as err:
                last_err = err
        assert last_err is not None
        raise last_err

    async def set_power(self, on: bool) -> bool:
        """Turn on/off, wait for status. -> acknowledged state."""
        params = await self._request(
            OP_ONOFF_SET, bytes([onoff_wire(on), self._next_tid()]))
        # The status reply to a SET echoes the (inverted) wire byte, not a real
        # measurement; present is params[0], target is params[1] mid-transition.
        return onoff_echo(params[1] if len(params) >= 3 else params[0])

    async def get_power(self) -> bool:
        """Query the current state. -> True=on."""
        params = await self._request(OP_ONOFF_GET, b"")
        return onoff_phys(params[0])
