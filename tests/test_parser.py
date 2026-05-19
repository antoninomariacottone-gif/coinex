from decimal import Decimal

from coinex_trade_bot.parser import parse_signal


def test_parse_italian_short_signal():
    signal = parse_signal(
        """🔴 TON – SHORT
➡️Punto di ingresso: 1.8002
Obiettivi:
1.7816
1.7513
1.7205
1.6086
❌ Stop Loss: 1.8909
✅ Dopo il primo take profit, spostiamo lo stop loss sul punto di ingresso."""
    )

    assert signal.market == "TONUSDT"
    assert signal.side == "short"
    assert signal.entry_price == Decimal("1.8002")
    assert signal.targets == [
        Decimal("1.7816"),
        Decimal("1.7513"),
        Decimal("1.7205"),
        Decimal("1.6086"),
    ]
    assert signal.stop_loss == Decimal("1.8909")
    assert signal.break_even_price == Decimal("1.8002")
