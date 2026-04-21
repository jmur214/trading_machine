"""Unit tests for HysteresisFilter."""

import pytest
from engines.engine_e_regime.hysteresis import HysteresisFilter


class TestHysteresisBasics:
    """Core state machine behavior."""

    def test_first_bar_accepts_immediately(self):
        f = HysteresisFilter(confirmation_bars=3)
        assert f.update("bull", 0.8) == "bull"
        assert f.confirmed_state == "bull"
        assert not f.is_transitioning

    def test_same_state_stays_confirmed(self):
        f = HysteresisFilter(confirmation_bars=3)
        f.update("bull", 0.8)
        assert f.update("bull", 0.7) == "bull"
        assert f.update("bull", 0.9) == "bull"
        assert not f.is_transitioning

    def test_transition_requires_confirmation_bars(self):
        f = HysteresisFilter(confirmation_bars=3)
        f.update("bull", 0.8)

        # First bar of "bear" — not yet confirmed
        assert f.update("bear", 0.7) == "bull"
        assert f.is_transitioning
        assert f.pending_count == 1

        # Second bar
        assert f.update("bear", 0.7) == "bull"
        assert f.pending_count == 2

        # Third bar — now confirms
        assert f.update("bear", 0.7) == "bear"
        assert f.confirmed_state == "bear"
        assert not f.is_transitioning

    def test_interrupted_transition_resets(self):
        f = HysteresisFilter(confirmation_bars=3)
        f.update("bull", 0.8)

        # Start transitioning to bear
        f.update("bear", 0.7)
        f.update("bear", 0.7)
        assert f.pending_count == 2

        # Interruption — back to bull
        assert f.update("bull", 0.8) == "bull"
        assert not f.is_transitioning
        assert f.pending_count == 0

    def test_new_pending_replaces_old(self):
        f = HysteresisFilter(confirmation_bars=3)
        f.update("bull", 0.8)

        # Start bear transition
        f.update("bear", 0.7)
        assert f.pending_state == "bear"

        # Switch to range — resets count
        f.update("range", 0.5)
        assert f.pending_state == "range"
        assert f.pending_count == 1

    def test_single_bar_confirmation(self):
        f = HysteresisFilter(confirmation_bars=1)
        f.update("bull", 0.8)
        assert f.update("bear", 0.7) == "bear"


class TestCrisisBypass:
    """Crisis states skip hysteresis when confidence is high."""

    def test_bypass_with_high_confidence(self):
        f = HysteresisFilter(
            confirmation_bars=5,
            bypass_states={"shock"},
            bypass_threshold=0.90,
        )
        f.update("normal", 0.8)

        # shock with high confidence — immediate
        assert f.update("shock", 0.95) == "shock"
        assert f.confirmed_state == "shock"
        assert not f.is_transitioning

    def test_no_bypass_below_threshold(self):
        f = HysteresisFilter(
            confirmation_bars=5,
            bypass_states={"shock"},
            bypass_threshold=0.90,
        )
        f.update("normal", 0.8)

        # shock with low confidence — must wait
        assert f.update("shock", 0.85) == "normal"
        assert f.is_transitioning
        assert f.pending_state == "shock"

    def test_bypass_only_for_listed_states(self):
        f = HysteresisFilter(
            confirmation_bars=5,
            bypass_states={"panic"},
            bypass_threshold=0.85,
        )
        f.update("calm", 0.8)

        # "stressed" is NOT a bypass state, even at high confidence
        assert f.update("stressed", 0.99) == "calm"
        assert f.is_transitioning

    def test_panic_bypass(self):
        f = HysteresisFilter(
            confirmation_bars=2,
            bypass_states={"panic"},
            bypass_threshold=0.85,
        )
        f.update("calm", 0.8)
        assert f.update("panic", 0.90) == "panic"

    def test_multiple_bypass_states(self):
        f = HysteresisFilter(
            confirmation_bars=5,
            bypass_states={"shock", "panic"},
            bypass_threshold=0.90,
        )
        f.update("normal", 0.8)
        assert f.update("panic", 0.95) == "panic"


class TestTransitionProgress:
    """Transition tracking and progress reporting."""

    def test_no_transition_is_zero(self):
        f = HysteresisFilter(confirmation_bars=5)
        f.update("bull", 0.8)
        assert f.transition_progress == 0.0

    def test_progress_increments(self):
        f = HysteresisFilter(confirmation_bars=4)
        f.update("bull", 0.8)
        f.update("bear", 0.7)
        assert f.transition_progress == pytest.approx(0.25)
        f.update("bear", 0.7)
        assert f.transition_progress == pytest.approx(0.50)
        f.update("bear", 0.7)
        assert f.transition_progress == pytest.approx(0.75)

    def test_progress_resets_on_confirm(self):
        f = HysteresisFilter(confirmation_bars=2)
        f.update("bull", 0.8)
        f.update("bear", 0.7)
        f.update("bear", 0.7)  # confirmed
        assert f.transition_progress == 0.0


class TestReset:
    """Reset clears all internal state."""

    def test_reset_clears_everything(self):
        f = HysteresisFilter(confirmation_bars=3)
        f.update("bull", 0.8)
        f.update("bear", 0.7)
        assert f.confirmed_state == "bull"
        assert f.pending_state == "bear"

        f.reset()
        assert f.confirmed_state is None
        assert f.pending_state is None
        assert f.pending_count == 0
        assert not f.is_transitioning

    def test_first_bar_after_reset(self):
        f = HysteresisFilter(confirmation_bars=3)
        f.update("bull", 0.8)
        f.reset()
        assert f.update("bear", 0.7) == "bear"  # first bar again


class TestHysteresisPerAxisDefaults:
    """Verify the default configs match the plan's axis specifications."""

    def test_trend_defaults(self):
        f = HysteresisFilter(confirmation_bars=5)
        f.update("bull", 0.8)
        # Need 5 bars to transition
        for _ in range(4):
            assert f.update("bear", 0.7) == "bull"
        assert f.update("bear", 0.7) == "bear"

    def test_volatility_defaults(self):
        f = HysteresisFilter(
            confirmation_bars=3,
            bypass_states={"shock"},
            bypass_threshold=0.90,
        )
        f.update("normal", 0.8)
        # Need 3 bars normally
        f.update("high", 0.7)
        f.update("high", 0.7)
        assert f.update("high", 0.7) == "high"

    def test_forward_stress_defaults(self):
        f = HysteresisFilter(
            confirmation_bars=2,
            bypass_states={"panic"},
            bypass_threshold=0.85,
        )
        f.update("calm", 0.8)
        # Only 2 bars needed
        f.update("cautious", 0.6)
        assert f.update("cautious", 0.6) == "cautious"
