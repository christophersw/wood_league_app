"""Worker that claims AnalysisJob rows and runs Stockfish analysis."""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, and_, func
from tqdm import tqdm

from app.services.stockfish_service import analyze_pgn
from app.storage.database import ENGINE, get_session, init_db
from app.storage.models import AnalysisJob, Game, GameAnalysis, MoveAnalysis

log = logging.getLogger(__name__)

_WORKER_ID = socket.gethostname()


@dataclass
class _ClaimedJob:
    id: int
    game_id: str
    depth: int


def _claim_job(depth: int) -> _ClaimedJob | None:
    """
    Atomically claim one pending job and return its key fields as a plain dataclass.
    Uses SELECT FOR UPDATE SKIP LOCKED on PostgreSQL; plain SELECT on SQLite.
    """
    is_pg = ENGINE.dialect.name == "postgresql"

    stmt = (
        select(AnalysisJob)
        .where(
            and_(
                AnalysisJob.status == "pending",
                AnalysisJob.depth <= depth,
            )
        )
        .order_by(AnalysisJob.priority.desc(), AnalysisJob.created_at)
        .limit(1)
    )
    if is_pg:
        stmt = stmt.with_for_update(skip_locked=True)

    with get_session() as session:
        job = session.execute(stmt).scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.worker_id = _WORKER_ID
        session.commit()
        # Copy scalar fields before session closes to avoid DetachedInstanceError
        return _ClaimedJob(id=job.id, game_id=job.game_id, depth=job.depth)


def _load_pgn(game_id: str) -> str:
    with get_session() as session:
        game = session.get(Game, game_id)
        return game.pgn if game and game.pgn else ""


def _save_analysis(job: _ClaimedJob, result) -> None:
    """Persist GameAnalysis + MoveAnalysis rows, update GameParticipant stats."""
    with get_session() as session:
        ga = session.execute(
            select(GameAnalysis).where(GameAnalysis.game_id == job.game_id)
        ).scalar_one_or_none()

        if ga is None:
            ga = GameAnalysis(game_id=job.game_id)
            session.add(ga)
            session.flush()

        ga.analyzed_at = result.analyzed_at
        ga.engine_depth = result.engine_depth
        ga.white_accuracy = result.white_stats.accuracy
        ga.black_accuracy = result.black_stats.accuracy
        ga.white_acpl = result.white_stats.acpl
        ga.black_acpl = result.black_stats.acpl
        ga.white_blunders = result.white_stats.blunders
        ga.white_mistakes = result.white_stats.mistakes
        ga.white_inaccuracies = result.white_stats.inaccuracies
        ga.black_blunders = result.black_stats.blunders
        ga.black_mistakes = result.black_stats.mistakes
        ga.black_inaccuracies = result.black_stats.inaccuracies
        if result.moves:
            ga.summary_cp = result.moves[-1].cp_eval

        for old in list(ga.moves):
            session.delete(old)
        session.flush()

        for mr in result.moves:
            session.add(MoveAnalysis(
                analysis_id=ga.id,
                ply=mr.ply,
                san=mr.san,
                fen=mr.fen,
                cp_eval=mr.cp_eval,
                best_move=mr.best_move,
                arrow_uci=mr.arrow_uci,
                cpl=mr.cpl,
                classification=mr.classification,
            ))

        game = session.get(Game, job.game_id)
        if game:
            for participant in game.participants:
                color = participant.color.lower()
                stats = result.white_stats if color == "white" else (
                    result.black_stats if color == "black" else None
                )
                if stats is None:
                    continue
                participant.quality_score = stats.accuracy
                participant.acpl = stats.acpl
                participant.blunder_count = stats.blunders
                participant.mistake_count = stats.mistakes
                participant.inaccuracy_count = stats.inaccuracies

        session.commit()


def _mark_completed(job_id: int) -> None:
    with get_session() as session:
        job = session.get(AnalysisJob, job_id)
        if job:
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            session.commit()


def _mark_failed(job_id: int, error: str) -> None:
    with get_session() as session:
        job = session.get(AnalysisJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = error
            job.retry_count = (job.retry_count or 0) + 1
            session.commit()


_STALE_MINUTES = 10


def _recover_stale_jobs() -> int:
    """Reset jobs stuck in 'running' for longer than _STALE_MINUTES back to 'pending'."""
    from sqlalchemy import update, func
    from app.storage.database import ENGINE

    is_pg = ENGINE.dialect.name == "postgresql"
    with get_session() as session:
        if is_pg:
            cutoff_expr = func.now() - func.cast(f"{_STALE_MINUTES} minutes", type_=None)
            # Use text for the interval cast which varies by dialect
            from sqlalchemy import text as sa_text
            result = session.execute(sa_text(
                "UPDATE analysis_jobs SET status='pending', worker_id=NULL, started_at=NULL "
                f"WHERE status='running' AND started_at < NOW() - INTERVAL '{_STALE_MINUTES} minutes'"
            ))
        else:
            # SQLite: use datetime arithmetic
            from sqlalchemy import text as sa_text
            result = session.execute(sa_text(
                "UPDATE analysis_jobs SET status='pending', worker_id=NULL, started_at=NULL "
                f"WHERE status='running' AND started_at < datetime('now', '-{_STALE_MINUTES} minutes')"
            ))
        session.commit()
        return result.rowcount


def run_worker(stockfish_path: str, depth: int = 20, threads: int = 1, poll_interval: float = 5.0, limit: int | None = None) -> None:
    """
    Main worker loop. Continuously claims and processes jobs until no more remain.
    Set poll_interval=0 to exit immediately when the queue is empty.
    Set limit to stop after processing that many games.
    """
    init_db()
    recovered = _recover_stale_jobs()
    if recovered:
        log.info("Recovered %d stale job(s) back to pending.", recovered)
    log.info("Worker starting. stockfish=%s depth=%d threads=%d limit=%s", stockfish_path, depth, threads, limit or "∞")

    # Count pending jobs for the progress bar total
    with get_session() as session:
        total = session.execute(
            select(func.count()).where(AnalysisJob.status == "pending")
        ).scalar_one()
    if limit is not None:
        total = min(total, limit)

    processed = 0
    bar = tqdm(total=total, unit="game", desc="Analyzing", dynamic_ncols=True)

    try:
        while True:
            if limit is not None and processed >= limit:
                log.info("Reached limit of %d games — exiting.", limit)
                break

            job = _claim_job(depth)

            if job is None:
                if poll_interval <= 0:
                    break
                time.sleep(poll_interval)
                continue

            bar.set_postfix_str(f"game {job.game_id[:16]}")
            move_bar = tqdm(total=None, unit="move", desc="  Move", leave=False,
                            dynamic_ncols=True, position=1)
            try:
                pgn_text = _load_pgn(job.game_id)
                if not pgn_text:
                    raise ValueError("No PGN for game")

                def on_move(ply: int, total: int, san: str) -> None:
                    if move_bar.total != total:
                        move_bar.total = total
                        move_bar.refresh()
                    move_bar.n = ply
                    move_bar.set_postfix_str(san)
                    move_bar.refresh()

                result = analyze_pgn(pgn_text, stockfish_path=stockfish_path,
                                     depth=depth, threads=threads, move_callback=on_move)
                _save_analysis(job, result)
                _mark_completed(job.id)
                processed += 1
                bar.update(1)
                bar.set_postfix_str(
                    f"W {result.white_stats.accuracy:.0f}%  B {result.black_stats.accuracy:.0f}%"
                )

            except Exception as exc:
                log.exception("Job %d failed: %s", job.id, exc)
                _mark_failed(job.id, str(exc))
                bar.update(1)
            finally:
                move_bar.close()
    finally:
        bar.close()

    log.info("Done. Processed %d game(s).", processed)
