import os
import time
from collections.abc import Mapping
from typing import Any
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from app.storage.database import get_session, init_db
from app.storage.models import AnalysisJob
from app.web.components.auth import require_auth

require_auth()
init_db()


def _load_dotenv_values() -> dict[str, str]:
    """Best-effort .env parser for values not exported into process env."""
    values: dict[str, str] = {}
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return values

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                values[key] = val
    except Exception:
        # Failing to parse .env should not break page rendering.
        return {}

    return values


def _resolve_config_value(name: str, dotenv_values: dict[str, str]) -> str:
    """Resolve a config value from env, Streamlit secrets, then .env."""
    env_val = os.environ.get(name, "").strip()
    if env_val:
        return env_val

    try:
        if name in st.secrets:
            sec_val = str(st.secrets[name]).strip()
            if sec_val:
                return sec_val
    except Exception:
        pass

    return dotenv_values.get(name, "").strip()


def _runpod_endpoint_ids() -> dict[str, str | None]:
    dotenv_values = _load_dotenv_values()

    stockfish_endpoint = _resolve_config_value("RUNPOD_STOCKFISH_ENDPOINT_ID", dotenv_values)
    if not stockfish_endpoint:
        stockfish_endpoint = _resolve_config_value("RUNPOD_ENDPOINT_ID", dotenv_values)

    lc0_endpoint = _resolve_config_value("RUNPOD_LC0_ENDPOINT_ID", dotenv_values)
    return {
        "stockfish": stockfish_endpoint or None,
        "lc0": lc0_endpoint or None,
    }


def _fetch_runpod_health(endpoint_id: str | None) -> tuple[dict[str, int] | None, str | None]:
    if not endpoint_id:
        return None, "Endpoint ID not configured (check RUNPOD_STOCKFISH_ENDPOINT_ID / RUNPOD_ENDPOINT_ID / RUNPOD_LC0_ENDPOINT_ID)"

    dotenv_values = _load_dotenv_values()
    api_key = _resolve_config_value("RUNPOD_API_KEY", dotenv_values)
    if not api_key:
        return None, "RUNPOD_API_KEY not set (env, st.secrets, or .env)"

    try:
        import runpod  # type: ignore
    except Exception as exc:
        return None, f"runpod package unavailable: {exc}"

    try:
        runpod.api_key = api_key
        endpoint = runpod.Endpoint(endpoint_id)
        data = endpoint.health(timeout=5)
    except Exception as exc:
        return None, f"health request failed: {exc}"

    if not isinstance(data, Mapping):
        return None, f"unexpected health payload: {type(data).__name__}"

    jobs = data.get("jobs", {}) if isinstance(data.get("jobs"), Mapping) else {}
    workers = data.get("workers", {}) if isinstance(data.get("workers"), Mapping) else {}

    normalized = {
        "jobs_in_queue": int(jobs.get("inQueue", 0) or 0),
        "jobs_in_progress": int(jobs.get("inProgress", 0) or 0),
        "jobs_completed": int(jobs.get("completed", 0) or 0),
        "jobs_failed": int(jobs.get("failed", 0) or 0),
        "jobs_retried": int(jobs.get("retried", 0) or 0),
        "workers_idle": int(workers.get("idle", 0) or 0),
        "workers_running": int(workers.get("running", 0) or 0),
    }
    return normalized, None


def _queue_counts_by_engine() -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(
            select(
                AnalysisJob.engine,
                AnalysisJob.status,
                func.count().label("count"),
            ).group_by(AnalysisJob.engine, AnalysisJob.status)
        ).all()
    return pd.DataFrame([r._asdict() for r in rows]) if rows else pd.DataFrame(
        columns=["engine", "status", "count"]
    )


def _queue_totals() -> dict[str, int]:
    with get_session() as s:
        rows = s.execute(
            select(AnalysisJob.status, func.count().label("n")).group_by(AnalysisJob.status)
        ).all()
    return {r.status: int(r.n) for r in rows}


def _get_recent_jobs(limit: int = 100) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(
            select(
                AnalysisJob.id,
                AnalysisJob.engine,
                AnalysisJob.status,
                AnalysisJob.game_id,
                AnalysisJob.depth,
                AnalysisJob.runpod_job_id,
                AnalysisJob.submitted_at,
                AnalysisJob.started_at,
                AnalysisJob.completed_at,
                AnalysisJob.duration_seconds,
                AnalysisJob.retry_count,
                AnalysisJob.error_message,
            )
            .order_by(AnalysisJob.id.desc())
            .limit(limit)
        ).all()
    return pd.DataFrame([r._asdict() for r in rows]) if rows else pd.DataFrame()


def _engine_queue_metric(df: pd.DataFrame, engine: str, status: str) -> int:
    if df.empty:
        return 0
    subset = df[(df["engine"] == engine) & (df["status"] == status)]
    if subset.empty:
        return 0
    return int(subset["count"].sum())


def _sample_active_jobs(sample_per_engine: int = 10) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(
            select(
                AnalysisJob.id,
                AnalysisJob.engine,
                AnalysisJob.status,
                AnalysisJob.game_id,
                AnalysisJob.depth,
                AnalysisJob.runpod_job_id,
                AnalysisJob.submitted_at,
            )
            .where(
                AnalysisJob.status.in_(["submitted", "running"]),
                AnalysisJob.runpod_job_id.is_not(None),
            )
            .order_by(AnalysisJob.submitted_at.desc())
            .limit(sample_per_engine * 8)
        ).all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([r._asdict() for r in rows])
    sampled: list[pd.DataFrame] = []
    for engine in ("stockfish", "lc0"):
        subset = df[df["engine"] == engine].head(sample_per_engine)
        if not subset.empty:
            sampled.append(subset)

    if not sampled:
        return pd.DataFrame()
    return pd.concat(sampled, ignore_index=True)


def _poll_runpod_job_statuses(
    sampled_jobs: pd.DataFrame,
    endpoint_ids: dict[str, str | None],
) -> tuple[pd.DataFrame, str | None]:
    if sampled_jobs.empty:
        return pd.DataFrame(), None

    dotenv_values = _load_dotenv_values()
    api_key = _resolve_config_value("RUNPOD_API_KEY", dotenv_values)
    if not api_key:
        return pd.DataFrame(), "RUNPOD_API_KEY not set (env, st.secrets, or .env)"

    try:
        from runpod.endpoint.runner import RunPodClient  # type: ignore
    except Exception as exc:
        return pd.DataFrame(), f"runpod package unavailable: {exc}"

    client = RunPodClient(api_key=api_key)
    records: list[dict[str, Any]] = []

    for row in sampled_jobs.to_dict("records"):
        engine = str(row.get("engine", ""))
        endpoint_id = endpoint_ids.get(engine)
        runpod_job_id = str(row.get("runpod_job_id", "") or "")

        base = {
            "id": row.get("id"),
            "engine": engine,
            "game_id": row.get("game_id"),
            "depth": row.get("depth"),
            "local_status": row.get("status"),
            "runpod_job_id": runpod_job_id,
            "submitted_at": row.get("submitted_at"),
        }

        if not endpoint_id:
            records.append({**base, "runpod_status": None, "delay_ms": None, "execution_ms": None, "poll_error": "endpoint ID not configured"})
            continue
        if not runpod_job_id:
            records.append({**base, "runpod_status": None, "delay_ms": None, "execution_ms": None, "poll_error": "missing runpod_job_id"})
            continue

        try:
            payload = client.get(f"{endpoint_id}/status/{runpod_job_id}", timeout=5)
            records.append({
                **base,
                "runpod_status": payload.get("status"),
                "delay_ms": payload.get("delayTime"),
                "execution_ms": payload.get("executionTime"),
                "poll_error": None,
            })
        except Exception as exc:
            records.append({**base, "runpod_status": None, "delay_ms": None, "execution_ms": None, "poll_error": str(exc)})

    return pd.DataFrame(records), None


st.title("Analysis Status")
st.caption("RunPod serverless + dispatcher pipeline status for Stockfish and Lc0.")
auto_refresh = st.toggle("Auto-refresh every 10s", value=False)

counts = _queue_totals()
total = sum(counts.values())
pending = counts.get("pending", 0)
submitted = counts.get("submitted", 0)
running = counts.get("running", 0)
completed = counts.get("completed", 0)
failed = counts.get("failed", 0)

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total Jobs", f"{total:,}")
c2.metric("Pending", f"{pending:,}")
c3.metric("Submitted", f"{submitted:,}")
c4.metric("Running", f"{running:,}")
c5.metric("Completed", f"{completed:,}")
c6.metric("Failed", f"{failed:,}")

if total > 0:
    pct = completed / total
    st.progress(pct, text=f"{pct:.1%} completed ({completed:,}/{total:,})")

st.markdown("---")
st.subheader("Queue by Engine")
by_engine = _queue_counts_by_engine()

engine_col_sf, engine_col_lc0 = st.columns(2)
for col, engine_name, depth_label in (
    (engine_col_sf, "stockfish", "depth"),
    (engine_col_lc0, "lc0", "nodes"),
):
    with col:
        st.markdown(f"**{engine_name.upper()}**")
        e_pending = _engine_queue_metric(by_engine, engine_name, "pending")
        e_submitted = _engine_queue_metric(by_engine, engine_name, "submitted")
        e_running = _engine_queue_metric(by_engine, engine_name, "running")
        e_completed = _engine_queue_metric(by_engine, engine_name, "completed")
        e_failed = _engine_queue_metric(by_engine, engine_name, "failed")

        m1, m2, m3 = st.columns(3)
        m1.metric("Pending", e_pending)
        m2.metric("Submitted", e_submitted)
        m3.metric("Running", e_running)
        m4, m5 = st.columns(2)
        m4.metric("Completed", e_completed)
        m5.metric("Failed", e_failed)
        st.caption(f"Queue uses engine-specific {depth_label} values in `analysis_jobs.depth`.")

if not by_engine.empty:
    st.dataframe(by_engine.sort_values(["engine", "status"]), use_container_width=True, hide_index=True)

st.markdown("---")
st.subheader("RunPod Endpoint Health")

endpoint_ids = _runpod_endpoint_ids()
health_cols = st.columns(2)

for col, engine_name in zip(health_cols, ["stockfish", "lc0"], strict=False):
    endpoint_id = endpoint_ids[engine_name]
    health, error = _fetch_runpod_health(endpoint_id)

    with col:
        st.markdown(f"**{engine_name.upper()} Endpoint**")
        st.caption(f"Endpoint ID: {endpoint_id or 'not configured'}")
        if error:
            st.warning(error)
            continue

        assert health is not None
        k1, k2 = st.columns(2)
        k1.metric("Workers Running", health["workers_running"])
        k2.metric("Workers Idle", health["workers_idle"])

        q1, q2, q3 = st.columns(3)
        q1.metric("In Queue", health["jobs_in_queue"])
        q2.metric("In Progress", health["jobs_in_progress"])
        q3.metric("Failed", health["jobs_failed"])

        q4, q5 = st.columns(2)
        q4.metric("Completed", health["jobs_completed"])
        q5.metric("Retried", health["jobs_retried"])

st.markdown("---")
st.subheader("Submitted Job Telemetry (Sampled)")
sample_per_engine = st.selectbox(
    "Sample size per engine",
    options=[5, 10, 20],
    index=1,
    help="Polls RunPod /status for the most recent submitted/running jobs per engine.",
)

sampled_jobs = _sample_active_jobs(sample_per_engine=sample_per_engine)
if sampled_jobs.empty:
    st.info("No submitted/running jobs with RunPod IDs to sample right now.")
else:
    telemetry_df, telemetry_error = _poll_runpod_job_statuses(sampled_jobs, endpoint_ids)
    if telemetry_error:
        st.warning(telemetry_error)
    elif telemetry_df.empty:
        st.info("No telemetry rows returned.")
    else:
        ok = telemetry_df[telemetry_df["poll_error"].isna()]
        completed_ok = ok[ok["runpod_status"] == "COMPLETED"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Sampled Jobs", len(telemetry_df))
        m2.metric("Poll Errors", int(telemetry_df["poll_error"].notna().sum()))
        m3.metric(
            "Avg Queue Delay (s)",
            f"{(completed_ok['delay_ms'].dropna().mean() / 1000):.1f}" if not completed_ok["delay_ms"].dropna().empty else "—",
        )
        m4.metric(
            "Avg Execution (s)",
            f"{(completed_ok['execution_ms'].dropna().mean() / 1000):.1f}" if not completed_ok["execution_ms"].dropna().empty else "—",
        )

        display_df = telemetry_df.copy()
        display_df["delay_s"] = display_df["delay_ms"].apply(
            lambda v: round(v / 1000, 2) if pd.notna(v) else None
        )
        display_df["execution_s"] = display_df["execution_ms"].apply(
            lambda v: round(v / 1000, 2) if pd.notna(v) else None
        )

        st.dataframe(
            display_df[
                [
                    "id",
                    "engine",
                    "game_id",
                    "runpod_job_id",
                    "local_status",
                    "runpod_status",
                    "delay_s",
                    "execution_s",
                    "poll_error",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("Job", width="small"),
                "engine": st.column_config.TextColumn("Engine", width="small"),
                "game_id": st.column_config.TextColumn("Game ID"),
                "runpod_job_id": st.column_config.TextColumn("RunPod Job ID"),
                "local_status": st.column_config.TextColumn("DB Status"),
                "runpod_status": st.column_config.TextColumn("RunPod Status"),
                "delay_s": st.column_config.NumberColumn("Queue Delay (s)", width="small"),
                "execution_s": st.column_config.NumberColumn("Execution (s)", width="small"),
                "poll_error": st.column_config.TextColumn("Poll Error"),
            },
        )

st.markdown("---")
st.subheader("Recent Jobs")
df = _get_recent_jobs(100)

if df.empty:
    st.info("No jobs found yet.")
else:
    status_icons = {
        "completed": "✅",
        "running": "⏳",
        "pending": "🕐",
        "submitted": "📤",
        "failed": "❌",
    }
    df["status"] = df["status"].map(lambda s: f"{status_icons.get(s, '')} {s}")
    df["duration_s"] = df["duration_seconds"].apply(
        lambda v: round(v) if pd.notna(v) else None
    )

    display_cols = [
        "id",
        "engine",
        "status",
        "game_id",
        "depth",
        "runpod_job_id",
        "submitted_at",
        "duration_s",
        "retry_count",
        "error_message",
    ]
    display_cols = [c for c in display_cols if c in df.columns]

    st.dataframe(
        df[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("Job", width="small"),
            "engine": st.column_config.TextColumn("Engine", width="small"),
            "game_id": st.column_config.TextColumn("Game ID"),
            "depth": st.column_config.NumberColumn("Depth/Nodes", width="small"),
            "runpod_job_id": st.column_config.TextColumn("RunPod Job ID"),
            "submitted_at": st.column_config.DatetimeColumn("Submitted At"),
            "duration_s": st.column_config.NumberColumn("Duration (s)", width="small"),
            "retry_count": st.column_config.NumberColumn("Retries", width="small"),
            "error_message": st.column_config.TextColumn("Error"),
        },
    )

if auto_refresh:
    time.sleep(10)
    st.rerun()
