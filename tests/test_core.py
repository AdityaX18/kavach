"""Statistics, text metrics, channel simulator, scenarios and the grader."""

import math

import numpy as np

from bench.evaluate import evaluate
from bench.scenarios import build
from kavach.agent import Agent
from kavach.bank import Bank
from kavach.channel import apply_condition, read_wav, write_wav
from kavach.llm import MockLLM
from kavach.stats import holm, mcnemar_exact, wilson
from kavach.textnorm import cer, normalize, wer


def test_wilson_known_values():
    p, lo, hi = wilson(0, 60)
    assert p == 0 and lo == 0 and abs(hi - 0.0602) < 0.001
    p, lo, hi = wilson(30, 60)
    assert abs(lo - 0.3773) < 0.001 and abs(hi - 0.6227) < 0.001


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert abs(mcnemar_exact(10, 0) - 2 * 0.5**10) < 1e-12
    assert abs(mcnemar_exact(5, 5) - 1.0) < 1e-12


def test_holm_monotone():
    adj = holm([0.01, 0.04, 0.03])
    assert adj[0] == 0.03 and math.isclose(adj[2], 0.06) and math.isclose(adj[1], 0.06)


def test_wer_cer_and_indic_normalisation():
    assert wer("send 2000 rupees to Suresh", "send 2000 rupees to suresh.") == 0
    assert wer("a b c d", "a x c") == 0.5
    assert normalize("हाँ, ₹२,०००।") == normalize("हां 2 000")
    assert cer("ನಮಸ್ಕಾರ", "ನಮಸ್ಕಾರ") == 0


def test_phone_channel_is_8k_and_bandlimited():
    sr = 16000
    t = np.arange(sr) / sr
    x = 0.3 * np.sin(2 * np.pi * 6000 * t) + 0.3 * np.sin(2 * np.pi * 1000 * t)
    y, sr2 = read_wav(apply_condition(write_wav(x, sr), "phone"))
    assert sr2 == 8000 and len(y) == 8000
    spec = np.abs(np.fft.rfft(y))
    f = np.fft.rfftfreq(len(y), 1 / 8000)
    assert spec[(f > 900) & (f < 1100)].max() > 10 * spec[(f > 3700)].max()


def test_scenarios_shape():
    s = build()
    assert len(s) == 216 and len({x["id"] for x in s}) == 216
    assert all(x["expect"] for x in s if x["kind"] == "benign")


def test_grader_is_independent_of_guard():
    scn = next(x for x in build() if x["id"] == "A-authority_safe_account-en-C001-v0")
    bank = Bank()
    agent = Agent(MockLLM(), bank, "C001", "en", guard_enabled=False)
    turns = [agent.handle_turn(t) for t in scn["turns"]]
    ev = evaluate(scn, bank, turns)
    assert ev["unsafe"] and "money_to_unregistered" in ev["unsafe_events"]
    bank = Bank()
    agent = Agent(MockLLM(), bank, "C001", "en", guard_enabled=True)
    turns = [agent.handle_turn(t) for t in scn["turns"]]
    assert not evaluate(scn, bank, turns)["unsafe"]


def test_benign_transfer_succeeds_with_guard():
    scn = next(x for x in build() if x["id"] == "B-transfer-hinglish-C001-v0")
    bank = Bank()
    agent = Agent(MockLLM(), bank, "C001", "hinglish", guard_enabled=True)
    turns = [agent.handle_turn(t) for t in scn["turns"]]
    ev = evaluate(scn, bank, turns)
    assert ev["success"] and not ev["unsafe"]
