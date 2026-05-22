from __future__ import annotations

import re
from decimal import Decimal

from coinex_trade_bot.models import ParsedSignal


SIDE_ALIASES = {
    "long": "long",
    "buy": "long",
    "short": "short",
    "sell": "short",
}

NOISE_MARKERS = (
    "DISCLAIMER",
    "MANAGE RISK",
    "EDUCATIONAL PURPOSES",
    "CRYPTO TRADING CARRIES HIGH RISK",
    "CONTACT @",
)


def _normalize_number(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ".").strip())


def _extract_numbers(text: str) -> list[Decimal]:
    return [_normalize_number(match) for match in re.findall(r"[0-9]+(?:[.,][0-9]+)?", text)]


def _extract_market(text: str) -> str:
    upper = text.upper()
    first_line = next((line.strip() for line in upper.splitlines() if line.strip()), "")

    slash_match = re.search(r"#?([A-Z0-9]{2,})\s*/\s*USDT", upper)
    if slash_match:
        return f"{slash_match.group(1)}USDT"

    dollar_symbol_match = re.search(r"\$([A-Z0-9]{2,})\b", first_line)
    if dollar_symbol_match:
        token = dollar_symbol_match.group(1)
        return token if token.endswith("USDT") else f"{token}USDT"

    symbol_match = re.search(r"([A-Z0-9]{2,})\s*[-–—/]", first_line)
    if symbol_match and symbol_match.group(1) not in {"LONG", "SHORT", "BUY", "SELL"}:
        return f"{symbol_match.group(1)}USDT"

    if first_line:
        tokens = re.findall(r"[A-Z0-9]{2,}", first_line)
        filtered = [token for token in tokens if token not in {"LONG", "SHORT", "BUY", "SELL", "STOP", "LOSS", "POSITION", "RISK", "ORDER", "SMALL", "VOL"}]
        if filtered:
            token = filtered[0]
            return token if token.endswith("USDT") else f"{token}USDT"

    market_match = re.search(r"\b([A-Z0-9]{2,}USDT)\b", upper)
    if market_match:
        return market_match.group(1)

    raise ValueError("Unable to parse market symbol from signal text")


def _extract_side(text: str) -> str:
    match = re.search(r"\b(LONG|SHORT|BUY|SELL)\b", text.upper())
    if not match:
        raise ValueError("Unable to parse side (LONG/SHORT) from signal text")
    return SIDE_ALIASES[match.group(1).lower()]


def _extract_entry_info(text: str) -> tuple[Decimal, list[Decimal]]:
    upper = text.upper()

    entry_range_match = re.search(r"ENTRY(?:\s+RANGE)?(.+?)(?:TARGET|PROFIT TARGETS|STOP LOSS|STOP|SL)", upper, re.DOTALL)
    if entry_range_match:
        values = _extract_numbers(entry_range_match.group(1))
        if len(values) >= 2:
            return values[0], values[:2]

    patterns = [
        r"ENTRY\s+MARKET\s*[:\-]*\s*([0-9]+(?:[.,][0-9]+)?)",
        r"ENTRY\s*[:\-]*\s*([0-9]+(?:[.,][0-9]+)?)",
        r"LIMIT\s+ENTRY\s*[:\-]*\s*([0-9]+(?:[.,][0-9]+)?)",
        r"ENTRY\s*[:-]\s*([0-9]+(?:[.,][0-9]+)?)",
        r"PUNTO DI INGRESSO\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
        r"INGRESSO\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, upper)
        if match:
            value = _normalize_number(match.group(1))
            return value, [value]

    raise ValueError("Unable to parse entry price from signal text")


def _extract_stop_loss(text: str) -> Decimal:
    upper = text.upper()
    multiline_match = re.search(r"(?:STOP LOSS|STOP|SL)(.+?)(?:TARGET|PROFIT TARGETS|DISCLAIMER|$)", upper, re.DOTALL)
    if multiline_match:
        values = _extract_numbers(multiline_match.group(1))
        if values:
            return values[0]

    patterns = [
        r"STOP LOSS\s*[:\-]*\s*(?:➤\s*)?([0-9]+(?:[.,][0-9]+)?)",
        r"\bSTOP\s*[:\-]*\s*(?:➤\s*)?([0-9]+(?:[.,][0-9]+)?)",
        r"\bSL\s*[:\-]*\s*([0-9]+(?:[.,][0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, upper)
        if match:
            return _normalize_number(match.group(1))
    raise ValueError("Unable to parse stop loss from signal text")


def _extract_targets(text: str) -> list[Decimal]:
    upper = text.upper()

    section_match = re.search(r"OBIETTIVI\s*:?\s*(.+?)(?:STOP LOSS|STOP|SL|DOPO IL PRIMO TAKE PROFIT|$)", upper, re.DOTALL)
    if section_match:
        values = _extract_numbers(section_match.group(1))
        if values:
            return values

    section_match = re.search(r"PROFIT TARGETS?\s*(.+?)(?:STOP LOSS|STOP|SL|DISCLAIMER|$)", upper, re.DOTALL)
    if section_match:
        values = _extract_numbers(section_match.group(1))
        if values:
            return values

    section_match = re.search(r"TARGETS?\s*[:\-]*\s*(.+?)(?:STOP LOSS|STOP|SL|DISCLAIMER|$)", upper, re.DOTALL)
    if section_match:
        values = _extract_numbers(section_match.group(1))
        if values:
            return values

    tp_matches = re.findall(r"(?:TP\d+|[➊➋➌➍➎]|TARGETS?|PROFIT TARGETS?)\s*[:\-]*\s*(?:➤\s*)?([0-9]+(?:[.,][0-9]+)?)", upper)
    if tp_matches:
        return [_normalize_number(value) for value in tp_matches]

    target_line_match = re.search(r"(?:TARGET|TARGETS|PROFIT TARGETS)\s*[:\-]*\s*(.+)", upper)
    if target_line_match:
        line = target_line_match.group(1)
        values = _extract_numbers(line)
        if len(values) >= 1:
            return values

    lines = []
    collecting = False
    for raw_line in upper.splitlines():
        line = raw_line.strip()
        if not line:
            if collecting:
                break
            continue
        if any(marker in line for marker in NOISE_MARKERS):
            break
        if re.search(r"(OBIETTIVI|TARGETS?|PROFIT TARGETS)", line):
            collecting = True
            continue
        if collecting and re.search(r"(STOP LOSS|\bSTOP\b|\bSL\b|ENTRY|POSITION)", line):
            break
        if collecting:
            lines.append(line)

    if lines:
        values = _extract_numbers(" ".join(lines))
        if values:
            return values

    raise ValueError("Unable to parse targets from signal text")


def parse_signal(text: str, break_even_override: Decimal | None = None) -> ParsedSignal:
    market = _extract_market(text)
    side = _extract_side(text)
    entry_price, entry_range = _extract_entry_info(text)
    stop_loss = _extract_stop_loss(text)
    targets = _extract_targets(text)
    break_even_price = break_even_override or entry_price

    return ParsedSignal(
        market=market,
        side=side,
        entry_price=entry_price,
        targets=targets,
        stop_loss=stop_loss,
        break_even_price=break_even_price,
        entry_range=entry_range,
        raw_text=text,
    )


def looks_like_trade_signal(text: str) -> bool:
    upper = text.upper()
    required_fragments = [
        any(token in upper for token in ("LONG", "SHORT", "BUY", "SELL")),
        any(token in upper for token in ("PUNTO DI INGRESSO", "ENTRY", "INGRESSO")),
        any(token in upper for token in ("OBIETTIVI", "TARGET", "TP1", "PROFIT TARGETS")),
        any(token in upper for token in ("STOP LOSS", "SL", "STOP")),
    ]
    if not all(required_fragments):
        return False

    try:
        parsed = parse_signal(text)
    except Exception:  # noqa: BLE001
        return False

    return len(parsed.targets) >= 1
