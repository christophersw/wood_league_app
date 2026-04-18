import math

import streamlit as st

from app.services.analysis_service import AnalysisService
from app.web.components.auth import require_auth
from app.web.components.game_board import render_svg_game_viewer

require_auth()

service = AnalysisService()


def _win_percent(cp: float) -> float:
    """Win percentage (0-100) using Lichess empirical sigmoid."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _move_accuracy(wp_before: float, wp_after: float) -> float:
    """Per-move accuracy from Win% before and after (0-100 scale)."""
    if wp_after >= wp_before:
        return 100.0
    win_diff = wp_before - wp_after
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * win_diff) - 3.166924740191411 + 1
    return max(0.0, min(100.0, raw))


def _harmonic_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    eps = 0.001
    return len(values) / sum(1.0 / max(v, eps) for v in values)


def _derive_side_stats(moves_df, white_to_move: bool) -> dict[str, float | int | None]:
    if "ply" not in moves_df.columns or "cpl" not in moves_df.columns:
        return {
            "accuracy": None,
            "acpl": None,
            "blunders": None,
            "mistakes": None,
            "inaccuracies": None,
        }

    side_mod = 1 if white_to_move else 0
    side = moves_df[(moves_df["ply"] % 2) == side_mod].copy()
    if side.empty:
        return {
            "accuracy": None,
            "acpl": None,
            "blunders": None,
            "mistakes": None,
            "inaccuracies": None,
        }

    cpl = side["cpl"].dropna()
    if cpl.empty:
        return {
            "accuracy": None,
            "acpl": None,
            "blunders": None,
            "mistakes": None,
            "inaccuracies": None,
        }

    # Approximate per-move accuracy from CPL (assumes starting from equal position).
    move_accs: list[float] = []
    for v in cpl.tolist():
        cp_loss = float(v)
        wp_before = 50.0  # assume roughly equal position
        wp_after = _win_percent(-cp_loss)  # mover's Win% after losing cp_loss
        move_accs.append(_move_accuracy(wp_before, wp_after))

    return {
        "accuracy": _harmonic_mean(move_accs),
        "acpl": float(cpl.mean()),
        "blunders": int((cpl >= 300).sum()),
        "mistakes": int(((cpl >= 100) & (cpl < 300)).sum()),
        "inaccuracies": int(((cpl >= 50) & (cpl < 100)).sum()),
    }

st.title("Game Analysis")
st.caption("Full-game SVG board with best-move arrows and eval chart.")

# session_state is preferred (set by the in-app button); query_params support direct URL navigation.
game_id = st.session_state.pop("pending_game_id", None) or st.query_params.get("game_id", "")

if not game_id:
    st.warning("No game selected. Choose a game from My History or Game Search.")
    st.stop()

analysis = service.get_game_analysis(game_id)
if analysis is None or analysis.moves.empty:
    st.error("Game analysis not found for the requested game_id.")
    st.stop()

st.subheader(f"{analysis.white} vs {analysis.black} — {analysis.result}")
details_parts = []
if analysis.date:
    details_parts.append(analysis.date)
if analysis.time_control:
    details_parts.append(analysis.time_control)
details_line = " · ".join(details_parts)
if analysis.url:
    details_line += f"  [View on Chess.com]({analysis.url})"
if details_line:
    st.caption(details_line)
st.caption(f"Game ID: {analysis.game_id}")

# Accuracy / blunder stats — only shown when Stockfish analysis exists
derived_white = _derive_side_stats(analysis.moves, white_to_move=True)
derived_black = _derive_side_stats(analysis.moves, white_to_move=False)

white_accuracy = analysis.white_accuracy if analysis.white_accuracy is not None else derived_white["accuracy"]
black_accuracy = analysis.black_accuracy if analysis.black_accuracy is not None else derived_black["accuracy"]
white_acpl = analysis.white_acpl if analysis.white_acpl is not None else derived_white["acpl"]
black_acpl = analysis.black_acpl if analysis.black_acpl is not None else derived_black["acpl"]
white_blunders = analysis.white_blunders if analysis.white_blunders is not None else derived_white["blunders"]
white_mistakes = analysis.white_mistakes if analysis.white_mistakes is not None else derived_white["mistakes"]
white_inaccuracies = analysis.white_inaccuracies if analysis.white_inaccuracies is not None else derived_white["inaccuracies"]
black_blunders = analysis.black_blunders if analysis.black_blunders is not None else derived_black["blunders"]
black_mistakes = analysis.black_mistakes if analysis.black_mistakes is not None else derived_black["mistakes"]
black_inaccuracies = analysis.black_inaccuracies if analysis.black_inaccuracies is not None else derived_black["inaccuracies"]

accuracy_is_derived = analysis.white_accuracy is None and white_accuracy is not None

if white_accuracy is not None and black_accuracy is not None:
    st.markdown("#### Engine Analysis")
    if analysis.engine_depth:
        st.caption(f"Stockfish depth {analysis.engine_depth}")
    if accuracy_is_derived:
        st.caption("Accuracy is derived from move CPL because stored accuracy was unavailable for this game.")

    col_w, col_b = st.columns(2)
    with col_w:
        st.markdown(f"**{analysis.white}** (White)")
        st.metric("Accuracy", f"{white_accuracy:.1f}%")
        a1, a2, a3 = st.columns(3)
        a1.metric("Blunders", white_blunders or 0)
        a2.metric("Mistakes", white_mistakes or 0)
        a3.metric("Inaccuracies", white_inaccuracies or 0)
        if white_acpl is not None:
            st.caption(f"Avg centipawn loss: {white_acpl:.1f}")
    with col_b:
        st.markdown(f"**{analysis.black}** (Black)")
        st.metric("Accuracy", f"{black_accuracy:.1f}%")
        b1, b2, b3 = st.columns(3)
        b1.metric("Blunders", black_blunders or 0)
        b2.metric("Mistakes", black_mistakes or 0)
        b3.metric("Inaccuracies", black_inaccuracies or 0)
        if black_acpl is not None:
            st.caption(f"Avg centipawn loss: {black_acpl:.1f}")
    st.markdown("---")
else:
    st.info(
        "Stockfish analysis not yet available for this game. "
        "Run `python -m app.ingest.run_analysis_worker --enqueue` to queue it."
    )

# Build eval data for the linked chart (only when real evals are present)
eval_data = None
if (
    "ply" in analysis.moves.columns
    and "cp_eval" in analysis.moves.columns
    and analysis.moves["cp_eval"].notna().any()
):
    eval_data = analysis.moves[["ply", "cp_eval"]].dropna().to_dict(orient="records")

render_svg_game_viewer(
    analysis.pgn,
    moves_df=analysis.moves,
    size=560,
    orientation="white",
    initial_ply="last",
    eval_data=eval_data,
)
