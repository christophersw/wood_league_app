"""
Title: board_builder.py — Chess board SVG frame builder
Description:
    Generates SVG board frames for the game analysis page. Produces one SVG per ply,
    with engine arrow overlays (Stockfish + Lc0) and injected evaluation labels.
    Chart data and HTML rendering are handled by views and templates respectively.

Changelog:
    2026-05-04 (#16): Rewrote to return frame data dict instead of HTML blob;
                      removed chart data and all HTML/CSS/JS generation.
    2025-xx-xx:       Initial implementation with build_board_viewer_html.
"""

from __future__ import annotations

import io
import re

import chess
import chess.pgn
import chess.svg

from games.services import GameAnalysisData, MoveRow

_BOARD_COLORS = {
    "square light": "#F2E6D0",
    "square dark": "#4A8C62",
    "margin": "#1A1A1A",
    "coord": "#D4A843",
}

_SF_ARROW_COLORS = ["#D4A843CC", "#D4A84377", "#D4A84333"]
_LC0_ARROW_COLORS = ["#4A6E8ACC", "#4A6E8A77", "#4A6E8A33"]


def _build_tier_map(by_ply: dict[int, MoveRow], use_cp_equiv: bool) -> dict[int, list]:
    """Build a ply-indexed map of top-3 engine move suggestions with scores.

    Parameters:
        by_ply (dict[int, MoveRow]): Map of ply to engine MoveRow.
        use_cp_equiv (bool): If True, uses cp_equiv as the primary score for
            all arrows (Lc0 mode). If False, uses per-arrow scores (SF mode).

    Returns:
        dict mapping ply → list of {uci, score} dicts for up to 3 moves.
    """
    result: dict[int, list] = {}
    for ply, row in by_ply.items():
        entries = []
        ucis = [row.arrow_uci, row.arrow_uci_2, row.arrow_uci_3]
        scores = [row.arrow_score_1, row.arrow_score_2, row.arrow_score_3]
        if use_cp_equiv:
            scores = [row.cp_equiv, None, None]
        for uci, score in zip(ucis, scores):
            if uci:
                entries.append({"uci": uci, "score": score})
        if entries:
            result[ply] = entries
    return result


def _inject_arrow_labels(svg: str, labels: list[dict], size: int, flipped: bool) -> str:
    """Inject evaluation labels on top of move arrows in the SVG board.

    Parameters:
        svg (str): SVG string from chess.svg.board to annotate.
        labels (list[dict]): List of label dicts with keys engine, label, from_sq, to_sq.
        size (int): Board render size in pixels.
        flipped (bool): Whether the board is rendered from Black's perspective.

    Returns:
        str: SVG string with evaluation label text and background rects injected
             before the closing </svg> tag.
    """
    if not labels or not svg:
        return svg
    _MARGIN = 15
    _SQ = 45

    def sq_to_px(sq: str) -> tuple[float, float]:
        """Convert algebraic square name (e.g. 'e4') to pixel center coordinates."""
        if not sq or len(sq) < 2:
            return (0.0, 0.0)
        try:
            file_index = ord(sq[0]) - ord("a")
            rank_index = int(sq[1]) - 1
            if flipped:
                file_index = 7 - file_index
                rank_index = 7 - rank_index
            return (_MARGIN + (file_index + 0.5) * _SQ, _MARGIN + (7 - rank_index + 0.5) * _SQ)
        except (ValueError, IndexError):
            return (0.0, 0.0)

    by_sq: dict[str, list[dict]] = {}
    for label_data in labels:
        to_sq = label_data.get("to_sq", "")
        if to_sq and label_data.get("label"):
            by_sq.setdefault(to_sq, []).append(label_data)

    font_size = 11
    line_h = font_size + 3
    text_elements: list[str] = []
    for to_sq, sq_labels in by_sq.items():
        cx, cy = sq_to_px(to_sq)
        base_y = cy - _SQ * 0.22
        n = len(sq_labels)
        start_y = base_y - (n - 1) * line_h / 2
        for idx, ld in enumerate(sq_labels):
            engine = str(ld.get("engine", "sf")).lower()
            fg = "#FFE082" if "sf" in engine else "#80CBC4"
            lx, ly = cx, start_y + idx * line_h
            text = str(ld.get("label", ""))
            text_elements.append(
                f'<rect x="{lx - 18:.1f}" y="{ly - font_size + 1:.1f}" width="36"'
                f' height="{font_size + 2}" rx="2" fill="#1A1A1A" fill-opacity="0.72"'
                f' pointer-events="none"/>'
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle"'
                f' dominant-baseline="auto" font-size="{font_size}" font-weight="bold"'
                f' font-family="monospace" fill="{fg}" pointer-events="none">{text}</text>'
            )

    if not text_elements:
        return svg
    return re.sub(r"</svg>", "\n".join(text_elements) + "\n</svg>", svg, count=1)


def build_board_frames(
    data: GameAnalysisData,
    size: int = 480,
    orientation: str = "white",
) -> dict:
    """Build per-ply SVG board frames with engine arrow overlays.

    Parses the game PGN, generates one SVG frame per ply (frame 0 = start
    position), and annotates each frame with Stockfish and/or Lc0 move arrows.

    Parameters:
        data (GameAnalysisData): Fully-populated game analysis data object.
        size (int): Board render size in pixels. Default 480.
        orientation (str): "white" (default) or "black".

    Returns:
        dict with keys: frames, arrow_labels_by_ply, san_list, total_frames,
        top_player, top_sym, top_side, bottom_player, bottom_sym, bottom_side,
        has_sf, has_lc0. Returns minimal dict with frames=[] if PGN fails.
    """
    flipped = orientation == "black"
    game = chess.pgn.read_game(io.StringIO(data.pgn))
    if game is None:
        return {
            "frames": [], "arrow_labels_by_ply": {}, "san_list": [],
            "total_frames": 0, "top_player": "", "top_sym": "", "top_side": "",
            "bottom_player": "", "bottom_sym": "", "bottom_side": "",
            "has_sf": False, "has_lc0": False,
        }

    board = game.board()
    start_ply_offset = board.ply()
    moves_played: list[chess.Move] = list(game.mainline_moves())

    sf_by_ply: dict[int, MoveRow] = {row.ply: row for row in data.moves}
    lc0_by_ply: dict[int, MoveRow] = {}
    if data.lc0_moves:
        for row in data.lc0_moves:
            lc0_by_ply[row.ply] = row

    sf_tier_map = _build_tier_map(sf_by_ply, use_cp_equiv=False) if sf_by_ply else None
    lc0_tier_map = _build_tier_map(lc0_by_ply, use_cp_equiv=True) if lc0_by_ply else None

    sf_played: dict[int, float] = {
        ply: row.cp_eval for ply, row in sf_by_ply.items() if row.cp_eval is not None
    }
    lc0_played: dict[int, float] = {
        ply: row.cp_equiv for ply, row in lc0_by_ply.items() if row.cp_equiv is not None
    }

    san_list: list[str] = []
    arrow_labels_by_ply: dict[int, list] = {}
    frames: list[str] = []

    frames.append(chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS))

    board = game.board()
    for ply_i, move in enumerate(moves_played, start=1):
        abs_ply = ply_i + start_ply_offset
        san_list.append(board.san(move))
        board.push(move)

        arrows: list[chess.svg.Arrow] = []

        def _add_arrows(
            tier_map: dict | None,
            played_scores: dict,
            colors: list[str],
            engine_prefix: str,
        ) -> None:
            """Add SVG arrows and compute evaluation labels for a single ply."""
            if tier_map is None:
                return
            tier_entries = tier_map.get(abs_ply) or tier_map.get(ply_i) or []
            scores = [e.get("score") for e in tier_entries]
            ucis = [e.get("uci", "") for e in tier_entries]
            played_score = played_scores.get(abs_ply) or played_scores.get(ply_i)
            base = scores[0] if scores and scores[0] is not None else None
            for i, uci in enumerate(ucis):
                if not (uci and len(uci) >= 4):
                    continue
                try:
                    rgba = colors[i] if i < len(colors) else colors[-1]
                    arrows.append(chess.svg.Arrow(
                        chess.parse_square(uci[:2]),
                        chess.parse_square(uci[2:4]),
                        color=rgba,
                    ))
                    score = scores[i] if i < len(scores) else None
                    label = ""
                    if played_score is not None and score is not None:
                        gain = float(score) - float(played_score)
                        if "lc0" in engine_prefix.lower():
                            bps = int(round((gain / 100.0) * 4))
                            label = f"{bps:+d}%" if bps != 0 else "±0%"
                        else:
                            label = f"{int(round(gain)):+d}"
                    elif base is not None and score is not None and i > 0:
                        gap = float(base) - float(score)
                        if "lc0" in engine_prefix.lower():
                            bps = int(round((gap / 100.0) * 4))
                            label = f"{bps:+d}%" if bps != 0 else "±0%"
                        else:
                            label = f"{int(round(gap)):+d}"
                    if label:
                        arrow_labels_by_ply.setdefault(ply_i, []).append({
                            "engine": engine_prefix.lower(),
                            "label": label,
                            "from_sq": uci[:2],
                            "to_sq": uci[2:4],
                        })
                except ValueError:
                    pass

        _add_arrows(sf_tier_map, sf_played, _SF_ARROW_COLORS, "sf")
        _add_arrows(lc0_tier_map, lc0_played, _LC0_ARROW_COLORS, "lc0")

        svg = chess.svg.board(
            board, size=size, lastmove=move, arrows=arrows,
            flipped=flipped, colors=_BOARD_COLORS,
        )
        svg = _inject_arrow_labels(svg, arrow_labels_by_ply.get(ply_i, []), size, flipped)
        frames.append(svg)

    top_player = data.black if not flipped else data.white
    top_sym = "♟" if not flipped else "♙"
    top_side = "Black" if not flipped else "White"
    bottom_player = data.white if not flipped else data.black
    bottom_sym = "♙" if not flipped else "♟"
    bottom_side = "White" if not flipped else "Black"

    return {
        "frames": frames,
        "arrow_labels_by_ply": arrow_labels_by_ply,
        "san_list": san_list,
        "total_frames": len(frames),
        "top_player": top_player,
        "top_sym": top_sym,
        "top_side": top_side,
        "bottom_player": bottom_player,
        "bottom_sym": bottom_sym,
        "bottom_side": bottom_side,
        "has_sf": data.has_sf,
        "has_lc0": data.has_lc0,
    }
