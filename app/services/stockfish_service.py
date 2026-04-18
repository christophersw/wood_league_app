"""Stockfish analysis service using python-chess chess.engine."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generator

import chess
import chess.engine
import chess.pgn

from app.config import get_settings

# Classification thresholds (centipawn loss from mover's perspective)
_BLUNDER_CPL = 300
_MISTAKE_CPL = 100
_INACCURACY_CPL = 50


@dataclass
class MoveResult:
    ply: int
    san: str
    fen: str
    cp_eval: float        # eval after the move was played (white-relative, centipawns)
    best_move: str        # UCI of the engine's top choice before this move
    arrow_uci: str        # same as best_move (consumed by the board UI)
    cpl: float            # centipawn loss for the side that just moved (≥ 0)
    classification: str   # blunder / mistake / inaccuracy / good / excellent


@dataclass
class PlayerStats:
    accuracy: float
    acpl: float
    blunders: int
    mistakes: int
    inaccuracies: int


@dataclass
class GameResult:
    white_stats: PlayerStats
    black_stats: PlayerStats
    moves: list[MoveResult]
    engine_depth: int
    analyzed_at: datetime


def _cp(score: chess.engine.Score) -> float:
    """Convert a Score to white-relative centipawns, clamping mate scores."""
    if score.is_mate():
        mate = score.mate()
        return 10000.0 if (mate is not None and mate > 0) else -10000.0
    val = score.score()
    return float(val) if val is not None else 0.0


def _win_prob(cp_white_relative: float) -> float:
    """Approximate win probability for White from a centipawn eval."""
    return 1.0 / (1.0 + math.exp(-cp_white_relative / 290.0))


def _accuracy_from_wp_loss(total_wp_loss: float) -> float:
    """chess.com-style accuracy from cumulative win-probability loss."""
    if total_wp_loss <= 0:
        return 100.0
    raw = 103.1668 * math.exp(-0.04354 * total_wp_loss) - 3.1669
    return max(0.0, min(100.0, raw))


def _classify(cpl: float) -> str:
    if cpl >= _BLUNDER_CPL:
        return "blunder"
    if cpl >= _MISTAKE_CPL:
        return "mistake"
    if cpl >= _INACCURACY_CPL:
        return "inaccuracy"
    if cpl >= 10:
        return "good"
    return "excellent"


def analyze_pgn(
    pgn_text: str,
    stockfish_path: str,
    depth: int = 20,
    threads: int = 1,
    move_callback: "callable[[int, int, str], None] | None" = None,
) -> GameResult:
    """Analyze a full game PGN and return per-move results plus player stats.

    move_callback(ply, total_moves, san) is called after each move is analyzed.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Could not parse PGN")

    # Count total moves up front so callers can show a denominator
    total_moves = sum(1 for _ in game.mainline_moves())

    engine_options: dict = {"Threads": str(threads)}
    limit = chess.engine.Limit(depth=depth)

    move_results: list[MoveResult] = []
    white_wp_losses: list[float] = []
    black_wp_losses: list[float] = []
    white_cpls: list[float] = []
    black_cpls: list[float] = []

    with chess.engine.SimpleEngine.popen_uci(stockfish_path) as engine:
        engine.configure(engine_options)
        board = game.board()

        # Eval before the first move (white's perspective)
        prev_info = engine.analyse(board, limit)
        prev_cp = _cp(prev_info["score"].white())

        for node in game.mainline():
            move = node.move
            ply = board.ply() + 1        # 1-based ply after the move
            is_white_move = board.turn == chess.WHITE

            san = board.san(move)
            best_result = engine.analyse(board, limit)
            best_cp_before = _cp(best_result["score"].white())
            best_move_uci = best_result.get("pv", [None])[0]
            best_move_str = best_move_uci.uci() if best_move_uci else ""

            board.push(move)
            after_info = engine.analyse(board, limit)
            after_cp = _cp(after_info["score"].white())

            # CPL from the mover's perspective
            if is_white_move:
                cpl = max(0.0, best_cp_before - after_cp)
            else:
                cpl = max(0.0, after_cp - best_cp_before)

            # Win-probability loss for the mover
            wp_before = _win_prob(best_cp_before if is_white_move else -best_cp_before)
            wp_after = _win_prob(after_cp if is_white_move else -after_cp)
            wp_loss = max(0.0, wp_before - wp_after) * 100.0  # scale to 0-100

            if is_white_move:
                white_cpls.append(cpl)
                white_wp_losses.append(wp_loss)
            else:
                black_cpls.append(cpl)
                black_wp_losses.append(wp_loss)

            move_results.append(MoveResult(
                ply=ply,
                san=san,
                fen=board.fen(),
                cp_eval=after_cp,
                best_move=best_move_str,
                arrow_uci=best_move_str,
                cpl=cpl,
                classification=_classify(cpl),
            ))
            if move_callback:
                move_callback(ply, total_moves, san)

    def _stats(cpls: list[float], wp_losses: list[float]) -> PlayerStats:
        if not cpls:
            return PlayerStats(accuracy=100.0, acpl=0.0, blunders=0, mistakes=0, inaccuracies=0)
        return PlayerStats(
            accuracy=_accuracy_from_wp_loss(sum(wp_losses)),
            acpl=sum(cpls) / len(cpls),
            blunders=sum(1 for c in cpls if c >= _BLUNDER_CPL),
            mistakes=sum(1 for c in cpls if _MISTAKE_CPL <= c < _BLUNDER_CPL),
            inaccuracies=sum(1 for c in cpls if _INACCURACY_CPL <= c < _MISTAKE_CPL),
        )

    return GameResult(
        white_stats=_stats(white_cpls, white_wp_losses),
        black_stats=_stats(black_cpls, black_wp_losses),
        moves=move_results,
        engine_depth=depth,
        analyzed_at=datetime.now(timezone.utc),
    )
