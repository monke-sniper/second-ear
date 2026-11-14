"""The chunker: where a chunk ends, and what counts as silence.

Frames are 250 ms. A tone frame is loud, a zero frame is a pause.
"""

from __future__ import annotations

from server.chunker import AudioChunker, frame_db, is_silent
from server.contracts import FRAME_BYTES
from tests.helpers import silence_frame, spoken_chunk, tone_frame

SECOND = 4 * FRAME_BYTES


def test_cuts_at_a_pause_once_the_chunk_is_two_seconds():
    chunker = AudioChunker()
    audio = spoken_chunk()  # 2.0 s of tone, then two quiet frames

    assert chunker.feed(audio[: 9 * FRAME_BYTES]) == []  # one quiet frame is not a pause
    chunks = chunker.feed(audio[9 * FRAME_BYTES :])

    assert chunks == [audio]
    assert chunker.buffered_bytes == 0


def test_a_pause_before_two_seconds_does_not_cut():
    chunker = AudioChunker()
    early_pause = tone_frame() * 4 + silence_frame() * 2  # 1.5 s in total

    assert chunker.feed(early_pause) == []
    assert chunker.feed(tone_frame() * 2) == []  # 2.0 s now, but the pause is over

    chunks = chunker.feed(silence_frame() * 2)
    assert len(chunks) == 1
    assert len(chunks[0]) == 10 * FRAME_BYTES


def test_force_closes_at_six_seconds_without_a_pause():
    chunker = AudioChunker()

    assert chunker.feed(tone_frame() * 23) == []
    chunks = chunker.feed(tone_frame() * 3)

    assert [len(c) for c in chunks] == [6 * SECOND]
    assert chunker.buffered_bytes == 2 * FRAME_BYTES


def test_odd_sized_input_gives_the_same_chunks_as_whole_frames():
    audio = spoken_chunk() + tone_frame() * 24 + spoken_chunk()
    whole = AudioChunker().feed(audio)

    sliced_chunker = AudioChunker()
    sliced: list[bytes] = []
    for start in range(0, len(audio), 777):  # 777 is odd and divides nothing
        sliced.extend(sliced_chunker.feed(audio[start : start + 777]))

    assert sliced == whole
    assert b"".join(whole) == audio  # nothing lost, nothing repeated


def test_every_chunk_is_between_two_and_six_seconds():
    audio = (spoken_chunk() + tone_frame() * 30 + silence_frame() * 9) * 3

    for piece in AudioChunker().feed(audio):
        assert 2 * SECOND <= len(piece) <= 6 * SECOND


def test_flush_returns_a_tail_of_two_seconds_or_more():
    chunker = AudioChunker()
    chunker.feed(tone_frame() * 9 + b"\x01")  # 2.25 s and half a sample

    tail = chunker.flush()

    assert tail == tone_frame() * 9
    assert chunker.buffered_bytes == 0


def test_flush_drops_a_tail_shorter_than_two_seconds():
    chunker = AudioChunker()
    chunker.feed(tone_frame() * 5)

    assert chunker.flush() is None
    assert chunker.buffered_bytes == 0


def test_reset_drops_buffered_audio_and_pause_state():
    chunker = AudioChunker()
    chunker.feed(tone_frame() * 7 + silence_frame())
    chunker.reset()

    # Without the reset, this one quiet frame would complete a pause at 2.25 s.
    assert chunker.feed(tone_frame() * 8 + silence_frame()) == []


def test_frame_db_is_floored_for_silence_and_louder_for_a_tone():
    assert frame_db(silence_frame()) == -120.0
    assert -31.0 < frame_db(tone_frame(1000)) < -30.0
    assert frame_db(b"") == -120.0


def test_is_silent_only_when_every_frame_is_quiet():
    assert is_silent(silence_frame() * 8) is True
    assert is_silent(tone_frame() * 8) is False
    assert is_silent(silence_frame() * 7 + tone_frame()) is False
    assert is_silent(tone_frame(100) * 8) is True  # about -50 dBFS, under the pause level
