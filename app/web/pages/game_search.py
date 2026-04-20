"""Game Search page — AI-powered and keyword search with board preview."""

from __future__ import annotations

import io

import chess.pgn
import chess.svg
import json
import pandas as pd
from sqlalchemy import select
import streamlit as st

from app.web.components.auth import require_auth
from app.services.game_search_service import (
    SearchPlanError,
    execute_sql_search,
    generate_search_plan,
    get_anthropic_model,
    is_anthropic_available,
    keyword_game_search,
)
from app.storage.database import get_session
from app.storage.models import Game
from app.services.opening_book import opening_at_each_ply
from app.web.components.html_embed import render_html_iframe

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATE_COLUMN_CANDIDATES = ("played_at", "date", "game_date", "end_time", "start_time")


def _ensure_pgn(df: pd.DataFrame) -> pd.DataFrame:
    """Fill in pgn column from DB where missing."""
    if "game_id" not in df.columns:
        return df
    working = df.copy()
    if "pgn" not in working.columns:
        working["pgn"] = ""

    missing_mask = working["pgn"].fillna("").astype(str).str.strip() == ""
    missing_ids = working.loc[missing_mask, "game_id"].dropna().unique().tolist()
    if not missing_ids:
        return working

    with get_session() as session:
        rows = session.execute(
            select(Game.id, Game.pgn).where(Game.id.in_([str(g) for g in missing_ids]))
        ).all()
    db_map = {r.id: (r.pgn or "") for r in rows}

    for idx in working.index:
        if missing_mask.at[idx]:
            working.at[idx, "pgn"] = db_map.get(working.at[idx, "game_id"], "")

    return working


def _board_animation_html(pgn_text: str, max_ply: int | None = None, interval_ms: int = 700) -> str:
    """Return self-contained HTML that animates a game frame by frame."""
    pgn_text = str(pgn_text or "").strip()
    if not pgn_text:
        return ""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return ""
    board = game.board()
    frames: list[str] = [chess.svg.board(board, size=360)]  # starting position
    last_move = None
    total_plies = 0
    for i, move in enumerate(game.mainline_moves(), start=1):
        last_move = move
        board.push(move)
        frames.append(chess.svg.board(board, lastmove=last_move, size=360))
        total_plies = i
        if max_ply is not None and i >= max_ply:
            break
    if len(frames) <= 1:
        return frames[0] if frames else ""

    # Get opening names for each ply from the Lichess book.
    book_depth = max_ply if max_ply is not None else max(total_plies, 1)
    ply_names = opening_at_each_ply(pgn_text, max_ply=book_depth)
    # Pad to match frame count if needed.
    while len(ply_names) < len(frames):
        ply_names.append(ply_names[-1] if ply_names else ("", "Starting Position"))

    frames_json = json.dumps(frames)
    labels_json = json.dumps([f"{eco} {name}".strip() for eco, name in ply_names])
    total = len(frames)
    return f"""
<style>
  #chess-anim {{ width: 360px; font-family: sans-serif; }}
  #board-frame svg {{ display: block; }}
  #anim-controls {{ margin-top: 8px; display: flex; gap: 8px; align-items: center; }}
  #btn-pp {{ padding: 3px 12px; cursor: pointer; font-size: 14px; }}
  #frame-label {{ font-size: 12px; color: #555; }}
  #anim-scrubber {{ flex: 1; cursor: pointer; }}
  #opening-label {{ margin-top: 4px; font-size: 13px; font-weight: 600; color: #333; min-height: 20px; }}
</style>
<div id="chess-anim">
  <div id="board-frame"></div>
  <div id="opening-label"></div>
  <div id="anim-controls">
    <button id="btn-pp" onclick="togglePlay()">&#9646;&#9646; Pause</button>
    <input id="anim-scrubber" type="range" min="0" max="{total - 1}" value="0"
           oninput="scrub(this.value)" />
    <span id="frame-label">Start</span>
  </div>
</div>
<script>
  const frames = {frames_json};
  const labels = {labels_json};
  let idx = 0, playing = true;
  let timer = setInterval(advance, {interval_ms});

  function render() {{
    document.getElementById('board-frame').innerHTML = frames[idx];
    document.getElementById('anim-scrubber').value = idx;
    document.getElementById('frame-label').textContent = idx === 0 ? 'Start' : 'Ply ' + idx;
    document.getElementById('opening-label').textContent = labels[idx] || '';
  }}

  function advance() {{
    idx = (idx + 1) % frames.length;
    render();
  }}

  function scrub(val) {{
    idx = parseInt(val);
    render();
  }}

  function togglePlay() {{
    playing = !playing;
    const btn = document.getElementById('btn-pp');
    if (playing) {{
      timer = setInterval(advance, {interval_ms});
      btn.innerHTML = '&#9646;&#9646; Pause';
    }} else {{
      clearInterval(timer);
      btn.innerHTML = '&#9654; Play';
    }}
  }}

  render();
</script>
"""


# ---------------------------------------------------------------------------
# Render results with board preview
# ---------------------------------------------------------------------------

def _render_results(results_df: pd.DataFrame) -> None:
    if results_df.empty:
        st.info("No games matched.")
        return

    enriched = _ensure_pgn(results_df)

    # Prepare display values.
    table_df = enriched.copy()
    if "played_at" in table_df.columns:
        played_dt = pd.to_datetime(table_df["played_at"], errors="coerce")
        table_df["played_at"] = played_dt.dt.strftime("%Y-%m-%d").fillna(table_df["played_at"].astype(str))

    st.markdown("---")

    # Two-column layout: results list (left, wider) + board preview (right)
    table_col, board_col = st.columns([2, 1])

    selected_row_idx = st.session_state.get("search_preview_idx")
    if selected_row_idx is not None and (
        selected_row_idx < 0 or selected_row_idx >= len(enriched)
    ):
        selected_row_idx = None

    with table_col:
        st.markdown("### Results")
        st.caption(f"Showing {len(enriched)} games. Select a row to preview.")

        date_col = next((c for c in DATE_COLUMN_CANDIDATES if c in table_df.columns), None)
        # Add a clickable link column for each game's analysis page.
        if "game_id" in table_df.columns:
            table_df["analysis"] = table_df["game_id"].apply(
                lambda gid: f"/game-analysis?game_id={gid}" if pd.notna(gid) and str(gid).strip() else None
            )

        preferred_order = [
            "analysis",
            "played_at",
            "date",
            "game_date",
            "end_time",
            "start_time",
            "white_username",
            "black_username",
            "player",
            "opponent",
            "color",
            "lichess_opening",
            "opening",
            "stockfish_cp",
        ]
        display_cols = [c for c in preferred_order if c in table_df.columns]
        if date_col and date_col in display_cols:
            display_cols.remove(date_col)
            display_cols.insert(0, date_col)
        if not display_cols:
            display_cols = [
                c for c in table_df.columns
                if c not in {"pgn", "game_id", "result", "result_pgn", "time_control", "analysis"}
            ]

        column_config = {
            col: st.column_config.Column(col.replace("_", " ").title()) for col in display_cols
        }
        if "analysis" in display_cols:
            column_config["analysis"] = st.column_config.LinkColumn(
                "Analysis", display_text="Open"
            )
        table_event = st.dataframe(
            table_df[display_cols],
            width='stretch',
            height=560,
            hide_index=True,
            column_config=column_config,
            on_select="rerun",
            selection_mode="single-row",
            key="results_table",
        )
        if table_event and table_event.selection and table_event.selection.rows:
            selected_row_idx = table_event.selection.rows[0]
            st.session_state["search_preview_idx"] = selected_row_idx

    with board_col:
        st.markdown("### Board Preview")
        if selected_row_idx is not None and selected_row_idx < len(enriched):
            row = enriched.iloc[selected_row_idx]
            pgn_text = str(row.get("pgn", ""))

            # Show game info
            opening = str(row.get("lichess_opening", row.get("opening", "")))
            white = str(row.get("white_username", ""))
            black = str(row.get("black_username", ""))
            result = str(row.get("result_pgn", row.get("result", "")))
            if opening:
                st.caption(f"**{opening}**")
            st.caption(f"{white} vs {black} — {result}")

            game_id = row.get("game_id", "")
            can_open = pd.notna(game_id) and str(game_id).strip() != ""
            if st.button(
                "Open in Analysis",
                key="search_open_preview",
                width='content',
                disabled=not can_open,
            ):
                st.session_state["pending_game_id"] = str(game_id)
                st.switch_page("app/web/pages/game_analysis.py")

            anim_html = _board_animation_html(pgn_text, max_ply=None, interval_ms=700)
            if anim_html:
                render_html_iframe(anim_html, height=430)
            else:
                st.info("No PGN available for this game.")
        else:
            st.info("Select a row to preview the full game.")


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

require_auth()

st.title("Game Search")
st.caption("Search your games and preview openings.")

anthropic_available = is_anthropic_available()
pending_opening_search = str(st.session_state.get("pending_opening_search", "")).strip()
if anthropic_available:
    default_search_mode = 1 if pending_opening_search else 0
    search_mode = st.radio(
        "Search mode",
        ["AI-Powered Search", "Keyword Search"],
        horizontal=True,
        index=default_search_mode,
        key="game_search_mode",
    )
else:
    st.warning("ANTHROPIC_API_KEY not configured. Keyword search only.")
    search_mode = "Keyword Search"

# ---- AI-Powered Search ----
if search_mode == "AI-Powered Search":
    st.markdown("### AI-Powered Search")
    st.caption("Describe the games you want. The app converts it into validated SQL.")

    with st.form("ai_search_form", clear_on_submit=False):
        query = st.text_input(
            "Search Query",
            key="ai_search_query",
            placeholder="e.g., last 30 days losses as black in sicilian openings",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Search", width='stretch')

    if submitted and query.strip():
        try:
            with st.spinner("Generating and executing SQL..."):
                plan = generate_search_plan(query)
                rows = execute_sql_search(plan.sql_query)
            st.session_state["ai_results"] = rows
            st.session_state["ai_sql"] = plan.sql_query
            st.session_state["ai_reasoning"] = plan.reasoning
            st.session_state.pop("ai_error", None)
        except SearchPlanError as exc:
            st.session_state["ai_error"] = str(exc)
            st.session_state["ai_results"] = []
            st.session_state["ai_sql"] = exc.candidate_sql
            st.session_state["ai_reasoning"] = exc.reasoning
        except Exception as exc:
            st.session_state["ai_error"] = str(exc)
            st.session_state["ai_results"] = []

    if st.session_state.get("ai_reasoning"):
        st.caption(f"Reasoning: {st.session_state['ai_reasoning']}")
    if st.session_state.get("ai_sql"):
        st.code(st.session_state["ai_sql"], language="sql")
    if st.session_state.get("ai_error"):
        st.error(st.session_state["ai_error"])

    saved_rows = st.session_state.get("ai_results", [])
    if saved_rows:
        df = pd.DataFrame(saved_rows)
        if "id" in df.columns:
            df = df.rename(columns={"id": "game_id"})
        _render_results(df)
    elif st.session_state.get("ai_search_query") and not st.session_state.get("ai_error"):
        st.info("No games matched that query.")

# ---- Keyword Search ----
else:
    st.markdown("### Keyword Search")

    auto_opening = str(st.session_state.pop("pending_opening_search", "")).strip()
    if auto_opening:
        st.session_state["kw_search_query"] = auto_opening
        result_df = keyword_game_search(auto_opening, limit=200)
        st.session_state["kw_results"] = result_df.to_dict(orient="records")
        st.session_state.pop("kw_error", None)
        st.caption(f"Applied opening filter from Opening Analysis: {auto_opening}")

    with st.form("keyword_search_form", clear_on_submit=False):
        keyword = st.text_input(
            "Keyword",
            key="kw_search_query",
            placeholder="e.g., sicilian, 15+10, win, opponent name",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Search", width='stretch')

    if submitted and keyword.strip():
        result_df = keyword_game_search(keyword.strip(), limit=200)
        st.session_state["kw_results"] = result_df.to_dict(orient="records")
        st.session_state.pop("kw_error", None)

    saved_kw = st.session_state.get("kw_results", [])
    if saved_kw:
        _render_results(pd.DataFrame(saved_kw))
    elif st.session_state.get("kw_search_query") and not st.session_state.get("kw_error"):
        st.info("No games matched that keyword.")
