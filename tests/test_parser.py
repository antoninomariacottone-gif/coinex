from decimal import Decimal

from coinex_trade_bot.parser import looks_like_trade_signal, parse_signal


def test_parse_italian_long_signal():
    signal = parse_signal(
        """🔴 ONDO – LONG
➡️Punto di ingresso: 0.4073
Obiettivi:
0.4115
0.4192
0.4267
0.4517
❌ Stop Loss: 0.3868
✅ Dopo il primo take profit, spostiamo lo stop loss sul punto di ingresso."""
    )

    assert signal.market == "ONDOUSDT"
    assert signal.side == "long"
    assert signal.entry_price == Decimal("0.4073")
    assert signal.targets == [Decimal("0.4115"), Decimal("0.4192"), Decimal("0.4267"), Decimal("0.4517")]
    assert signal.stop_loss == Decimal("0.3868")


def test_parse_english_tp_signal():
    signal = parse_signal(
        """🟢 LONG  - $SEI- RISK ORDER - SMALL VOL
-  Entry: 0.06417
- limit entry: 0.06093
- SL: 0.05823
🎯 TP1: 0.07093
🎯 TP2: 0.07846
🎯 TP3: 0.12699"""
    )

    assert signal.market == "SEIUSDT"
    assert signal.side == "long"
    assert signal.entry_price == Decimal("0.06417")
    assert signal.targets == [Decimal("0.07093"), Decimal("0.07846"), Decimal("0.12699")]
    assert signal.stop_loss == Decimal("0.05823")


def test_parse_entry_range_signal():
    signal = parse_signal(
        """📊 #TIA/USDT

🟢 POSITION: LONG

💰 ENTRY RANGE
➤ 0.435 - 0.41

🎯 PROFIT TARGETS
➊ 0.445
➋ 0.46
➌ 0.49

🛑 STOP LOSS
➤ 0.385"""
    )

    assert signal.market == "TIAUSDT"
    assert signal.side == "long"
    assert signal.entry_price == Decimal("0.435")
    assert signal.entry_range == [Decimal("0.435"), Decimal("0.41")]
    assert signal.targets == [Decimal("0.445"), Decimal("0.46"), Decimal("0.49")]
    assert signal.stop_loss == Decimal("0.385")


def test_parse_inline_target_signal():
    signal = parse_signal(
        """🔰 SAHARA/USDT 🔰

🟢 LONG

🔳 ENTRY :- 0.03560

☑️ TARGET:- 0.03650 - 0.038 - 0.040

🔴 STOP :- 0.03350"""
    )

    assert signal.market == "SAHARAUSDT"
    assert signal.side == "long"
    assert signal.entry_price == Decimal("0.03560")
    assert signal.targets == [Decimal("0.03650"), Decimal("0.038"), Decimal("0.040")]
    assert signal.stop_loss == Decimal("0.03350")


def test_detect_trade_signal_and_ignore_noise():
    assert looks_like_trade_signal("UNI + 3.5R") is False
    assert looks_like_trade_signal("Preso il primo obiettivo") is False
    assert (
        looks_like_trade_signal(
            """🔴 ONDO – LONG
➡️Punto di ingresso: 0.4073
Obiettivi:
0.4115
0.4192
0.4267
0.4517
❌ Stop Loss: 0.3868"""
        )
        is True
    )
