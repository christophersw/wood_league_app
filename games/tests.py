"""
Title: tests.py — Unit tests for the games app
Description:
    Tests for game analysis services, board frame generation, stat card rendering,
    opening ID lookup, queue endpoint, and plySync integration.

Changelog:
    2026-05-04 (#16): Initial test suite for game analysis page rewrite
"""

from django.test import TestCase

from games.board_builder import (
    _build_tier_map,
    _inject_arrow_labels,
    build_board_frames,
)
from games.services import GameAnalysisData, MoveRow
from games.stat_cards import (
    _acc_color,
    _bar_row,
    _quality_row,
    _rerun_button,
    build_lc0_card,
    build_sf_card,
    build_stat_cards_html,
)
from games.views import _details_string, _opening_label


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_PGN = (
    '[Event "?"][Site "?"][Date "2024.01.01"][Round "?"]'
    '[White "Alice"][Black "Bob"][Result "1-0"]\n\n'
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 1-0"
)


def _make_data(**kwargs) -> GameAnalysisData:
    """Build a minimal GameAnalysisData for tests with sensible defaults."""
    defaults = dict(
        game_id="test123",
        white="Alice",
        black="Bob",
        result="1-0",
        pgn=SIMPLE_PGN,
        moves=[],
        eco_code="C65",
        opening_name="Ruy Lopez",
        lichess_opening="Ruy Lopez: Berlin Defence",
        opening_id=42,
        white_accuracy=88.5,
        black_accuracy=72.3,
        white_acpl=18.0,
        black_acpl=42.0,
    )
    defaults.update(kwargs)
    return GameAnalysisData(**defaults)


def _make_move_row(ply: int, classification: str | None = None, cp_eval: float | None = 0.0) -> MoveRow:
    """Build a minimal MoveRow for tests."""
    return MoveRow(
        ply=ply,
        san="e4" if ply == 1 else "e5",
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        cp_eval=cp_eval,
        classification=classification,
    )


# ---------------------------------------------------------------------------
# services: GameAnalysisData properties
# ---------------------------------------------------------------------------

class GameAnalysisDataPropertiesTest(TestCase):
    """Tests for GameAnalysisData computed properties."""

    def test_has_sf_true_when_accuracy_present(self):
        """has_sf returns True when white_accuracy is set."""
        data = _make_data(white_accuracy=85.0)
        self.assertTrue(data.has_sf)

    def test_has_sf_false_when_no_accuracy_or_acpl(self):
        """has_sf returns False when neither accuracy nor acpl is set."""
        data = _make_data(white_accuracy=None, black_accuracy=None, white_acpl=None, black_acpl=None)
        self.assertFalse(data.has_sf)

    def test_has_lc0_false_when_no_lc0_moves(self):
        """has_lc0 returns False when lc0_moves is None."""
        data = _make_data(lc0_moves=None)
        self.assertFalse(data.has_lc0)

    def test_has_lc0_true_when_moves_present(self):
        """has_lc0 returns True when lc0_moves list is non-empty."""
        data = _make_data(lc0_moves=[_make_move_row(1)])
        self.assertTrue(data.has_lc0)

    def test_white_label_includes_rating(self):
        """white_label appends rating in parentheses when present."""
        data = _make_data(white_rating=1800)
        self.assertEqual(data.white_label, "Alice (1800)")

    def test_white_label_no_rating(self):
        """white_label returns plain name when no rating is set."""
        data = _make_data(white_rating=None)
        self.assertEqual(data.white_label, "Alice")

    def test_opening_id_stored(self):
        """opening_id field is stored and returned as provided."""
        data = _make_data(opening_id=99)
        self.assertEqual(data.opening_id, 99)

    def test_opening_id_defaults_none(self):
        """opening_id defaults to None if not provided."""
        data = GameAnalysisData(game_id="x", white="A", black="B", result="*", pgn=SIMPLE_PGN)
        self.assertIsNone(data.opening_id)


# ---------------------------------------------------------------------------
# services: view helpers
# ---------------------------------------------------------------------------

class ViewHelperTest(TestCase):
    """Tests for view helper functions in games.views."""

    def test_details_string_both(self):
        """_details_string joins date and time_control with ·"""
        data = _make_data(date="2024-01-15", time_control="600+0")
        result = _details_string(data)
        self.assertIn("2024-01-15", result)
        self.assertIn("600+0", result)

    def test_details_string_date_only(self):
        """_details_string returns just date when time_control is empty."""
        data = _make_data(date="2024-01-15", time_control="")
        self.assertEqual(_details_string(data), "2024-01-15")

    def test_details_string_empty(self):
        """_details_string returns empty string when no date or time_control."""
        data = _make_data(date="", time_control="")
        self.assertEqual(_details_string(data), "")

    def test_opening_label_prefers_lichess(self):
        """_opening_label uses lichess_opening when available."""
        data = _make_data(eco_code="C65", lichess_opening="Ruy Lopez: Berlin Defence")
        label = _opening_label(data)
        self.assertIn("Berlin Defence", label)
        self.assertIn("C65", label)

    def test_opening_label_fallback_to_eco_name(self):
        """_opening_label falls back to eco_code · opening_name."""
        data = _make_data(eco_code="C65", opening_name="Ruy Lopez", lichess_opening=None)
        self.assertEqual(_opening_label(data), "C65 · Ruy Lopez")

    def test_opening_label_empty_when_no_data(self):
        """_opening_label returns empty string when no opening data."""
        data = _make_data(eco_code="", opening_name="", lichess_opening=None)
        self.assertEqual(_opening_label(data), "")


# ---------------------------------------------------------------------------
# board_builder: _build_tier_map
# ---------------------------------------------------------------------------

class BuildTierMapTest(TestCase):
    """Tests for the _build_tier_map helper in board_builder."""

    def test_returns_empty_for_empty_input(self):
        """_build_tier_map returns empty dict for empty input."""
        self.assertEqual(_build_tier_map({}, use_cp_equiv=False), {})

    def test_single_row_with_one_arrow(self):
        """_build_tier_map builds correct entry for a single-arrow move row."""
        row = _make_move_row(1)
        row.arrow_uci = "e2e4"
        row.arrow_score_1 = 50.0
        result = _build_tier_map({1: row}, use_cp_equiv=False)
        self.assertIn(1, result)
        self.assertEqual(result[1][0]["uci"], "e2e4")

    def test_uses_cp_equiv_when_flag_set(self):
        """_build_tier_map uses cp_equiv as the score when use_cp_equiv=True."""
        row = _make_move_row(1)
        row.arrow_uci = "e2e4"
        row.cp_equiv = 120.0
        row.arrow_score_1 = 999.0
        result = _build_tier_map({1: row}, use_cp_equiv=True)
        self.assertEqual(result[1][0]["score"], 120.0)

    def test_skips_empty_uci(self):
        """_build_tier_map skips entries with empty UCI strings."""
        row = _make_move_row(1)
        row.arrow_uci = ""
        self.assertEqual(_build_tier_map({1: row}, use_cp_equiv=False), {})


# ---------------------------------------------------------------------------
# board_builder: _inject_arrow_labels
# ---------------------------------------------------------------------------

class InjectArrowLabelsTest(TestCase):
    """Tests for _inject_arrow_labels SVG injection."""

    def test_returns_unchanged_when_no_labels(self):
        """_inject_arrow_labels returns original SVG when labels is empty."""
        svg = '<svg width="480" height="480"></svg>'
        self.assertEqual(_inject_arrow_labels(svg, [], 480, False), svg)

    def test_injects_text_element(self):
        """_inject_arrow_labels inserts a <text> element before </svg>."""
        svg = '<svg width="480" height="480"></svg>'
        labels = [{"engine": "sf", "label": "+25", "from_sq": "e2", "to_sq": "e4"}]
        result = _inject_arrow_labels(svg, labels, 480, False)
        self.assertIn("<text", result)
        self.assertIn("+25", result)

    def test_returns_original_when_svg_is_empty(self):
        """_inject_arrow_labels returns original when svg is empty string."""
        labels = [{"engine": "sf", "label": "+10", "from_sq": "e2", "to_sq": "e4"}]
        self.assertEqual(_inject_arrow_labels("", labels, 480, False), "")


# ---------------------------------------------------------------------------
# board_builder: build_board_frames
# ---------------------------------------------------------------------------

class BuildBoardFramesTest(TestCase):
    """Tests for build_board_frames main function."""

    def test_returns_only_start_frame_for_pgn_with_no_moves(self):
        """build_board_frames returns 1 frame (start position) for a PGN with no moves."""
        data = _make_data(pgn="not valid pgn")
        result = build_board_frames(data)
        self.assertEqual(len(result["frames"]), 1)
        self.assertEqual(result["san_list"], [])

    def test_frame_count_matches_ply_plus_one(self):
        """build_board_frames produces one frame per ply plus the start position."""
        data = _make_data()
        result = build_board_frames(data)
        self.assertEqual(result["total_frames"], len(result["frames"]))
        self.assertGreater(result["total_frames"], 1)

    def test_orientation_white_puts_alice_at_bottom(self):
        """board orientation=white places the white player at the bottom."""
        data = _make_data()
        result = build_board_frames(data, orientation="white")
        self.assertEqual(result["bottom_player"], "Alice")
        self.assertEqual(result["top_player"], "Bob")

    def test_orientation_black_flips_players(self):
        """board orientation=black places the black player at the bottom."""
        data = _make_data()
        result = build_board_frames(data, orientation="black")
        self.assertEqual(result["bottom_player"], "Bob")
        self.assertEqual(result["top_player"], "Alice")

    def test_san_list_length(self):
        """san_list contains one entry per move (total_frames - 1)."""
        data = _make_data()
        result = build_board_frames(data)
        self.assertEqual(len(result["san_list"]), result["total_frames"] - 1)

    def test_first_frame_is_svg(self):
        """The first frame (start position) is a valid SVG string."""
        data = _make_data()
        result = build_board_frames(data)
        self.assertIn("<svg", result["frames"][0])


# ---------------------------------------------------------------------------
# stat_cards: helpers
# ---------------------------------------------------------------------------

class AccColorTest(TestCase):
    """Tests for _acc_color accuracy tier coloring."""

    def test_high_accuracy_forest_green(self):
        """_acc_color returns forest green for accuracy >= 90."""
        self.assertEqual(_acc_color(95.0), "#1A3A2A")

    def test_mid_accuracy_moss(self):
        """_acc_color returns moss for accuracy 80-89."""
        self.assertEqual(_acc_color(85.0), "#4A6554")

    def test_low_accuracy_gold(self):
        """_acc_color returns gold for accuracy 70-79."""
        self.assertEqual(_acc_color(75.0), "#D4A843")

    def test_very_low_accuracy_red(self):
        """_acc_color returns red for accuracy below 70."""
        self.assertEqual(_acc_color(55.0), "#B53541")


class BarRowTest(TestCase):
    """Tests for _bar_row HTML generation."""

    def test_contains_player_name(self):
        """_bar_row includes the player name in output."""
        self.assertIn("Alice", _bar_row("♙", "Alice", 85.0, "85.0%"))

    def test_wide_bar_embeds_label(self):
        """_bar_row embeds value inside bar when pct > 15."""
        self.assertIn("80.0%", _bar_row("♙", "Alice", 80.0, "80.0%"))

    def test_escapes_html_in_name(self):
        """_bar_row HTML-escapes player names to prevent injection."""
        html = _bar_row("♙", "<script>bad</script>", 50.0, "50%")
        self.assertNotIn("<script>", html)


class QualityRowTest(TestCase):
    """Tests for _quality_row classification bar HTML generation."""

    def test_shows_counts_when_wide_enough(self):
        """_quality_row shows count label for segments >= 6% wide."""
        html = _quality_row("♙", "Alice", 0, 0, 0, 0, 0, 5, 10)
        self.assertIn("??", html)

    def test_hides_count_when_segment_narrow(self):
        """_quality_row hides count for very small segments (< 6%)."""
        html = _quality_row("♙", "Alice", 0, 0, 0, 0, 0, 1, 20)
        self.assertNotIn("?? 1", html)

    def test_all_zeros_produces_minimal_html(self):
        """_quality_row with all zeros returns a row with no colored segments."""
        html = _quality_row("♙", "Alice", 0, 0, 0, 0, 0, 0, 10)
        self.assertIn("dub-row", html)
        self.assertNotIn("dub-bril", html)


class RerunButtonTest(TestCase):
    """Tests for _rerun_button HTML generation."""

    def test_active_button_calls_open_queue_modal(self):
        """Active rerun button calls openQueueModal with correct engine."""
        html = _rerun_button("stockfish", queued=False)
        self.assertIn("openQueueModal('stockfish')", html)
        self.assertNotIn("disabled", html)

    def test_queued_button_is_disabled(self):
        """Queued rerun button renders as disabled."""
        self.assertIn("disabled", _rerun_button("stockfish", queued=True))

    def test_lc0_button_uses_lc0_engine(self):
        """Lc0 rerun button passes 'lc0' to openQueueModal."""
        self.assertIn("openQueueModal('lc0')", _rerun_button("lc0", queued=False))


# ---------------------------------------------------------------------------
# stat_cards: card builders
# ---------------------------------------------------------------------------

class BuildSfCardTest(TestCase):
    """Tests for build_sf_card HTML output."""

    def test_returns_empty_string_when_no_sf(self):
        """build_sf_card returns empty string when has_sf is False."""
        data = _make_data(white_accuracy=None, black_accuracy=None, white_acpl=None, black_acpl=None)
        self.assertEqual(build_sf_card(data), "")

    def test_contains_accuracy_section(self):
        """build_sf_card includes accuracy bars when accuracy data exists."""
        self.assertIn("Accuracy", build_sf_card(_make_data()))

    def test_rerun_button_present(self):
        """build_sf_card includes the rerun button."""
        self.assertIn("Re-run Analysis", build_sf_card(_make_data()))

    def test_queued_button_when_queued(self):
        """build_sf_card shows disabled button when queued=True."""
        self.assertIn("Already Queued", build_sf_card(_make_data(), queued=True))


class BuildLc0CardTest(TestCase):
    """Tests for build_lc0_card HTML output."""

    def test_returns_empty_when_no_lc0(self):
        """build_lc0_card returns empty string when has_lc0 is False."""
        self.assertEqual(build_lc0_card(_make_data(lc0_moves=None)), "")

    def test_contains_wdl_section(self):
        """build_lc0_card includes WDL section when WDL data exists."""
        data = _make_data(lc0_moves=[_make_move_row(1)], lc0_white_win_prob=60.0,
                          lc0_white_draw_prob=25.0, lc0_white_loss_prob=15.0)
        self.assertIn("Win / Draw / Loss", build_lc0_card(data))

    def test_rerun_button_lc0(self):
        """build_lc0_card includes an Lc0 rerun button."""
        data = _make_data(lc0_moves=[_make_move_row(1)], lc0_white_win_prob=50.0,
                          lc0_white_draw_prob=30.0, lc0_white_loss_prob=20.0)
        self.assertIn("openQueueModal('lc0')", build_lc0_card(data))


class BuildStatCardsHtmlTest(TestCase):
    """Tests for build_stat_cards_html combined output."""

    def test_includes_css(self):
        """build_stat_cards_html always includes the DUB CSS."""
        self.assertIn("<style>", build_stat_cards_html(_make_data()))

    def test_fallback_message_when_no_analysis(self):
        """build_stat_cards_html returns fallback text when no analysis available."""
        data = _make_data(white_accuracy=None, black_accuracy=None,
                          white_acpl=None, black_acpl=None, lc0_moves=None)
        self.assertIn("No engine analysis", build_stat_cards_html(data))

    def test_passes_sf_queued_flag(self):
        """build_stat_cards_html passes sf_queued to the SF card builder."""
        self.assertIn("Already Queued", build_stat_cards_html(_make_data(), sf_queued=True))
