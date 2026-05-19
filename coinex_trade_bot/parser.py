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


def _normalize_number(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ".").strip())


def _extract_market(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")

    dollar_symbol_match = re.search(r"\$([A-Z0-9]{2,})\b", first_line.upper())
    if dollar_symbol_match:
        token = dollar_symbol_match.group(1)
        return token if token.endswith("USDT") else f"{token}USDT"

    symbol_match = re.search(r"([A-Z0-9]{2,})\s*[-–—/\?]", first_line.upper())
    if symbol_match and symbol_match.group(1) not in {"LONG", "SHORT", "BUY", "SELL"}:
        return f"{symbol_match.group(1)}USDT"

    if first_line:
        tokens = re.findall(r"[A-Z0-9]{2,}", first_line.upper())
        filtered = [token for token in tokens if token not in {"LONG", "SHORT", "BUY", "SELL", "STOP", "LOSS"}]
        if filtered:
            token = filtered[0]
            return token if token.endswith("USDT") else f"{token}USDT"

    market_match = re.search(r"\b([A-Z0-9]{2,}USDT)\b", text.upper())
    if market_match:
        return market_match.group(1)

    raise ValueError("Unable to parse market symbol from signal text")


def _extract_side(text: str) -> str:
    match = re.search(r"\b(LONG|SHORT|BUY|SELL)\b", text.upper())
    if not match:
        raise ValueError("Unable to parse side (LONG/SHORT) from signal text")
    return SIDE_ALIASES[match.group(1).lower()]


def _extract_entry(text: str) -> Decimal:
    patterns = [
        r"ENTRY\s+MARKET\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
        r"ENTRY\s+LIMIT\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
        r"PUNTO DI INGRESSO\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
        r"ENTRY(?:\s+PRICE)?\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
        r"INGRESSO\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.upper())
        if match:
            return _normalize_number(match.group(1))
    raise ValueError("Unable to parse entry price from signal text")


def _extract_stop_loss(text: str) -> Decimal:
    patterns = [
        r"STOP LOSS\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
        r"\bSTOP\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
        r"\bSL\s*:\s*([0-9]+(?:[.,][0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.upper())
        if match:
            return _normalize_number(match.group(1))
    raise ValueError("Unable to parse stop loss from signal text")


def _extract_targets(text: str) -> list[Decimal]:
    upper_text = text.upper()
    section_match = re.search(r"OBIETTIVI\s*:\s*(.+?)(?:STOP LOSS|STOP|DOPO IL PRIMO TAKE PROFIT|$)", upper_text, re.DOTALL)
    if not section_match:
        section_match = re.search(r"TARGETS?\s*:\s*(.+?)(?:STOP LOSS|STOP|DOPO IL PRIMO TAKE PROFIT|$)", upper_text, re.DOTALL)
    if not section_match and re.search(r"\bTP\d*\s*:", upper_text):
        section_match = re.search(r"(TP\d*\s*:\s*.+?)(?:DISCLAIMER|CLOSE\s+\d+%|$)", upper_text, re.DOTALL)
    if not section_match:
        raise ValueError("Unable to parse targets from signal text")

    block = section_match.group(1)
    if re.search(r"\bTP\d*\s*:", block):
        numbers = re.findall(r"TP\d*\s*:\s*([0-9]+(?:[.,][0-9]+)?)", block)
    else:
        numbers = re.findall(r"[0-9]+(?:[.,][0-9]+)?", block)
    targets = [_normalize_number(value) for value in numbers]
    if len(targets) < 1:
        raise ValueError("No targets found in signal text")
    return targets


def parse_signal(text: str, break_even_override: Decimal | None = None) -> ParsedSignal:
    market = _extract_market(text)
    side = _extract_side(text)
    entry_price = _extract_entry(text)
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
        raw_text=text,
    )


def looks_like_trade_signal(text: str) -> bool:
    upper = text.upper()
    required_fragments = [
        any(token in upper for token in ("LONG", "SHORT", "BUY", "SELL")),
        "PUNTO DI INGRESSO" in upper or "ENTRY" in upper or "INGRESSO" in upper,
        "OBIETTIVI" in upper or "TARGET" in upper or re.search(r"\bTP\d*\s*:", upper) is not None,
        "STOP LOSS" in upper or re.search(r"\bSTOP\s*:", upper) is not None or re.search(r"\bSL\s*:", upper) is not None,
    ]
    if not all(required_fragments):
        return False

    try:
        parsed = parse_signal(text)
    except Exception:  # noqa: BLE001
        return False

    return len(parsed.targets) >= 1
