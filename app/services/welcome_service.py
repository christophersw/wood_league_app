"""Data service for the Welcome tab.

Provides:
  - ELO timeseries for all club players
  - Top-N recent games by combined accuracy
  - Top-N all-time games by lowest combined ACPL
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import and_, func, select

from app.storage.database import get_session, init_db
from app.storage.models import (
    Game,
    GameAnalysis,
    GameParticipant,
    Lc0GameAnalysis,
    MoveAnalysis,
    Player,
)

# Games with fewer than this many plies are excluded from all welcome queries.
_MIN_PLIES = 20  # 10 full moves (white + black)


def _sufficient_moves_subquery():
    """Return a subquery of game_ids with at least _MIN_PLIES analysed plies."""
    return (
        select(GameAnalysis.game_id)
        .join(MoveAnalysis, MoveAnalysis.analysis_id == GameAnalysis.id)
        .group_by(GameAnalysis.game_id)
        .having(func.count(MoveAnalysis.id) >= _MIN_PLIES)
    )


class WelcomeService:
    def __init__(self) -> None:
        init_db()

    # ── Club members ────────────────────────────────────────────────────────────

    def get_club_member_names(self) -> list[str]:
        """Return sorted list of all club player usernames."""
        with get_session() as session:
            rows = session.execute(
                select(Player.username).order_by(Player.username)
            ).scalars().all()
        return list(rows)

    # ── ELO timeseries ──────────────────────────────────────────────────────

    def get_all_players_elo_timeseries(self, lookback_days: int = 90) -> pd.DataFrame:
        """Return daily average ELO for every club player over the lookback window.

        Columns: date, player, rating
        """
        floor_date = datetime.utcnow().date() - timedelta(days=lookback_days)
        with get_session() as session:
            rows = session.execute(
                select(
                    func.date(Game.played_at).label("played_date"),
                    Player.username,
                    func.avg(GameParticipant.player_rating).label("rating"),
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .where(
                    and_(
                        GameParticipant.player_rating.is_not(None),
                        func.date(Game.played_at) >= floor_date,
                    )
                )
                .group_by(func.date(Game.played_at), Player.username)
                .order_by(func.date(Game.played_at), Player.username)
            ).all()

        if not rows:
            return pd.DataFrame(columns=["date", "player", "rating"])

        df = pd.DataFrame(
            [
                {
                    "date": row.played_date,
                    "player": row.username,
                    "rating": float(row.rating),
                }
                for row in rows
            ]
        )
        df["date"] = pd.to_datetime(df["date"])
        return df

    # ── Player accuracy timeseries ──────────────────────────────────────────

    def get_player_accuracy_timeseries(self, lookback_days: int = 90) -> pd.DataFrame:
        """Return daily average accuracy for club players over the lookback window.

        Only players tracked in the Player table (i.e. club members) are included.
        Each player appears once per day, averaged across all their games that day.

        Columns: date, player, accuracy
        """
        floor_date = datetime.utcnow() - timedelta(days=lookback_days)
        with get_session() as session:
            # White-side rows — club player played as white
            white_rows = session.execute(
                select(
                    func.date(Game.played_at).label("played_date"),
                    Player.username.label("player"),
                    func.avg(GameAnalysis.white_accuracy).label("accuracy"),
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .join(GameAnalysis, GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        Game.played_at >= floor_date,
                        func.lower(GameParticipant.color) == "white",
                        GameAnalysis.white_accuracy.is_not(None),
                        Game.id.in_(_sufficient_moves_subquery()),
                    )
                )
                .group_by(func.date(Game.played_at), Player.username)
            ).all()

            # Black-side rows — club player played as black
            black_rows = session.execute(
                select(
                    func.date(Game.played_at).label("played_date"),
                    Player.username.label("player"),
                    func.avg(GameAnalysis.black_accuracy).label("accuracy"),
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .join(GameAnalysis, GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        Game.played_at >= floor_date,
                        func.lower(GameParticipant.color) == "black",
                        GameAnalysis.black_accuracy.is_not(None),
                        Game.id.in_(_sufficient_moves_subquery()),
                    )
                )
                .group_by(func.date(Game.played_at), Player.username)
            ).all()

        if not white_rows and not black_rows:
            return pd.DataFrame(columns=["date", "player", "accuracy"])

        records = [
            {"date": r.played_date, "player": r.player, "accuracy": float(r.accuracy)}
            for r in white_rows + black_rows
        ]
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        # Average across both colors when a player played multiple games on one day
        df = (
            df.groupby(["date", "player"], as_index=False)["accuracy"]
            .mean()
            .sort_values(["date", "player"])
        )
        return df

    # ── Best recent games (by accuracy) ─────────────────────────────────────

    def get_best_recent_games_by_accuracy(
        self,
        limit: int = 10,
        lookback_days: int = 30,
    ) -> pd.DataFrame:
        """Top N games played within *lookback_days*, ranked by combined accuracy.

        Columns: game_id, played_at, white, black, avg_accuracy,
                 white_accuracy, black_accuracy,
                 wdl_win, wdl_draw, wdl_loss
        """
        floor_date = datetime.utcnow() - timedelta(days=lookback_days)
        avg_acc = (GameAnalysis.white_accuracy + GameAnalysis.black_accuracy) / 2
        with get_session() as session:
            rows = session.execute(
                select(
                    Game.id,
                    Game.played_at,
                    Game.white_username,
                    Game.black_username,
                    GameAnalysis.white_accuracy,
                    GameAnalysis.black_accuracy,
                    Lc0GameAnalysis.white_win_prob,
                    Lc0GameAnalysis.white_draw_prob,
                    Lc0GameAnalysis.white_loss_prob,
                )
                .join(GameAnalysis, GameAnalysis.game_id == Game.id)
                .outerjoin(Lc0GameAnalysis, Lc0GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        Game.played_at >= floor_date,
                        GameAnalysis.white_accuracy.is_not(None),
                        GameAnalysis.black_accuracy.is_not(None),
                        Game.id.in_(_sufficient_moves_subquery()),
                    )
                )
                .order_by(avg_acc.desc())
                .limit(limit)
            ).all()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(
            [
                {
                    "game_id": row.id,
                    "played_at": row.played_at,
                    "white": row.white_username or "?",
                    "black": row.black_username or "?",
                    "avg_accuracy": (row.white_accuracy + row.black_accuracy) / 2,
                    "white_accuracy": row.white_accuracy,
                    "black_accuracy": row.black_accuracy,
                    "wdl_win": row.white_win_prob,
                    "wdl_draw": row.white_draw_prob,
                    "wdl_loss": row.white_loss_prob,
                }
                for row in rows
            ]
        )

    # ── Best all-time games (by ACPL) ────────────────────────────────────────

    def get_best_all_time_games_by_acpl(self, limit: int = 10) -> pd.DataFrame:
        """Top N all-time games ranked by lowest combined ACPL.

        Columns: game_id, played_at, white, black, avg_acpl,
                 white_acpl, black_acpl, white_accuracy, black_accuracy,
                 wdl_win, wdl_draw, wdl_loss
        """
        avg_acpl = (GameAnalysis.white_acpl + GameAnalysis.black_acpl) / 2
        with get_session() as session:
            rows = session.execute(
                select(
                    Game.id,
                    Game.played_at,
                    Game.white_username,
                    Game.black_username,
                    GameAnalysis.white_acpl,
                    GameAnalysis.black_acpl,
                    GameAnalysis.white_accuracy,
                    GameAnalysis.black_accuracy,
                    Lc0GameAnalysis.white_win_prob,
                    Lc0GameAnalysis.white_draw_prob,
                    Lc0GameAnalysis.white_loss_prob,
                )
                .join(GameAnalysis, GameAnalysis.game_id == Game.id)
                .outerjoin(Lc0GameAnalysis, Lc0GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        GameAnalysis.white_acpl.is_not(None),
                        GameAnalysis.black_acpl.is_not(None),
                        Game.id.in_(_sufficient_moves_subquery()),
                    )
                )
                .order_by(avg_acpl.asc())
                .limit(limit)
            ).all()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(
            [
                {
                    "game_id": row.id,
                    "played_at": row.played_at,
                    "white": row.white_username or "?",
                    "black": row.black_username or "?",
                    "avg_acpl": (row.white_acpl + row.black_acpl) / 2,
                    "white_acpl": row.white_acpl,
                    "black_acpl": row.black_acpl,
                    "white_accuracy": row.white_accuracy,
                    "black_accuracy": row.black_accuracy,
                    "wdl_win": row.white_win_prob,
                    "wdl_draw": row.white_draw_prob,
                    "wdl_loss": row.white_loss_prob,
                }
                for row in rows
            ]
        )
