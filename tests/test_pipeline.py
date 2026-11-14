"""CallSession: what one chunk turns into, and what the session remembers.

The scorer is scripted, so each test states the scores it needs and nothing else.
"""

from __future__ import annotations

import json

from server.contracts import AlertLevel, SimulateRequest
from server.explainer import GENERIC_SAFE_EXIT, Explainer
from server.pipeline import CallSession, simulate
from tests.helpers import FAKE_ORGS, FakeAnthropic, ScriptedScorer

CARD = "four one one one two two two two three three three three"


def run(scores, texts=None, seconds=4.0):
    """Feed one chunk per score and return (session, steps)."""
    session = CallSession(ScriptedScorer(scores))
    texts = texts or [f"chunk {index}" for index in range(len(scores))]
    return session, [session.ingest(text, seconds) for text in texts]


def levels(steps):
    return [step.alert.level.value for step in steps if step.alert is not None]


def test_a_spoken_chunk_gives_a_transcript_and_a_risk_event():
    _session, steps = run([0.2], ["hello there"])

    step = steps[0]
    assert step.transcript.text == "hello there"
    assert step.transcript.t_s == 4.0
    assert (step.risk.score, step.risk.t_s, step.risk.level) == (0.2, 4.0, AlertLevel.none)
    assert step.alert is None and step.danger is None
    assert [event.type for event in step.events] == ["transcript", "risk"]


def test_a_silent_chunk_only_moves_the_clock():
    scorer = ScriptedScorer([0.9])
    session = CallSession(scorer)

    quiet = [session.ingest("", 4.0), session.ingest("   ", 2.5)]
    spoken = session.ingest("hello", 4.0)

    assert [step.events for step in quiet] == [(), ()]
    assert spoken.transcript.t_s == 10.5
    assert len(scorer.calls) == 1  # the quiet chunks were never scored
    assert len(session.history) == 1


def test_the_scorer_sees_the_whole_transcript_so_far():
    scorer = ScriptedScorer([0.1])
    session = CallSession(scorer)

    session.ingest("hello grandma", 4.0)
    session.ingest("it is me", 4.0)

    assert scorer.calls == ["hello grandma", "hello grandma it is me"]


def test_alerts_rise_from_caution_to_scam_one_event_each():
    _session, steps = run([0.6, 0.9, 0.9, 0.95])

    assert levels(steps) == ["caution", "scam"]
    caution, scam = steps[0].alert, steps[2].alert
    assert (caution.trigger, caution.t_s) == ("smoothed_risk", 4.0)
    assert (scam.trigger, scam.t_s, scam.score) == ("two_high_chunks", 12.0, 0.9)


def test_caution_falling_back_sends_nothing_and_is_not_announced_twice():
    _session, steps = run([0.6, 0.6, 0.0, 0.0, 0.0, 0.9, 0.2])

    assert levels(steps) == ["caution"]
    # The level on the risk event does follow the rules down and up again.
    assert [step.risk.level.value for step in steps] == [
        "caution", "caution", "none", "none", "none", "none", "none",
    ]  # fmt: skip


def test_scam_straight_from_none_is_one_alert():
    _session, steps = run([0.0, 0.0, 0.0, 0.9, 0.9])

    assert levels(steps) == ["scam"]
    assert [event.type for event in steps[4].events] == ["transcript", "risk", "alert"]


def test_danger_fires_once_per_call():
    _session, steps = run([0.9, 0.9, 0.9], ["read me the code", CARD, CARD])

    fired = [step.danger for step in steps if step.danger is not None]
    assert len(fired) == 1
    assert (fired[0].digit_count, fired[0].t_s) == (12, 8.0)


def test_the_digit_gate_uses_the_latest_raw_score_not_the_smoothed_one():
    # Raw 0.4 with a smoothed risk of 0.6: caution is on, but the gate is shut.
    _session, shut = run([0.9, 0.5, 0.4], ["hi", "ok", CARD])
    # Raw 0.6 with a smoothed risk of 0.2: no alert at all, but the gate is open.
    _session, open_ = run([0.0, 0.0, 0.6], ["hi", "ok", CARD])

    assert shut[2].risk.level is AlertLevel.caution and shut[2].danger is None
    assert open_[2].risk.level is AlertLevel.none and open_[2].danger is not None


def test_a_scam_alert_keeps_the_gate_open_at_low_risk():
    _session, steps = run([0.9, 0.9, 0.1], ["hi", "ok", CARD])

    assert steps[2].danger is not None


def test_no_event_carries_the_number_that_was_read_out():
    _session, steps = run([0.9, 0.9], ["hello", "the card is 4111 1111 1111 1111 thanks"])

    wire = json.dumps([event.model_dump(mode="json") for s in steps for event in s.events])
    leaked = "4111" in wire
    assert leaked is False
    assert steps[1].transcript.text == "the card is [number] thanks"


def test_reset_starts_a_new_call():
    session, _steps = run([0.9, 0.9, 0.9, 0.9, 0.9], ["hi", CARD])
    generation = session.generation

    session.reset()
    again = [session.ingest("hi", 4.0), session.ingest(CARD, 4.0)]

    assert session.generation == generation + 1
    assert again[0].transcript.t_s == 4.0
    assert levels(again) == ["caution", "scam"]
    assert again[1].danger is not None
    assert len(session.chunks) == 2


class BrokenScorer:
    name = "broken"

    def __init__(self, value: object) -> None:
        self.value = value

    def score(self, transcript: str) -> float:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value  # type: ignore[return-value]


def test_a_broken_scorer_scores_zero_and_the_call_goes_on():
    for value in (RuntimeError("model gone"), float("nan"), 7.5, -1.0):
        step = CallSession(BrokenScorer(value)).ingest("hello", 4.0)
        expected = 1.0 if value == 7.5 else 0.0
        assert step.risk.score == expected


def explainer_with(fake: FakeAnthropic) -> Explainer:
    return Explainer(client=fake, orgs=FAKE_ORGS)


def test_simulate_returns_the_timeline_alerts_explainers_and_danger():
    fake = FakeAnthropic()
    request = SimulateRequest(chunks=["hi grandma", "", "send bail", "now", CARD])

    response = simulate(request, ScriptedScorer([0.6, 0.9, 0.9, 0.9]), explainer_with(fake))

    assert [point.t_s for point in response.timeline] == [4.0, 12.0, 16.0, 20.0]
    assert [alert.level.value for alert in response.alerts] == ["caution", "scam"]
    assert [e.t_s for e in response.explainers] == [alert.t_s for alert in response.alerts]
    assert [e.scam_type for e in response.explainers] == ["grandparent", "grandparent"]
    assert [(d.digit_count, d.t_s) for d in response.danger] == [(12, 20.0)]
    assert len(fake.calls) == 2  # once per alert, never per chunk


def test_simulate_with_a_failing_explainer_keeps_every_alert():
    fake = FakeAnthropic(raises=RuntimeError("no key"))
    request = SimulateRequest(chunks=["a", "b", "c"])

    response = simulate(request, ScriptedScorer([0.6, 0.9, 0.9]), explainer_with(fake))

    assert [alert.level.value for alert in response.alerts] == ["caution", "scam"]
    assert all(e.degraded for e in response.explainers)
    assert all(e.safe_exit_line == GENERIC_SAFE_EXIT for e in response.explainers)
    assert all(e.official_number is None for e in response.explainers)
