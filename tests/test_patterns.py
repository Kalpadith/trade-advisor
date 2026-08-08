from helpers import df_from_rows
from tradeadvisor.indicators.patterns import add_patterns

FLAT = (100.0, 100.6, 99.4, 100.0)


def test_bullish_engulfing_fires_and_mirror_does_not():
    rows = [FLAT] * 5 + [
        (105.0, 105.5, 99.5, 100.0),   # bearish candle
        (99.5, 106.5, 99.0, 106.0),    # engulfs it, bullish
    ]
    df = add_patterns(df_from_rows(rows))
    assert bool(df["pat_bull_engulf"].iloc[-1])
    assert not bool(df["pat_bear_engulf"].iloc[-1])

    mirror = [FLAT] * 5 + [
        (100.0, 105.5, 99.5, 105.0),   # bullish candle
        (105.5, 106.0, 98.5, 99.0),    # engulfs it, bearish
    ]
    dfm = add_patterns(df_from_rows(mirror))
    assert bool(dfm["pat_bear_engulf"].iloc[-1])
    assert not bool(dfm["pat_bull_engulf"].iloc[-1])


def test_hammer_requires_down_leg():
    down = [(110 - i, 110.6 - i, 109.4 - i, 109.5 - i) for i in range(8)]
    hammer = (102.0, 102.3, 99.0, 102.2)  # long lower wick, tiny upper wick
    df = add_patterns(df_from_rows(down + [hammer]))
    assert bool(df["pat_hammer"].iloc[-1])

    up = [(100 + i, 101.1 + i, 99.9 + i, 100.5 + i) for i in range(8)]
    df_up = add_patterns(df_from_rows(up + [hammer]))
    assert not bool(df_up["pat_hammer"].iloc[-1])


def test_shooting_star():
    up = [(100 + i, 101.1 + i, 99.9 + i, 100.5 + i) for i in range(8)]
    star = (108.0, 111.0, 107.9, 107.95)  # long upper wick after an up-leg
    df = add_patterns(df_from_rows(up + [star]))
    assert bool(df["pat_shooting_star"].iloc[-1])


def test_doji():
    df = add_patterns(df_from_rows([FLAT] * 5 + [(100.0, 101.0, 99.0, 100.05)]))
    assert bool(df["pat_doji"].iloc[-1])
    df2 = add_patterns(df_from_rows([FLAT] * 5 + [(100.0, 101.0, 99.0, 100.9)]))
    assert not bool(df2["pat_doji"].iloc[-1])


def test_morning_and_evening_star():
    morning = [FLAT] * 5 + [
        (106.0, 106.5, 99.5, 100.0),   # strong bearish
        (100.0, 100.6, 99.4, 100.1),   # small body
        (100.1, 105.8, 100.0, 105.5),  # bullish close above bar-1 midpoint
    ]
    df = add_patterns(df_from_rows(morning))
    assert bool(df["pat_morning_star"].iloc[-1])

    evening = [FLAT] * 5 + [
        (100.0, 106.5, 99.5, 106.0),
        (106.0, 106.6, 105.4, 105.9),
        (105.9, 106.0, 99.9, 100.2),
    ]
    dfe = add_patterns(df_from_rows(evening))
    assert bool(dfe["pat_evening_star"].iloc[-1])
    assert not bool(dfe["pat_morning_star"].iloc[-1])
