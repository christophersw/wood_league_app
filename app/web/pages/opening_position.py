"""Opening Position detail page.

URL: /opening-position?opening_id=<int>

Shows a static board of the opening position plus:
  - Timeframe + player filters
  - Opening share pie (this opening vs all others)
  - Per-player W/D/L grouped bar
  - Per-player average accuracy horizontal bar
  - Continuation Sankey (3 moves beyond the opening)
  - Frequency-over-time line chart
  - Filterable game table
"""

from __future__ import annotations

import base64
from html import escape

import chess
import chess.svg
import pandas as pd
import streamlit as st
import streamlit.components.v1 as _components
from app.services.opening_position_service import OpeningPositionService
from app.services.welcome_service import WelcomeService
from app.web.components.auth import require_auth
from app.web.components.html_embed import render_html_iframe
from app.web.components.charts import (
    opening_frequency_trend,
    opening_player_accuracy_bar,
    opening_share_pie,
)

require_auth()

_svc = OpeningPositionService()
_wsvc = WelcomeService()

# ── Board colours (Du Bois palette) ──────────────────────────────────────────
_BOARD_COLORS = {
    "square light": "#F2E6D0",
    "square dark": "#4A8C62",
    "margin": "#1A1A1A",
    "coord": "#D4A843",
}

# ── Table CSS (reuse welcome page style) ─────────────────────────────────────
_TABLE_STYLE = """
<style>
.op-table {
  width: 100%;
  border-collapse: collapse;
  border: 2px solid #1A1A1A;
  font-family: 'DM Mono', monospace;
}
.op-table thead tr { background: #1A3A2A; }
.op-table thead th {
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
.op-table tbody tr:nth-child(odd)  { background: #F9F3E8; }
.op-table tbody tr:nth-child(even) { background: #EFE4CC; }
.op-table tbody tr { border-bottom: 1px solid #D4C4A0; }
.op-table td {
  padding: 0.42rem 0.6rem;
  vertical-align: middle;
  white-space: nowrap;
  font-size: 0.8rem;
}
.op-player { font-family: 'EB Garamond', Georgia, serif; font-size: 0.95rem; color: #1A1A1A; }
.op-acc   { font-weight: 700; color: #1A3A2A; }
.op-win   { color: #4A6554; font-weight: 600; }
.op-loss  { color: #B53541; font-weight: 600; }
.op-draw  { color: #4A6E8A; font-weight: 600; }
.op-date  { font-size: 0.68rem; color: #8B3A2A; }
.op-open {
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
.op-open:hover { background: #1A1A1A; color: #F2E6D0; text-decoration: none; }
</style>
"""

_ENGINE_CSS = """<style>
.dub { font-family: 'DM Mono', 'Courier New', monospace; color: #1A1A1A; margin-bottom: 1.6rem; }
.dub-head {
  border-top: 3px solid #1A1A1A; border-bottom: 1.5px solid #1A1A1A;
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px 0 4px; margin-bottom: 16px;
}
.dub-title { font-family: 'Playfair Display SC', Georgia, serif; font-size: 0.92rem; letter-spacing: 0.07em; color: #1A3A2A; }
.dub-meta { font-size: 0.60rem; letter-spacing: 0.06em; color: #8B3A2A; text-transform: uppercase; }
.dub-row { display: grid; grid-template-columns: 140px 1fr 52px; align-items: center; gap: 0 8px; margin-bottom: 5px; }
.dub-player-lbl { font-size: 0.70rem; letter-spacing: 0.03em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #1A1A1A; }
.dub-chess { color: #8B3A2A; margin-right: 3px; }
.dub-val { font-size: 0.78rem; font-weight: 700; text-align: right; white-space: nowrap; color: #1A1A1A; }
.dub-stack { height: 26px; display: flex; border: 1.5px solid #1A1A1A; overflow: hidden; }
.dub-seg { display: flex; align-items: center; justify-content: center; font-size: 0.60rem; font-weight: 700; overflow: hidden; white-space: nowrap; color: #F2E6D0; }
.dub-win  { background: #1A3A2A; }
.dub-draw { background: #8B3A2A; }
.dub-loss { background: #B53541; }
</style>"""


def _wdl_html(stats_df: "pd.DataFrame") -> str:
    def _seg(cls: str, pct: float, lbl: str) -> str:
        txt = lbl if pct >= 9 else ""
        return f'<div class="dub-seg {cls}" style="flex:{pct:.1f}">{escape(txt)}</div>'

    rows = []
    for _, row in stats_df.iterrows():
        win = float(row["win_pct"])
        draw = float(row["draw_pct"])
        loss = float(row["loss_pct"])
        total = int(row["games"])
        segs = (
            _seg("dub-win", win, f"W {win:.0f}%")
            + _seg("dub-draw", draw, f"D {draw:.0f}%")
            + _seg("dub-loss", loss, f"L {loss:.0f}%")
        )
        rows.append(
            f'<div class="dub-row">'
            f'<div class="dub-player-lbl">{escape(str(row["player"]))}</div>'
            f'<div class="dub-stack">{segs}</div>'
            f'<div class="dub-val" style="font-size:0.65rem;color:#1A1A1A">{total}</div>'
            f'</div>'
        )

    head = (
        '<div class="dub">'
        '<div class="dub-head">'
        '<span class="dub-title">Results by Player</span>'
        '<span class="dub-meta">W / D / L</span>'
        '</div>'
    )
    return head + "".join(rows) + "</div>"


def _opening_tree_html(tree_ctx: dict, opening_epd: str) -> tuple[str, int]:
    """Return (full_html_doc, height_px) for _components.html().

    st.components.v1.html() uses a srcdoc iframe and renders SVG reliably.
    Navigation uses window.parent.postMessage() — always permitted from
    sandboxed iframes — caught by the st.html() listener injected separately
    into the main page, which then sets window.location.href freely.
    """
    lineage = tree_ctx.get("lineage", [])
    children = tree_ctx.get("children", [])

    if not lineage:
        return "", 0

    # ── Layout constants ─────────────────────────────────────────────────────
    NW, NH = 248, 110      # node width, height (wider/taller to fit board preview)
    BOARD_SZ = 94          # chess board preview pixel size
    H_GAP = 54             # horizontal gap between lineage nodes
    V_GAP = 14             # vertical gap between child nodes
    FORK_GAP = 72          # gap from current-node right edge to children col
    LABEL_H = 22           # label row above nodes
    PAD = 22               # outer padding

    # ── Board preview helper ─────────────────────────────────────────────────
    def _board_img_href(fen: str | None) -> str | None:
        if not fen:
            return None
        try:
            board = chess.Board(fen)
            svg_str = chess.svg.board(board, size=BOARD_SZ, colors=_BOARD_COLORS, coordinates=False)
            encoded = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
            return f"data:image/svg+xml;base64,{encoded}"
        except Exception:
            return None

    n_lin = len(lineage)
    n_ch = len(children)

    ch_col_h = max(0, n_ch * NH + max(0, n_ch - 1) * V_GAP)
    content_h = max(NH, ch_col_h)
    canvas_h = LABEL_H + PAD + content_h + PAD

    lin_top = LABEL_H + PAD + (content_h - NH) / 2
    lin_cy = lin_top + NH / 2
    ch_top = LABEL_H + PAD + (content_h - ch_col_h) / 2

    lin_xs = [PAD + i * (NW + H_GAP) for i in range(n_lin)]
    cur_right = lin_xs[-1] + NW
    ch_x = cur_right + FORK_GAP
    canvas_w = (ch_x + NW + PAD) if n_ch > 0 else (cur_right + PAD)

    # ── Edge weight helpers ──────────────────────────────────────────────────
    edge_gs = [lineage[i]["games"] for i in range(1, n_lin)] + [c["games"] for c in children]
    raw_max = max(edge_gs) if edge_gs else 0
    max_g = raw_max if raw_max > 0 else 1   # guard against all-zero (no games in scope)

    def _sw(g: int) -> float:
        return max(1.5, min(10.0, 1.5 + (g / max_g) * 8.5))

    def _so(g: int) -> float:
        return max(0.2, min(0.95, 0.2 + (g / max_g) * 0.75))

    # ── Text helpers ─────────────────────────────────────────────────────────
    def _wrap(text: str, max_chars: int = 20) -> list[str]:
        words, lines, cur = text.split(), [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            lines.append(cur)
        return lines[:2]

    # ── Build SVG ────────────────────────────────────────────────────────────
    p: list[str] = []

    # Full HTML document required for st.components.v1.html() srcdoc iframe.
    # Navigation uses postMessage to parent (sandbox allows it); the main page
    # listens with st.html() and sets window.location.href freely.
    p.append(
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        'body{{margin:0;background:#F9F3E8;overflow-x:auto;overflow-y:hidden}}'
        '.ot-node rect{{transition:filter .12s ease}}'
        '.ot-node:hover rect{{filter:brightness(0.88) drop-shadow(0 2px 8px rgba(26,26,26,.28))}}'
        '.ot-node{{cursor:pointer}}'
        '</style></head><body>'
    )
    p.append(
        f'<svg width="{canvas_w:.0f}" height="{canvas_h:.0f}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block">'
    )
    # Background
    p.append(f'<rect width="{canvas_w:.0f}" height="{canvas_h:.0f}" fill="#F9F3E8"/>')

    # Section labels
    lin_lbl_cx = lin_xs[0] + (lin_xs[-1] + NW - lin_xs[0]) / 2
    p.append(
        f'<text x="{lin_lbl_cx:.0f}" y="14" text-anchor="middle" '
        f'font-family="monospace" font-size="9" letter-spacing="2" '
        f'fill="#8B3A2A" opacity="0.55" font-weight="600">LINEAGE</text>'
    )
    if n_ch > 0:
        p.append(
            f'<text x="{ch_x + NW / 2:.0f}" y="14" text-anchor="middle" '
            f'font-family="monospace" font-size="9" letter-spacing="2" '
            f'fill="#1A3A2A" opacity="0.55" font-weight="600">CONTINUATIONS</text>'
        )

    # Lineage arrows — width encodes frequency, no arrowheads
    for i in range(n_lin - 1):
        x1, x2 = lin_xs[i] + NW, lin_xs[i + 1]
        g = lineage[i + 1]["games"]
        p.append(
            f'<line x1="{x1:.1f}" y1="{lin_cy:.1f}" '
            f'x2="{x2:.1f}" y2="{lin_cy:.1f}" '
            f'stroke="#D4A843" stroke-width="{_sw(g):.1f}" '
            f'stroke-opacity="{_so(g):.2f}" stroke-linecap="round"/>'
        )

    # Child bezier connectors — width encodes frequency, no arrowheads
    for j, child in enumerate(children):
        cy2 = ch_top + j * (NH + V_GAP) + NH / 2
        g = child["games"]
        cp1x = cur_right + (ch_x - cur_right) * 0.4
        cp2x = cur_right + (ch_x - cur_right) * 0.6
        p.append(
            f'<path d="M{cur_right:.1f},{lin_cy:.1f} '
            f'C{cp1x:.1f},{lin_cy:.1f} {cp2x:.1f},{cy2:.1f} {ch_x:.1f},{cy2:.1f}" '
            f'stroke="#1A3A2A" stroke-width="{_sw(g):.1f}" '
            f'stroke-opacity="{_so(g):.2f}" fill="none" stroke-linecap="round"/>'
        )

    # Node renderer
    def _node(node: dict, x: float, y: float, *, is_current: bool = False, is_child: bool = False) -> None:
        oid = node.get("opening_id")
        eco = str(node.get("eco") or "").upper()
        raw_name = str(node.get("name") or "Unknown")
        games = int(node.get("games") or 0)
        fen = node.get("fen") or node.get("epd")
        name_lines = _wrap(raw_name)

        if is_current:
            fill, stroke, sw_b = "#1A3A2A", "#D4A843", "3"
            ec, nc, gc = "#D4A843", "#F2E6D0", "#7EAD8A"
            board_border = "#D4A843"
        elif is_child:
            fill, stroke, sw_b = "#EFE4CC", "#1A1A1A", "1.5"
            ec, nc, gc = "#8B3A2A", "#1A3A2A", "#5A5A5A"
            board_border = "#1A1A1A"
        else:
            fill, stroke, sw_b = "#F2E6D0", "#1A1A1A", "1.5"
            ec, nc, gc = "#8B3A2A", "#1A3A2A", "#5A5A5A"
            board_border = "#1A1A1A"

        if oid:
            url = f"/opening-position?opening_id={oid}"
            onclick = f"window.parent.postMessage({{url:'{url}'}}, '*')"
            open_tag = f'<g class="ot-node" onclick="{onclick}" style="cursor:pointer">'
            close_tag = '</g>'
        else:
            open_tag = '<g class="ot-node">'
            close_tag = '</g>'

        # Board preview: right-aligned, vertically centred, with 1px border rect
        bx = x + NW - BOARD_SZ - 6
        by = y + (NH - BOARD_SZ) / 2
        img_href = _board_img_href(fen)

        p.append(open_tag)
        p.append(
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{NW}" height="{NH}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw_b}"/>'
        )
        # Board preview
        if img_href:
            p.append(
                f'<rect x="{bx:.0f}" y="{by:.0f}" width="{BOARD_SZ}" height="{BOARD_SZ}" '
                f'fill="none" stroke="{board_border}" stroke-width="1" opacity="0.4"/>'
            )
            p.append(
                f'<image x="{bx:.0f}" y="{by:.0f}" width="{BOARD_SZ}" height="{BOARD_SZ}" '
                f'href="{img_href}" preserveAspectRatio="xMidYMid meet"/>'
            )
        # ECO code
        p.append(
            f'<text x="{x + 10:.0f}" y="{y + 16:.0f}" '
            f'font-family="monospace" font-size="9" letter-spacing="1.5" '
            f'font-weight="600" fill="{ec}">{escape(eco)}</text>'
        )
        # Name (up to 2 lines)
        for k, line in enumerate(name_lines):
            p.append(
                f'<text x="{x + 10:.0f}" y="{y + 32 + k * 16:.0f}" '
                f'font-family="Georgia,serif" font-size="12" fill="{nc}">{escape(line)}</text>'
            )
        # Game count
        p.append(
            f'<text x="{x + 10:.0f}" y="{y + NH - 13:.0f}" '
            f'font-family="monospace" font-size="9" fill="{gc}">{games} games</text>'
        )
        p.append(close_tag)

    for i, node in enumerate(lineage):
        _node(node, lin_xs[i], lin_top, is_current=(node.get("epd") == opening_epd))

    for j, child in enumerate(children):
        _node(child, ch_x, ch_top + j * (NH + V_GAP), is_child=True)

    p.append('</svg></body></html>')
    return "".join(p), int(canvas_h) + 6


_TIMEFRAMES = {
    "Last 30 days": 30,
    "Last 90 days": 90,
    "Last 6 months": 180,
    "Last year": 365,
    "All time": None,
}

# ── Opening lookup ────────────────────────────────────────────────────────────

opening_id_str = st.query_params.get("opening_id", "")

if not opening_id_str:
    st.title("Opening Position")
    st.info("No opening selected. Search for an opening below.")

    query = st.text_input("Search openings", placeholder="e.g. Italian Game, Sicilian…")
    if query:
        results = _svc.search_openings(query, limit=20)
        if results:
            for r in results:
                col_a, col_b = st.columns([5, 1])
                col_a.markdown(f"**{r['eco']}** {r['name']}")
                if col_b.button("View", key=f"view_{r['id']}"):
                    st.query_params["opening_id"] = str(r["id"])
                    st.rerun()
        else:
            st.warning("No openings found.")
    st.stop()

try:
    opening_id = int(opening_id_str)
except ValueError:
    st.error("Invalid opening_id.")
    st.stop()

opening = _svc.get_opening(opening_id)
if opening is None:
    st.error(f"Opening #{opening_id} not found.")
    st.stop()

# ── Page header ───────────────────────────────────────────────────────────────

st.title(opening["name"])
st.caption(f"{opening['eco']}  ·  {opening['ply_depth']} half-moves  ·  {opening['pgn']}")

# ── Filters ───────────────────────────────────────────────────────────────────

all_members = _wsvc.get_club_member_names()
col_tf, col_pl = st.columns([1, 2])
with col_tf:
    selected_label = st.selectbox(
        "Timeframe",
        options=list(_TIMEFRAMES.keys()),
        index=1,
        label_visibility="collapsed",
        key="op_timeframe",
    )
with col_pl:
    selected_players = st.multiselect(
        "Players",
        options=all_members,
        default=all_members,
        label_visibility="collapsed",
        placeholder="All members",
        key="op_players",
    )

lookback = _TIMEFRAMES[selected_label]
active_players = selected_players if selected_players else all_members
scope_players_label = (
    "All members"
    if len(active_players) == len(all_members)
    else (
        ", ".join(active_players)
        if len(active_players) <= 4
        else f"{len(active_players)} selected players"
    )
)
scope_label = f"{selected_label} · Players: {scope_players_label}"

# ── Data load ─────────────────────────────────────────────────────────────────

games_df = _svc.get_games(opening, lookback_days=lookback, players=active_players)

# ── Board + opening share (side by side) ──────────────────────────────────────

board_col, pie_col = st.columns([1, 1])

with board_col:
    st.subheader("Opening Position")
    board = chess.Board(opening["final_fen"])
    svg = chess.svg.board(
        board,
        size=340,
        colors=_BOARD_COLORS,
        coordinates=True,
    )
    board_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ margin: 0; background: transparent; display: flex; justify-content: center; }}
  svg {{ display: block; }}
</style></head>
<body>{svg}</body></html>"""
    render_html_iframe(board_html, height=360)

with pie_col:
    st.subheader("Opening Position Share")
    st.caption(f"Scope: {scope_label}")
    share_df = _svc.opening_share(
        opening,
        games_df,
        lookback_days=lookback,
        players=active_players,
    )
    if share_df.empty or share_df["games"].sum() == 0:
        st.info("No game data available for this period.")
    else:
        fig_pie = opening_share_pie(share_df, opening["name"], scope_label=scope_label)
        st.plotly_chart(fig_pie, width='stretch', config={"displaylogo": False})

st.divider()

# ── Opening tree (lineage + continuations) ───────────────────────────────────
# Rendered always — even when there are no games in scope, the tree structure
# is meaningful and arrows simply show at minimum weight.

st.subheader("Opening Tree Context")
st.caption(
    f"How this opening sits in the opening tree ({scope_label}). "
    "Arrow width reflects how many scoped games used each transition."
)

tree_ctx = _svc.opening_tree_context(
    opening,
    lookback_days=lookback,
    players=active_players,
    max_children=9,
)

lineage = tree_ctx.get("lineage", [])
children = tree_ctx.get("children", [])
selected_games = int(tree_ctx.get("selected_games", 0))
total_scoped_games = int(tree_ctx.get("total_scoped_games", 0))

if not lineage:
    st.info("No lineage could be determined for this opening.")
else:
    # Listener injected into the main Streamlit page DOM (not sandboxed).
    # Receives postMessage from the component iframe and navigates freely.
    st.html(
        '<script>'
        'window.addEventListener("message",function(e){'
        'if(e.data&&e.data.url&&e.data.url.startsWith("/opening-position"))'
        'window.location.href=e.data.url;'
        '});'
        '</script>',
        unsafe_allow_javascript=True,
    )
    _tree_html, _tree_h = _opening_tree_html(tree_ctx, opening["epd"])
    _components.html(_tree_html, height=_tree_h + 20, scrolling=True)
    _pct_note = (
        f" ({selected_games / total_scoped_games * 100.0:.1f}% of scoped games)"
        if total_scoped_games else ""
    )
    st.caption(
        f"Current opening highlighted in dark green. {selected_games} scoped games reached this node{_pct_note}. "
        "Nodes link to their opening page."
    )

st.divider()

if games_df.empty:
    st.info(f"No games found with this opening in the selected period.")
    st.stop()

total_games = games_df["game_id"].nunique()
st.caption(
    f"**{total_games}** club games played through this opening "
    f"in the {selected_label.lower()}."
)

# ── Per-player stats ──────────────────────────────────────────────────────────

stats_df = _svc.player_stats(games_df)

wdl_col, acc_col = st.columns(2)

with wdl_col:
    if stats_df.empty:
        st.info("No player stats available.")
    else:
        st.html(_ENGINE_CSS + _wdl_html(stats_df))

with acc_col:
    stats_with_acc = stats_df.dropna(subset=["avg_accuracy"])
    if stats_with_acc.empty:
        st.info("No analyzed games with accuracy data in the current scope.")
    else:
        fig_acc = opening_player_accuracy_bar(
            stats_df,
            opening["name"],
            scope_label=scope_label,
        )
        st.plotly_chart(fig_acc, width='stretch', config={"displaylogo": False})

# ── Player stats summary cards ────────────────────────────────────────────────

if not stats_df.empty:
    card_cols = st.columns(len(stats_df))
    for col, (_, row) in zip(card_cols, stats_df.iterrows()):
        with col:
            st.markdown(
                f"<div style='font-family:\"DM Mono\",monospace;font-size:0.7rem;"
                f"letter-spacing:0.08em;text-transform:uppercase;color:#8B3A2A'>"
                f"{escape(row['player'])}</div>"
                f"<div style='font-family:\"EB Garamond\",Georgia,serif;font-size:1.5rem;"
                f"font-weight:600;color:#1A1A1A'>{int(row['games'])} games</div>"
                f"<div style='font-size:0.75rem;color:#4A6554'>W {row['wins']} "
                f"· D {row['draws']} · L {row['losses']}</div>"
                f"<div style='font-size:0.75rem;color:#5A5A5A'>"
                f"{'♙' if row['as_white'] >= row['as_black'] else '♟'} "
                f"White {row['as_white']} · Black {row['as_black']}</div>",
                unsafe_allow_html=True,
            )

st.divider()

# ── Frequency over time ───────────────────────────────────────────────────────

st.subheader("How Often is This Opening Played?")
st.caption(
    "Dashed line is monthly total unique games. Solid lines are per-player entries in the same scope."
)
freq_df = _svc.frequency_over_time(games_df)
if not freq_df.empty:
    fig_freq = opening_frequency_trend(freq_df, opening["name"], scope_label=scope_label)
    st.plotly_chart(fig_freq, width='stretch', config={"displaylogo": False})
else:
    st.info("Not enough data for a trend chart.")

st.divider()

# ── Game table ────────────────────────────────────────────────────────────────

st.subheader("Games")

# Filters above the table
tcol1, tcol2, tcol3 = st.columns(3)
with tcol1:
    _tbl_player = st.selectbox(
        "Filter by player",
        options=["All"] + sorted(games_df["club_player"].unique().tolist()),
        index=0,
        key="tbl_player",
    )
with tcol2:
    _tbl_color = st.selectbox(
        "Color",
        options=["All", "White", "Black"],
        index=0,
        key="tbl_color",
    )
with tcol3:
    _tbl_result = st.selectbox(
        "Result",
        options=["All", "Win", "Draw", "Loss"],
        index=0,
        key="tbl_result",
    )

# Apply table filters to a deduplicated game view
_tbl_df = games_df.copy()
if _tbl_player != "All":
    _tbl_df = _tbl_df[_tbl_df["club_player"] == _tbl_player]
if _tbl_color != "All":
    _tbl_df = _tbl_df[_tbl_df["color"] == _tbl_color.lower()]
if _tbl_result != "All":
    _tbl_df = _tbl_df[_tbl_df["result"] == _tbl_result]

# One row per game in the table to align with headline game counts.
_tbl_df = _tbl_df.drop_duplicates(subset=["game_id"], keep="first")
_tbl_df = _tbl_df.sort_values("played_at", ascending=False)

if _tbl_df.empty:
    st.info("No games match the selected filters.")
else:
    def _fmt_acc(v: float | None) -> str:
        return f"{v:.1f}%" if v is not None else "—"

    def _result_class(r: str) -> str:
        return {"Win": "op-win", "Loss": "op-loss", "Draw": "op-draw"}.get(r, "")

    _rows_html = []
    for _, row in _tbl_df.iterrows():
        date_str = row["played_at"].strftime("%d %b %Y") if hasattr(row["played_at"], "strftime") else str(row["played_at"])[:10]
        color_sym = "♙" if row["color"] == "white" else "♟"
        opponent = row["black_username"] if row["color"] == "white" else row["white_username"]
        p_acc = _fmt_acc(
            row["white_accuracy"] if row["color"] == "white" else row["black_accuracy"]
        )
        p_acpl = f"{row['white_acpl']:.1f}" if row["color"] == "white" and row["white_acpl"] is not None else (
            f"{row['black_acpl']:.1f}" if row["color"] == "black" and row["black_acpl"] is not None else "—"
        )
        link = escape(f"/game-analysis?game_id={row['game_id']}")
        result_cls = _result_class(row["result"])
        _rows_html.append(
            f"<tr>"
            f'<td class="op-date">{escape(date_str)}</td>'
            f'<td class="op-player">{escape(row["club_player"])}</td>'
            f'<td>{color_sym}</td>'
            f'<td class="op-player">{escape(str(opponent))}</td>'
            f'<td class="{result_cls}">{escape(row["result"])}</td>'
            f'<td class="op-acc">{escape(p_acc)}</td>'
            f'<td class="op-acc">{escape(p_acpl)}</td>'
            f'<td><a class="op-open" href="{link}" target="_blank">Open</a></td>'
            f"</tr>"
        )

    st.html(
        _TABLE_STYLE
        + f"""<table class="op-table">
          <thead><tr>
            <th>Date</th><th>Player</th><th></th><th>Opponent</th>
            <th>Result</th><th>Accuracy</th><th>ACPL</th><th></th>
          </tr></thead>
          <tbody>{"".join(_rows_html)}</tbody>
        </table>"""
    )
    st.caption(f"{len(_tbl_df)} unique games shown.")
