"""
Title: views.py — Game analysis page views
Description:
    Handles rendering and HTMX partial responses for the game analysis page,
    including the main page view, the HTMX board partial (supports orientation
    flip without full reload), and the queue-analysis POST endpoint.

Changelog:
    2026-05-04 (#16): Full rewrite for ply-sync architecture; added board_partial
                      and queue_analysis views; removed build_board_viewer_html usage
"""

import io as _io
import json

import chess
import chess.pgn as _pgn
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from analysis.models import AnalysisJob
from games.board_builder import build_board_frames, _BOARD_COLORS
from games.models import Game
from games.services import get_game_analysis
from games.stat_cards import _DUB_CSS, build_lc0_card, build_sf_card

_ACTIVE_STATUSES = [
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_SUBMITTED,
    AnalysisJob.STATUS_RUNNING,
]


def _details_string(data) -> str:
    """
    Build the date · time-control details string for the page header.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        String like "2024-03-15 14:30 · 600+0", or empty string.
    """
    parts = []
    if data.date:
        parts.append(data.date)
    if data.time_control:
        parts.append(data.time_control)
    return " · ".join(parts)


def _opening_label(data) -> str:
    """
    Build a human-readable opening label from the game's ECO and name fields.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        Opening label string, preferring lichess_opening name when available.
    """
    if data.lichess_opening:
        if data.eco_code:
            return f"{data.eco_code} · {data.lichess_opening}"
        return data.lichess_opening
    if data.eco_code and data.opening_name:
        return f"{data.eco_code} · {data.opening_name}"
    return data.eco_code or data.opening_name or ""


def _queue_status(slug: str) -> tuple[bool, bool]:
    """
    Check whether Stockfish or Lc0 analysis is currently queued for this game.

    Params:
        slug (str): Game URL slug.

    Returns:
        Tuple of (sf_queued, lc0_queued) booleans.
    """
    active = AnalysisJob.objects.filter(
        game__slug=slug,
        status__in=_ACTIVE_STATUSES,
    ).values_list("engine", flat=True)
    engines = set(active)
    return ("stockfish" in engines), ("lc0" in engines)


def _build_eval_json(data) -> str:
    """
    Serialize Stockfish per-move evaluation data as a JSON string.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        JSON string of [{ply, cp_eval, san, classification}] or "null".
    """
    if not (data.has_sf and data.moves):
        return "null"
    rows = [
        {
            "ply": r.ply,
            "cp_eval": r.cp_eval,
            "san": r.san,
            "classification": r.classification or "",
        }
        for r in data.moves
        if r.cp_eval is not None
    ]
    return json.dumps(rows)


def _build_wdl_json(data) -> str:
    """
    Serialize Lc0 per-move WDL data as a JSON string.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        JSON string of [{ply, wdl_win, wdl_draw, wdl_loss, san, classification}] or "null".
    """
    if not data.lc0_moves:
        return "null"
    rows = [
        {
            "ply": r.ply,
            "wdl_win": r.wdl_win or 0,
            "wdl_draw": r.wdl_draw or 0,
            "wdl_loss": r.wdl_loss or 0,
            "san": r.san,
            "classification": r.classification or "",
        }
        for r in data.lc0_moves
        if r.wdl_win is not None
    ]
    return json.dumps(rows)


def _build_pgn_moves_json(data) -> str:
    """
    Serialize the move list for the client-side PGN table as a JSON string.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        JSON string of [{ply, move_number, color, san, classification}].
    """
    rows = [
        {
            "ply": r.ply,
            "move_number": (r.ply + 1) // 2,
            "color": "white" if r.ply % 2 == 1 else "black",
            "san": r.san,
            "classification": r.classification or "",
        }
        for r in (data.moves or [])
    ]
    return json.dumps(rows)


def game_analysis(request: HttpRequest, slug: str) -> HttpResponse:
    """
    Render the main game analysis page.

    Loads game and analysis data, builds engine stat cards and serialized
    chart/PGN data for client-side rendering. The board itself is loaded
    via HTMX (board_partial view) so orientation changes don't reload the page.

    Params:
        request (HttpRequest): The HTTP request.
        slug (str): Game URL slug.

    Returns:
        Rendered analysis.html with full context, or analysis.html with
        no_data=True if the game has no parseable PGN or analysis.
    """
    game = get_object_or_404(Game, slug=slug)
    data = get_game_analysis(slug)

    if data is None or not data.moves:
        return render(request, "games/analysis.html", {
            "game": game,
            "no_data": True,
        })

    initial_ply = 0
    try:
        initial_ply = max(0, int(request.GET.get("ply", 0)))
    except (ValueError, TypeError):
        pass

    initial_perspective = request.GET.get("orientation", "white")
    if initial_perspective not in ("white", "black"):
        initial_perspective = "white"

    sf_queued, lc0_queued = _queue_status(slug)
    engine_cards_html = _DUB_CSS + build_sf_card(data, queued=sf_queued) + build_lc0_card(data, queued=lc0_queued)

    return render(request, "games/analysis.html", {
        "game": game,
        "data": data,
        "no_data": False,
        "details": _details_string(data),
        "opening_label": _opening_label(data),
        "opening_id": data.opening_id,
        "chesscom_url": data.url,
        "engine_cards_html": engine_cards_html,
        "sf_eval_json": _build_eval_json(data),
        "lc0_wdl_json": _build_wdl_json(data),
        "pgn_moves_json": _build_pgn_moves_json(data),
        "initial_ply": initial_ply,
        "initial_perspective": initial_perspective,
        "has_sf": data.has_sf,
        "has_lc0": data.has_lc0,
        "white": data.white,
        "black": data.black,
    })


def board_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """
    HTMX partial: render the interactive board for a given orientation.

    Called on initial page load (hx-trigger="load") and on board flip.
    Generates all SVG frames server-side and embeds them as JSON in the
    response so client-side JS can animate without further requests.

    Params:
        request (HttpRequest): The HTTP request; reads ?orientation= GET param.
        slug (str): Game URL slug.

    Returns:
        Rendered _board_partial.html, or a minimal error partial if no data.
    """
    game = get_object_or_404(Game, slug=slug)
    data = get_game_analysis(slug)

    orientation = request.GET.get("orientation", "white")
    if orientation not in ("white", "black"):
        orientation = "white"

    if data is None or not data.moves:
        return render(request, "games/_board_error_partial.html", {"game": game})

    board_data = build_board_frames(data, size=480, orientation=orientation)

    # Build is_best_map: ply → True if the player's move matched SF best move
    sf_by_ply = {row.ply: row for row in data.moves}
    game_obj = _pgn.read_game(_io.StringIO(data.pgn))
    is_best_map: dict[int, bool] = {}
    if game_obj:
        _board = game_obj.board()
        _start = _board.ply()
        _board = game_obj.board()
        for _ply_i, _move in enumerate(game_obj.mainline_moves(), start=1):
            _abs = _ply_i + _start
            _row = sf_by_ply.get(_abs) or sf_by_ply.get(_ply_i)
            if _row and _row.arrow_uci:
                is_best_map[_ply_i] = _move.uci() == _row.arrow_uci
            _board.push(_move)

    return render(request, "games/_board_partial.html", {
        "slug": slug,
        "orientation": orientation,
        "frames_json": json.dumps(board_data["frames"]),
        "arrow_data_json": json.dumps(board_data["arrows_by_ply"]),
        "san_list_json": json.dumps(board_data["san_list"]),
        "is_best_json": json.dumps(is_best_map),
        "total_frames": board_data["total_frames"],
        "top_player": board_data["top_player"],
        "top_sym": board_data["top_sym"],
        "top_side": board_data["top_side"],
        "bottom_player": board_data["bottom_player"],
        "bottom_sym": board_data["bottom_sym"],
        "bottom_side": board_data["bottom_side"],
        "has_sf": board_data["has_sf"],
        "has_lc0": board_data["has_lc0"],
        "overlay_viewbox_size": board_data["overlay_geometry"]["viewbox_size"],
        "overlay_board_margin": board_data["overlay_geometry"]["board_margin"],
        "overlay_square_size": board_data["overlay_geometry"]["square_size"],
        "no_arrows": False,
    })


def engine_line_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """
    HTMX partial: render an engine line continuation board.

    Called when user clicks an arrow on the main board. Reconstructs the board position
    at the given ply, plays the specified move, and continues from there, displaying
    up to 50+ moves of continuation.

    Query params:
        ply (int): Starting ply in the main game (before the clicked move).
        move_uci (str): The UCI move to play (the clicked arrow).
        engine (str): "sf" or "lc0" (which engine suggested this move).
        tier (int): 1, 2, or 3 (which tier of suggestion this was).
        orientation (str): "white" or "black" (perspective, must match main board).

    Returns:
        Rendered _engine_line_partial.html with the continuation board frames,
        or error partial if unable to reconstruct position or find continuation data.
    """
    game = get_object_or_404(Game, slug=slug)
    data = get_game_analysis(slug)

    if data is None or not data.moves or not data.pgn:
        return render(request, "games/_board_error_partial.html", {"game": game})

    try:
        ply = int(request.GET.get("ply", 0))
    except (ValueError, TypeError):
        ply = 0
    ply = max(0, ply)

    move_uci = request.GET.get("move_uci", "").strip()
    if not move_uci or len(move_uci) < 4:
        return HttpResponse("Invalid move_uci", status=400)

    engine = request.GET.get("engine", "sf").strip().lower()
    if engine not in ("sf", "lc0"):
        engine = "sf"

    try:
        tier = int(request.GET.get("tier", 1))
    except (ValueError, TypeError):
        tier = 1
    tier = max(1, min(3, tier))

    orientation = request.GET.get("orientation", "white")
    if orientation not in ("white", "black"):
        orientation = "white"

    # Reconstruct board position up to the given ply
    game_obj = _pgn.read_game(_io.StringIO(data.pgn))
    if game_obj is None:
        return HttpResponse("Cannot parse PGN", status=400)

    board = game_obj.board()
    moves_list = list(game_obj.mainline_moves())

    # Play moves up to the specified ply
    # ply is 1-indexed from board_builder (ply 1 = after move 1)
    # To reach ply N, we need to play moves 0 to N-1 in the moves_list
    moves_played_in_continuation = []
    print(f"[DEBUG] engine_line_partial: reconstructing to ply {ply}, total moves: {len(moves_list)}")
    for i, move in enumerate(moves_list):
        if i >= ply:
            break
        board.push(move)
        print(f"[DEBUG] Pushed move {i}: {move.uci()}")

    print(f"[DEBUG] Board after {ply} moves: {board.fen()}")
    # Play the clicked move
    try:
        clicked_move = board.parse_uci(move_uci)
        board.push(clicked_move)
        moves_played_in_continuation.append(clicked_move)
        print(f"[DEBUG] Played clicked move: {move_uci} (in position {board.fen()})")
    except (ValueError, AssertionError) as e:
        print(f"[DEBUG] Failed to play {move_uci}: {e}")
        return HttpResponse("Invalid move_uci for position", status=400)

    # Collect continuation moves from the game if they exist after this ply
    # Otherwise, generate empty board frames (just the position after the move)
    context_parts = ["Best" if tier == 1 else f"Move {tier}"]
    context_parts.append(engine.upper())
    context_parts.append(f"(ply {ply}+{len(moves_played_in_continuation)})")
    context_label = " ".join(context_parts)

    # Generate board frames for the continuation
    # For now, we'll just show the continuation position with empty moves
    # (We could extend this to show actual continuation if stored in DB)
    flipped = orientation == "black"
    
    frames = []
    san_list = []
    arrow_labels_by_ply = {}

    # Frame 0: position after the clicked move
    frames.append(chess.svg.board(board, size=480, flipped=flipped, colors=_BOARD_COLORS))

    # Try to continue with moves from the game (if this position continues in the actual game)
    # This is a simplified version; a full implementation would show all continuation moves
    continuation_board = board.copy()
    continuation_moves = []
    
    # Find where we are in the game and continue from there if possible
    current_board = game_obj.board()
    moves_to_reach = []
    for i, move in enumerate(moves_list):
        if i >= ply:
            break
        moves_to_reach.append(move)
    
    # Play those moves to get to our position
    for m in moves_to_reach:
        current_board.push(m)
    
    # Try to play the clicked move in the game
    try:
        if current_board.parse_uci(move_uci) in current_board.legal_moves:
            current_board.push(current_board.parse_uci(move_uci))
            
            # Collect remaining moves from the game
            remaining_game_moves = []
            for i, move in enumerate(moves_list):
                if i > ply:
                    remaining_game_moves.append(move)
            
            # Generate frames for continuation (up to 50+ moves)
            for move_idx, move in enumerate(remaining_game_moves[:50]):
                try:
                    if move in continuation_board.legal_moves:
                        san = continuation_board.san(move)
                        continuation_board.push(move)
                        san_list.append(san)
                        
                        frames.append(chess.svg.board(
                            continuation_board,
                            size=480,
                            lastmove=move,
                            flipped=flipped,
                            colors=_BOARD_COLORS,
                        ))
                except (ValueError, AssertionError):
                    break
    except (ValueError, AssertionError):
        pass

    return render(request, "games/_engine_line_partial.html", {
        "frames_json": json.dumps(frames),
        "arrow_labels_json": json.dumps(arrow_labels_by_ply),
        "san_list_json": json.dumps(san_list),
        "context_label": context_label,
        "total_frames": len(frames),
    })


def queue_analysis(request: HttpRequest, slug: str) -> HttpResponse:
    """
    Queue a game for engine re-analysis.

    Accepts engine="stockfish" or engine="lc0" in the POST body. Enforces
    that a game cannot be queued if an active job already exists for that engine.

    Params:
        request (HttpRequest): POST request with engine field.
        slug (str): Game URL slug.

    Returns:
        HTMX partial HTML fragment: success or already-queued button state.
        Returns 400 for invalid engine values.
    """
    engine = request.POST.get("engine", "").strip().lower()
    if engine not in ("stockfish", "lc0"):
        return HttpResponse("Invalid engine", status=400)

    game = get_object_or_404(Game, slug=slug)

    already_queued = AnalysisJob.objects.filter(
        game=game,
        engine=engine,
        status__in=_ACTIVE_STATUSES,
    ).exists()

    if already_queued:
        return render(request, "games/_queue_already_queued.html", {"engine": engine})

    AnalysisJob.objects.create(
        game=game,
        engine=engine,
        status=AnalysisJob.STATUS_PENDING,
        priority=1,
    )
    return render(request, "games/_queue_success.html", {"engine": engine})
