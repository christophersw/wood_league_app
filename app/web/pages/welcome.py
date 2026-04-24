"""Welcome tab — accuracy trends, best recent games, and best games ever."""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

import pandas as pd
import streamlit as st

from app.services.welcome_service import WelcomeService
from app.web.components.auth import require_auth
from app.web.components.charts import player_accuracy_chart, player_elo_chart

require_auth()

_service = WelcomeService()

_TIMEFRAMES = {
    "Last 30 days":  30,
    "Last 90 days":  90,
    "Last 6 months": 180,
    "Last year":     365,
}

# ── Helpers ──────────────────────────────────────────────────────────────────


def _fmt_accuracy(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%"


def _fmt_acpl(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}"


def _fmt_wdl(win: float | None, draw: float | None, loss: float | None) -> str:
    if win is None or draw is None or loss is None:
        return "—"
    return f"W {win:.0f}% · D {draw:.0f}% · L {loss:.0f}%"


def _is_recent(played_at: object, days: int = 7) -> bool:
    cutoff = datetime.utcnow() - timedelta(days=days)
    if isinstance(played_at, pd.Timestamp):
        ts = played_at
        # Strip tz so comparison is always naive
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return ts >= pd.Timestamp(cutoff)
    if isinstance(played_at, datetime):
        naive = played_at.replace(tzinfo=None) if played_at.tzinfo is not None else played_at
        return naive >= cutoff
    return False


# ── Game tables ───────────────────────────────────────────────────────────────

_TABLE_STYLE = """
<style>
.wc-table {
  width: 100%;
  border-collapse: collapse;
  border: 2px solid #1A1A1A;
  font-family: 'DM Mono', monospace;
}
.wc-table thead tr {
  background: #1A3A2A;
}
.wc-table thead th {
  font-family: 'DM Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #F2E6D0;
  font-weight: 600;
  padding: 0.45rem 0.6rem;
  text-align: left;
  border: none;
}
.wc-table tbody tr:nth-child(odd)  { background: #F9F3E8; }
.wc-table tbody tr:nth-child(even) { background: #EFE4CC; }
.wc-table tbody tr { border-bottom: 1px solid #D4C4A0; }
.wc-table td {
  padding: 0.42rem 0.6rem;
  vertical-align: middle;
  white-space: nowrap;
}
.wc-rank  { font-size: 0.72rem; color: #8B3A2A; font-weight: 600; }
.wc-player { font-family: 'EB Garamond', Georgia, serif; font-size: 0.95rem; color: #1A1A1A; white-space: nowrap; }
.wc-acc   { font-size: 0.82rem; font-weight: 700; color: #1A3A2A; }
.wc-acpl  { font-size: 0.82rem; font-weight: 700; color: #4A6554; }
.wc-wdl   { font-size: 0.68rem; color: #5A5A5A; }
.wc-date  { font-size: 0.68rem; color: #8B3A2A; }
.wc-badge {
  display: inline-block;
  background: #B53541;
  color: #F2E6D0;
  font-size: 0.55rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 1px 4px;
  margin-left: 4px;
  vertical-align: middle;
}
.wc-open {
  display: inline-block;
  border: 1.5px solid #1A1A1A;
  color: #1A3A2A;
  font-family: 'DM Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 2px 8px;
  text-decoration: none;
  white-space: nowrap;
}
.wc-open:hover { background: #1A1A1A; color: #F2E6D0; text-decoration: none; }
</style>
"""


def _accuracy_table_html(df: pd.DataFrame) -> str:
    rows = []
    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        white    = escape(str(row["white"]))
        black    = escape(str(row["black"]))
        avg_acc  = _fmt_accuracy(row.get("avg_accuracy"))
        w_acc    = _fmt_accuracy(row.get("white_accuracy"))
        b_acc    = _fmt_accuracy(row.get("black_accuracy"))
        wdl      = _fmt_wdl(row.get("wdl_win"), row.get("wdl_draw"), row.get("wdl_loss"))
        played   = row.get("played_at")
        date_str = played.strftime("%d %b %Y") if hasattr(played, "strftime") else str(played)[:10]
        link     = escape(f"/game-analysis?game_id={row['game_id']}")
        rows.append(f"""<tr>
          <td class="wc-rank">#{rank}</td>
          <td class="wc-player">♙ {white}</td>
          <td class="wc-player">♟ {black}</td>
          <td class="wc-acc">{avg_acc}</td>
          <td class="wc-acc">{w_acc} / {b_acc}</td>
          <td class="wc-wdl">{wdl}</td>
          <td class="wc-date">{escape(date_str)}</td>
          <td><a class="wc-open" href="{link}" target="_blank">Open</a></td>
        </tr>""")
    return _TABLE_STYLE + f"""<table class="wc-table">
      <thead><tr>
        <th>#</th><th>White</th><th>Black</th>
        <th>Avg Acc</th><th>W / B Acc</th>
        <th>Avg WDL</th><th>Date</th><th></th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


def _acpl_table_html(df: pd.DataFrame, highlight_recent: bool = True) -> str:
    rows = []
    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        white    = escape(str(row["white"]))
        black    = escape(str(row["black"]))
        avg_acpl = _fmt_acpl(row.get("avg_acpl"))
        w_acpl   = _fmt_acpl(row.get("white_acpl"))
        b_acpl   = _fmt_acpl(row.get("black_acpl"))
        avg_acc  = _fmt_accuracy(
            (row["white_accuracy"] + row["black_accuracy"]) / 2
            if row.get("white_accuracy") is not None and row.get("black_accuracy") is not None
            else None
        )
        wdl      = _fmt_wdl(row.get("wdl_win"), row.get("wdl_draw"), row.get("wdl_loss"))
        played   = row.get("played_at")
        date_str = played.strftime("%d %b %Y") if hasattr(played, "strftime") else str(played)[:10]
        badge    = '<span class="wc-badge">New</span>' if highlight_recent and _is_recent(played) else ""
        link     = escape(f"/game-analysis?game_id={row['game_id']}")
        rows.append(f"""<tr>
          <td class="wc-rank">#{rank}</td>
          <td class="wc-player">♙ {white}</td>
          <td class="wc-player">♟ {black}</td>
          <td class="wc-acpl">{avg_acpl}</td>
          <td class="wc-acpl">{w_acpl} / {b_acpl}</td>
          <td class="wc-acc">{avg_acc}</td>
          <td class="wc-wdl">{wdl}</td>
          <td class="wc-date">{escape(date_str)}{badge}</td>
          <td><a class="wc-open" href="{link}" target="_blank">Open</a></td>
        </tr>""")
    return _TABLE_STYLE + f"""<table class="wc-table">
      <thead><tr>
        <th>#</th><th>White</th><th>Black</th>
        <th>Avg ACPL</th><th>W / B ACPL</th>
        <th>Avg Acc</th><th>Avg WDL</th><th>Date</th><th></th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


# ── Page ──────────────────────────────────────────────────────────────────────

st.title("Woodland Chess Club")
st.caption("Club overview — accuracy trends, best played games, and all-time records.")

# ── Filters ───────────────────────────────────────────────────────────────────

st.subheader("Member Accuracy Trends")

all_members = _service.get_club_member_names()
col_tf, col_pl = st.columns([1, 2])
with col_tf:
    selected_label = st.selectbox(
        "Timeframe",
        options=list(_TIMEFRAMES.keys()),
        index=1,
        label_visibility="collapsed",
    )
with col_pl:
    selected_players = st.multiselect(
        "Players",
        options=all_members,
        default=all_members,
        label_visibility="collapsed",
        placeholder="All members",
    )

lookback = _TIMEFRAMES[selected_label]
# Fallback: if the user deselects everyone, treat it as "all"
active_players = selected_players if selected_players else all_members


def _filter_by_player(df: pd.DataFrame) -> pd.DataFrame:
    """Filter a player-column dataframe to active_players."""
    if "player" in df.columns:
        return df[df["player"].isin(active_players)]
    return df


def _filter_games_by_player(df: pd.DataFrame) -> pd.DataFrame:
    """Keep games where white or black is an active player."""
    if df.empty:
        return df
    mask = df["white"].isin(active_players) | df["black"].isin(active_players)
    return df[mask]


acc_df = _service.get_player_accuracy_timeseries(lookback_days=lookback)
acc_df = _filter_by_player(acc_df)

if acc_df.empty:
    st.info("No analysed games found for this period.")
else:
    fig = player_accuracy_chart(acc_df)
    st.plotly_chart(fig, use_container_width=True)

# ── ELO Trends ───────────────────────────────────────────────────────────────

st.subheader("Member ELO Trends")
elo_df = _service.get_all_players_elo_timeseries(lookback_days=lookback)
elo_df = _filter_by_player(elo_df)

if elo_df.empty:
    st.info("No rating data available for this period.")
else:
    elo_fig = player_elo_chart(elo_df)
    st.plotly_chart(elo_fig, use_container_width=True)

st.divider()

# ── Best Recent Games (by Accuracy) ──────────────────────────────────────────

st.subheader("Best Played Games — Recent")
st.caption("Top 10 games from the last 30 days ranked by combined accuracy (Stockfish).")

recent_df = _service.get_best_recent_games_by_accuracy(limit=10, lookback_days=30)
recent_df = _filter_games_by_player(recent_df)
if recent_df.empty:
    st.info("No analysed games found in the last 30 days.")
else:
    st.html(_accuracy_table_html(recent_df))

st.divider()

# ── Best Club Games Ever (by ACPL) ───────────────────────────────────────────

st.subheader("Best Club Games Ever")
st.caption(
    "All-time top 10 games by lowest combined Average Centipawn Loss (ACPL). "
    "Games played in the last 7 days are highlighted."
)

ever_df = _service.get_best_all_time_games_by_acpl(limit=10)
ever_df = _filter_games_by_player(ever_df)
if ever_df.empty:
    st.info("No analysed games found.")
else:
    st.html(_acpl_table_html(ever_df, highlight_recent=True))
