import streamlit as st

from app.services.analysis_service import AnalysisService
from app.web.components.auth import require_auth
from app.web.components.game_board import render_svg_game_viewer

require_auth()

service = AnalysisService()

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

# Accuracy / blunder stats — only shown when Stockfish analysis exists
if analysis.white_accuracy is not None:
    st.markdown("#### Engine Analysis")
    if analysis.engine_depth:
        st.caption(f"Stockfish depth {analysis.engine_depth}")

    col_w, col_b = st.columns(2)
    with col_w:
        st.markdown(f"**{analysis.white}** (White)")
        st.metric("Accuracy", f"{analysis.white_accuracy:.1f}%")
        a1, a2, a3 = st.columns(3)
        a1.metric("Blunders", analysis.white_blunders or 0)
        a2.metric("Mistakes", analysis.white_mistakes or 0)
        a3.metric("Inaccuracies", analysis.white_inaccuracies or 0)
        if analysis.white_acpl is not None:
            st.caption(f"Avg centipawn loss: {analysis.white_acpl:.1f}")
    with col_b:
        st.markdown(f"**{analysis.black}** (Black)")
        st.metric("Accuracy", f"{analysis.black_accuracy:.1f}%")
        b1, b2, b3 = st.columns(3)
        b1.metric("Blunders", analysis.black_blunders or 0)
        b2.metric("Mistakes", analysis.black_mistakes or 0)
        b3.metric("Inaccuracies", analysis.black_inaccuracies or 0)
        if analysis.black_acpl is not None:
            st.caption(f"Avg centipawn loss: {analysis.black_acpl:.1f}")
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
