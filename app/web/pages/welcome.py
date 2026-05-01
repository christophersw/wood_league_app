"""Welcome tab — accuracy trends, best recent games, and best games ever."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
import zoneinfo

import pandas as pd
import streamlit as st

from app.services.opening_analysis_service import OpeningAnalysisService
from app.services.welcome_service import WelcomeService
from app.web.components.auth import require_auth
from app.web.components.charts import (
    opening_wins_losses_bar,
    player_accuracy_chart,
    player_elo_chart,
    welcome_opening_sankey,
)

require_auth()

_service = WelcomeService()
_oa_service = OpeningAnalysisService()

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
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
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


_DEFAULT_TZ = zoneinfo.ZoneInfo("America/New_York")


def _fmt_last_ingest(event: dict | None, tz: zoneinfo.ZoneInfo = _DEFAULT_TZ) -> str:
    """Format last ingest event for display."""
    if event is None:
        return "Never"
    completed_at = event.get("completed_at")
    ts = completed_at if completed_at is not None else event.get("started_at")
    if ts is None:
        return "Unknown"
    if isinstance(ts, pd.Timestamp):
        dt = ts.to_pydatetime()
    elif isinstance(ts, datetime):
        dt = ts
    else:
        return str(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(tz)
    tz_abbr = dt.strftime("%Z")
    return dt.strftime(f"%b %d, %Y at %I:%M %p {tz_abbr}")


# ── Helpers ──────────────────────────────────────────────────────────────────


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


def _recent_games_table_html(df: pd.DataFrame) -> str:
    rows = []
    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        white       = escape(str(row["white"]))
        black       = escape(str(row["black"]))
        opening     = escape(str(row.get("opening_name", "Unknown")))
        opening_id  = row.get("opening_id")
        avg_acc     = _fmt_accuracy(row.get("avg_accuracy"))
        played      = row.get("played_at")
        date_str    = played.strftime("%d %b %Y") if hasattr(played, "strftime") else str(played)[:10]
        slug        = row.get("slug") or None
        game_link   = escape(f"/game-analysis?slug={slug}") if slug else escape(f"/game-analysis?game_id={row['game_id']}")
        link_label  = "Open"

        # Link to opening position page if opening_id is available
        if opening_id:
            opening_link = escape(f"/opening-position?opening_id={opening_id}")
        else:
            opening_link = "/opening-position"

        rows.append(f"""<tr>
          <td class="wc-rank">#{rank}</td>
          <td class="wc-player">♙ {white}</td>
          <td class="wc-player">♟ {black}</td>
          <td><a class="wc-open" href="{opening_link}" target="_blank">{opening}</a></td>
          <td class="wc-acc">{avg_acc}</td>
          <td class="wc-date">{escape(date_str)}</td>
          <td><a class="wc-open" href="{game_link}" target="_blank">{link_label}</a></td>
        </tr>""")
    return _TABLE_STYLE + f"""<table class="wc-table">
      <thead><tr>
        <th>#</th><th>White</th><th>Black</th>
        <th>Opening</th><th>Accuracy</th><th>Date</th><th></th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


# ── Page ──────────────────────────────────────────────────────────────────────

st.title("Wood League Chess Club")
st.caption("Club overview — accuracy trends, best played games, and all-time records.")

# ── Most Recent Games ─────────────────────────────────────────────────────────

st.subheader("Most Recent Games")

# Get last ingest event for timestamp display
last_ingest = _service.get_last_system_event("ingest")
_browser_tz_str = st.context.timezone if hasattr(st, "context") and st.context.timezone else None
try:
    _display_tz = zoneinfo.ZoneInfo(_browser_tz_str) if _browser_tz_str else _DEFAULT_TZ
except zoneinfo.ZoneInfoNotFoundError:
    _display_tz = _DEFAULT_TZ
last_check_time = _fmt_last_ingest(last_ingest, _display_tz)
st.caption(f"The 10 most recently played games · Last checked for updates: {last_check_time}")

recent_games = _service.get_most_recent_games(limit=10)
if recent_games.empty:
    st.info("No analysed games found.")
else:
    st.html(_recent_games_table_html(recent_games))

st.divider()

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
    st.plotly_chart(fig, width='stretch')

# ── ELO Trends ───────────────────────────────────────────────────────────────

st.subheader("Member ELO Trends")
elo_df = _service.get_all_players_elo_timeseries(lookback_days=lookback)
elo_df = _filter_by_player(elo_df)

if elo_df.empty:
    st.info("No rating data available for this period.")
else:
    elo_fig = player_elo_chart(elo_df)
    st.plotly_chart(elo_fig, width='stretch')

st.divider()

# ── Opening Continuations (Sankey) ───────────────────────────────────────────

st.subheader("Opening Continuations")
st.caption("Click a node to see stats for that opening path.")

_edges_df, _node_stats_df = _service.get_opening_flow(
    lookback_days=lookback,
    players=active_players,
    min_games=2,
)

# Trim to top 5 root openings (nodes that are sources but never targets)
if not _edges_df.empty:
    _all_targets = set(_edges_df["target"])
    _root_nodes = [s for s in _edges_df["source"].unique() if s not in _all_targets]
    _root_games = (
        _node_stats_df[_node_stats_df["node"].isin(_root_nodes)]
        .nlargest(5, "games")["node"]
        .tolist()
    )
    _reachable: set[str] = set(_root_games)
    for _depth in range(3):
        _reachable |= set(
            _edges_df[_edges_df["source"].isin(_reachable)]["target"]
        )
    _edges_df = _edges_df[
        _edges_df["source"].isin(_reachable) & _edges_df["target"].isin(_reachable)
    ].reset_index(drop=True)

if _edges_df.empty:
    st.info("No opening data available for this period.")
else:
    _total_games = int(
        _node_stats_df[
            _node_stats_df["node"].isin(set(_edges_df["source"]) | set(_edges_df["target"]))
        ]["games"].max()
    ) if not _node_stats_df.empty else 0

    _sankey_title = f"Opening Continuations — {selected_label}  ·  {_total_games} games"

    _selected_node: str | None = st.session_state.get("_opening_selected_node")

    _sankey_fig = welcome_opening_sankey(
        _edges_df,
        _node_stats_df,
        selected_node=_selected_node,
        title=_sankey_title,
    )
    # Build the ordered node label list to resolve point_number → label
    _sankey_labels: list[str] = list(dict.fromkeys(
        _edges_df["source"].tolist() + _edges_df["target"].tolist()
    ))

    _sankey_event = st.plotly_chart(
        _sankey_fig,
        width='stretch',
        on_select="rerun",
        key="opening_sankey",
    )

    # Handle click events — Sankey node clicks come in as point_number (node index)
    _clicked_label: str | None = None
    if _sankey_event and _sankey_event.selection:
        pts = _sankey_event.selection.get("points", [])
        if pts:
            pt = pts[0]
            # Try label/customdata first, fall back to point_number index
            _clicked_label = (
                pt.get("label")
                or (pt.get("customdata")[0] if isinstance(pt.get("customdata"), list) and pt.get("customdata") else None)
                or pt.get("customdata")
            )
            if _clicked_label is None:
                idx = pt.get("point_number")
                if idx is not None and 0 <= idx < len(_sankey_labels):
                    _clicked_label = _sankey_labels[idx]

    if _clicked_label and _clicked_label != _selected_node:
        st.session_state["_opening_selected_node"] = _clicked_label
        st.rerun()
    elif _clicked_label and _clicked_label == _selected_node:
        # Second click on same node deselects it
        st.session_state.pop("_opening_selected_node", None)
        st.rerun()

    # ── Stats panel for selected node ─────────────────────────────────────
    if _selected_node and not _node_stats_df.empty:
        _ns_row = _node_stats_df[_node_stats_df["node"] == _selected_node]
        if not _ns_row.empty:
            _ns = _ns_row.iloc[0]
            st.markdown(f"**{_selected_node}** — {int(_ns['games'])} games")

            _c1, _c2, _c3, _c4 = st.columns(4)
            _c1.metric("Wins", f"{int(_ns['wins'])}  ({_ns['win_pct']:.0f}%)")
            _c2.metric("Draws", f"{int(_ns['draws'])}  ({_ns['draw_pct']:.0f}%)")
            _c3.metric("Losses", f"{int(_ns['losses'])}  ({_ns['loss_pct']:.0f}%)")
            _wa = _ns.get("avg_white_accuracy")
            _ba = _ns.get("avg_black_accuracy")
            if _wa is not None and _ba is not None:
                _c4.metric("Avg Accuracy", f"W {_wa:.0f}% / B {_ba:.0f}%")
            elif _wa is not None:
                _c4.metric("White Accuracy", f"{_wa:.0f}%")
            elif _ba is not None:
                _c4.metric("Black Accuracy", f"{_ba:.0f}%")

            # Player breakdown table
            _player_counts: dict = _ns.get("players") or {}
            if _player_counts:
                _player_rows = sorted(_player_counts.items(), key=lambda x: -x[1])
                _player_html_rows = "".join(
                    f'<tr><td class="wc-player">{escape(p)}</td>'
                    f'<td class="wc-acc">{n}</td></tr>'
                    for p, n in _player_rows
                )
                st.html(
                    _TABLE_STYLE
                    + f"""<table class="wc-table" style="max-width:320px">
                      <thead><tr><th>Player</th><th>Games</th></tr></thead>
                      <tbody>{_player_html_rows}</tbody>
                    </table>"""
                )
            if st.button("Clear selection", key="clear_opening"):
                st.session_state.pop("_opening_selected_node", None)
                st.rerun()

# ── Most Common Openings (Wins vs Losses) ────────────────────────────────────

if not _edges_df.empty:
    _all_club_games = _oa_service.club_recent_games()

    # Apply the same time filter as the rest of the page
    _oa_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback)
    _oa_played = pd.to_datetime(_all_club_games["played_at"], errors="coerce")
    if _oa_played.dt.tz is not None:
        _oa_played = _oa_played.dt.tz_localize(None)
    _all_club_games = _all_club_games[_oa_played >= _oa_cutoff].copy()

    # Apply the same player filter
    _all_club_games = _all_club_games[
        _all_club_games["player"].isin([p.lower() for p in active_players])
    ]

    _opening_metrics_df = _oa_service.opening_metrics_table(_all_club_games)

    if not _opening_metrics_df.empty:
        # Build a context label for the chart title
        _player_label = (
            ", ".join(sorted(active_players))
            if active_players != all_members
            else "All Members"
        )
        _oa_title = f"Most Common Openings — {selected_label} · {_player_label}"

        _oa_fig = opening_wins_losses_bar(_opening_metrics_df)
        _oa_fig.update_layout(title_text=_oa_title)
        st.plotly_chart(_oa_fig, width='stretch', config={"displaylogo": False})

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
# NOTE: this section is intentionally NOT filtered by timeframe or player —
# it always shows the all-time best 10 games in the database.

st.subheader("🏆 Best Club Games — All Time")
st.caption(
    "The 10 best games ever played by the club, ranked by lowest combined ACPL (all time, "
    "unaffected by the timeframe or player filters above). "
    "Games played in the last 7 days are marked New."
)

ever_df = _service.get_best_all_time_games_by_acpl(limit=10)
if ever_df.empty:
    st.info("No analysed games found.")
else:
    st.html(_acpl_table_html(ever_df, highlight_recent=True))
