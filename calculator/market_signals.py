"""Market breadth and funding-cost signals used by the technical summary.

The 10-year yield uses the same Yahoo series as the rate card. Breadth and the
high-yield spread come from TradingView, because the FRED host does not respond
from the refresh environment.
"""

from __future__ import annotations

import base64
import json
import os
import random
import socket
import ssl
import string
import struct
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .sheet_sources import fetch_text, fetch_us_ohlcv

BREADTH_LABEL = "미국 주식 20일선 상회 비율"
TREASURY_LABEL = "미국 10년물 금리 20일 변화"
CREDIT_LABEL = "미국 저신용 회사채 금리 차이"
_TV_URL = "wss://data.tradingview.com/socket.io/websocket?type=chart"
_UNAVAILABLE = {"status": "판단 불가", "change": None, "current": None}
_RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "market_signal_rules.json"
MARKET_SIGNAL_RULES = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
_DISPLAY_DECIMALS = int(MARKET_SIGNAL_RULES["displayDecimals"])


def _status(value: float, caution: float, warning: float) -> str:
    return "경고" if value >= warning else "주의" if value >= caution else "정상"


def _breadth_status(percent: float) -> str:
    rules = MARKET_SIGNAL_RULES["breadth"]
    return "경고" if percent < rules["warningBelow"] else "주의" if percent < rules["cautionBelow"] else "정상"


def _change_signal(closes: list[float], caution: float, warning: float) -> dict[str, Any]:
    if len(closes) < 21:
        return dict(_UNAVAILABLE)
    change = round(closes[-1] - closes[-21], _DISPLAY_DECIMALS)
    return {
        "status": _status(change, caution, warning),
        "change": change,
        "current": closes[-1],
    }


def _yahoo_closes(symbol: str) -> list[float]:
    return [float(row["close"]) for row in fetch_us_ohlcv(symbol, range_value="6mo")]


def _read_exact(sock: ssl.SSLSocket, pending: bytearray, size: int) -> bytes:
    while len(pending) < size:
        chunk = sock.recv(65536)
        if not chunk:
            raise RuntimeError("market data socket closed")
        pending.extend(chunk)
    data = bytes(pending[:size])
    del pending[:size]
    return data


def _send_frame(sock: ssl.SSLSocket, opcode: int, payload: bytes) -> None:
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _read_frame(sock: ssl.SSLSocket, pending: bytearray) -> tuple[int, int, bytes]:
    header = _read_exact(sock, pending, 2)
    fin = header[0] & 0x80
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(sock, pending, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(sock, pending, 8))[0]
    if header[1] & 0x80:
        mask = _read_exact(sock, pending, 4)
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(_read_exact(sock, pending, length)))
    else:
        payload = _read_exact(sock, pending, length)
    return fin, opcode, payload


def _read_text(sock: ssl.SSLSocket, pending: bytearray) -> str:
    fragments: list[bytes] = []
    while True:
        fin, opcode, payload = _read_frame(sock, pending)
        if opcode == 0x8:
            raise RuntimeError("market data socket closed")
        if opcode == 0x9:
            _send_frame(sock, 0xA, payload)
            continue
        if opcode == 0xA:
            continue
        if opcode in (0x0, 0x1):
            fragments.append(payload)
            if fin:
                return b"".join(fragments).decode("utf-8", "replace")


def _connect_tradingview(timeout: float) -> tuple[ssl.SSLSocket, bytearray]:
    parsed = urlparse(_TV_URL)
    raw = socket.create_connection((parsed.hostname, 443), timeout=timeout)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname)
    key = base64.b64encode(os.urandom(16)).decode()
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {parsed.hostname}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Origin: https://www.tradingview.com\r\n"
        "User-Agent: Mozilla/5.0\r\n"
        "\r\n"
    )
    sock.sendall(request.encode())
    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response.extend(chunk)
    head, _, leftover = bytes(response).partition(b"\r\n\r\n")
    if b" 101 " not in head.split(b"\r\n", 1)[0]:
        raise RuntimeError(head[:180].decode("utf-8", "replace"))
    sock.settimeout(timeout)
    return sock, bytearray(leftover)


def _tv_message(func: str, params: list[Any]) -> str:
    payload = json.dumps({"m": func, "p": params}, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _tv_packets(buffer: str) -> tuple[list[str], str]:
    packets: list[str] = []
    cursor = 0
    while True:
        marker = buffer.find("~m~", cursor)
        if marker < 0:
            break
        length_end = buffer.find("~m~", marker + 3)
        if length_end < 0:
            break
        try:
            length = int(buffer[marker + 3:length_end])
        except ValueError:
            break
        start = length_end + 3
        end = start + length
        if end > len(buffer):
            break
        packets.append(buffer[start:end])
        cursor = end
    return packets, buffer[cursor:]


def _closes_from_timescale(message: dict[str, Any]) -> dict[int, float]:
    payload = message.get("p") or []
    if len(payload) < 2 or not isinstance(payload[1], dict):
        return {}
    series = payload[1].get("s1", {}).get("s") or []
    points: dict[int, float] = {}
    for bar in series:
        values = bar.get("v") or []
        if len(values) >= 5:
            points[int(bar["i"])] = float(values[4])
    return points


def _tradingview_closes(symbol: str, bars: int) -> list[float]:
    sock, pending = _connect_tradingview(12)
    try:
        chart = "cs_" + "".join(random.choice(string.ascii_lowercase) for _ in range(12))
        _send_frame(sock, 0x1, _tv_message("set_auth_token", ["unauthorized_user_token"]).encode())
        _send_frame(sock, 0x1, _tv_message("chart_create_session", [chart, ""]).encode())
        symbol_def = json.dumps({"symbol": symbol, "adjustment": "splits"}, separators=(",", ":"))
        _send_frame(sock, 0x1, _tv_message("resolve_symbol", [chart, "symbol_1", "=" + symbol_def]).encode())
        _send_frame(sock, 0x1, _tv_message("create_series", [chart, "s1", "s1", "symbol_1", "1D", bars]).encode())
        text = ""
        points: dict[int, float] = {}
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            text += _read_text(sock, pending)
            packets, text = _tv_packets(text)
            completed = False
            for packet in packets:
                if packet.startswith("~h~"):
                    echoed = f"~m~{len(packet)}~m~{packet}"
                    _send_frame(sock, 0x1, echoed.encode())
                    continue
                try:
                    message = json.loads(packet)
                except json.JSONDecodeError:
                    continue
                if message.get("m") == "timescale_update":
                    points.update(_closes_from_timescale(message))
                elif message.get("m") == "symbol_error":
                    raise RuntimeError(f"unknown market symbol {symbol}")
                elif message.get("m") == "series_completed":
                    completed = True
            if completed and points:
                break
        return [points[index] for index in sorted(points)]
    finally:
        sock.close()


def _nyse_stock_count() -> int | None:
    """Count NYSE listings behind the breadth percentage, excluding ETFs and test issues."""
    text = fetch_text("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
    count = 0
    for line in text.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 7 or parts[0].startswith("File Creation"):
            continue
        if parts[2] == "N" and parts[4] == "N" and parts[6] == "N":
            count += 1
    return count or None


def _breadth() -> dict[str, Any]:
    try:
        closes = _tradingview_closes("INDEX:MMTW", 5)
    except Exception:  # noqa: BLE001 - market signals remain best-effort
        closes = []
    if not closes or not 0 <= closes[-1] <= 100:
        return {"status": "판단 불가", "value": None}
    percent = closes[-1]
    signal: dict[str, Any] = {"status": _breadth_status(percent), "value": percent}
    try:
        count = _nyse_stock_count()
    except Exception:  # noqa: BLE001 - the percentage still stands without the count
        count = None
    if count:
        signal["count"] = count
        signal["numerator"] = round(percent * count / 100)
    return signal


def _treasury() -> dict[str, Any]:
    try:
        closes = _yahoo_closes("^TNX")
    except Exception:  # noqa: BLE001 - market signals remain best-effort
        return dict(_UNAVAILABLE)
    rules = MARKET_SIGNAL_RULES["treasury"]
    return _change_signal(closes, rules["caution"], rules["warning"])


def _credit() -> dict[str, Any]:
    try:
        closes = _tradingview_closes("FRED:BAMLH0A0HYM2", 40)
    except Exception:  # noqa: BLE001 - market signals remain best-effort
        return dict(_UNAVAILABLE)
    rules = MARKET_SIGNAL_RULES["credit"]
    return _change_signal(closes, rules["caution"], rules["warning"])


def aggregate_market_signal_status(statuses: list[str]) -> str:
    rules = MARKET_SIGNAL_RULES["combined"]
    if statuses.count("경고") >= rules["warningSignalCount"] or statuses.count("주의") >= rules["cautionCountForWarning"]:
        return "경고"
    if "주의" in statuses:
        return "주의"
    if "정상" in statuses:
        return "정상"
    return "판단 불가"


def build_market_signals() -> dict[str, Any]:
    signals: dict[str, Any] = {
        "breadth": _breadth(),
        "treasury": _treasury(),
        "credit": _credit(),
    }
    statuses = [signals[key]["status"] for key in ("breadth", "treasury", "credit")]
    signals["status"] = aggregate_market_signal_status(statuses)
    return signals


def _breadth_text(breadth: dict[str, Any]) -> str:
    value = breadth.get("value")
    if not isinstance(value, (int, float)):
        return "데이터 수집 실패 · 판단 불가"
    count = breadth.get("count")
    numerator = breadth.get("numerator")
    count_text = f" ({numerator:,}/{count:,})" if isinstance(count, int) and count > 0 and isinstance(numerator, int) else ""
    return f"{value:.0f}%{count_text} · {breadth.get('status', '판단 불가')}"


def _change_text(signal: dict[str, Any], *, spread: bool) -> str:
    change = signal.get("change")
    current = signal.get("current")
    if not isinstance(change, (int, float)) or not isinstance(current, (int, float)):
        return "데이터 수집 실패 · 판단 불가"
    unit = "%p" if spread else "%"
    return f"{current:.2f}{unit} · 20거래일 {change:+.2f}%p · {signal.get('status', '판단 불가')}"


def market_signal_rows(signals: dict[str, Any]) -> list[list[str]]:
    return [
        ["고점 신호 종합", str(signals.get("status") or "판단 불가")],
        [BREADTH_LABEL, _breadth_text(signals.get("breadth") or {})],
        [TREASURY_LABEL, _change_text(signals.get("treasury") or {}, spread=False)],
        [CREDIT_LABEL, _change_text(signals.get("credit") or {}, spread=True)],
    ]
