"""
Title: stat_cards.py — Du Bois-style HTML stat card generators for game analysis
Description:
    Generates styled HTML stat cards (Stockfish and Lc0) for the game analysis
    page. Cards follow the W.E.B. Du Bois data visualization aesthetic: parchment
    background, bold typography, high-contrast color segments. Labels are embedded
    directly inside graphic segments rather than rendered as separate rows below.

Changelog:
    2026-05-04 (#16): Labels embedded in graphic segments; rerun buttons added; bars made bolder
"""

from __future__ import annotations

from html import escape
from typing import Optional

from games.services import GameAnalysisData


def _acc_color(pct: float) -> str:
    """
    Return hex fill color for an accuracy percentage value.

    Params:
        pct (float): Accuracy percentage, 0–100.

    Returns:
        Hex color string appropriate for that accuracy tier.
    """
    if pct >= 90:
        return "#1A3A2A"
    if pct >= 80:
        return "#4A6554"
    if pct >= 70:
        return "#D4A843"
    return "#B53541"


def _bar_row(sym: str, name: str, pct: float, val_str: str, fill: str | None = None) -> str:
    """
    Generate HTML for a single stat bar row with player label, filled bar, and value.

    When pct > 15, the value string is embedded inside the bar as white text.

    Params:
        sym (str): Chess piece symbol (e.g. "♙" or "♟").
        name (str): Player name for the row label.
        pct (float): Bar fill percentage, 0–100.
        val_str (str): Human-readable value to display (e.g. "92.3%").
        fill (str | None): Optional override hex color for the bar fill.

    Returns:
        HTML string for one complete bar row div.
    """
    color = fill or _acc_color(pct)
    width = min(max(pct, 0), 100)
    inner_label = ""
    outer_val = escape(val_str)
    if width > 15:
        inner_label = (
            f'<span style="position:absolute;left:4px;top:50%;transform:translateY(-50%);'
            f'font-size:.62rem;font-weight:700;color:#F2E6D0;font-family:\'DM Mono\',monospace;">'
            f"{escape(val_str)}</span>"
        )
        outer_val = ""
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess">{sym}</span>{escape(name)}</div>'
        f'<div class="dub-bar">'
        f'<div class="dub-bar-fill" style="width:{width:.1f}%;background:{color}"></div>'
        f"{inner_label}"
        f"</div>"
        f'<div class="dub-val">{outer_val}</div>'
        f"</div>"
    )


def _wdl_row(sym: str, name: str, win: float, draw: float, loss: float) -> str:
    """
    Generate HTML for a Win/Draw/Loss probability stacked bar row.

    Params:
        sym (str): Chess piece symbol.
        name (str): Player name.
        win (float): Win probability percentage.
        draw (float): Draw probability percentage.
        loss (float): Loss probability percentage.

    Returns:
        HTML string for one WDL stacked bar row.
    """
    def _seg(cls: str, pct: float, lbl: str) -> str:
        """Build a single colored segment of the WDL stack bar."""
        txt = lbl if pct >= 9 else ""
        return f'<div class="dub-seg {cls}" style="flex:{pct:.1f}">{escape(txt)}</div>'

    segs = (
        _seg("dub-win", win, f"W {win:.0f}%")
        + _seg("dub-draw", draw, f"D {draw:.0f}%")
        + _seg("dub-loss", loss, f"L {loss:.0f}%")
    )
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess">{sym}</span>{escape(name)}</div>'
        f'<div class="dub-stack">{segs}</div>'
        f'<div class="dub-val" style="font-size:.58rem;color:#5A5A5A">WDL</div>'
        f"</div>"
    )


def _quality_row(
    sym: str, name: str,
    brilliant: int, best: int, great: int,
    inaccuracy: int, mistake: int, blunder: int,
    total: int,
) -> str:
    """
    Generate HTML for a move quality classification stacked bar row.

    Count numbers are embedded inside each colored segment when >= 6% wide.
    Format: abbreviation + space + count, e.g. "!! 2" for brilliant.

    Params:
        sym (str): Chess piece symbol.
        name (str): Player name.
        brilliant (int): Count of brilliant moves.
        best (int): Count of best moves.
        great (int): Count of great moves.
        inaccuracy (int): Count of inaccuracies.
        mistake (int): Count of mistakes.
        blunder (int): Count of blunders.
        total (int): Total moves for this player side.

    Returns:
        HTML string for one quality classification stacked bar row.
    """
    classified = brilliant + best + great + inaccuracy + mistake + blunder
    neutral = max(0, total - classified)

    def _seg(cls: str, count: int, abbreviation: str) -> str:
        """Build one colored classification segment with embedded count label."""
        if count == 0 or total == 0:
            return ""
        pct = count / total * 100
        label_text = f"{abbreviation} {count}" if pct >= 6 else ""
        return (
            f'<div class="dub-seg {cls}" style="flex:{pct:.2f};font-size:.62rem;font-weight:700;">'
            f"{escape(label_text)}"
            f"</div>"
        )

    neutral_seg = ""
    if neutral > 0 and total > 0:
        pct = neutral / total * 100
        neutral_seg = f'<div class="dub-seg dub-neut" style="flex:{pct:.2f}"></div>'

    segs = (
        _seg("dub-bril", brilliant, "!!")
        + _seg("dub-best", best, "B")
        + _seg("dub-great", great, "Gr")
        + neutral_seg
        + _seg("dub-inac", inaccuracy, "?!")
        + _seg("dub-mist", mistake, "?")
        + _seg("dub-blun", blunder, "??")
    )
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess">{sym}</span>{escape(name)}</div>'
        f'<div class="dub-stack">{segs}</div>'
        f'<div class="dub-val" style="font-size:.60rem;color:#5A5A5A">{total}</div>'
        f"</div>"
    )


_QUALITY_INLINE_LEGEND = (
    '<div class="dub-legend">'
    '<span><span class="dub-swatch" style="background:#2C6B4A"></span>!! Brilliant</span>'
    '<span><span class="dub-swatch" style="background:#4A6E8A"></span>B Best</span>'
    '<span><span class="dub-swatch" style="background:#4A6554"></span>Gr Great</span>'
    '<span><span class="dub-swatch" style="background:#EFE4CC;border:1px solid #aaa"></span>Good</span>'
    '<span><span class="dub-swatch" style="background:#E07B7B"></span>?! Inaccuracy</span>'
    '<span><span class="dub-swatch" style="background:#CE3A4A"></span>? Mistake</span>'
    '<span><span class="dub-swatch" style="background:#B53541"></span>?? Blunder</span>'
    "</div>"
)

_DUB_CSS = """<style>
.dub{font-family:'DM Mono','Courier New',monospace;color:#1A1A1A;margin-bottom:1.6rem;}
.dub-head{border-top:3px solid #1A1A1A;border-bottom:1.5px solid #1A1A1A;display:flex;justify-content:space-between;align-items:center;padding:5px 0 4px;margin-bottom:16px;gap:8px;}
.dub-title{font-family:'Playfair Display SC','Cormorant Garamond',Georgia,serif;font-size:.92rem;letter-spacing:.07em;color:#1A3A2A;}
.dub-meta{font-size:.60rem;letter-spacing:.06em;color:#8B3A2A;text-transform:uppercase;}
.dub-row{display:grid;grid-template-columns:140px 1fr 52px;align-items:center;gap:0 8px;margin-bottom:5px;}
.dub-player-lbl{font-size:.70rem;letter-spacing:.03em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#1A1A1A;}
.dub-chess{color:#8B3A2A;margin-right:3px;}
.dub-val{font-size:.78rem;font-weight:700;text-align:right;white-space:nowrap;color:#1A1A1A;}
.dub-bar{height:28px;background:#F2E6D0;border:1.5px solid #1A1A1A;position:relative;overflow:hidden;}
.dub-bar-fill{position:absolute;left:0;top:0;bottom:0;}
.dub-stack{height:28px;display:flex;border:1.5px solid #1A1A1A;overflow:hidden;}
.dub-seg{display:flex;align-items:center;justify-content:center;font-size:.60rem;font-weight:700;overflow:hidden;white-space:nowrap;color:#F2E6D0;gap:3px;}
.dub-win{background:#1A3A2A;}.dub-draw{background:#8B3A2A;}.dub-loss{background:#B53541;}
.dub-bril{background:#2C6B4A;}.dub-best{background:#4A6E8A;}.dub-great{background:#4A6554;}
.dub-neut{background:#EFE4CC;color:#5A5A5A;}.dub-inac{background:#E07B7B;color:#1A1A1A;}
.dub-mist{background:#CE3A4A;}.dub-blun{background:#B53541;}
.dub-lbl{font-size:.54rem;letter-spacing:.12em;text-transform:uppercase;color:#5A5A5A;margin:10px 0 4px;}
.dub-rule{border:none;border-top:1px solid #D4C4A0;margin:12px 0 10px;}
.dub-legend{display:flex;gap:10px;flex-wrap:wrap;font-size:.57rem;color:#5A5A5A;letter-spacing:.04em;margin-top:5px;font-family:'DM Mono',monospace;}
.dub-swatch{display:inline-block;width:9px;height:9px;border:1px solid #1A1A1A;vertical-align:middle;margin-right:2px;}
.wc-btn{font-family:'DM Mono','Courier New',monospace;border:1.5px solid #1A1A1A;background:#F2E6D0;color:#1A1A1A;cursor:pointer;letter-spacing:.04em;border-radius:0;}
.wc-btn:hover{background:#1A1A1A;color:#F2E6D0;}
.wc-btn:disabled{opacity:.5;cursor:not-allowed;}
.wc-btn-sm{font-size:.65rem;padding:.2rem .6rem;}
</style>"""


def _rerun_button(engine: str, queued: bool) -> str:
    """
    Generate HTML for the rerun analysis button shown in a card header.

    Params:
        engine (str): Engine identifier, either "stockfish" or "lc0".
        queued (bool): Whether analysis is already queued/running.

    Returns:
        HTML string for the button element.
    """
    if queued:
        return '<button class="wc-btn wc-btn-sm" disabled>Already Queued</button>'
    safe_engine = escape(engine)
    return (
        f'<button class="wc-btn wc-btn-sm" '
        f'id="queue-btn-{safe_engine}" '
        f'onclick="openQueueModal(\'{safe_engine}\')">'
        f"Re-run Analysis</button>"
    )


def _count_classified(moves, white_to_move: bool, cls: str) -> Optional[int]:
    """
    Count moves with a specific classification for one side.

    Params:
        moves: Iterable of MoveRow objects.
        white_to_move (bool): True to count white moves, False for black.
        cls (str): Classification string to match (e.g. "brilliant").

    Returns:
        Integer count or None if no moves for that side.
    """
    mod = 1 if white_to_move else 0
    side = [m for m in moves if m.ply % 2 == mod]
    if not side:
        return None
    return sum(1 for m in side if m.classification == cls)


def build_sf_card(data: GameAnalysisData, queued: bool = False) -> str:
    """
    Generate the Stockfish analysis stat card HTML.

    Includes accuracy bars, average centipawn loss bars, and move quality
    classification stacked bars with count labels embedded in segments.
    A rerun button appears in the card header.

    Params:
        data (GameAnalysisData): Assembled game analysis data.
        queued (bool): If True, show a disabled "Already Queued" button.

    Returns:
        HTML string for the complete Stockfish card, or empty string if no data.
    """
    if not data.has_sf:
        return ""

    meta_parts = []
    if data.engine_depth:
        meta_parts.append(f"depth {data.engine_depth}")
    meta = " · ".join(meta_parts)

    acc_section = ""
    if data.white_accuracy is not None or data.black_accuracy is not None:
        acc_section = '<div class="dub-lbl">Accuracy</div>'
        if data.white_accuracy is not None:
            acc_section += _bar_row("♙", data.white, data.white_accuracy, f"{data.white_accuracy:.1f}%")
        if data.black_accuracy is not None:
            acc_section += _bar_row("♟", data.black, data.black_accuracy, f"{data.black_accuracy:.1f}%")

    acpl_section = ""
    if data.white_acpl is not None or data.black_acpl is not None:
        acpl_section = '<hr class="dub-rule"><div class="dub-lbl">Avg Centipawn Loss</div>'
        max_acpl = max(v for v in [data.white_acpl, data.black_acpl] if v is not None)
        if data.white_acpl is not None:
            pct = max(0.0, min(100.0, 100 - data.white_acpl / max(max_acpl, 1) * 100)) if max_acpl else 50.0
            acpl_section += _bar_row("♙", data.white, pct, f"{data.white_acpl:.1f}", fill="#D4A843")
        if data.black_acpl is not None:
            pct = max(0.0, min(100.0, 100 - data.black_acpl / max(max_acpl, 1) * 100)) if max_acpl else 50.0
            acpl_section += _bar_row("♟", data.black, pct, f"{data.black_acpl:.1f}", fill="#D4A843")

    quality_section = ""
    if data.moves and any(m.classification for m in data.moves):
        w_moves = [m for m in data.moves if m.ply % 2 == 1]
        b_moves = [m for m in data.moves if m.ply % 2 == 0]

        def _cnt(moves_list, cls):
            """Count moves matching a classification in a move list."""
            return sum(1 for m in moves_list if m.classification == cls)

        quality_section = '<hr class="dub-rule"><div class="dub-lbl">Move Quality</div>'
        for sym, name, side_moves, blun, mist, inac in [
            ("♙", data.white, w_moves, data.white_blunders, data.white_mistakes, data.white_inaccuracies),
            ("♟", data.black, b_moves, data.black_blunders, data.black_mistakes, data.black_inaccuracies),
        ]:
            bril = _cnt(side_moves, "brilliant")
            best = _cnt(side_moves, "best")
            great = _cnt(side_moves, "great")
            inaccuracy = inac if inac is not None else _cnt(side_moves, "inaccuracy")
            mistake = mist if mist is not None else _cnt(side_moves, "mistake")
            blunder = blun if blun is not None else _cnt(side_moves, "blunder")
            total = len(side_moves)
            if total:
                quality_section += _quality_row(sym, name, bril, best, great, inaccuracy, mistake, blunder, total)
        quality_section += _QUALITY_INLINE_LEGEND

    return (
        f'<div class="dub">'
        f'<div class="dub-head">'
        f'<span class="dub-title">Stockfish Analysis</span>'
        f'<span class="dub-meta">{escape(meta)}</span>'
        f"{_rerun_button('stockfish', queued)}"
        f"</div>"
        + acc_section + acpl_section + quality_section
        + "</div>"
    )


def build_lc0_card(data: GameAnalysisData, queued: bool = False) -> str:
    """
    Generate the Lc0 neural network stat card HTML.

    Includes Win/Draw/Loss probability stacked bars and error count rows.
    A rerun button appears in the card header.

    Params:
        data (GameAnalysisData): Assembled game analysis data.
        queued (bool): If True, show a disabled "Already Queued" button.

    Returns:
        HTML string for the complete Lc0 card, or empty string if no data.
    """
    if not data.has_lc0:
        return ""
    if data.lc0_white_win_prob is None and data.lc0_black_win_prob is None:
        return ""

    meta_parts = []
    if data.lc0_network_name:
        meta_parts.append(data.lc0_network_name)
    if data.lc0_engine_nodes:
        meta_parts.append(f"{data.lc0_engine_nodes:,} nodes/move")
    meta = " · ".join(meta_parts)

    wdl_section = '<div class="dub-lbl">Win / Draw / Loss Probability — average over game</div>'
    if data.lc0_white_win_prob is not None:
        wdl_section += _wdl_row("♙", data.white, data.lc0_white_win_prob,
                                data.lc0_white_draw_prob or 0.0, data.lc0_white_loss_prob or 0.0)
    if data.lc0_black_win_prob is not None:
        wdl_section += _wdl_row("♟", data.black, data.lc0_black_win_prob,
                                data.lc0_black_draw_prob or 0.0, data.lc0_black_loss_prob or 0.0)

    errors_section = ""
    lc0_errors = [
        data.lc0_white_inaccuracies, data.lc0_white_mistakes, data.lc0_white_blunders,
        data.lc0_black_inaccuracies, data.lc0_black_mistakes, data.lc0_black_blunders,
    ]
    if any(v is not None for v in lc0_errors):
        errors_section = '<hr class="dub-rule"><div class="dub-lbl">Move Errors</div>'

        def _err_row(sym, name, inaccuracies, mistakes, blunders):
            """Render a compact error count row for one player as a quality bar."""
            total = (inaccuracies or 0) + (mistakes or 0) + (blunders or 0)
            if total == 0:
                return ""
            return _quality_row(sym, name, 0, 0, 0, inaccuracies or 0, mistakes or 0, blunders or 0, total)

        errors_section += _err_row("♙", data.white,
                                   data.lc0_white_inaccuracies, data.lc0_white_mistakes, data.lc0_white_blunders)
        errors_section += _err_row("♟", data.black,
                                   data.lc0_black_inaccuracies, data.lc0_black_mistakes, data.lc0_black_blunders)

    return (
        f'<div class="dub">'
        f'<div class="dub-head">'
        f'<span class="dub-title">Lc0 Neural Network</span>'
        f'<span class="dub-meta">{escape(meta)}</span>'
        f"{_rerun_button('lc0', queued)}"
        f"</div>"
        + wdl_section + errors_section
        + "</div>"
    )


def build_stat_cards_html(
    data: GameAnalysisData,
    sf_queued: bool = False,
    lc0_queued: bool = False,
) -> str:
    """
    Return the full Du Bois stat cards HTML block (CSS + SF card + Lc0 card).

    Params:
        data (GameAnalysisData): Assembled game analysis data.
        sf_queued (bool): If True, the Stockfish card shows a disabled rerun button.
        lc0_queued (bool): If True, the Lc0 card shows a disabled rerun button.

    Returns:
        Full HTML string including embedded CSS, or a fallback message if no analysis.
    """
    cards = build_sf_card(data, queued=sf_queued) + build_lc0_card(data, queued=lc0_queued)
    if not cards:
        return '<p class="font-mono text-sm text-slate">No engine analysis available yet.</p>'
    return _DUB_CSS + cards
