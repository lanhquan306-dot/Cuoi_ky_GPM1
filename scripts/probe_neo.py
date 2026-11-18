"""Thăm dò NEO API: ghi tin thô và đo các đặc tính mà đề/tài liệu chưa nói rõ.

BƯỚC 1 (trong giờ giao dịch, trên máy có IP đã đăng ký):
    python scripts/probe_neo.py record --out data/raw/probe.jsonl --seconds 300
BƯỚC 2 (phân tích - chạy được offline):
    python scripts/probe_neo.py analyze data/raw/probe.jsonl --ts-field <đường.dẫn.thời.gian> --ts-format epoch_ms

Báo cáo cho biết: các khóa JSON xuất hiện (để điền config/neo_field_map.yaml), số tin/giây mỗi mã,
độ trễ (nếu tin có thời gian sàn), có/không các trường: sổ lệnh 3 mức, KL cộng dồn, mua/bán nước ngoài, room.
"""
import _bootstrap  # noqa: F401
import argparse
import asyncio
import json
import os
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from execscreen.config import ROOT, load_dotenv_if_present
from execscreen.neo_api.field_map import dig, parse_ts

KEYWORDS = {
    "sổ lệnh (bid/ask)": ["bid", "ask", "buy", "sell", "mua", "ban", "offer"],
    "khối lượng cộng dồn": ["totalvol", "total_vol", "volume", "accumulated", "cum", "totalqty", "tongkl"],
    "nước ngoài": ["foreign", "fbuy", "fsell", "nuocngoai", "nn"],
    "room": ["room"],
    "trần/sàn/tham chiếu": ["ceil", "floor", "ref", "tran", "san"],
}


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten(v, f"{prefix}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            yield from flatten(v, f"{prefix}{i}.")
    else:
        yield prefix[:-1], obj


async def record(out: str, seconds: int):
    import websockets
    load_dotenv_if_present()
    from execscreen.neo_api.auth import TokenProvider, mask
    import pandas as pd
    conn = yaml.safe_load(open(ROOT / "config" / "neo_connection.yaml", encoding="utf-8"))["websocket"]
    uni = pd.read_csv(ROOT / "config" / "universe_sample.csv").symbol.tolist()[:10]   # thăm dò 10 mã
    tok = TokenProvider()
    url = os.environ[conn["url_env"]]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    print(f"Kết nối {url} (token {mask(tok.get())}) trong {seconds}s ...")
    headers = {conn["auth_header"]: f'{conn["auth_scheme"]} {tok.get()}'.strip()}
    n = 0
    with open(out, "a", encoding="utf-8") as fh:
        async with websockets.connect(url, additional_headers=headers) as ws:
            await ws.send(conn["subscribe_template"].replace("{symbols_json}", json.dumps(uni)))
            t_end = time.time() + seconds
            while time.time() < t_end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    print("... 10s không có tin")
                    continue
                fh.write(json.dumps({"recv": time.time(), "raw": raw if isinstance(raw, str) else raw.decode("utf-8", "replace")},
                                    ensure_ascii=False) + "\n")
                n += 1
    print(f"Đã ghi {n} tin vào {out}")


def analyze(path: str, ts_field: str | None, ts_format: str, sym_field: str | None):
    keys, per_sym, lat = Counter(), defaultdict(list), []
    n = bad = 0
    for line in open(path, encoding="utf-8"):
        rec = json.loads(line)
        try:
            payload = json.loads(rec["raw"])
        except json.JSONDecodeError:
            bad += 1
            continue
        for m in (payload if isinstance(payload, list) else [payload]):
            n += 1
            for k, _ in flatten(m):
                keys[k] += 1
            if sym_field:
                s = dig(m, sym_field)
                if s:
                    per_sym[s].append(rec["recv"])
            if ts_field:
                try:
                    t = parse_ts(dig(m, ts_field), ts_format)
                    lat.append(rec["recv"] - t.astimezone(timezone.utc).timestamp())
                except Exception:
                    pass
    print(f"Số tin: {n} (không phải JSON: {bad})\n\n== CÁC KHÓA XUẤT HIỆN (đường dẫn: số lần) ==")
    for k, c in keys.most_common(80):
        print(f"  {k}: {c}")
    print("\n== GỢI Ý TRƯỜNG DỮ LIỆU (theo từ khóa tên khóa) ==")
    low = [k.lower() for k in keys]
    for label, kws in KEYWORDS.items():
        hit = sorted({k for k in keys if any(w in k.lower() for w in kws)})[:8]
        print(f"  {label}: {'CÓ  ' + ', '.join(hit) if hit else 'KHÔNG thấy'}")
    if per_sym:
        rates = {s: (len(t) / max(t[-1] - t[0], 1e-9) if len(t) > 1 else 0.0) for s, t in per_sym.items()}
        print("\n== TẦN SUẤT TIN/GIÂY THEO MÃ (trung bình) ==")
        for s, r in sorted(rates.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {s}: {r:.2f}")
    if lat:
        lat.sort()
        q = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))]
        print(f"\n== ĐỘ TRỄ (nhận - thời gian trong tin), giây; cần đồng bộ NTP ==\n"
              f"  P50={q(.5):.3f}  P95={q(.95):.3f}  max={lat[-1]:.3f}  (n={len(lat)})")
    else:
        print("\n(Chưa đo được độ trễ: cung cấp --ts-field nếu tin có thời gian của sàn)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--out", default="data/raw/probe.jsonl")
    r.add_argument("--seconds", type=int, default=300)
    an = sub.add_parser("analyze")
    an.add_argument("file")
    an.add_argument("--ts-field")
    an.add_argument("--ts-format", default="epoch_ms")
    an.add_argument("--symbol-field")
    a = ap.parse_args()
    if a.cmd == "record":
        asyncio.run(record(a.out, a.seconds))
    else:
        analyze(a.file, a.ts_field, a.ts_format, a.symbol_field)
