import math
from html import escape

from sqlalchemy import and_, select
import streamlit as st

from app.config import get_settings
from app.ingest.enqueue_analysis import enqueue_game
from app.services.analysis_service import AnalysisService
from app.storage.database import get_session
from app.services.opening_labels import opening_display_label
from app.storage.models import AnalysisJob
from app.web.components.auth import require_auth
from app.web.components.game_board import render_svg_game_viewer

require_auth()

_settings = get_settings()

service = AnalysisService()

# ── Du Bois engine analysis CSS ───────────────────────────────────────────────
_ENGINE_CSS = """<style>
.dub {
  font-family: 'DM Mono', 'Courier New', monospace;
  color: #1A1A1A;
  margin-bottom: 1.6rem;
}
.dub-head {
  border-top: 3px solid #1A1A1A;
  border-bottom: 1.5px solid #1A1A1A;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 5px 0 4px;
  margin-bottom: 16px;
}
.dub-title {
  font-family: 'Playfair Display SC', 'Cormorant Garamond', Georgia, serif;
  font-size: 0.92rem;
  letter-spacing: 0.07em;
  color: #1A3A2A;
}
.dub-meta {
  font-size: 0.60rem;
  letter-spacing: 0.06em;
  color: #8B3A2A;
  text-transform: uppercase;
}
/* Standard comparison row: [player label] [bar] [value] */
.dub-row {
  display: grid;
  grid-template-columns: 140px 1fr 52px;
  align-items: center;
  gap: 0 8px;
  margin-bottom: 5px;
}
.dub-player-lbl {
  font-size: 0.70rem;
  letter-spacing: 0.03em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #1A1A1A;
}
.dub-chess { color: #8B3A2A; margin-right: 3px; }
.dub-val {
  font-size: 0.78rem;
  font-weight: 700;
  text-align: right;
  white-space: nowrap;
  color: #1A1A1A;
}
/* Horizontal bar */
.dub-bar {
  height: 22px;
  background: #F2E6D0;
  border: 1.5px solid #1A1A1A;
  position: relative;
  overflow: hidden;
}
.dub-bar-fill {
  position: absolute;
  left: 0; top: 0; bottom: 0;
}
/* Stacked bar (WDL, move quality) */
.dub-stack {
  height: 26px;
  display: flex;
  border: 1.5px solid #1A1A1A;
  overflow: hidden;
}
.dub-seg {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.60rem;
  font-weight: 700;
  overflow: hidden;
  white-space: nowrap;
  color: #F2E6D0;
}
/* WDL colours */
.dub-win  { background: #1A3A2A; }
.dub-draw { background: #8B3A2A; }
.dub-loss { background: #B53541; }
/* Move quality colours */
.dub-bril { background: #2C6B4A; }
.dub-best { background: #4A6E8A; }
.dub-great { background: #4A6554; }
.dub-neut { background: #EFE4CC; color: #5A5A5A; }
.dub-inac { background: #E07B7B; color: #1A1A1A; }
.dub-mist { background: #CE3A4A; }
.dub-blun { background: #B53541; }
/* Section sub-label */
.dub-lbl {
  font-size: 0.54rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #5A5A5A;
  margin: 10px 0 4px;
}
.dub-rule {
  border: none;
  border-top: 1px solid #D4C4A0;
  margin: 12px 0 10px;
}
/* Count summary: bold number + small label */
.dub-counts-row {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 0 8px;
  margin-bottom: 4px;
}
.dub-counts {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  align-items: baseline;
}
.dub-count {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
}
.dub-n { font-size: 1.10rem; font-weight: 700; line-height: 1; }
.dub-k { font-size: 0.56rem; letter-spacing: 0.06em; text-transform: uppercase; color: #5A5A5A; }
.c-bril { color: #2C6B4A; }
.c-best { color: #4A6E8A; }
.c-great { color: #4A6554; }
.c-inac { color: #E07B7B; }
.c-mist { color: #CE3A4A; }
.c-blun { color: #B53541; }
/* Legend row */
.dub-legend {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 0.57rem;
  color: #5A5A5A;
  letter-spacing: 0.04em;
  margin-top: 5px;
}
.dub-swatch {
  display: inline-block;
  width: 9px; height: 9px;
  border: 1px solid #1A1A1A;
  vertical-align: middle;
  margin-right: 2px;
}
</style>"""


# ── Du Bois render helpers ─────────────────────────────────────────────────────

def _acc_color(pct: float) -> str:
    if pct >= 90: return "#1A3A2A"
    if pct >= 80: return "#4A6554"
    if pct >= 70: return "#D4A843"
    return "#B53541"


def _bar_row(sym: str, name: str, pct: float, val_str: str, fill: str | None = None) -> str:
    color = fill or _acc_color(pct)
    w = min(max(pct, 0), 100)
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess">{sym}</span>{escape(name)}</div>'
        f'<div class="dub-bar"><div class="dub-bar-fill" style="width:{w:.1f}%;background:{color}"></div></div>'
        f'<div class="dub-val">{escape(val_str)}</div>'
        f'</div>'
    )


def _wdl_row(sym: str, name: str, win: float, draw: float, loss: float) -> str:
    def _seg(cls: str, pct: float, lbl: str) -> str:
        txt = lbl if pct >= 9 else ""
        return f'<div class="dub-seg {cls}" style="flex:{pct:.1f}">{escape(txt)}</div>'
    segs = (
        _seg("dub-win",  win,  f"W {win:.0f}%")
        + _seg("dub-draw", draw, f"D {draw:.0f}%")
        + _seg("dub-loss", loss, f"L {loss:.0f}%")
    )
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess">{sym}</span>{escape(name)}</div>'
        f'<div class="dub-stack">{segs}</div>'
        f'<div class="dub-val" style="font-size:0.58rem;color:#5A5A5A">WDL</div>'
        f'</div>'
    )


def _quality_row(
    sym: str, name: str,
    brilliant: int, best: int, great: int,
    inaccuracy: int, mistake: int, blunder: int,
    total: int,
) -> str:
    classified = brilliant + best + great + inaccuracy + mistake + blunder
    neutral = max(0, total - classified)

    def _seg(cls: str, n: int, lbl: str) -> str:
        if n == 0 or total == 0:
            return ""
        pct = n / total * 100
        txt = lbl if pct >= 6 else ""
        return f'<div class="dub-seg {cls}" style="flex:{pct:.2f}">{escape(txt)}</div>'

    neu_seg = ""
    if neutral > 0 and total > 0:
        pct = neutral / total * 100
        neu_seg = f'<div class="dub-seg dub-neut" style="flex:{pct:.2f}"></div>'

    segs = (
        _seg("dub-bril", brilliant, "!!")
        + _seg("dub-best", best, "B")
        + _seg("dub-great", great, "Gr")
        + neu_seg
        + _seg("dub-inac", inaccuracy, "?!")
        + _seg("dub-mist", mistake, "?")
        + _seg("dub-blun", blunder, "??")
    )
    total_label = str(total) if total else ""
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess">{sym}</span>{escape(name)}</div>'
        f'<div class="dub-stack">{segs}</div>'
        f'<div class="dub-val" style="font-size:0.60rem;color:#5A5A5A">{total_label}</div>'
        f'</div>'
    )


def _count(n: int | None, label: str, cls: str) -> str:
    if n is None:
        return ""
    return (
        f'<span class="dub-count">'
        f'<span class="dub-n {cls}">{n}</span>'
        f'<span class="dub-k">{escape(label)}</span>'
        f'</span>'
    )


def _counts_row(sym: str, name: str, items: list[tuple[int | None, str, str]]) -> str:
    spans = "".join(_count(n, lbl, cls) for n, lbl, cls in items)
    return (
        f'<div class="dub-counts-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess">{sym}</span>{escape(name)}</div>'
        f'<div class="dub-counts">{spans}</div>'
        f'</div>'
    )


_QUALITY_LEGEND = (
    '<div class="dub-legend">'
    '<span><span class="dub-swatch" style="background:#2C6B4A"></span>Brilliant</span>'
    '<span><span class="dub-swatch" style="background:#4A6E8A"></span>Best</span>'
    '<span><span class="dub-swatch" style="background:#4A6554"></span>Great</span>'
    '<span><span class="dub-swatch" style="background:#EFE4CC"></span>Good</span>'
    '<span><span class="dub-swatch" style="background:#E07B7B"></span>Inaccuracy</span>'
    '<span><span class="dub-swatch" style="background:#CE3A4A"></span>Mistake</span>'
    '<span><span class="dub-swatch" style="background:#B53541"></span>Blunder</span>'
    '</div>'
)


def _render_stockfish_html(
    white: str, black: str,
    w_acc: float, b_acc: float,
    w_acpl: float | None, b_acpl: float | None,
    w_bril: int | None, b_bril: int | None,
    w_best: int | None, b_best: int | None,
    w_great: int | None, b_great: int | None,
    w_inac: int | None, b_inac: int | None,
    w_mist: int | None, b_mist: int | None,
    w_blun: int | None, b_blun: int | None,
    w_total: int, b_total: int,
    depth: int | None,
    derived: bool,
) -> str:
    meta_parts = []
    if depth:
        meta_parts.append(f"Depth {depth}")
    if derived:
        meta_parts.append("Accuracy derived from CPL")
    meta = " · ".join(meta_parts)

    # Accuracy bars (same 0–100 scale, colour encodes quality)
    acc_section = (
        f'<div class="dub-lbl">Accuracy</div>'
        + _bar_row("♙", white, w_acc, f"{w_acc:.1f}%")
        + _bar_row("♟", black, b_acc, f"{b_acc:.1f}%")
    )

    # CPL bars (0–100 scale: 100 CPL = full bar; higher = redder)
    acpl_section = ""
    if w_acpl is not None or b_acpl is not None:
        w_str = f"{w_acpl:.1f}" if w_acpl is not None else "—"
        b_str = f"{b_acpl:.1f}" if b_acpl is not None else "—"
        w_pct = min(100.0, (w_acpl or 0))
        b_pct = min(100.0, (b_acpl or 0))
        acpl_section = (
            f'<div class="dub-lbl">Avg Centipawn Loss</div>'
            + _bar_row("♙", white, w_pct, w_str, fill="#B53541")
            + _bar_row("♟", black, b_pct, b_str, fill="#B53541")
        )

    # Move quality stacked bars + count summary
    quality_section = ""
    if w_total > 0 or b_total > 0:
        rows = ""
        if w_total > 0:
            rows += _quality_row(
                "♙", white,
                w_bril or 0, w_best or 0, w_great or 0,
                w_inac or 0, w_mist or 0, w_blun or 0,
                w_total,
            )
        if b_total > 0:
            rows += _quality_row(
                "♟", black,
                b_bril or 0, b_best or 0, b_great or 0,
                b_inac or 0, b_mist or 0, b_blun or 0,
                b_total,
            )
        w_summary = _counts_row("♙", white, [
            (w_bril, "Brilliant", "c-bril"),
            (w_best, "Best", "c-best"),
            (w_great, "Great", "c-great"),
            (w_inac, "Inaccuracy", "c-inac"),
            (w_mist, "Mistake", "c-mist"),
            (w_blun, "Blunder", "c-blun"),
        ])
        b_summary = _counts_row("♟", black, [
            (b_bril, "Brilliant", "c-bril"),
            (b_best, "Best", "c-best"),
            (b_great, "Great", "c-great"),
            (b_inac, "Inaccuracy", "c-inac"),
            (b_mist, "Mistake", "c-mist"),
            (b_blun, "Blunder", "c-blun"),
        ])
        quality_section = (
            f'<hr class="dub-rule">'
            f'<div class="dub-lbl">Move Quality</div>'
            + rows
            + _QUALITY_LEGEND
            + f'<div style="margin-top:8px">{w_summary}{b_summary}</div>'
        )

    return (
        f'<div class="dub">'
        f'<div class="dub-head">'
        f'<span class="dub-title">Stockfish Analysis</span>'
        f'<span class="dub-meta">{escape(meta)}</span>'
        f'</div>'
        + acc_section + acpl_section + quality_section
        + '</div>'
    )


def _render_lc0_html(
    white: str, black: str,
    w_win: float, w_draw: float, w_loss: float,
    b_win: float, b_draw: float, b_loss: float,
    w_inac: int | None, w_mist: int | None, w_blun: int | None,
    b_inac: int | None, b_mist: int | None, b_blun: int | None,
    network: str | None, nodes: int | None,
) -> str:
    meta_parts = []
    if network:
        meta_parts.append(network)
    if nodes:
        meta_parts.append(f"{nodes:,} nodes/move")
    meta = " · ".join(meta_parts)

    wdl_section = (
        f'<div class="dub-lbl">Win / Draw / Loss Probability — average over game</div>'
        + _wdl_row("♙", white, w_win, w_draw, w_loss)
        + _wdl_row("♟", black, b_win, b_draw, b_loss)
    )

    errors_section = ""
    if any(v is not None for v in [w_inac, w_mist, w_blun, b_inac, b_mist, b_blun]):
        w_row = _counts_row("♙", white, [
            (w_inac, "Inaccurate", "c-inac"),
            (w_mist, "Mistake", "c-mist"),
            (w_blun, "Blunder", "c-blun"),
        ])
        b_row = _counts_row("♟", black, [
            (b_inac, "Inaccurate", "c-inac"),
            (b_mist, "Mistake", "c-mist"),
            (b_blun, "Blunder", "c-blun"),
        ])
        errors_section = (
            f'<hr class="dub-rule">'
            f'<div class="dub-lbl">Move Errors</div>'
            + w_row + b_row
        )

    return (
        f'<div class="dub">'
        f'<div class="dub-head">'
        f'<span class="dub-title">Lc0 Neural Network</span>'
        f'<span class="dub-meta">{escape(meta)}</span>'
        f'</div>'
        + wdl_section + errors_section
        + '</div>'
    )


# ── Stat computation helpers (unchanged) ──────────────────────────────────────

def _count_classified_moves(moves_df, white_to_move: bool, classification: str) -> int | None:
    if "classification" not in moves_df.columns or moves_df.empty:
        return None
    side_mod = 1 if white_to_move else 0
    side = moves_df[(moves_df["ply"] % 2) == side_mod]
    if side.empty:
        return None
    return int((side["classification"] == classification).sum())


def _count_side_moves(moves_df, white_to_move: bool) -> int:
    if moves_df.empty:
        return 0
    side_mod = 1 if white_to_move else 0
    return len(moves_df[(moves_df["ply"] % 2) == side_mod])


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
    with get_session() as session:
        job = session.execute(
            select(AnalysisJob)
            .where(
                and_(
                    AnalysisJob.game_id == game_id,
                    AnalysisJob.engine == engine,
                    AnalysisJob.status.in_(["pending", "submitted", "running"]),
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

game_id = st.query_params.get("game_id", "")

# Support slug-based URLs: resolve slug -> game_id
_slug = st.query_params.get("slug", "")
if not game_id and _slug:
    from app.storage.models import Game as _Game
    from app.storage.database import get_session as _get_session
    from sqlalchemy import select as _select
    with _get_session() as _s:
        _resolved = _s.scalar(_select(_Game.id).where(_Game.slug == _slug))
    if _resolved:
        game_id = _resolved
        st.query_params["game_id"] = game_id
    else:
        st.error(f"No game found for slug '{_slug}'.")
        st.stop()

if not game_id and "pending_game_id" in st.session_state:
    game_id = st.session_state.pop("pending_game_id")
    st.query_params["game_id"] = game_id

if not game_id:
    st.warning("No game selected. Choose a game from My History or Game Search.")
    st.stop()

analysis = service.get_game_analysis(game_id)
if analysis is None or analysis.moves.empty:
    st.error("Game analysis not found for the requested game_id.")
    st.stop()

def _player_label(name: str, rating: int | None) -> str:
    return f"{name} ({rating})" if rating else name


white_label = _player_label(analysis.white, analysis.white_rating)
black_label = _player_label(analysis.black, analysis.black_rating)

st.subheader(f"{white_label} vs {black_label} — {analysis.result}")
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
# Show slug-based permalink if available, fall back to raw game_id
from app.storage.models import Game as _Game
from app.storage.database import get_session as _get_session
from sqlalchemy import select as _select
with _get_session() as _s:
    _game_slug = _s.scalar(_select(_Game.slug).where(_Game.id == analysis.game_id))
if _game_slug:
    st.caption(f"Game: [{_game_slug}](/game-analysis?slug={_game_slug})")
else:
    st.caption(f"Game ID: [{analysis.game_id}](/game-analysis?game_id={analysis.game_id})")

# ── Opening label ─────────────────────────────────────────────────────────────
if analysis.eco_code or analysis.opening_name:
    _op_name = opening_display_label(analysis.eco_code, analysis.lichess_opening, analysis.opening_name, analysis.pgn)
    _op_href = f"/opening-position?opening_id={analysis.opening_id}" if analysis.opening_id else "/opening-position"
    st.html(
        '<style>'
        '.ga-open{'
        'display:inline-block;border:1.5px solid #1A1A1A;color:#1A3A2A;'
        'font-family:"DM Mono",monospace;font-size:0.6rem;letter-spacing:0.08em;'
        'text-transform:uppercase;padding:2px 8px;text-decoration:none;white-space:nowrap}'
        '.ga-open:hover{background:#1A1A1A;color:#F2E6D0;text-decoration:none}'
        '</style>'
        f'<a class="ga-open" href="{escape(_op_href)}">{escape(_op_name)}</a>'
    )

_render_queue_flash()

# ── Lc0 WDL section ──────────────────────────────────────────────────────────
lc0_ready = (
    analysis.lc0_white_win_prob is not None
    and analysis.lc0_moves is not None
    and not analysis.lc0_moves.empty
)

if lc0_ready:
    st.html(_ENGINE_CSS + _render_lc0_html(
        white=white_label,
        black=black_label,
        w_win=analysis.lc0_white_win_prob,
        w_draw=analysis.lc0_white_draw_prob,
        w_loss=analysis.lc0_white_loss_prob,
        b_win=analysis.lc0_black_win_prob,
        b_draw=analysis.lc0_black_draw_prob,
        b_loss=analysis.lc0_black_loss_prob,
        w_inac=analysis.lc0_white_inaccuracies,
        w_mist=analysis.lc0_white_mistakes,
        w_blun=analysis.lc0_white_blunders,
        b_inac=analysis.lc0_black_inaccuracies,
        b_mist=analysis.lc0_black_mistakes,
        b_blun=analysis.lc0_black_blunders,
        network=analysis.lc0_network_name,
        nodes=analysis.lc0_engine_nodes,
    ))


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
    w_total = _count_side_moves(analysis.moves, white_to_move=True)
    b_total = _count_side_moves(analysis.moves, white_to_move=False)
    st.html(_ENGINE_CSS + _render_stockfish_html(
        white=white_label,
        black=black_label,
        w_acc=white_accuracy,
        b_acc=black_accuracy,
        w_acpl=white_acpl,
        b_acpl=black_acpl,
        w_bril=white_brilliant_moves,
        b_bril=black_brilliant_moves,
        w_best=white_best_moves,
        b_best=black_best_moves,
        w_great=white_great_moves,
        b_great=black_great_moves,
        w_inac=white_inaccuracies,
        b_inac=black_inaccuracies,
        w_mist=white_mistakes,
        b_mist=black_mistakes,
        w_blun=white_blunders,
        b_blun=black_blunders,
        w_total=w_total,
        b_total=b_total,
        depth=analysis.engine_depth,
        derived=accuracy_is_derived,
    ))

# ── Analysis state flags (used here and in Admin section below) ───────────────
missing_lc0 = not lc0_ready
missing_sf = white_accuracy is None and black_accuracy is None

has_lc0 = not missing_lc0
has_sf = not missing_sf

if missing_lc0 or missing_sf:
    st.markdown("---")
    if missing_lc0 and missing_sf:
        st.info("No engine analysis yet for this game. Scroll to the Admin section at the bottom to queue analysis.")
    elif missing_lc0:
        st.info("Lc0 analysis is not yet available for this game. Scroll to the Admin section to queue it.")
    else:
        st.info("Stockfish analysis is not yet available for this game. Scroll to the Admin section to queue it.")

# ── Board viewer ──────────────────────────────────────────────────────────────
st.markdown("---")

# Build per-engine tiered arrow maps: {ply: [best_uci, better_uci, good_uci]}
def _build_sf_tiers(df) -> "dict[int, list[str]]":
    tiers: dict[int, list[str]] = {}
    for _, r in df.iterrows():
        tier = [
            str(r.get("arrow_uci", "") or ""),
            str(r.get("arrow_uci_2", "") or ""),
            str(r.get("arrow_uci_3", "") or ""),
        ]
        if any(tier):
            tiers[int(r["ply"])] = tier
    return tiers

def _build_lc0_tiers(df) -> "dict[int, list[str]]":
    tiers: dict[int, list[str]] = {}
    for _, r in df.iterrows():
        tier = [
            str(r.get("arrow_uci", "") or ""),
            str(r.get("arrow_uci_2", "") or ""),
        ]
        if any(tier):
            tiers[int(r["ply"])] = tier
    return tiers

_sf_tiers = _build_sf_tiers(analysis.moves) if not analysis.moves.empty else {}
_lc0_tiers = (
    _build_lc0_tiers(analysis.lc0_moves)
    if lc0_ready and analysis.lc0_moves is not None and not analysis.lc0_moves.empty
    else {}
)

_has_sf  = bool(_sf_tiers)
_has_lc0 = bool(_lc0_tiers)

# Per-engine on/off toggles (only show checkboxes for engines that have data)
_show_sf  = False
_show_lc0 = False
if _has_sf or _has_lc0:
    st.html("""<style>
      .arrow-legend{display:flex;gap:18px;align-items:center;
        font-family:'DM Mono',monospace;font-size:0.62rem;
        letter-spacing:0.07em;text-transform:uppercase;margin-top:2px}
      .arrow-legend .swatch{display:inline-block;width:28px;height:5px;
        border-radius:2px;margin-right:4px;vertical-align:middle}
    </style>
    <div class="arrow-legend">
      <span><span class="swatch" style="background:linear-gradient(90deg,#D4A843CC,#D4A84777,#D4A84733)"></span>Stockfish: best · better · good</span>
      <span><span class="swatch" style="background:linear-gradient(90deg,#4A6E8ACC,#4A6E8A77,#4A6E8A33)"></span>Lc0: best · better</span>
    </div>""")
    _chk_col1, _chk_col2, *_ = st.columns([1, 1, 3])
    with _chk_col1:
        _show_sf  = st.checkbox("Stockfish arrows", value=_has_sf,  disabled=not _has_sf)
    with _chk_col2:
        _show_lc0 = st.checkbox("Lc0 arrows",       value=_has_lc0, disabled=not _has_lc0)

board_sf_tiers  = _sf_tiers  if _show_sf  else None
board_lc0_tiers = _lc0_tiers if _show_lc0 else None

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
    moves_df=analysis.moves,
    size=560,
    orientation="white",
    initial_ply="last",
    wdl_data=wdl_data,
    eval_data=eval_data,
    white_player=white_label,
    black_player=black_label,
    sf_arrow_tiers=board_sf_tiers,
    lc0_arrow_tiers=board_lc0_tiers,
)

# ── Admin ─────────────────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("Admin", expanded=False):
    st.warning(
        "⚠️ Running engine analysis costs real money and has a real environmental impact. "
        "Only queue games when necessary.",
        icon="⚠️",
    )

    lc0_queue_status = _engine_queue_status(game_id, "lc0") if missing_lc0 else None
    sf_queue_status = _engine_queue_status(game_id, "stockfish") if missing_sf else None
    lc0_requeue_status = _engine_queue_status(game_id, "lc0") if has_lc0 else None
    sf_requeue_status = _engine_queue_status(game_id, "stockfish") if has_sf else None

    show_lc0_queue = missing_lc0 and lc0_queue_status is None
    show_sf_queue = missing_sf and sf_queue_status is None
    show_lc0_reanalyze = has_lc0 and lc0_requeue_status is None
    show_sf_reanalyze = has_sf and sf_requeue_status is None

    any_queue = show_lc0_queue or show_sf_queue
    any_reanalyze = show_lc0_reanalyze or show_sf_reanalyze

    if any_queue:
        st.markdown("**Queue analysis**")
        q_col_lc0, q_col_sf = st.columns(2)
        if show_lc0_queue:
            with q_col_lc0:
                if st.button(
                    "Queue Lc0 Analysis",
                    help="Add to Lc0 analysis queue (LC0_PATH is only required when running the worker)",
                ):
                    queued = enqueue_game(game_id, engine="lc0", depth=_settings.lc0_nodes)
                    if queued:
                        _set_queue_flash("success", "Queued for Lc0 analysis. Start the worker to process it.")
                    else:
                        _set_queue_flash("info", "Already in the Lc0 queue.")
                    st.rerun()
        if show_sf_queue:
            with q_col_sf:
                if st.button(
                    "Queue Stockfish Analysis",
                    help="Add to Stockfish analysis queue",
                ):
                    queued = enqueue_game(game_id, engine="stockfish", depth=_settings.analysis_depth)
                    if queued:
                        _set_queue_flash("success", "Queued for Stockfish analysis. Start the worker to process it.")
                    else:
                        _set_queue_flash("info", "Already in the Stockfish queue.")
                    st.rerun()

    if any_queue and any_reanalyze:
        st.markdown("---")

    if any_reanalyze:
        st.markdown("**Reanalyze**")
        st.caption("Queuing reanalysis will overwrite all prior engine output for this game.")
        re_col_lc0, re_col_sf = st.columns(2)
        if show_lc0_reanalyze:
            with re_col_lc0:
                if st.button(
                    "Reanalyze with Lc0",
                    key="requeue_lc0",
                    help="Queue a fresh Lc0 run. New results overwrite previous Lc0 analysis.",
                ):
                    queued = enqueue_game(game_id, engine="lc0", depth=_settings.lc0_nodes)
                    if queued:
                        _set_queue_flash("success", "Queued Lc0 reanalysis. New output will replace the current analysis.")
                    else:
                        _set_queue_flash("info", "Lc0 is already queued for this game.")
                    st.rerun()
        if show_sf_reanalyze:
            with re_col_sf:
                if st.button(
                    "Reanalyze with Stockfish",
                    key="requeue_stockfish",
                    help="Queue a fresh Stockfish run. New results overwrite previous Stockfish analysis.",
                ):
                    queued = enqueue_game(game_id, engine="stockfish", depth=_settings.analysis_depth)
                    if queued:
                        _set_queue_flash("success", "Queued Stockfish reanalysis. New output will replace the current analysis.")
                    else:
                        _set_queue_flash("info", "Stockfish is already queued for this game.")
                    st.rerun()

    if not any_queue and not any_reanalyze:
        st.info("Analysis is currently in progress for this game. Buttons will appear here once the queue is clear.")
