import math
from html import escape

from sqlalchemy import and_, select
import streamlit as st

from app.config import get_settings
from app.ingest.enqueue_analysis import enqueue_game
from app.services.analysis_service import AnalysisService
from app.storage.database import get_session
from app.storage.models import AnalysisJob
from app.web.components.auth import require_auth
from app.web.components.game_board import render_svg_game_viewer

require_auth()

_settings = get_settings()

service = AnalysisService()


def _render_stat_card(
    label: str,
    value: str | int | float,
    kind: str,
    compact: bool = False,
    extra_class: str = "",
) -> None:
    safe_label = escape(str(label))
    safe_value = escape(str(value))
    safe_kind = escape(str(kind))
    compact_class = " analysis-stat--compact" if compact else ""
    safe_extra_class = escape(extra_class.strip())
    extra_class_attr = f" {safe_extra_class}" if safe_extra_class else ""
    st.markdown(
        f"""
                <div class="analysis-stat{compact_class}{extra_class_attr}">
                    <div class="analysis-stat__label">{safe_label}</div>
                    <div class="analysis-stat-card analysis-stat-card--{safe_kind}">
                        <div class="analysis-stat-card__value">{safe_value}</div>
                    </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_top_stat_row(cards: list[tuple[str, str | int | float, str]]):
    widths = [max(2.6, len(label) * 0.3 + 1.7) for label, _, _ in cards]
    name_col, *stat_cols = st.columns([3.2, *widths])
    for col, (label, value, kind) in zip(stat_cols, cards):
        with col:
            _render_stat_card(
                label,
                value,
                kind,
                compact=True,
                extra_class="analysis-stat--top-row-compact",
            )
    return name_col


def _render_three_stat_grid(cards: list[tuple[str, str | int | float, str]]) -> None:
    cols = st.columns(len(cards))
    for col, (label, value, kind) in zip(cols, cards):
        with col:
            _render_stat_card(label, value, kind)


def _render_stat_row_gap() -> None:
    st.markdown('<div class="analysis-stat-row-gap" aria-hidden="true"></div>', unsafe_allow_html=True)


def _count_classified_moves(moves_df, white_to_move: bool, classification: str) -> int | None:
    if "classification" not in moves_df.columns or moves_df.empty:
        return None
    side_mod = 1 if white_to_move else 0
    side = moves_df[(moves_df["ply"] % 2) == side_mod]
    if side.empty:
        return None
    return int((side["classification"] == classification).sum())


def _set_queue_flash(level: str, message: str) -> None:
    st.session_state["queue_flash"] = {"level": level, "message": message}


def _render_queue_flash() -> None:
    payload = st.session_state.pop("queue_flash", None)
    if not payload:
        return

    level = str(payload.get("level", "info"))
    message = str(payload.get("message", ""))
    if not message:
        return

    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


def _engine_queue_status(game_id: str, engine: str) -> str | None:
    """Return pending/running status for this game+engine if already queued."""
    with get_session() as session:
        job = session.execute(
            select(AnalysisJob)
            .where(
                and_(
                    AnalysisJob.game_id == game_id,
                    AnalysisJob.engine == engine,
                    AnalysisJob.status.in_(["pending", "running"]),
                )
            )
            .order_by(AnalysisJob.created_at.desc())
        ).scalar_one_or_none()
    return None if job is None else str(job.status)


def _win_percent(cp: float) -> float:
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _move_accuracy(wp_before: float, wp_after: float) -> float:
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
        return {"accuracy": None, "acpl": None, "blunders": None, "mistakes": None, "inaccuracies": None}

    side_mod = 1 if white_to_move else 0
    side = moves_df[(moves_df["ply"] % 2) == side_mod].copy()
    if side.empty:
        return {"accuracy": None, "acpl": None, "blunders": None, "mistakes": None, "inaccuracies": None}

    cpl = side["cpl"].dropna()
    if cpl.empty:
        return {"accuracy": None, "acpl": None, "blunders": None, "mistakes": None, "inaccuracies": None}

    move_accs: list[float] = []
    for v in cpl.tolist():
        cp_loss = float(v)
        wp_before = 50.0
        wp_after = _win_percent(-cp_loss)
        move_accs.append(_move_accuracy(wp_before, wp_after))

    return {
        "accuracy": _harmonic_mean(move_accs),
        "acpl": float(cpl.mean()),
        "blunders": int((cpl >= 300).sum()),
        "mistakes": int(((cpl >= 100) & (cpl < 300)).sum()),
        "inaccuracies": int(((cpl >= 50) & (cpl < 100)).sum()),
    }



# ── Page header ──────────────────────────────────────────────────────────────
st.title("Game Analysis")

if "pending_game_id" in st.session_state:
    st.query_params["game_id"] = st.session_state.pop("pending_game_id")
game_id = st.query_params.get("game_id", "")

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
st.caption(f"Game ID: [{analysis.game_id}](/game-analysis?game_id={analysis.game_id})")
_render_queue_flash()

# ── Lc0 WDL section ──────────────────────────────────────────────────────────
lc0_ready = (
    analysis.lc0_white_win_prob is not None
    and analysis.lc0_moves is not None
    and not analysis.lc0_moves.empty
)

if lc0_ready:
    st.markdown("---")
    st.markdown("### Lc0 Neural Network Analysis")
    nodes_label = f"{analysis.lc0_engine_nodes:,} nodes/move" if analysis.lc0_engine_nodes else ""
    net_label = analysis.lc0_network_name or ""
    caption_parts = [p for p in [net_label, nodes_label] if p]
    if caption_parts:
        st.caption(" · ".join(caption_parts))

    col_w, col_divider, col_b = st.columns([1, 0.03, 1])
    with col_w:
        w_name_col = _render_top_stat_row([
            ("Avg Win %", f"{analysis.lc0_white_win_prob:.1f}%", "accuracy"),
            ("Avg Draw %", f"{analysis.lc0_white_draw_prob:.1f}%", "accuracy"),
            ("Avg Loss %", f"{analysis.lc0_white_loss_prob:.1f}%", "accuracy"),
        ])
        with w_name_col:
            st.markdown(f"**{analysis.white}** (White)")
        _render_three_stat_grid([
            ("Inaccurate", analysis.lc0_white_inaccuracies or 0, "inaccuracy"),
            ("Mistake", analysis.lc0_white_mistakes or 0, "mistake"),
            ("Blunder", analysis.lc0_white_blunders or 0, "blunder"),
        ])
    with col_divider:
        st.markdown('<div class="analysis-player-divider" aria-hidden="true"></div>', unsafe_allow_html=True)
    with col_b:
        b_name_col = _render_top_stat_row([
            ("Avg Win %", f"{analysis.lc0_black_win_prob:.1f}%", "accuracy"),
            ("Avg Draw %", f"{analysis.lc0_black_draw_prob:.1f}%", "accuracy"),
            ("Avg Loss %", f"{analysis.lc0_black_loss_prob:.1f}%", "accuracy"),
        ])
        with b_name_col:
            st.markdown(f"**{analysis.black}** (Black)")
        _render_three_stat_grid([
            ("Inaccurate", analysis.lc0_black_inaccuracies or 0, "inaccuracy"),
            ("Mistake", analysis.lc0_black_mistakes or 0, "mistake"),
            ("Blunder", analysis.lc0_black_blunders or 0, "blunder"),
        ])


# ── Stockfish section ─────────────────────────────────────────────────────────
derived_white = _derive_side_stats(analysis.moves, white_to_move=True)
derived_black = _derive_side_stats(analysis.moves, white_to_move=False)

white_accuracy    = analysis.white_accuracy    or derived_white["accuracy"]
black_accuracy    = analysis.black_accuracy    or derived_black["accuracy"]
white_acpl        = analysis.white_acpl        or derived_white["acpl"]
black_acpl        = analysis.black_acpl        or derived_black["acpl"]
white_blunders    = analysis.white_blunders    if analysis.white_blunders    is not None else derived_white["blunders"]
white_mistakes    = analysis.white_mistakes    if analysis.white_mistakes    is not None else derived_white["mistakes"]
white_inaccuracies= analysis.white_inaccuracies if analysis.white_inaccuracies is not None else derived_white["inaccuracies"]
black_blunders    = analysis.black_blunders    if analysis.black_blunders    is not None else derived_black["blunders"]
black_mistakes    = analysis.black_mistakes    if analysis.black_mistakes    is not None else derived_black["mistakes"]
black_inaccuracies= analysis.black_inaccuracies if analysis.black_inaccuracies is not None else derived_black["inaccuracies"]

white_best_moves = _count_classified_moves(analysis.moves, white_to_move=True, classification="best")
black_best_moves = _count_classified_moves(analysis.moves, white_to_move=False, classification="best")
white_brilliant_moves = _count_classified_moves(analysis.moves, white_to_move=True, classification="brilliant")
black_brilliant_moves = _count_classified_moves(analysis.moves, white_to_move=False, classification="brilliant")
white_great_moves = _count_classified_moves(analysis.moves, white_to_move=True, classification="great")
black_great_moves = _count_classified_moves(analysis.moves, white_to_move=False, classification="great")

accuracy_is_derived = analysis.white_accuracy is None and white_accuracy is not None

if white_accuracy is not None and black_accuracy is not None:
    st.markdown("---")
    st.markdown("### Stockfish Analysis")
    if analysis.engine_depth:
        st.caption(f"Depth {analysis.engine_depth}")
    if accuracy_is_derived:
        st.caption("Accuracy derived from move CPL (stored accuracy unavailable).")

    col_w, col_divider, col_b = st.columns([1, 0.03, 1])
    with col_w:
        if white_acpl is not None:
            w_name_col, w_acc_col, w_acpl_col = st.columns([3.3, 1.35, 1.35])
        else:
            w_name_col, w_acc_col = st.columns([4.5, 1.5])
        with w_name_col:
            st.markdown(f"**{analysis.white}** (White)")
        with w_acc_col:
            _render_stat_card(
                "Accuracy",
                f"{white_accuracy:.1f}%",
                "accuracy",
                compact=True,
                extra_class="analysis-stat--top-row-compact",
            )
        if white_acpl is not None:
            with w_acpl_col:
                _render_stat_card(
                    "Avg CPL",
                    f"{white_acpl:.1f}",
                    "accuracy",
                    compact=True,
                    extra_class="analysis-stat--top-row-compact",
                )
        _render_three_stat_grid([
            ("Best", white_best_moves if white_best_moves is not None else "-", "best"),
            ("Brilliant", white_brilliant_moves if white_brilliant_moves is not None else "-", "brilliant"),
            ("Great", white_great_moves if white_great_moves is not None else "-", "great"),
        ])
        _render_stat_row_gap()
        _render_three_stat_grid([
            ("Blunder", white_blunders or 0, "blunder"),
            ("Mistake", white_mistakes or 0, "mistake"),
            ("Inaccuracy", white_inaccuracies or 0, "inaccuracy"),
        ])
    with col_divider:
        st.markdown('<div class="analysis-player-divider" aria-hidden="true"></div>', unsafe_allow_html=True)
    with col_b:
        if black_acpl is not None:
            b_name_col, b_acc_col, b_acpl_col = st.columns([3.3, 1.35, 1.35])
        else:
            b_name_col, b_acc_col = st.columns([4.5, 1.5])
        with b_name_col:
            st.markdown(f"**{analysis.black}** (Black)")
        with b_acc_col:
            _render_stat_card(
                "Accuracy",
                f"{black_accuracy:.1f}%",
                "accuracy",
                compact=True,
                extra_class="analysis-stat--top-row-compact",
            )
        if black_acpl is not None:
            with b_acpl_col:
                _render_stat_card(
                    "Avg CPL",
                    f"{black_acpl:.1f}",
                    "accuracy",
                    compact=True,
                    extra_class="analysis-stat--top-row-compact",
                )
        _render_three_stat_grid([
            ("Best", black_best_moves if black_best_moves is not None else "-", "best"),
            ("Brilliant", black_brilliant_moves if black_brilliant_moves is not None else "-", "brilliant"),
            ("Great", black_great_moves if black_great_moves is not None else "-", "great"),
        ])
        _render_stat_row_gap()
        _render_three_stat_grid([
            ("Blunder", black_blunders or 0, "blunder"),
            ("Mistake", black_mistakes or 0, "mistake"),
            ("Inaccuracy", black_inaccuracies or 0, "inaccuracy"),
        ])

# ── Queue buttons ─────────────────────────────────────────────────────────────
missing_lc0 = not lc0_ready
missing_sf = white_accuracy is None and black_accuracy is None

if missing_lc0 or missing_sf:
    st.markdown("---")
    if missing_lc0 and missing_sf:
        st.info("No engine analysis yet for this game.")

    lc0_queue_status = _engine_queue_status(game_id, "lc0") if missing_lc0 else None
    sf_queue_status = _engine_queue_status(game_id, "stockfish") if missing_sf else None

    btn_col_lc0, btn_col_sf = st.columns(2)
    if missing_lc0:
        with btn_col_lc0:
            if lc0_queue_status:
                st.caption(f"Queue status: {lc0_queue_status.title()}")
            if st.button(
                "Queue Lc0 Analysis",
                disabled=lc0_queue_status is not None,
                help=(
                    f"Lc0 analysis is already {lc0_queue_status}."
                    if lc0_queue_status
                    else "Add to Lc0 analysis queue (LC0_PATH is only required when running the worker)"
                ),
            ):
                queued = enqueue_game(game_id, engine="lc0", depth=_settings.lc0_nodes)
                if queued:
                    _set_queue_flash("success", "Queued for Lc0 analysis. Start the worker to process it.")
                else:
                    _set_queue_flash("info", "Already in the Lc0 queue.")
                st.rerun()
    if missing_sf:
        with btn_col_sf:
            if sf_queue_status:
                st.caption(f"Queue status: {sf_queue_status.title()}")
            if st.button(
                "Queue Stockfish Analysis",
                disabled=sf_queue_status is not None,
                help=(
                    f"Stockfish analysis is already {sf_queue_status}."
                    if sf_queue_status
                    else "Add to Stockfish analysis queue"
                ),
            ):
                queued = enqueue_game(game_id, engine="stockfish", depth=_settings.analysis_depth)
                if queued:
                    _set_queue_flash("success", "Queued for Stockfish analysis. Start the worker to process it.")
                else:
                    _set_queue_flash("info", "Already in the Stockfish queue.")
                st.rerun()

# ── Board viewer ──────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### Board")

# Use Lc0 arrows when available, otherwise fall back to Stockfish arrows
moves_df = analysis.moves.copy()
if lc0_ready and "arrow_uci" in analysis.lc0_moves.columns:
    lc0_arrow_map = {
        int(r["ply"]): str(r["arrow_uci"])
        for _, r in analysis.lc0_moves.iterrows()
        if r.get("arrow_uci")
    }
    if lc0_arrow_map:
        moves_df["arrow_uci"] = moves_df["ply"].map(lc0_arrow_map).fillna(
            moves_df["arrow_uci"] if "arrow_uci" in moves_df.columns else ""
        )

# Build chart data — pass both when available; board renders them as stacked charts
wdl_data = None
if lc0_ready:
    wdl_cols = ["ply", "san", "wdl_win", "wdl_draw", "wdl_loss", "classification"]
    wdl_data = analysis.lc0_moves[[c for c in wdl_cols if c in analysis.lc0_moves.columns]].to_dict(orient="records")

eval_data = None
if "cp_eval" in analysis.moves.columns and analysis.moves["cp_eval"].notna().any():
    sf = analysis.moves[["ply", "cp_eval"] + [c for c in ["san", "classification"] if c in analysis.moves.columns]].dropna(subset=["cp_eval"])
    eval_data = sf.to_dict(orient="records")

render_svg_game_viewer(
    analysis.pgn,
    moves_df=moves_df,
    size=560,
    orientation="white",
    initial_ply="last",
    wdl_data=wdl_data,
    eval_data=eval_data,
    white_player=analysis.white,
    black_player=analysis.black,
)
