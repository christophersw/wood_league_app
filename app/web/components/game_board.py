from __future__ import annotations

import io
import json
import math
from uuid import uuid4

import chess
import chess.pgn
import chess.svg
import pandas as pd
import streamlit as st

from app.web.components.html_embed import render_html_iframe

# ── Du Bois palette board colors ─────────────────────────────────────────────
_BOARD_COLORS = {
    "square light": "#F2E6D0",  # Parchment
    "square dark": "#4A8C62",  # Medium green (matches opening preview)
    "margin": "#1A1A1A",  # Ebony
    "coord": "#D4A843",  # Whisky
}

# Per-engine tiered arrow colors: best / better / good
# Stockfish: whisky amber; Lc0: steel blue (both already in the Du Bois palette)
_SF_ARROW_COLORS = ["#D4A843CC", "#D4A84377", "#D4A84333"]
_LC0_ARROW_COLORS = ["#4A6E8ACC", "#4A6E8A77", "#4A6E8A33"]


def _apply_custom_pieces(svg: str) -> str:
    """Return python-chess native SVG pieces without overriding defs."""
    return svg


def _inject_arrow_labels(
    svg: str, labels: list[dict], size: int, flipped: bool
) -> str:
    """Inject SVG text labels at arrow tips in the board SVG."""
    import re
    
    if not labels or not svg:
        return svg
    
    # python-chess SVG uses a fixed internal coordinate space regardless of `size`:
    # viewBox="0 0 390 390", MARGIN=15, SQUARE_SIZE=45
    _MARGIN = 15
    _SQ = 45

    def sq_to_px(sq: str) -> tuple[float, float]:
        if not sq or len(sq) < 2:
            return (0.0, 0.0)
        try:
            f = ord(sq[0]) - ord('a')
            r = int(sq[1]) - 1
            if flipped:
                f = 7 - f
                r = 7 - r
            x = _MARGIN + (f + 0.5) * _SQ
            y = _MARGIN + (7 - r + 0.5) * _SQ
            return (x, y)
        except (ValueError, IndexError):
            return (0.0, 0.0)
    
    # Group labels by destination square so co-located ones can be spaced apart
    by_sq: dict[str, list[dict]] = {}
    for label_data in labels:
        to_sq = label_data.get("to_sq", "")
        text = label_data.get("label", "")
        if not to_sq or not text:
            continue
        by_sq.setdefault(to_sq, []).append(label_data)

    font_size = 11
    line_h = font_size + 3  # vertical gap between stacked labels (viewBox units)

    text_elements = []
    for to_sq, sq_labels in by_sq.items():
        cx, cy = sq_to_px(to_sq)
        # Place the group in the upper-centre of the square (viewBox units)
        base_y = cy - _SQ * 0.22
        # Stack multiple labels vertically, centred together
        n = len(sq_labels)
        start_y = base_y - (n - 1) * line_h / 2
        for idx, label_data in enumerate(sq_labels):
            text = label_data.get("label", "")
            engine = label_data.get("engine", "SF").lower()
            fg = "#FFE082" if ("sf" in engine or "stock" in engine) else "#80CBC4"
            lx = cx
            ly = start_y + idx * line_h
            text_elements.append(
                f'<rect x="{lx - 18:.1f}" y="{ly - font_size + 1:.1f}" '
                f'width="36" height="{font_size + 2}" rx="2" '
                f'fill="#1A1A1A" fill-opacity="0.72" pointer-events="none"/>'
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                f'dominant-baseline="auto" font-size="{font_size}" font-weight="bold" '
                f'font-family="monospace" fill="{fg}" pointer-events="none">{text}</text>'
            )
    
    if not text_elements:
        return svg
    
    # Insert text elements before closing </svg> tag
    text_html = "\n".join(text_elements)
    svg_with_labels = re.sub(r'</svg>', f'{text_html}\n</svg>', svg, count=1)
    return svg_with_labels


def render_svg_game_viewer(
    pgn: str,
    moves_df: pd.DataFrame,
    size: int = 560,
    orientation: str = "white",
    initial_ply: int | str = "last",
    eval_data: list[dict] | None = None,
    wdl_data: list[dict] | None = None,
    white_player: str = "White",
    black_player: str = "Black",
    sf_arrow_tiers: "dict[int, list[dict[str, object]]] | None" = None,
    lc0_arrow_tiers: "dict[int, list[dict[str, object]]] | None" = None,
    sf_played_scores: "dict[int, float] | None" = None,
    lc0_played_scores: "dict[int, float] | None" = None,
    sf_arrow_label_prefix: str = "SF",
    lc0_arrow_label_prefix: str = "Lc0",
    has_sf: bool = False,
    has_lc0: bool = False,
    show_sf_initial: bool = True,
    show_lc0_initial: bool = True,
) -> None:
    """Full-game SVG viewer with play/pause, scrubber, move list, and best-move arrows.

    ``moves_df`` must have columns: ply, san, fen, arrow_uci (UCI of best move).
    ``wdl_data`` — optional list of {"ply": int, "wdl_win": int, "wdl_draw": int, "wdl_loss": int}
    dicts (permille, white-perspective). When provided, renders a Lc0 WDL stacked area chart.
    ``eval_data`` — optional list of {"ply": int, "cp_eval": float} dicts.
    When provided (and wdl_data is None), renders a centipawn bar chart.
    Both charts are interactive: navigating the board highlights the current position,
    and clicking the chart jumps the board to that ply.
    """
    viewer_id = f"svg-{uuid4().hex}"
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        st.warning("Could not parse PGN.")
        return

    flipped = orientation == "black"
    start_ply_offset = game.board().ply()

    # -- Build SVG frames for each position -----------------------------------
    board = game.board()
    moves_played: list[chess.Move] = list(game.mainline_moves())

    # Build a lookup from ply → arrow_uci
    arrow_map: dict[int, str] = {}
    san_list: list[str] = []
    if not moves_df.empty:
        for _, row in moves_df.iterrows():
            # Stored analysis ply may be absolute (from FEN start) while this
            # viewer is frame-indexed from 1 for the first displayed move.
            p_abs = int(row["ply"])
            p_rel = p_abs - start_ply_offset
            if p_rel < 1:
                continue
            arrow_map[p_rel] = str(row.get("arrow_uci", "") or "")
            san_list.append(str(row.get("san", "")))
    else:
        for move in moves_played:
            san_list.append(board.san(move))
        board = game.board()  # reset

    frames: list[str] = []
    is_best_map: dict[int, bool] = {}
    arrow_labels_by_ply: dict[int, list[dict[str, object]]] = {}

    # Frame 0: starting position (no arrows, no lastmove)
    frames.append(
        _apply_custom_pieces(
            chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS)
        )
    )

    board = game.board()  # reset
    for ply_i, move in enumerate(moves_played, start=1):
        board.push(move)
        # Best-move arrow for this ply
        arrows: list[chess.svg.Arrow] = []

        def _add_arrows(
            tier_map: "dict[int, list[dict[str, object]]] | None",
            played_scores: "dict[int, float] | None",
            colors: list[str],
            engine_prefix: str,
        ) -> None:
            if tier_map is None:
                return

            abs_ply = ply_i + start_ply_offset
            tier_entries = tier_map.get(abs_ply, [])
            scores: list[float | None] = []
            ucis: list[str] = []
            for entry in tier_entries:
                if isinstance(entry, dict):
                    ucis.append(str(entry.get("uci", "") or ""))
                    raw_score = entry.get("score")
                    try:
                        score_f = float(raw_score) if raw_score is not None else None
                    except (TypeError, ValueError):
                        score_f = None
                    scores.append(score_f)
                else:
                    ucis.append(str(entry or ""))
                    scores.append(None)

            played_score = None
            if played_scores is not None:
                played_score = played_scores.get(abs_ply)

            base = scores[0] if scores and scores[0] is not None else None
            max_gap = 0.0
            if base is not None:
                for s in scores[1:]:
                    if s is not None:
                        max_gap = max(max_gap, max(0.0, float(base - s)))

            def _tier_alpha(i: int, s: float | None) -> int:
                default = [220, 140, 75]
                if i >= len(default):
                    return 75
                alpha = default[i]
                if base is None or s is None:
                    return alpha
                gap = max(0.0, float(base - s))
                # Normalized emphasis by relative gap; larger gap => lighter weaker lines.
                rel = 0.0 if max_gap <= 1e-9 else min(1.0, gap / max_gap)
                if i == 0:
                    return 245
                # Blend between slightly dark and faint based on relative weakness.
                return int(max(50, min(220, round(200 - 130 * rel))))

            for i, uci in enumerate(ucis):
                if not (uci and len(uci) >= 4 and i < len(colors)):
                    continue
                try:
                    rgba = colors[i]
                    if len(rgba) == 9 and rgba.startswith("#"):
                        rgba = rgba[:7] + f"{_tier_alpha(i, scores[i]):02X}"
                    arrows.append(
                        chess.svg.Arrow(
                            chess.parse_square(uci[:2]),
                            chess.parse_square(uci[2:4]),
                            color=rgba,
                        )
                    )
                    score_txt = ""
                    if played_score is not None and scores[i] is not None:
                        # Labels show advantage of candidate over played move
                        # SF: raw centipawns; Lc0: win% change
                        gain = float(scores[i]) - float(played_score)
                        if "lc0" in engine_prefix.lower():
                            # Lc0: convert cp-equiv to win% change (roughly: 1 pawn = 0.04 win%)
                            win_pct_change = (gain / 100.0) * 0.04
                            rounded = int(round(win_pct_change * 100))  # convert to bps
                            score_txt = f"{rounded:+d}%" if rounded != 0 else "±0%"
                        else:
                            # Stockfish: raw centipawns
                            rounded = int(round(gain))
                            score_txt = f"{rounded:+d}"
                    elif base is not None and scores[i] is not None:
                        gap = float(base) - float(scores[i])
                        if "lc0" in engine_prefix.lower():
                            win_pct_change = (gap / 100.0) * 0.04
                            rounded = int(round(win_pct_change * 100))
                            score_txt = f"{rounded:+d}%" if rounded != 0 else "±0%"
                        else:
                            rounded = int(round(gap))
                            score_txt = f"{rounded:+d}"
                    elif scores[i] is not None:
                        # Fallback: show raw score if we can't compare
                        score_val = float(scores[i])
                        if "lc0" in engine_prefix.lower():
                            rounded = int(round(score_val))
                            score_txt = f"{rounded:+d}%"
                        else:
                            rounded = int(round(score_val))
                            score_txt = f"{rounded:+d}"
                    
                    label = score_txt
                    payload = {
                        "engine": engine_prefix,
                        "label": label,
                        "uci": uci,
                        "tier": i + 1,
                        "from_sq": uci[:2],
                        "to_sq": uci[2:4],
                    }
                    arrow_labels_by_ply.setdefault(ply_i, []).append(payload)
                    if abs_ply != ply_i:
                        arrow_labels_by_ply.setdefault(abs_ply, []).append(payload)
                except ValueError:
                    pass

        # Track best-move match for eval chart highlighting (use SF tier-1 when available)
        # Tier maps use absolute plies; arrow_map uses relative plies (already normalised above)
        _sf_entry0 = (
            ((sf_arrow_tiers or {}).get(ply_i + start_ply_offset, [{}]) or [{}])[0]
            if sf_arrow_tiers
            else {"uci": arrow_map.get(ply_i, "")}
        )
        _sf_best = (
            str(_sf_entry0.get("uci", "") or "")
            if isinstance(_sf_entry0, dict)
            else str(_sf_entry0 or "")
        )
        if _sf_best:
            is_best_map[ply_i] = move.uci() == _sf_best

        if sf_arrow_tiers is not None:
            _add_arrows(
                sf_arrow_tiers,
                sf_played_scores,
                _SF_ARROW_COLORS,
                sf_arrow_label_prefix,
            )
        else:
            # Fallback: use moves_df arrow_uci as a single-tier SF arrow
            uci_str = arrow_map.get(ply_i, "")
            if uci_str and len(uci_str) >= 4:
                try:
                    arrows.append(
                        chess.svg.Arrow(
                            chess.parse_square(uci_str[:2]),
                            chess.parse_square(uci_str[2:4]),
                            color=_SF_ARROW_COLORS[0],
                        )
                    )
                except ValueError:
                    pass

        _add_arrows(
            lc0_arrow_tiers,
            lc0_played_scores,
            _LC0_ARROW_COLORS,
            lc0_arrow_label_prefix,
        )

        board_svg = chess.svg.board(
            board,
            size=size,
            lastmove=move,
            arrows=arrows,
            flipped=flipped,
            colors=_BOARD_COLORS,
        )
        
        # Inject arrow labels into the SVG
        # Check both relative ply (ply_i) and absolute ply (ply_i + start_ply_offset)
        labels_for_ply = arrow_labels_by_ply.get(ply_i, [])
        if not labels_for_ply:
            labels_for_ply = arrow_labels_by_ply.get(ply_i + start_ply_offset, [])
        
        if labels_for_ply:
            board_svg = _inject_arrow_labels(
                board_svg, labels_for_ply, size, flipped
            )

        frames.append(_apply_custom_pieces(board_svg))

    total_frames = len(frames)  # 0..N where 0=start, 1=after move 1, etc.

    if isinstance(initial_ply, int) and 0 <= initial_ply < total_frames:
        start_ply = initial_ply
    else:
        start_ply = total_frames - 1

    # -- Build move list HTML (numbered moves) --------------------------------
    move_spans: list[str] = []
    for i, san in enumerate(san_list):
        ply = i + 1
        if ply % 2 == 1:
            move_no = (ply + 1) // 2
            move_spans.append(f'<span class="move-num">{move_no}.</span>')
        move_spans.append(
            f'<span class="move" data-ply="{ply}" onclick="goTo({ply})">{san}</span>'
        )
    moves_html = " ".join(move_spans)

    # -- Serialize SVG frames as JSON -----------------------------------------
    frames_json = json.dumps(frames)
    arrow_labels_json = json.dumps(arrow_labels_by_ply)

    top_player = black_player if not flipped else white_player
    top_sym = "♟" if not flipped else "♙"
    top_side = "Black" if not flipped else "White"
    bottom_player = white_player if not flipped else black_player
    bottom_sym = "♙" if not flipped else "♟"
    bottom_side = "White" if not flipped else "Black"

    _sf_checked = "checked" if (has_sf and show_sf_initial) else ""
    _lc0_checked = "checked" if (has_lc0 and show_lc0_initial) else ""
    _sf_disabled = "" if has_sf else "disabled"
    _lc0_disabled = "" if has_lc0 else "disabled"
    _toggles_display = "flex" if (has_sf or has_lc0) else "none"
    _js_show_sf = "true" if (has_sf and show_sf_initial) else "false"
    _js_show_lc0 = "true" if (has_lc0 and show_lc0_initial) else "false"

    html = f"""
    <style>
      #{viewer_id} {{
        font-family: Georgia, serif;
        max-width: 1200px;
        background: transparent;
      }}
      #{viewer_id} .viewer-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 20px;
        align-items: start;
      }}
      #{viewer_id} .board-pane,
      #{viewer_id} .analysis-pane {{
        min-width: 0;
      }}
      #{viewer_id} .board-pane {{
        display: flex;
        flex-direction: column;
        gap: 0;
      }}
      #{viewer_id} .board-wrap {{
        border-left: 2px solid #1A1A1A;
        border-right: 2px solid #1A1A1A;
      }}
      #{viewer_id} .board-wrap svg {{ display: block; margin: 0 auto; }}
      #{viewer_id} .player-label {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-top: 2.5px solid #1A1A1A;
        border-bottom: 1px solid #1A1A1A;
        padding: 5px 4px;
        margin: 0;
      }}
      #{viewer_id} .player-label .player-side {{
        font-family: monospace;
        font-size: 10px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #8B3A2A;
      }}
      #{viewer_id} .player-label .player-name {{
        font-family: Georgia, serif;
        font-size: 15px;
        font-weight: 600;
        color: #1A1A1A;
        letter-spacing: 0.02em;
      }}
      #{viewer_id} .controls {{
        display: flex; align-items: center; gap: 5px;
        padding: 8px 0 6px;
        justify-content: center;
        border-top: 1px solid #D4C4A0;
      }}
      #{viewer_id} .controls button {{
        background: transparent;
        color: #1A1A1A;
        border: 1.5px solid #1A1A1A;
        border-radius: 0;
        padding: 4px 10px;
        cursor: pointer;
        font-family: monospace;
        font-size: 13px;
        min-width: 32px;
        transition: background 0.15s, color 0.15s;
      }}
      #{viewer_id} .controls button:hover {{
        background: #1A1A1A;
        color: #F2E6D0;
      }}
      #{viewer_id} .controls input[type=range] {{
        flex: 1;
        max-width: 260px;
        accent-color: #D4A843;
      }}
      #{viewer_id} .ply-label {{
        font-family: monospace;
        font-size: 11px;
        color: #8B3A2A;
        min-width: 72px;
        text-align: center;
        letter-spacing: 0.04em;
      }}
      #{viewer_id} .analysis-pane {{
        display: flex;
        flex-direction: column;
        gap: 8px;
      }}
      #{viewer_id} .analysis-pane > div {{
        width: 100%;
      }}
      #{viewer_id} .move-list {{
        max-height: 220px;
        overflow-y: auto;
        padding: 5px 6px;
        font-family: monospace;
        font-size: 12px;
        line-height: 2.0;
        border-top: 2.5px solid #1A1A1A;
        border-bottom: 1.5px solid #1A1A1A;
        border-left: none;
        border-right: none;
        border-radius: 0;
        background: rgba(242,230,208,0.45);
      }}
      #{viewer_id} .move-list .move-num {{
        color: #8B3A2A;
        font-size: 11px;
        margin-left: 4px;
      }}
      #{viewer_id} .move-list .move {{
        cursor: pointer;
        padding: 1px 5px;
        border-radius: 0;
        color: #1A1A1A;
        transition: background 0.1s;
      }}
      #{viewer_id} .move-list .move:hover {{ background: rgba(212,168,67,0.20); }}
      #{viewer_id} .move-list .move.active {{
        background: #1A3A2A;
        color: #F2E6D0;
        font-weight: 600;
      }}
      #{viewer_id} .arrow-labels {{
        display: none;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
        padding: 4px 4px 8px;
        min-height: 24px;
        font-family: monospace;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.02em;
      }}
      #{viewer_id} .arrow-chip {{
        display: inline-flex;
        align-items: center;
        padding: 2px 7px;
        border: 1px solid #1A1A1A;
        background: rgba(242,230,208,0.92);
        color: #1A1A1A;
      }}
      #{viewer_id} .arrow-chip--sf {{
        background: rgba(212,168,67,0.22);
      }}
      #{viewer_id} .arrow-chip--lc0 {{
        background: rgba(74,110,138,0.22);
      }}
      #{viewer_id} .arrow-toggles {{
        display: {_toggles_display};
        gap: 14px;
        align-items: center;
        padding: 5px 2px 2px;
        font-family: 'DM Mono', monospace;
        font-size: 0.72rem;
        letter-spacing: 0.04em;
      }}
      #{viewer_id} .arrow-toggle-label {{
        display: inline-flex;
        align-items: center;
        gap: 5px;
        cursor: pointer;
        user-select: none;
      }}
      #{viewer_id} .arrow-toggle-label input[type="checkbox"] {{
        accent-color: inherit;
        width: 13px;
        height: 13px;
        cursor: pointer;
      }}
      #{viewer_id} .arrow-swatch {{
        display: inline-block;
        width: 18px;
        height: 4px;
        border-radius: 2px;
        vertical-align: middle;
      }}
      @media (max-width: 900px) {{
        #{viewer_id} .viewer-grid {{
          grid-template-columns: 1fr;
        }}
        #{viewer_id} .move-list {{
          max-height: 160px;
        }}
      }}
    </style>

    <div id="{viewer_id}">
      <div class="viewer-grid">
        <div class="board-pane">
          <div class="player-label">
            <span class="player-side">{top_sym} {top_side}</span>
            <span class="player-name">{top_player}</span>
          </div>
          <div class="board-wrap" id="{viewer_id}-board"></div>
          <div class="player-label">
            <span class="player-side">{bottom_sym} {bottom_side}</span>
            <span class="player-name">{bottom_player}</span>
          </div>
          <div class="controls">
            <button onclick="goTo(0)" title="Start">&#x23EE;</button>
            <button onclick="goTo(Math.max(0, currentPly-1))" title="Back">&#x25C0;</button>
            <button id="{viewer_id}-playbtn" onclick="togglePlay()" title="Play/Pause">&#x25B6;</button>
            <button onclick="goTo(Math.min({total_frames - 1}, currentPly+1))" title="Forward">&#x25B6;&#xFE0E;</button>
            <button onclick="goTo({total_frames - 1})" title="End">&#x23ED;</button>
            <input type="range" id="{viewer_id}-slider" min="0" max="{total_frames - 1}"
                   value="{start_ply}" oninput="goTo(parseInt(this.value))">
            <span class="ply-label" id="{viewer_id}-label"></span>
          </div>
          <div class="move-list" id="{viewer_id}-moves">{moves_html}</div>
          <div class="arrow-toggles" id="{viewer_id}-arrow-toggles">
            <label class="arrow-toggle-label" style="color:#D4A843" title="Stockfish arrows">
              <input type="checkbox" id="{viewer_id}-sf-toggle" {_sf_checked} {_sf_disabled} onchange="toggleArrows()">
              <span class="arrow-swatch" style="background:linear-gradient(90deg,#D4A843EE,#D4A84308)"></span>
              SF
            </label>
            <label class="arrow-toggle-label" style="color:#4A6E8A" title="Lc0 arrows">
              <input type="checkbox" id="{viewer_id}-lc0-toggle" {_lc0_checked} {_lc0_disabled} onchange="toggleArrows()">
              <span class="arrow-swatch" style="background:linear-gradient(90deg,#4A6E8AEE,#4A6E8A08)"></span>
              Lc0
            </label>
          </div>
        </div>
        <div class="analysis-pane">
          <div id="{viewer_id}-eval"></div>
        </div>
      </div>
    </div>

    <script>
    (function() {{
      const frames = {frames_json};
      const arrowLabels = {arrow_labels_json};
      const totalFrames = frames.length;
      const startPlyOffset = {start_ply_offset};
      let currentPly = {start_ply};
      let playing = false;
      let timer = null;

      const boardEl = document.getElementById('{viewer_id}-board');
      const slider = document.getElementById('{viewer_id}-slider');
      const label = document.getElementById('{viewer_id}-label');
      const playBtn = document.getElementById('{viewer_id}-playbtn');
      const movesEl = document.getElementById('{viewer_id}-moves');
      const arrowLabelsEl = document.getElementById('{viewer_id}-arrow-labels');
      const sfToggle = document.getElementById('{viewer_id}-sf-toggle');
      const lc0Toggle = document.getElementById('{viewer_id}-lc0-toggle');
      const allMoveSpans = movesEl.querySelectorAll('.move');

      let showSF = {_js_show_sf};
      let showLc0 = {_js_show_lc0};

      window.currentPly = currentPly;

      function applyArrowVisibility() {{
        boardEl.querySelectorAll('line[stroke*="D4A843"], polygon[fill*="D4A843"]').forEach(function(el) {{
          el.style.display = showSF ? '' : 'none';
        }});
        boardEl.querySelectorAll('line[stroke*="4A6E8A"], polygon[fill*="4A6E8A"]').forEach(function(el) {{
          el.style.display = showLc0 ? '' : 'none';
        }});
      }}

      window.toggleArrows = function() {{
        if (sfToggle) showSF = sfToggle.checked;
        if (lc0Toggle) showLc0 = lc0Toggle.checked;
        applyArrowVisibility();
      }};

      function render() {{
        boardEl.innerHTML = frames[currentPly];
        applyArrowVisibility();
        slider.value = currentPly;
        if (currentPly === 0) {{
          label.textContent = 'Start';
        }} else {{
          const moveNum = Math.ceil(currentPly / 2);
          const side = currentPly % 2 === 1 ? '' : '...';
          label.textContent = moveNum + '.' + side + ' (ply ' + currentPly + ')';
        }}
        // highlight active move in list
        allMoveSpans.forEach(s => s.classList.remove('active'));
        const plyLabels = (
          arrowLabels[currentPly]
          || arrowLabels[String(currentPly)]
          || arrowLabels[currentPly + startPlyOffset]
          || arrowLabels[String(currentPly + startPlyOffset)]
          || []
        );
        if (arrowLabelsEl) {{
          if (plyLabels.length) {{
            arrowLabelsEl.replaceChildren();
            plyLabels.forEach((x) => {{
              const chip = document.createElement('span');
              const engine = String(x.engine || '').toLowerCase();
              chip.className = 'arrow-chip' + (engine ? ' arrow-chip--' + engine : '');
              chip.textContent = String(x.label || '');
              arrowLabelsEl.appendChild(chip);
            }});
            arrowLabelsEl.style.display = 'flex';
          }} else {{
            arrowLabelsEl.replaceChildren();
            arrowLabelsEl.style.display = 'none';
          }}
        }} else {{
          console.error('[render] arrowLabelsEl is null!');
        }}
        if (currentPly > 0) {{
          const active = movesEl.querySelector('.move[data-ply="' + currentPly + '"]');
          if (active) {{
            active.classList.add('active');
            active.scrollIntoView({{ block: 'nearest' }});
          }}
        }}
        // highlight current ply on eval chart
        if (typeof window.updateEvalHighlight === 'function') {{
          window.updateEvalHighlight(currentPly);
        }}
      }}

      window.goTo = function(ply) {{
        currentPly = Math.max(0, Math.min(totalFrames - 1, ply));
        window.currentPly = currentPly;
        render();
      }};

      window.togglePlay = function() {{
        if (playing) {{
          clearInterval(timer);
          playing = false;
          playBtn.innerHTML = '\\u25B6';
        }} else {{
          if (currentPly >= totalFrames - 1) currentPly = 0;
          playing = true;
          playBtn.innerHTML = '\\u23F8';
          timer = setInterval(() => {{
            if (currentPly >= totalFrames - 1) {{
              clearInterval(timer);
              playing = false;
              playBtn.innerHTML = '\\u25B6';
              return;
            }}
            currentPly++;
            window.currentPly = currentPly;
            render();
          }}, 800);
        }}
      }};

      render();
    }})();
    </script>
    """

    # -- Optionally embed linked charts (WDL stacked area and/or cp bar) -------
    charts_html = ""
    extra_height = 0

    # Inject the Plotly CDN once if either chart is needed
    if wdl_data or eval_data:
        charts_html += (
            '<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>\n'
        )

    # Add a second div for the Stockfish chart when both are present
    if wdl_data and eval_data:
        html = html.replace(
            f'<div id="{viewer_id}-eval"></div>',
            f'<div id="{viewer_id}-eval"></div><div id="{viewer_id}-eval2" style="margin-top:12px"></div>',
        )

    if wdl_data:
        wdl_json = json.dumps(wdl_data)
        wdl_count = len(wdl_data)
        wdl_height = max(240, min(400, 160 + wdl_count * 4))
        extra_height += wdl_height + 20
        charts_html += f"""
    <script>
    (function() {{
      const wdlData = {wdl_json};
      const plies = wdlData.map(d => Number(d.ply));
      const wins   = wdlData.map(d => Number(d.wdl_win)  / 10);
      const draws  = wdlData.map(d => Number(d.wdl_draw) / 10);
      const losses = wdlData.map(d => Number(d.wdl_loss) / 10);

      const traceWin = {{
        x: plies, y: wins, name: '♙ White Win',
        type: 'scatter', mode: 'lines', stackgroup: 'wdl',
        fill: 'tozeroy', fillcolor: 'rgba(242,230,208,0.90)',
        line: {{ color: '#D4C4A0', width: 1.5 }},
        hovertemplate: 'White win: %{{y:.1f}}%<extra></extra>',
      }};
      const traceDraw = {{
        x: plies, y: draws, name: 'Draw',
        type: 'scatter', mode: 'lines', stackgroup: 'wdl',
        fill: 'tonexty', fillcolor: 'rgba(139,58,42,0.50)',
        line: {{ color: '#8B3A2A', width: 1 }},
        hovertemplate: 'Draw: %{{y:.1f}}%<extra></extra>',
      }};
      const traceLoss = {{
        x: plies, y: losses, name: '♟ Black Win',
        type: 'scatter', mode: 'lines', stackgroup: 'wdl',
        fill: 'tonexty', fillcolor: 'rgba(26,26,26,0.85)',
        line: {{ color: '#1A1A1A', width: 1.5 }},
        hovertemplate: 'Black win: %{{y:.1f}}%<extra></extra>',
      }};

      // Classification markers — white dots along the bottom, black dots along the top.
      // Odd ply = white's move; even ply = black's move.
      const clsMeta = [
        {{ cls: 'blunder',    color: '#9B3A3A', size: 10, label: 'Blunder ??'     }},
        {{ cls: 'mistake',    color: '#C4762A', size: 8,  label: 'Mistake ?'      }},
        {{ cls: 'inaccuracy', color: '#B8962E', size: 6,  label: 'Inaccuracy ?!'  }},
      ];
      // Build four trace groups per classification: white (bottom) and black (top)
      const clsTraces = clsMeta.flatMap(m => {{
        const whitePts = wdlData.filter(d => d.classification === m.cls && Number(d.ply) % 2 === 1);
        const blackPts = wdlData.filter(d => d.classification === m.cls && Number(d.ply) % 2 === 0);
        const traceWhite = {{
          x: whitePts.map(d => Number(d.ply)),
          y: whitePts.map(() => 2),
          name: m.label,
          legendgroup: m.cls,
          type: 'scatter', mode: 'markers',
          marker: {{ color: m.color, size: m.size, symbol: 'circle', line: {{ color: '#F2E6D0', width: 1 }} }},
          customdata: whitePts.map(d => [d.san || '', '\u2659']),
          hovertemplate: '%{{customdata[1]}} %{{customdata[0]}} \u2014 ' + m.label + '<extra></extra>',
        }};
        const traceBlack = {{
          x: blackPts.map(d => Number(d.ply)),
          y: blackPts.map(() => 98),
          name: m.label,
          legendgroup: m.cls,
          showlegend: false,
          type: 'scatter', mode: 'markers',
          marker: {{ color: m.color, size: m.size, symbol: 'circle', line: {{ color: '#F2E6D0', width: 1 }} }},
          customdata: blackPts.map(d => [d.san || '', '\u265f']),
          hovertemplate: '%{{customdata[1]}} %{{customdata[0]}} \u2014 ' + m.label + '<extra></extra>',
        }};
        return [traceWhite, traceBlack];
      }});

      const wdlWhiteName = {json.dumps(white_player)};
      const wdlBlackName = {json.dumps(black_player)};

      // Vertical whisky line marking the current ply
      const wdlHighlight = {{
        x: [null, null], y: [0, 100], mode: 'lines',
        showlegend: false, hoverinfo: 'skip',
        line: {{ color: '#C17F24', width: 2, dash: 'dot' }},
      }};

      const allWdlTraces = [traceWin, traceDraw, traceLoss, ...clsTraces, wdlHighlight];
      const wdlHighlightIdx = allWdlTraces.length - 1;

      const wdlDiv = document.getElementById('{viewer_id}-eval');
      Plotly.newPlot(wdlDiv, allWdlTraces, {{
        xaxis: {{
          title: {{ text: 'Ply (half-move)', font: {{ size: 11, color: '#1C1C1C', family: 'DM Mono, monospace' }} }},
          zeroline: false,
          gridcolor: '#EDE0C4', tickfont: {{ size: 11, color: '#1C1C1C', family: 'DM Mono, monospace' }},
        }},
        yaxis: {{
          title: {{ text: 'Win/Draw/Loss (%)', font: {{ size: 11, color: '#1C1C1C', family: 'DM Mono, monospace' }} }},
          range: [0, 100], ticksuffix: '%',
          gridcolor: '#EDE0C4', tickfont: {{ size: 11, color: '#1C1C1C', family: 'DM Mono, monospace' }},
        }},
        legend: {{ orientation: 'h', y: -0.22, font: {{ color: '#1C1C1C', family: 'EB Garamond, serif', size: 12 }},
          bgcolor: 'rgba(0,0,0,0)', bordercolor: '#EDE0C4', borderwidth: 1 }},
        margin: {{ l: 55, r: 20, t: 56, b: 60 }},
        height: {wdl_height},
        paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(237,224,196,0.2)',
        font: {{ color: '#1C1C1C', family: 'EB Garamond, serif' }}, hovermode: 'x unified',
        annotations: [
          {{ text: wdlWhiteName + ' vs ' + wdlBlackName + ' \u2014 Win / Draw / Loss',
            xref: 'paper', yref: 'paper', x: 0.5, y: 1.13, xanchor: 'center', showarrow: false,
            font: {{ size: 15, color: '#1A1A1A', family: 'Georgia, serif' }} }},
        ],
      }}, {{ displaylogo: false, responsive: true }}).then(() => {{
        window._evalChart = wdlDiv;
        wdlDiv.on('plotly_click', function(data) {{
          if (data.points && data.points.length > 0) window.goTo(data.points[0].x);
        }});
        if (typeof window._chartReady === 'function') window._chartReady();
      }});

      window._updateWdlHighlight = function(ply) {{
        Plotly.restyle(wdlDiv, {{ x: [[ply, ply]], y: [[0, 100]] }}, [wdlHighlightIdx]);
      }};
    }})();
    </script>
    """

    if eval_data:
        eval_json = json.dumps(eval_data)
        is_best_map_json = json.dumps(is_best_map)
        eval_count = len(eval_data)
        sf_height = max(300, 210 + eval_count * 7)
        extra_height += sf_height + 20
        eval_div_id = f"{viewer_id}-eval2" if wdl_data else f"{viewer_id}-eval"
        charts_html += f"""
    <script>
    (function() {{
      const evalData = {eval_json};
      const whiteName = {json.dumps(white_player)};
      const blackName = {json.dumps(black_player)};
      const MATE_CP_BASE = 10000;
      const MATE_THRESHOLD = 9000;
      const DISPLAY_CP_CAP = 1200;

      const points = evalData.map(d => {{
        const ply = Number(d.ply);
        const moveNumber = Math.ceil(ply / 2);
        const player = ply % 2 === 1 ? 'White' : 'Black';
        const rawCp = Number(d.cp_eval ?? 0);
        const cls = d.classification || '';
        const isMate = Math.abs(rawCp) >= MATE_THRESHOLD;
        const side = rawCp >= 0 ? 'White' : 'Black';
        let mateMoves = null;
        if (isMate) {{
          const recovered = Math.round(MATE_CP_BASE - Math.abs(rawCp));
          if (recovered > 0) mateMoves = recovered;
        }}
        const displayCp = isMate
          ? (rawCp >= 0 ? DISPLAY_CP_CAP : -DISPLAY_CP_CAP)
          : Math.max(-DISPLAY_CP_CAP, Math.min(DISPLAY_CP_CAP, rawCp));
        const hoverText = isMate
          ? (mateMoves ? `${{side}} mate in ${{mateMoves}}` : `${{side}} forced mate`)
          : `${{rawCp >= 0 ? '+' : ''}}${{Math.round(rawCp)}} cp`;
        const textLabel = isMate
          ? (mateMoves ? `M${{rawCp >= 0 ? '+' : '-'}}${{mateMoves}}` : `M${{rawCp >= 0 ? '+' : '-'}}`)
          : '';
        return {{ ply, moveNumber, player, rawCp, displayCp, isMate, hoverText, textLabel, cls, san: d.san || '' }};
      }});

      points.forEach((p, idx) => {{
        if (idx === 0) {{
          p.changeText = 'N/A';
          return;
        }}
        const delta = p.rawCp - points[idx - 1].rawCp;
        const rounded = Math.round(delta);
        p.changeText = `${{rounded >= 0 ? '+' : ''}}${{rounded}} cp`;
      }});

      const plies = points.map(p => p.ply);
      const evals = points.map(p => p.displayCp);
      const moveTickVals = plies.filter(p => p % 2 === 1);
      const moveTickText = moveTickVals.map(p => String(Math.ceil(p / 2)));
      // Bar fill: classification drives colour when present; side-default otherwise.
      // All seven Stockfish categories: brilliant / great / best / excellent / inaccuracy / mistake / blunder
      const clsColor = {{
        brilliant:  '#A8D4B8',  // pale sage — lightest positive
        great:      '#76B08A',  // soft green
        best:       '#4A8C62',  // board dark-square green
        excellent:  '#2E6647',  // deeper green, one step below best
        inaccuracy: '#E8BC5A',  // light gold
        mistake:    '#D4724A',  // terracotta
        blunder:    '#B53541',  // crimson
      }};
      // Default when no classification stored: ebony on white-side, parchment on black-side
      const baseColors = points.map(p =>
        clsColor[p.cls] || (p.rawCp >= 0 ? '#1A1A1A' : '#F2E6D0')
      );
      const baseOpacity = evals.map(() => 1.0);

      function barLineAttrs(activePly) {{
        return {{
          color: plies.map(p => p === activePly ? '#D4A843' : 'rgba(0,0,0,0)'),
          width: plies.map(p => p === activePly ? 2.0 : 0),
        }};
      }}

      const staticAnnotations = [
        {{ text: whiteName + ' vs ' + blackName + ' \u2014 Stockfish Evaluation',
          xref: 'paper', yref: 'paper', x: 0.5, y: 1.13, xanchor: 'center', showarrow: false,
          font: {{ size: 15, color: '#1A1A1A', family: 'Georgia, serif' }} }},
      ];

      function arrowAnnotation(activePly) {{
        const idx = plies.indexOf(activePly);
        if (idx < 0) return staticAnnotations;
        const positiveBar = evals[idx] >= 0;
        return [...staticAnnotations, {{
          x: 0, y: activePly,
          xref: 'x', yref: 'y',
          ax: positiveBar ? -40 : 40, ay: 0,
          axref: 'pixel', ayref: 'pixel',
          showarrow: true, arrowhead: 2, arrowsize: 1.2,
          arrowwidth: 2, arrowcolor: '#B8962E',
          text: '', standoff: 2,
        }}];
      }}

      const trace = {{
        x: evals, y: plies, type: 'bar', orientation: 'h',
        marker: {{ color: baseColors.slice(), opacity: baseOpacity.slice(),
          line: barLineAttrs(null) }},
        text: points.map(p => p.textLabel), textposition: 'outside',
        customdata: points.map(p => [
          p.moveNumber,
          p.player,
          p.changeText,
          p.hoverText,
          p.cls ? ' (' + p.cls + ')' : '',
          p.san ? ' \\u2014 ' + p.san : '',
        ]),
        hovertemplate: 'Move %{{customdata[0]}} (%{{customdata[1]}}) %{{customdata[5]}}<br>Change: %{{customdata[2]}}<br>Eval: %{{customdata[3]}}%{{customdata[4]}}<extra></extra>',
      }};

      // Classification marker dots — mirroring the WDL chart convention.
      // White moves (odd ply) appear at the left edge (x ≈ −cap); black moves at the right edge (x ≈ +cap).
      const sfClsMeta = [
        {{ cls: 'blunder',    color: '#9B3A3A', size: 10, label: 'Blunder ??'    }},
        {{ cls: 'mistake',    color: '#C4762A', size: 8,  label: 'Mistake ?'     }},
        {{ cls: 'inaccuracy', color: '#B8962E', size: 6,  label: 'Inaccuracy ?!' }},
      ];
      const sfClsTraces = sfClsMeta.flatMap(m => {{
        const whitePts = points.filter(p => p.cls === m.cls && p.ply % 2 === 1);
        const blackPts = points.filter(p => p.cls === m.cls && p.ply % 2 === 0);
        const tWhite = {{
          x: whitePts.map(() => -(DISPLAY_CP_CAP * 1.08)),
          y: whitePts.map(p => p.ply),
          name: m.label,
          legendgroup: 'sf-' + m.cls,
          type: 'scatter', mode: 'markers',
          marker: {{ color: m.color, size: m.size, symbol: 'circle', line: {{ color: '#F2E6D0', width: 1 }} }},
          customdata: whitePts.map(p => [p.san || '', '\u2659', p.moveNumber]),
          hovertemplate: 'Move %{{customdata[2]}} %{{customdata[1]}} %{{customdata[0]}} \u2014 ' + m.label + '<extra></extra>',
        }};
        const tBlack = {{
          x: blackPts.map(() => DISPLAY_CP_CAP * 1.08),
          y: blackPts.map(p => p.ply),
          name: m.label,
          legendgroup: 'sf-' + m.cls,
          showlegend: false,
          type: 'scatter', mode: 'markers',
          marker: {{ color: m.color, size: m.size, symbol: 'circle', line: {{ color: '#F2E6D0', width: 1 }} }},
          customdata: blackPts.map(p => [p.san || '', '\u265f', p.moveNumber]),
          hovertemplate: 'Move %{{customdata[2]}} %{{customdata[1]}} %{{customdata[0]}} \u2014 ' + m.label + '<extra></extra>',
        }};
        return [tWhite, tBlack];
      }});

      const sfDiv = document.getElementById('{eval_div_id}');
      Plotly.newPlot(sfDiv, [trace, ...sfClsTraces], {{
        xaxis: {{
          zeroline: true, zerolinecolor: '#1A1A1A', zerolinewidth: 2.5,
          range: [-DISPLAY_CP_CAP * 1.15, DISPLAY_CP_CAP * 1.15],
          tickvals: [-1200, -800, -400, -200, 0, 200, 400, 800, 1200],
          ticktext: ['-12', '-8', '-4', '-2', '0', '+2', '+4', '+8', '+12'],
          tickfont: {{ size: 11, color: '#1C1C1C', family: 'monospace' }},
          gridcolor: 'rgba(90,90,90,0.18)', gridwidth: 1,
        }},
        yaxis: {{
          title: {{ text: 'Move', font: {{ size: 12, color: '#1C1C1C', family: 'monospace' }} }},
          autorange: 'reversed',
          tickvals: moveTickVals,
          ticktext: moveTickText,
          tickfont: {{ size: 11, color: '#1C1C1C', family: 'monospace' }},
          gridcolor: 'rgba(90,90,90,0.18)', gridwidth: 1,
        }},
        margin: {{ l: 55, r: 55, t: 56, b: 52 }},
        bargap: 0.08, height: {sf_height},
        paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
        shapes: [
          {{ type: 'rect', xref: 'x', yref: 'paper',
            x0: 0, x1: DISPLAY_CP_CAP * 1.15, y0: 0, y1: 1,
            fillcolor: '#F2E6D0', opacity: 1.0, layer: 'below', line: {{ width: 0 }} }},
          {{ type: 'rect', xref: 'x', yref: 'paper',
            x0: -DISPLAY_CP_CAP * 1.15, x1: 0, y0: 0, y1: 1,
            fillcolor: '#1A1A1A', opacity: 1.0, layer: 'below', line: {{ width: 0 }} }},
        ],
        font: {{ color: '#1C1C1C', family: 'Georgia, serif' }},
        annotations: staticAnnotations,
      }}, {{ displaylogo: false, responsive: true }}).then(() => {{
        if (!window._evalChart) window._evalChart = sfDiv;
        sfDiv.on('plotly_click', function(data) {{
          if (data.points && data.points.length > 0) window.goTo(data.points[0].y);
        }});
        if (typeof window._chartReady === 'function') window._chartReady();
      }});

      window._updateSfHighlight = function(ply) {{
        Plotly.restyle(sfDiv, {{
          'marker.opacity': [plies.map(p => p === ply ? 1.0 : 1.0)],
          'marker.line.color': [barLineAttrs(ply).color],
          'marker.line.width': [barLineAttrs(ply).width],
        }});
        Plotly.relayout(sfDiv, {{ annotations: arrowAnnotation(ply) }});
      }};
    }})();
    </script>
    """

    # Unified highlight dispatcher called by the board on every ply change.
    # Charts register themselves via window._chartReady(); the dispatcher fires
    # immediately for any chart that loads after the board has already moved.
    if wdl_data or eval_data:
        charts_html += """
    <script>
    window.updateEvalHighlight = function(ply) {
      if (typeof window._updateWdlHighlight === 'function') window._updateWdlHighlight(ply);
      if (typeof window._updateSfHighlight  === 'function') window._updateSfHighlight(ply);
    };
    // Called by each chart once its Plotly render is complete so it can sync
    // to wherever the board already is.
    window._chartReady = function() {
      window.updateEvalHighlight(window.currentPly || 0);
    };
    </script>
    """

    html = html + charts_html

    # Height: board + controls + move list + charts
    render_html_iframe(html, height=size + 280 + extra_height)


def render_pgn_viewer(
    pgn: str,
    size: int = 560,
    orientation: str = "white",
    board_theme: str = "blue",
    initial_ply: int | str = "last",
) -> None:
    viewer_id = f"lpv-{uuid4().hex}"
    safe_pgn = json.dumps(pgn)
    safe_orientation = "black" if orientation == "black" else "white"
    safe_theme = board_theme if board_theme in {"blue", "green", "brown"} else "blue"
    safe_initial_ply: int | str
    if isinstance(initial_ply, int) and initial_ply >= 0:
        safe_initial_ply = initial_ply
    else:
        safe_initial_ply = "last"

    initial_ply_js = json.dumps(safe_initial_ply)

    # Uses the official lichess-org/pgn-viewer package for move tree, controls,
    # and board playback UI.
    html_payload = f"""
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@lichess-org/pgn-viewer@2.6.0/dist/lichess-pgn-viewer.css" />

        <style>
            #{viewer_id} {{ width: min({size + 180}px, 100%); }}
            #{viewer_id} .lpv__board {{ width: {size}px; max-width: 100%; }}

            #{viewer_id}.theme-blue cg-board square.light {{ background: #d8e3ef; }}
            #{viewer_id}.theme-blue cg-board square.dark {{ background: #7b96b2; }}

            #{viewer_id}.theme-green cg-board square.light {{ background: #e2eadf; }}
            #{viewer_id}.theme-green cg-board square.dark {{ background: #6f8f5f; }}

            #{viewer_id}.theme-brown cg-board square.light {{ background: #f0d9b5; }}
            #{viewer_id}.theme-brown cg-board square.dark {{ background: #b58863; }}
        </style>

        <div id="{viewer_id}" class="theme-{safe_theme}"></div>

        <script nomodule>
            document.getElementById('{viewer_id}').innerHTML = '<p>Modern chess viewer requires module-enabled browser support.</p>';
        </script>

        <script type="module">
            import LichessPgnViewer from 'https://cdn.jsdelivr.net/npm/@lichess-org/pgn-viewer@2.6.0/+esm';

            const target = document.getElementById('{viewer_id}');
            const pgn = {safe_pgn};

            LichessPgnViewer(target, {{
                pgn,
                orientation: '{safe_orientation}',
                showClocks: false,
                showMoves: 'auto',
                scrollToMove: true,
                initialPly: {initial_ply_js},
            }});
        </script>
        """

    render_html_iframe(html_payload, height=size + 220)
