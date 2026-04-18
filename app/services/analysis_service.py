from __future__ import annotations

from dataclasses import dataclass
import io

import chess.pgn
import pandas as pd
from sqlalchemy import select

from app.storage.database import get_session, init_db
from app.storage.models import Game, GameAnalysis, MoveAnalysis


@dataclass
class GameAnalysisData:
    game_id: str
    white: str
    black: str
    result: str
    pgn: str
    moves: pd.DataFrame
    date: str = ""
    time_control: str = ""
    url: str = ""
    # Per-player accuracy stats (None when not yet analyzed by Stockfish)
    white_accuracy: float | None = None
    black_accuracy: float | None = None
    white_acpl: float | None = None
    black_acpl: float | None = None
    white_blunders: int | None = None
    white_mistakes: int | None = None
    white_inaccuracies: int | None = None
    black_blunders: int | None = None
    black_mistakes: int | None = None
    black_inaccuracies: int | None = None
    engine_depth: int | None = None


class AnalysisService:
    def __init__(self) -> None:
        init_db()

    def get_game_analysis(self, game_id: str) -> GameAnalysisData | None:
        if not game_id:
            return None

        with get_session() as session:
            db_game = session.get(Game, game_id)
            if db_game is None:
                return None

            pgn_text = db_game.pgn or ""
            date = ""
            time_control = db_game.time_control or ""
            if db_game.played_at:
                date = db_game.played_at.strftime("%Y-%m-%d %H:%M")

            # Resolve PGN headers for fields not in DB
            game = chess.pgn.read_game(io.StringIO(pgn_text)) if pgn_text else None
            if game is None:
                return None

            white = db_game.white_username or game.headers.get("White", "White")
            black = db_game.black_username or game.headers.get("Black", "Black")
            result = db_game.result_pgn or game.headers.get("Result", "*")
            if not date:
                date = game.headers.get("Date", "")
            if not time_control:
                time_control = game.headers.get("TimeControl", "")
            url = game.headers.get("Link", "")

            # Try to load real Stockfish analysis
            ga = session.execute(
                select(GameAnalysis).where(GameAnalysis.game_id == game_id)
            ).scalar_one_or_none()

            if ga is not None and ga.analyzed_at is not None and ga.moves:
                moves_df = _moves_from_db(ga.moves)
                return GameAnalysisData(
                    game_id=game_id,
                    white=white,
                    black=black,
                    result=result,
                    pgn=pgn_text,
                    moves=moves_df,
                    date=date,
                    time_control=time_control,
                    url=url,
                    white_accuracy=ga.white_accuracy,
                    black_accuracy=ga.black_accuracy,
                    white_acpl=ga.white_acpl,
                    black_acpl=ga.black_acpl,
                    white_blunders=ga.white_blunders,
                    white_mistakes=ga.white_mistakes,
                    white_inaccuracies=ga.white_inaccuracies,
                    black_blunders=ga.black_blunders,
                    black_mistakes=ga.black_mistakes,
                    black_inaccuracies=ga.black_inaccuracies,
                    engine_depth=ga.engine_depth,
                )

        # Fallback: build move list from PGN without engine evals
        board = game.board()
        rows: list[dict] = []
        for ply, move in enumerate(game.mainline_moves(), start=1):
            san = board.san(move)
            board.push(move)
            rows.append({
                "ply": ply,
                "san": san,
                "fen": board.fen(),
                "cp_eval": None,
                "best_move": "",
                "arrow_uci": "",
                "cpl": None,
                "classification": None,
            })

        return GameAnalysisData(
            game_id=game_id,
            white=white,
            black=black,
            result=result,
            pgn=pgn_text,
            moves=pd.DataFrame(rows),
            date=date,
            time_control=time_control,
            url=url,
        )


def _moves_from_db(move_rows: list[MoveAnalysis]) -> pd.DataFrame:
    sorted_moves = sorted(move_rows, key=lambda m: m.ply)
    rows = [
        {
            "ply": m.ply,
            "san": m.san,
            "fen": m.fen,
            "cp_eval": m.cp_eval,
            "best_move": m.best_move,
            "arrow_uci": m.arrow_uci,
            "cpl": m.cpl,
            "classification": m.classification,
        }
        for m in sorted_moves
    ]
    return pd.DataFrame(rows)
