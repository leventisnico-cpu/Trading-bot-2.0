"""research/ftmo_breadth.py: the bot's rule on more markets, as pre-registered
in research/ftmo_breadth.md. The lists, the loading, the distribution
adjustment, the checks and the verdict wiring, on a made-up market."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ftmo_replay import CYCLES, write_market  # noqa: E402

_spec = importlib.util.spec_from_file_location("ftmo_breadth",
                                               ROOT / "research" / "ftmo_breadth.py")
bd = importlib.util.module_from_spec(_spec)
sys.modules["ftmo_breadth"] = bd
_spec.loader.exec_module(bd)
ss, so = bd.ss, bd.so
VERIFY_FILES = bd.verify_files


def write_extra(folder: Path, like: Path, cycles=CYCLES) -> None:
    """Five more markets on the sessions of ``like`` (one of the four's
    files): the same kind of path, with their dips at other times."""
    stamps = pd.read_csv(like)["timestamp"]
    n = len(stamps)
    for fn, lead, scale in zip(bd.EXTRA.values(), (7, 11, 14, 17, 20),
                               (0.9, 1.1, 0.8, 1.0, 1.3)):
        rets = [0.0015] * (225 + lead)
        for dip, after in cycles:
            rets += ([-0.012] * dip + [0.011 if after > 0 else -0.013] * abs(after)
                     + [0.001] * 6)
        c = 50 * np.cumprod(1 + np.array((rets + [0.001] * n)[:n]) * scale)
        o = np.concatenate([[50.0], c[:-1]])
        pd.DataFrame({"timestamp": stamps, "open": o, "high": np.maximum(o, c) * 1.002,
                      "low": np.minimum(o, c) * 0.998, "close": c}
                     ).to_csv(folder / fn, index=False)


@pytest.fixture(scope="module")
def folders(tmp_path_factory):
    four, five = tmp_path_factory.mktemp("four"), tmp_path_factory.mktemp("five")
    write_market(four)
    write_extra(five, four / "qqq_long.csv")
    return four, five


@pytest.fixture(scope="module")
def market(folders):
    return bd.load(*folders)


def test_the_lists_are_the_notes():
    assert bd.UNIVERSES["B0"] == tuple(bd.base.SYMS) == (
        "US100 (QQQ)", "US500 (SPY)", "US30 (DIA)", "US2000 (IWM)")
    assert bd.UNIVERSES["B1"] == bd.US + ("XAUUSD (GLD)",)
    assert bd.UNIVERSES["B2"] == bd.US + ("GER40 (EWG)", "UK100 (EWU)", "JP225 (EWJ)",
                                          "AUS200 (EWA)")
    assert bd.UNIVERSES["B3"] == bd.US + tuple(bd.EXTRA) and len(bd.UNIVERSES["B3"]) == 9
    assert bd.JUDGED == ("B1", "B2", "B3") and bd.SENSITIVITY == ("B2 adj", "B3 adj")
    for b in (0, 1):                                 # the rule is the bot's: W2+S2
        pol = ss.FTMO_POL[bd.KEY][b]
        assert (pol.risk, pol.ml_buffer, pol.free_slots, pol.room_share, pol.exits,
                pol.entry, pol.r_atr, pol.cap_buffer) == (0.03, 0.015, True, 1.0, "scale",
                                                          "fast4", 3.0, 0.002)


def test_the_published_rows_are_the_slots_notes():
    note = (ROOT / "research" / "ftmo_slots_sizing.md").read_text(encoding="utf-8")
    assert f"| W2+S2 | {bd.PUBLISHED['signals']} |" in note
    for b, bound in enumerate(bd.BOUNDS):
        assert f"| W2+S2 | {bound} | {bd.PUBLISHED['trades'][b]} |" in note
        for ci, c in enumerate(bd.COHORTS):
            assert f"| W2+S2 {bound} | {c} | {bd.PUBLISHED['ftmo'][(b, ci)]} |" in note
            m = bd.PUBLISHED["starts"][ci]
            breached, p18, ever = bd.PUBLISHED["counts"][(b, ci)]
            line, = [ln for ln in note.splitlines()
                     if ln.startswith(f"| W2+S2 | {c} | {bound} |")]
            cells = [x.strip() for x in line.split("|")]
            assert cells[4].startswith(f"{breached}/{m} (")
            assert cells[5].startswith(f"{p18}/{m} (") and cells[6].startswith(f"{ever}/{m} (")


def test_the_new_markets_load_on_the_same_sessions_and_leave_the_four_alone(folders, market):
    dates, four, five = market
    ref_dates, ref = bd.base.load_all(folders[0])
    assert np.array_equal(dates, ref_dates)
    assert list(four) == list(bd.US) and list(five) == list(bd.EXTRA)
    for k in bd.US:
        for f in ref[k]:
            assert np.array_equal(four[k][f], ref[k][f], equal_nan=True)
    assert tuple(bd.base.SYMS) == bd.US              # the loader's own list was put back
    b3 = bd.universe("B3", four, five)
    assert list(b3) == list(bd.UNIVERSES["B3"])
    assert b3["US500 (SPY)"] is four["US500 (SPY)"] and b3["JP225 (EWJ)"] is five["JP225 (EWJ)"]
    assert list(bd.universe("B0", four, five)) == list(bd.US)


@pytest.mark.parametrize("change", ["a session missing in one file",
                                    "a session too many in one file",
                                    "a session too many in every file"])
def test_another_calendar_is_refused(folders, tmp_path, change):
    four, five = folders
    for f in five.iterdir():
        rows = f.read_text().splitlines()
        one = f.name == "ewj_long.csv"
        if change == "a session missing in one file" and one:
            del rows[300]
        if change == "a session too many in every file" or (
                change == "a session too many in one file" and one):
            rows.append("2030-01-05T05:00:00+0000,1,1,1,1")      # a Saturday
        (tmp_path / f.name).write_text("\n".join(rows) + "\n")
    with pytest.raises(SystemExit, match="sessions differ"):
        bd.load(four, tmp_path)


def test_the_files_must_be_the_notes(folders, tmp_path, monkeypatch):
    four, five = folders
    with pytest.raises(SystemExit, match="is not the note's file"):
        bd.verify_files(four, five)                  # a made-up market is not the note's
    names = list(bd.base.SYMS.values()) + list(bd.EXTRA.values())
    assert sorted(bd.SHA256) == sorted(names) and all(len(h) == 64 for h in bd.SHA256.values())
    own = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
           for folder in (four, five) for f in folder.iterdir()}
    monkeypatch.setattr(bd, "SHA256", own)
    bd.verify_files(four, five)                      # the files it was given: passes
    for f in five.iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes() + (b" " if f.name == "ewa_long.csv"
                                                           else b""))
    with pytest.raises(SystemExit, match="ewa_long.csv is not the note's file"):
        bd.verify_files(four, tmp_path)              # one byte more in one file


def test_a_failed_check_stops_the_run_also_under_python_O():
    bd.must(True, "fine")
    with pytest.raises(SystemExit, match="check failed: the reason; 3"):
        bd.must(False, "the reason", 3)
    out = subprocess.run([sys.executable, "-O", "-B", str(ROOT / "research" / "ftmo_breadth.py"),
                          "--data-dir", "nowhere", "--extra-dir", "nowhere"],
                         capture_output=True, text=True)
    assert out.returncode != 0 and "run without -O" in out.stderr


def test_b0_with_the_diagnostics_is_the_published_account(market):
    dates, four, five = market
    for b in (0, 1):
        pol = ss.CONT_POL[bd.KEY][b]
        ref, _ = so.full_run(dates, four, pol, ss.SlotAcct)
        m = bd.continuous(dates, bd.universe("B0", four, five), pol)
        assert len(ref.trades) > 10 and m["trades_by"] == list(ref.trades)
        assert sum(g["n"] for g in m["markets"].values()) == m["trades"] == m["all"]["n"]
        assert m["all"]["exp"] == pytest.approx(m["exp"]) and 0 < m["max_notional"] < 6.0


class Watched(bd.Wide):
    """Records the most positions at risk (stop under entry) after any session."""
    most = 0

    def step(self, i):
        out = super().step(i)
        Watched.most = max(Watched.most, sum(p.stop < p.entry for p in self.pos.values()))
        return out


def test_more_markets_take_more_trades_with_never_more_than_two_at_risk(market):
    dates, four, five = market
    pol = ss.CONT_POL[bd.KEY][0]
    b0, _ = so.full_run(dates, bd.universe("B0", four, five), pol, bd.Wide)
    Watched.most = 0
    b3, _ = so.full_run(dates, bd.universe("B3", four, five), pol, Watched)
    assert b3.entered > b0.entered and b3.max_open > b0.max_open
    assert Watched.most == 2                             # the two slots still bind
    assert {t["sym"] for t in b3.log} & set(bd.EXTRA)    # and new markets were traded
    assert b3.max_notional > b0.max_notional


def test_the_signals_counted_from_the_prices_are_the_accounts(market):
    dates, four, five = market
    view = bd.data_view({**four, **five})
    acct, _ = so.full_run(dates, bd.universe("B3", four, five), ss.CONT_POL[bd.KEY][0],
                          ss.SlotAcct)
    assert sum(r["signals"] for r in view["rows"].values()) == acct.sig["signals"] > 20
    assert view["sessions"] == len(dates) - bd.WARMUP
    assert view["any"]["B0"] <= view["any"]["B1"] <= view["any"]["B3"]
    assert view["any"]["B0"] <= view["any"]["B2"] <= view["any"]["B3"]
    for k in bd.EXTRA:
        assert 0 <= view["rows"][k]["alone"] <= view["rows"][k]["signals"]
    assert all(-1 <= r["corr_us"] <= 1 for r in view["rows"].values())


def cell_starts():
    return {c: ([200, 215, 230], []) for c in bd.COHORTS}


def test_a_cell_runs_on_its_own_list(market):
    dates, four, five = market
    starts, c = cell_starts(), bd.COHORTS[0]
    inst = {k: bd.universe(k, four, five) for k in bd.UNIVERSES}
    bd.DATA.update(dates=dates, inst=inst, starts=starts)
    j, got = bd.job(("stats", "B0", 0, c))
    ss.DATA.update(dates=dates, inst=four, starts=starts)
    assert j == ("stats", "B0", 0, c) and ss.same(got, ss.job(("stats", bd.KEY, 0, c))[1])
    _, wide = bd.job(("stats", "B3", 1, c))
    with ss.harness(ss.SlotAcct):
        ref = bd.policy.stats(dates, inst["B3"], ss.FTMO_POL[bd.KEY][1], *starts[c])
    assert ss.same(wide, ref) and not ss.same(wide, bd.job(("stats", "B0", 1, c))[1])
    assert bd.job(("probe", "B3", 0, c))[1]["n"] == 3


def test_the_published_check_passes_on_its_own_rows_and_catches_a_changed_cell(market,
                                                                             monkeypatch):
    dates, four, five = market
    starts, years = cell_starts(), 1.5
    inst = {"B0": bd.universe("B0", four, five)}
    bd.DATA.update(dates=dates, inst=inst, starts=starts)
    metrics = [bd.continuous(dates, inst["B0"], ss.CONT_POL[bd.KEY][b]) for b in (0, 1)]
    ftmo = dict(bd.job((kind, "B0", b, c)) for kind in ("stats", "probe")
                for b in (0, 1) for c in bd.COHORTS)
    view = bd.data_view({**four, **five})
    where = [(b, ci, c) for b in (0, 1) for ci, c in enumerate(bd.COHORTS)]
    monkeypatch.setattr(bd, "PUBLISHED", dict(
        starts=(3, 3), trades={b: bd.trade_cells(metrics[b], years) for b in (0, 1)},
        signals=bd.signal_cells(metrics[0]),
        ftmo={(b, ci): bd.ftmo_cells(ftmo[("stats", "B0", b, c)], ftmo[("probe", "B0", b, c)])
              for b, ci, c in where},
        counts={(b, ci): bd.counts(ftmo[("stats", "B0", b, c)], 3) for b, ci, c in where}))
    bd.check_b0(years, metrics, ftmo, starts, view)          # its own rows: passes

    key = ("stats", "B0", 1, bd.COHORTS[1])
    worse = {**ftmo, key: dict(ftmo[key], breach=ftmo[key]["breach"] + 1 / 3)}
    with pytest.raises(SystemExit, match="FTMO figures differ"):
        bd.check_b0(years, metrics, worse, starts, view)
    with pytest.raises(SystemExit, match="trades differ"):
        bd.check_b0(2 * years, metrics, ftmo, starts, view)
    with pytest.raises(SystemExit, match="start dates"):
        bd.check_b0(years, metrics, ftmo, {c: ([200], []) for c in bd.COHORTS}, view)
    other = dict(view, rows={**view["rows"], bd.US[0]: dict(view["rows"][bd.US[0]], signals=0)})
    with pytest.raises(SystemExit, match="signals counted from the prices"):
        bd.check_b0(years, metrics, ftmo, starts, other)
    fewer = {**ftmo, key: dict(ftmo[key], p18=ftmo[key]["p18"] + 1 / 3)}
    with pytest.raises(SystemExit, match="differ from W2\\+S2's"):
        bd.check_b0(years, metrics, fewer, starts, view)


def test_the_start_dates_are_every_fifth_session_split_at_2019():
    dates = np.array(pd.bdate_range("2018-01-01", periods=700), dtype="datetime64[ns]")
    got = bd.make_starts(dates)                      # the last session is 2020-09-04
    assert (bd.WARMUP, bd.STEP, bd.SIX_MONTHS, bd.FUNDED_DAYS) == (200, 5, 183, 252)
    assert bd.SPLIT == np.datetime64("2019-01-01")
    # 2018 has 261 weekdays: session 260 is its last. Evaluations need six months of
    # data after the start (the last such session is 568), funded runs 252 sessions.
    assert got[bd.COHORTS[0]] == (list(range(200, 261, 5)), list(range(200, 261, 5)))
    assert got[bd.COHORTS[1]] == (list(range(265, 566, 5)), list(range(265, 446, 5)))


def stats(breach, p18, pe):
    return dict(breach=breach, p18=p18, pe=pe)


def test_the_verdict_rows_count_against_b0():
    starts = {bd.COHORTS[0]: (list(range(100)), []), bd.COHORTS[1]: (list(range(200)), [])}
    ftmo = {}
    for b in (0, 1):
        for c in bd.COHORTS:
            ftmo[("stats", "B0", b, c)] = stats(0.10, 0.30, 0.40)
            ftmo[("stats", "B1", b, c)] = stats(0.10, 0.31, 0.40)
    rs = bd.rows(ftmo, starts, "B1")
    assert rs[0] == (bd.COHORTS[0], 0, 100, 10, 10, 31, 30, 40, 40)
    assert rs[3] == (bd.COHORTS[1], 1, 200, 20, 20, 62, 60, 80, 80)
    assert ss.judge(rs) == (True, True)
    text = "\n".join(bd.verdict_lines(ftmo, starts, ["B1"], judged=True))
    assert "**Beats B0:** B1; preferred by the tie-break: **B1**." in text
    assert "| B1 | 2011–18 | pessimistic | 10/100 (10.0%) vs 10/100 (10.0%) | 31/100 (31.0%) " \
           "vs 30/100 (30.0%) | 40/100 (40.0%) vs 40/100 (40.0%) | yes |" in text

    ftmo[("stats", "B1", 1, bd.COHORTS[1])] = stats(0.105, 0.31, 0.40)   # one breach more
    text = "\n".join(bd.verdict_lines(ftmo, starts, ["B1"], judged=True))
    assert "**No list beats B0** by the rule." in text
    assert "no worse anywhere: no; better somewhere: yes" in text
    text = "\n".join(bd.verdict_lines(ftmo, starts, ["B1"], judged=False))
    assert "nothing is adopted" in text and "Beats B0" not in text and "No list" not in text


def test_the_tie_break_takes_passes_then_fewer_breaches_then_fewer_markets():
    def rs(ever, breached):
        return [(c, b, 100, breached, 20, 35, 30, ever, 40) for c in bd.COHORTS for b in (0, 1)]
    assert bd.prefer({"B1": rs(45, 10), "B3": rs(50, 15)}) == "B3"   # more pass within the data
    assert bd.prefer({"B2": rs(45, 12), "B3": rs(45, 10)}) == "B3"   # then fewer breach
    assert bd.prefer({"B3": rs(45, 10), "B2": rs(45, 10), "B1": rs(45, 10)}) == "B1"
    weak = rs(50, 10)
    weak[2] = (bd.COHORTS[1], 0, 100, 10, 20, 35, 30, 41, 40)        # its lowest cell decides
    assert bd.prefer({"B1": rs(45, 10), "B3": weak}) == "B1"


def frame(closes):
    days = pd.bdate_range("2024-01-02", periods=len(closes))   # Tue 2, Wed 3, Thu 4, Fri 5, Mon 8
    closes = [float(c) for c in closes]
    return days, pd.DataFrame({
        "timestamp": [d.strftime("%Y-%m-%dT05:00:00+0000") for d in days],
        "open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
        "close": closes, "volume": 1.0})


def test_the_adjustment_scales_every_price_before_the_ex_date():
    days, df = frame([100, 100, 98, 98, 98])         # 2.00 paid on the third session
    div = pd.DataFrame({"ex_date": [days[2].strftime("%Y-%m-%d")], "amount": [2.0]})
    adj, applied = bd.adjust(df, div)
    assert list(adj["close"]) == pytest.approx([98.0] * 5)          # the drop is gone
    assert list(adj["high"]) == pytest.approx([101 * 0.98] * 2 + [99.0] * 3)
    assert list(adj["low"]) == pytest.approx([99 * 0.98] * 2 + [97.0] * 3)
    assert list(adj["open"]) == pytest.approx([98.0] * 5)
    assert applied == [(days[2], pytest.approx(0.02))]
    assert list(df["close"]) == [100, 100, 98, 98, 98] and list(adj.columns) == list(df.columns)


def test_an_ex_date_between_sessions_applies_from_the_next_one_and_outside_ones_are_ignored():
    days, df = frame([50] * 6)
    div = pd.DataFrame({"ex_date": ["2023-12-15", "2024-01-02", "2024-01-06", "2024-02-01"],
                        "amount": [1.0, 1.0, 0.5, 1.0]})
    adj, applied = bd.adjust(df, div)
    assert [d for d, _ in applied] == [days[4]]      # Saturday the 6th: Monday the 8th
    assert list(adj["close"]) == pytest.approx([49.5] * 4 + [50.0] * 2)


def test_distributions_compound_and_a_wrong_split_basis_is_refused():
    days, df = frame([100, 100, 99, 99, 97.02])
    div = pd.DataFrame({"ex_date": [days[2].strftime("%Y-%m-%d"), days[4].strftime("%Y-%m-%d")],
                        "amount": [1.0, 1.98]})      # 1% of 100, then 2% of 99
    adj, applied = bd.adjust(df, div)
    assert list(adj["close"]) == pytest.approx([97.02] * 5)
    assert [s for _, s in applied] == pytest.approx([0.01, 0.02])
    bad = pd.DataFrame({"ex_date": [days[2].strftime("%Y-%m-%d")], "amount": [12.0]})
    with pytest.raises(SystemExit, match="split basis"):
        bd.adjust(df, bad)


def write_div(folder: Path, like: Path, at=(260, 330)) -> list:
    """A 1.5% distribution for each country fund on two sessions."""
    stamps = bd.ny_days(pd.read_csv(like)["timestamp"])
    for k in bd.COUNTRIES:
        fn = bd.EXTRA[k]
        close = pd.read_csv(like.parent / fn)["close"]
        pd.DataFrame({"ex_date": [stamps[i].strftime("%Y-%m-%d") for i in at],
                      "amount": [0.015 * close[i - 1] for i in at]}
                     ).to_csv(folder / fn.replace("_long.csv", "_div.csv"), index=False)
    return [stamps[i] for i in at]


def test_the_adjusted_funds_load_on_the_same_sessions(folders, market, tmp_path):
    dates, four, five = market
    ex = write_div(tmp_path, folders[1] / "gld_long.csv")
    dates_a, adjusted, applied = bd.load_adjusted(folders[1], tmp_path)
    assert np.array_equal(dates, dates_a) and list(adjusted) == list(bd.COUNTRIES)
    i0, i1 = (int(np.searchsorted(dates, np.datetime64(d))) for d in ex)
    for k in bd.COUNTRIES:
        raw, adj = five[k]["c"], adjusted[k]["c"]
        assert [d for d, _ in applied[k]] == ex
        assert adj[:i0] == pytest.approx(raw[:i0] * 0.985 ** 2)
        assert adj[i0:i1] == pytest.approx(raw[i0:i1] * 0.985)
        assert adj[i1:] == pytest.approx(raw[i1:])
        src = pd.read_csv(folders[1] / bd.EXTRA[k])
        div = pd.read_csv(tmp_path / bd.EXTRA[k].replace("_long.csv", "_div.csv"))
        d = bd.drop_view(src, bd.adjust(src, div)[0], applied[k])
        assert (d["n"], d["total"], d["mean"]) == (2, pytest.approx(0.03), pytest.approx(0.015))
        assert d["gap_raw"] == pytest.approx(0.0)            # the made-up open is the last close
        assert d["gap_adj"] == pytest.approx(1 / 0.985 - 1)
    b3 = bd.universe("B3 adj", four, five, adjusted)
    assert list(b3) == list(bd.UNIVERSES["B3"]) and b3[bd.GOLD] is five[bd.GOLD]
    assert all(b3[k] is adjusted[k] for k in bd.COUNTRIES)
    assert all(b3[k] is four[k] for k in bd.US)


@pytest.fixture
def study(tmp_path, monkeypatch):
    """A longer made-up market in three folders, the study's two data checks
    stubbed (it is not the published market) and few start dates; and a
    record of the markets every account and FTMO cell ran on."""
    four, five, div = tmp_path / "four", tmp_path / "five", tmp_path / "div"
    for folder in (four, five, div):
        folder.mkdir()
    write_market(four, CYCLES * 3)
    write_extra(five, four / "qqq_long.csv", CYCLES * 3)
    write_div(div, five / "gld_long.csv")
    monkeypatch.setattr(bd, "verify_files", lambda *a: None)
    monkeypatch.setattr(bd, "check_b0", lambda *a, **k: None)
    monkeypatch.setattr(bd, "STEP", 25)
    monkeypatch.setattr(bd, "SPLIT", np.datetime64("2012-06-01"))
    ran = []
    real_run, real_job = so.full_run, ss.job

    def full_run(dates, inst, pol, cls):
        ran.append(tuple(inst))
        return real_run(dates, inst, pol, cls)

    def job(j):
        ran.append(tuple(ss.DATA["inst"]))
        return real_job(j)
    monkeypatch.setattr(so, "full_run", full_run)
    monkeypatch.setattr(ss, "job", job)
    args = ["--data-dir", str(four), "--extra-dir", str(five), "--jobs", "1"]
    return args, ["--div-dir", str(div)], ran


def new_markets(ran) -> set:
    return {m for markets in ran for m in markets} - set(bd.US)


def test_the_whole_study_runs_end_to_end_on_a_made_up_market(study, tmp_path):
    args, div, ran = study
    report = tmp_path / "report.md"
    assert bd.main(args + div + ["--report", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    for needle in ("What the prices alone show", "**The distributions**", "**Per trade**",
                   "| B3 | XAUUSD (GLD) |", "**Each market alone**", "| GER40 (EWG) adj |",
                   "### Verdict against B0", "| **B1** |", "| **B2** |", "| **B3** |",
                   "### Sensitivity", "| **B3 adj** |", "nothing is adopted"):
        assert needle in text, needle
    judged = text.split("### Verdict against B0")[1].split("### Sensitivity")[0]
    assert judged.count("no worse anywhere:") == 3            # one line per judged list
    assert ("**Beats B0:**" in judged) + ("**No list beats B0** by the rule." in judged) == 1
    assert "Beats B0" not in text.split("### Sensitivity")[1]
    assert new_markets(ran) == set(bd.EXTRA)                  # every new market was run
    for n in (4, 5, 8, 9, 1):                                 # the lists, and each market alone
        assert any(len(markets) == n for markets in ran), n


def test_without_the_distributions_there_are_no_sensitivity_rows(study, tmp_path):
    args, _, ran = study
    report = tmp_path / "report.md"
    assert bd.main(args + ["--report", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    assert "### Verdict against B0" in text and "| **B3** |" in text
    for absent in ("Sensitivity", " adj", "**The distributions**"):
        assert absent not in text, absent


def test_check_only_runs_accounts_on_the_four_indices_only(study, capsys):
    args, div, ran = study
    assert bd.main(args + div + ["--check-only"]) == 0
    shown = capsys.readouterr().out
    assert "no account was run on a new market" in shown and "Verdict" not in shown
    assert "What the prices alone show" in shown and "Per trade" not in shown
    assert "**The distributions**" in shown
    assert len(ran) >= 12 and new_markets(ran) == set()       # B0's accounts and cells only


def test_a_failed_b0_check_stops_the_run_before_any_new_market(study, monkeypatch):
    args, div, ran = study

    def failed(*a, **k):
        bd.must(False, "B0's trades differ from W2+S2's")
    monkeypatch.setattr(bd, "check_b0", failed)
    with pytest.raises(SystemExit, match="B0's trades differ"):
        bd.main(args + div)
    assert len(ran) >= 12 and new_markets(ran) == set()


def test_files_that_are_not_the_notes_stop_the_run_before_any_account(study, monkeypatch):
    args, div, ran = study
    monkeypatch.setattr(bd, "verify_files", VERIFY_FILES)     # the real file check again
    with pytest.raises(SystemExit, match="is not the note's file"):
        bd.main(args + div)
    assert ran == []
