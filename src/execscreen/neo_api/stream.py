"""Client WebSocket NEO: kết nối lại tự động, giới hạn thời gian chờ, không làm sập khi tin lỗi.

TRẠNG THÁI: chưa kiểm thử với máy chủ thật (không truy cập được từ môi trường phát triển).
Giao thức đăng ký/xác thực phải điền ở `config/neo_connection.yaml`, tên trường ở `config/neo_field_map.yaml`.
Dùng `scripts/probe_neo.py` để ghi tin thô và xác nhận trước khi chạy bộ thu thập.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import AsyncIterator, Callable

from .auth import TokenProvider, mask
from .field_map import FieldMapper, ParseError, StateMerger
from .models import Snapshot

log = logging.getLogger("execscreen.neo.stream")


def backoff_delays(min_s: float, max_s: float, rng: random.Random | None = None):
    """Chuỗi thời gian chờ tăng dần (nhân đôi) có nhiễu, tối đa max_s."""
    rng = rng or random.Random()
    d = min_s
    while True:
        yield min(max_s, d) * (0.8 + 0.4 * rng.random())
        d = min(max_s, d * 2)


class NeoStreamClient:
    def __init__(self, url: str, token: TokenProvider, mapper: FieldMapper, symbols: list[str],
                 conn_cfg: dict, raw_sink: Callable[[str], None] | None = None,
                 on_status: Callable[[str, dict], None] | None = None):
        self.url, self.token, self.mapper, self.symbols = url, token, mapper, symbols
        self.cfg = conn_cfg
        self.raw_sink = raw_sink          # ghi tin thô (JSONL) để kiểm toán/phát lại
        self.on_status = on_status or (lambda ev, info: None)
        self.merger = StateMerger("neo")
        self.parse_errors = 0
        self.messages = 0

    def _subscribe_message(self) -> str:
        tpl = self.cfg["subscribe_template"]
        return tpl.replace("{symbols_json}", json.dumps(self.symbols))

    def _headers(self) -> dict:
        return {self.cfg["auth_header"]: f'{self.cfg["auth_scheme"]} {self.token.get()}'.strip()}

    async def snapshots(self) -> AsyncIterator[Snapshot]:
        import websockets  # nhập muộn để phần còn lại chạy được khi chưa cài
        delays = backoff_delays(self.cfg.get("reconnect_min_s", 1), self.cfg.get("reconnect_max_s", 60))
        while True:
            try:
                log.info("Kết nối %s (token %s)", self.url, mask(self.token.get()))
                async with websockets.connect(self.url, additional_headers=self._headers(),
                                              ping_interval=self.cfg.get("ping_interval_s", 20)) as ws:
                    await ws.send(self._subscribe_message())
                    self.on_status("connected", {})
                    delays = backoff_delays(self.cfg.get("reconnect_min_s", 1),
                                            self.cfg.get("reconnect_max_s", 60))
                    async for raw in ws:
                        self.messages += 1
                        if self.raw_sink:
                            self.raw_sink(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
                        snap = self._handle(raw)
                        if snap is not None:
                            yield snap
            except asyncio.CancelledError:
                raise
            except Exception as e:  # mất kết nối, token hết hạn, lỗi mạng...
                wait = next(delays)
                log.warning("Mất kết nối (%s). Thử lại sau %.1fs", type(e).__name__, wait)
                self.on_status("disconnected", {"error": type(e).__name__, "retry_in": wait})
                await asyncio.sleep(wait)

    def _handle(self, raw) -> Snapshot | None:
        try:
            payload = json.loads(raw)
            msgs = payload if isinstance(payload, list) else [payload]
            last = None
            for m in msgs:
                sym, ts, vals = self.mapper.parse(m)
                last = self.merger.update(sym, ts, vals) or last
            return last
        except (ParseError, json.JSONDecodeError) as e:
            self.parse_errors += 1
            if self.parse_errors <= 5 or self.parse_errors % 1000 == 0:
                log.warning("Bỏ qua tin không đọc được (%s) #%d", e, self.parse_errors)
            return None
