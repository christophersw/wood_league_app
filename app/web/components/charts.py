import io
from datetime import datetime, timedelta

import chess.pgn
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ── Du Bois Palette — After the 1900 Paris Exposition plates ─────────────────
_GP = {
    "parchment": "#F2E6D0",  # warm cream — chart paper
    "linen":     "#E8D5B0",  # tan — secondary backgrounds
    "ebony":     "#1A1A1A",  # near-black — text
    "forest":    "#1A3A2A",  # deep forest — headings, sidebar
    "moss":      "#4A6554",  # Du Bois green — wins / positive
    "whisky":    "#D4A843",  # ochre-gold — primary accent
    "peat":      "#8B3A2A",  # brick-red-brown — losses / negative
    "smoke":     "#5A5A5A",  # neutral grey
    "gilt":      "#B8922A",  # deep gold — borders, highlights
    # move-quality reds — kept intentional but shifted to Du Bois crimson family
    "crimson":   "#B53541",  # Du Bois crimson — blunder
    "scarlet":   "#CE3A4A",  # mistake
    "rose":      "#E07B7B",  # inaccuracy
    # positives
    "brilliant": "#2C6B4A",  # brilliant move
    "steel":     "#4A6E8A",  # Du Bois steel blue — accent/draw
}

_GP_FONT  = "EB Garamond, Georgia, serif"
_GP_MONO  = "DM Mono, Courier New, monospace"
_GP_TITLE = "Playfair Display SC, Cormorant Garamond, Georgia, serif"

# Du Bois colorway: crimson → gold → green → steel blue → brick → pink → ochre → teal
_GP_COLORWAY = [
    "#B53541", "#D4A843", "#4A6554", "#4A6E8A",
    "#8B3A2A", "#E07B7B", "#C4933F", "#2C6B4A",
]


def _gp_layout(**overrides) -> dict:
    """Return a Plotly layout dict applying the Du Bois palette theme."""
    base: dict = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(242,230,208,0.5)",  # flat cream — no gradient
        font=dict(family=_GP_FONT, color=_GP["ebony"], size=13),
        title_font=dict(family=_GP_TITLE, size=16, color=_GP["forest"]),
        colorway=_GP_COLORWAY,
        xaxis=dict(
            gridcolor=_GP["linen"],
            gridwidth=1,
            linecolor=_GP["ebony"],
            linewidth=2,
            tickfont=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            title_font=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            zerolinecolor=_GP["ebony"],
            zerolinewidth=2,
        ),
        yaxis=dict(
            gridcolor=_GP["linen"],
            gridwidth=1,
            linecolor=_GP["ebony"],
            linewidth=2,
            tickfont=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            title_font=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            zerolinecolor=_GP["ebony"],
            zerolinewidth=2,
        ),
        legend=dict(
            bgcolor="rgba(242,230,208,0.9)",
            bordercolor=_GP["ebony"],
            borderwidth=1,
            font=dict(family=_GP_FONT, color=_GP["ebony"], size=12),
        ),
    )
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def elo_trend_chart(df: pd.DataFrame, selected_player: str):
    fig = px.line(
        df,
        x="date",
        y="rating",
        color="player",
        title="ELO Trend (Daily Games)",
        markers=False,
        color_discrete_sequence=_GP_COLORWAY,
    )
    fig.update_traces(opacity=0.35)
    fig.for_each_trace(
        lambda trace: trace.update(opacity=1.0, line=dict(width=3.5))
        if trace.name == selected_player
        else None
    )
    fig.update_layout(**_gp_layout(
        legend_title="Player",
        margin=dict(l=20, r=20, t=56, b=20),
    ))
    return fig


def opening_pie_chart(df: pd.DataFrame):
    fig = px.pie(
        df,
        names="opening",
        values="games",
        title="Recent Openings Distribution (Depth = 5 Ply)",
        color_discrete_sequence=_GP_COLORWAY,
    )
    fig.update_traces(
        textposition="inside",
        textinfo="percent+label",
        textfont=dict(family=_GP_MONO, size=11, color=_GP["parchment"]),
        marker=dict(line=dict(color=_GP["ebony"], width=2)),
    )
    fig.update_layout(**_gp_layout())
    return fig


def eval_timeline_chart(df: pd.DataFrame, selected_ply: int | None = None):
    fig = px.bar(df, x="ply", y="cp_eval", title="Engine Evaluation by Ply")

    if selected_ply is not None:
        colors = [
            _GP["whisky"] if int(p) != selected_ply else _GP["gilt"]
            for p in df["ply"].tolist()
        ]
        fig.update_traces(marker_color=colors, marker_line_color=_GP["ebony"], marker_line_width=1)
    else:
        fig.update_traces(marker_color=_GP["whisky"], marker_line_color=_GP["ebony"], marker_line_width=1)

    # Split background: warm cream above zero (white advantage), near-black below (black advantage)
    fig.add_hrect(y0=0, y1=2500,  fillcolor=_GP["parchment"], opacity=1.0, layer="below", line_width=0)
    fig.add_hrect(y0=-2500, y1=0, fillcolor="#1A1A1A", opacity=1.0, layer="below", line_width=0)

    fig.add_hline(y=0, line_dash="dot", line_color=_GP["smoke"])
    fig.update_layout(**_gp_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(title="Centipawns"),
        xaxis=dict(title="Ply"),
        clickmode="event+select",
    ))
    return fig


def opening_starburst_chart(df: pd.DataFrame, depth: int = 5):
    """Build a sunburst from opening ply data, with lichess opening labels on large segments."""
    if df.empty:
        return None

    depth = max(1, min(depth, 20))
    denorm_cols = [f"opening_ply_{i}" for i in range(1, depth + 1)]
    has_denorm = all(col in df.columns for col in denorm_cols)
    has_lichess = "lichess_opening" in df.columns

    # Collect per-game move sequences and lichess opening names.
    game_data: list[tuple[list[str], str]] = []
    for _, row in df.iterrows():
        plies: list[str] = []
        if has_denorm:
            for col in denorm_cols:
                val = row.get(col)
                if val is None:
                    break
                t = str(val).strip()
                if not t:
                    break
                plies.append(t)

        if not plies and "pgn" in df.columns:
            pgn = str(row.get("pgn") or "").strip()
            if pgn:
                game = chess.pgn.read_game(io.StringIO(pgn))
                if game is not None:
                    board = game.board()
                    for i, move in enumerate(game.mainline_moves(), 1):
                        plies.append(board.san(move))
                        board.push(move)
                        if i >= depth:
                            break

        if not plies:
            continue

        lichess = str(row.get("lichess_opening") or "").strip() if has_lichess else ""
        game_data.append((plies, lichess))

    if not game_data:
        return None

    # Build hierarchy nodes.
    nodes: dict[str, dict] = {}
    for plies, lichess in game_data:
        for d in range(1, min(len(plies), depth) + 1):
            nid = "/".join(plies[:d])
            pid = "/".join(plies[:d - 1]) if d > 1 else ""
            if nid not in nodes:
                nodes[nid] = {
                    "label": plies[d - 1],
                    "parent": pid,
                    "value": 0,
                    "lichess_names": [],
                }
            nodes[nid]["value"] += 1
            if lichess:
                nodes[nid]["lichess_names"].append(lichess)

    total = sum(n["value"] for n in nodes.values() if n["parent"] == "")

    ids, labels_arr, parents_arr, values_arr = [], [], [], []
    texts, hovertexts, customdata_arr = [], [], []

    for nid in sorted(nodes):
        n = nodes[nid]
        ids.append(nid)
        labels_arr.append(n["label"])
        parents_arr.append(n["parent"])
        values_arr.append(n["value"])

        # Dominant lichess opening name for this node.
        lnames = n["lichess_names"]
        if lnames:
            mode = pd.Series(lnames).mode()
            name = str(mode.iloc[0]) if not mode.empty else ""
        else:
            name = ""

        pct = n["value"] / total * 100 if total else 0
        # Show lichess name on segments >= 3% of total.
        if name and pct >= 3:
            short = name.split(" ", 1)[1] if " " in name else name
            texts.append(short)
        else:
            texts.append("")
        hovertexts.append(name or "")
        customdata_arr.append(name or "")

    fig = go.Figure(go.Sunburst(
        ids=ids,
        labels=labels_arr,
        parents=parents_arr,
        values=values_arr,
        text=texts,
        hovertext=hovertexts,
        customdata=customdata_arr,
        branchvalues="total",
        textinfo="label+text+percent parent",
        hovertemplate="<b>%{label}</b><br>Games: %{value}<br>%{hovertext}<extra></extra>",
        insidetextorientation="auto",
        marker=dict(colors=_GP_COLORWAY * 20, line=dict(color=_GP["ebony"], width=2)),
    ))
    fig.update_layout(**_gp_layout(
        title=f"Opening Star-burst (First {depth} Plies)",
        margin=dict(l=10, r=10, t=56, b=10),
    ))
    return fig


def opening_frequency_bar(df: pd.DataFrame):
    if df.empty:
        return go.Figure()

    top = df.sort_values("games", ascending=False).head(15)
    fig = px.bar(
        top,
        x="games",
        y="opening_label",
        orientation="h",
        title="Opening Frequency",
        labels={"opening_label": "Opening", "games": "Games"},
        color_discrete_sequence=[_GP["whisky"]],
    )
    fig.update_traces(marker_line_color=_GP["ebony"], marker_line_width=1.5)
    fig.update_layout(**_gp_layout(
        yaxis=dict(categoryorder="total ascending"),
        margin=dict(l=10, r=10, t=56, b=10),
    ))
    return fig


def opening_wdl_stacked(metrics_df: pd.DataFrame):
    if metrics_df.empty:
        return go.Figure()

    top = metrics_df.sort_values("games", ascending=False).head(12).copy()
    melted = top.melt(
        id_vars=["opening_label", "games"],
        value_vars=["wins", "draws", "losses"],
        var_name="outcome",
        value_name="count",
    )
    fig = px.bar(
        melted,
        x="opening_label",
        y="count",
        color="outcome",
        title="Win / Draw / Loss by Opening",
        labels={"opening_label": "Opening", "count": "Games", "outcome": "Outcome"},
        color_discrete_map={
            "wins":   _GP["moss"],
            "draws":  _GP["steel"],
            "losses": _GP["crimson"],
        },
    )
    fig.update_traces(marker_line_color=_GP["ebony"], marker_line_width=1.5)
    fig.update_layout(**_gp_layout(
        barmode="stack",
        xaxis=dict(tickangle=-35),
        margin=dict(l=10, r=10, t=56, b=10),
    ))
    return fig


def welcome_elo_chart(df: pd.DataFrame, recent_days: int = 7) -> go.Figure:
    """ELO trend chart for all club players."""
    if df.empty:
        return go.Figure()

    fig = go.Figure()

    for i, player in enumerate(sorted(df["player"].unique())):
        pdata = df[df["player"] == player].sort_values("date")
        color = _GP_COLORWAY[i % len(_GP_COLORWAY)]

        fig.add_trace(
            go.Scatter(
                x=pdata["date"],
                y=pdata["rating"],
                mode="lines",
                name=player,
                line=dict(color=color, width=3.5),
                hovertemplate="%{fullData.name}<br>%{x|%d %b %Y}<br><b>%{y:.0f}</b><extra></extra>",
            )
        )

    fig.update_layout(
        **_gp_layout(
            title_text="Club ELO Trends",
            legend_title="Player",
            margin=dict(l=20, r=20, t=56, b=20),
            hovermode="x unified",
        )
    )
    return fig


def opening_bubble(metrics_df: pd.DataFrame):
    if metrics_df.empty:
        return go.Figure()

    fig = px.scatter(
        metrics_df,
        x="games",
        y="win_pct",
        size="games",
        color="wins",
        hover_name="opening_label",
        custom_data=["opening_label"],
        hover_data={"wins": True, "draw_pct": True, "loss_pct": True, "avg_game_length": True, "avg_move10_cp": True},
        title="Opening Bubble Map (Frequency vs Win Rate)",
        labels={"games": "Frequency", "win_pct": "Win %", "wins": "Total Wins", "opening_label": "Opening"},
        size_max=45,
        color_continuous_scale=[
            [0.0, _GP["peat"]],
            [0.5, _GP["whisky"]],
            [1.0, _GP["moss"]],
        ],
    )
    fig.update_traces(marker_line_color=_GP["ebony"], marker_line_width=1.5)
    fig.update_layout(**_gp_layout(
        showlegend=False,
        margin=dict(l=10, r=10, t=56, b=10),
    ))
    return fig


def opening_timeline_heatmap(timeline_df: pd.DataFrame, title: str):
    if timeline_df.empty:
        return go.Figure()

    time_col = "time_bucket" if "time_bucket" in timeline_df.columns else "week_start"
    bucket_label = "Week"
    if "bucket_label" in timeline_df.columns and not timeline_df["bucket_label"].empty:
        bucket_label = str(timeline_df["bucket_label"].iloc[0])

    pivot = timeline_df.pivot_table(
        index="opening_label",
        columns=time_col,
        values="games",
        aggfunc="sum",
        fill_value=0,
    )

    xvals = [d.strftime("%Y-%m-%d") for d in pivot.columns]
    yvals = pivot.index.tolist()
    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=xvals,
            y=yvals,
            colorscale=[
                [0.0, _GP["parchment"]],
                [0.4, _GP["whisky"]],
                [0.7, _GP["crimson"]],
                [1.0, _GP["forest"]],
            ],
            colorbar=dict(
                title="Games",
                tickfont=dict(family=_GP_MONO, color=_GP["peat"], size=10),
                titlefont=dict(family=_GP_MONO, color=_GP["peat"], size=10),
            ),
            hovertemplate=f"Opening: %{{y}}<br>{bucket_label}: %{{x}}<br>Games: %{{z}}<extra></extra>",
        )
    )
    fig.update_layout(**_gp_layout(
        title=title,
        xaxis=dict(title=bucket_label),
        yaxis=dict(title="Opening"),
        margin=dict(l=10, r=10, t=56, b=10),
    ))
    return fig


def player_fingerprint_radar(df: pd.DataFrame):
    if df.empty:
        return go.Figure()

    theta = df["family"].tolist()
    r = df["share_pct"].tolist()
    fig = go.Figure(
        data=go.Scatterpolar(
            r=r,
            theta=theta,
            fill="toself",
            name="Opening Fingerprint",
            line=dict(color=_GP["crimson"], width=3.5),
            marker=dict(size=8, color=_GP["whisky"], line=dict(color=_GP["ebony"], width=1.5)),
            fillcolor="rgba(181,53,65,0.15)",
        )
    )
    fig.update_layout(**_gp_layout(
        title="Player Opening Fingerprint",
        polar=dict(
            bgcolor="rgba(245,237,216,0.6)",
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                gridcolor=_GP["linen"],
                linecolor=_GP["smoke"],
                tickfont=dict(family=_GP_MONO, color=_GP["peat"], size=10),
            ),
            angularaxis=dict(
                gridcolor=_GP["linen"],
                linecolor=_GP["smoke"],
                tickfont=dict(family=_GP_FONT, color=_GP["ebony"], size=12),
            ),
        ),
        showlegend=False,
        margin=dict(l=10, r=10, t=56, b=10),
    ))
    return fig


def opening_flow_sankey(flow_df: pd.DataFrame):
    if flow_df.empty:
        return go.Figure()

    labels = list(dict.fromkeys(flow_df["source"].tolist() + flow_df["target"].tolist()))
    idx_map = {label: i for i, label in enumerate(labels)}

    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    label=labels,
                    pad=18,
                    thickness=16,
                    color=_GP["crimson"],
                    line=dict(color=_GP["ebony"], width=1),
                ),
                link=dict(
                    source=[idx_map[s] for s in flow_df["source"]],
                    target=[idx_map[t] for t in flow_df["target"]],
                    value=flow_df["games"].tolist(),
                    color="rgba(212,168,67,0.30)",
                ),
            )
        ]
    )
    fig.update_layout(**_gp_layout(
        title="Opening-to-Opening Flow",
        margin=dict(l=10, r=10, t=56, b=10),
    ))
    return fig


def opening_wins_losses_bar(metrics_df: pd.DataFrame, top_n: int = 15) -> go.Figure:
    if metrics_df.empty:
        return go.Figure()

    top = metrics_df.sort_values("games", ascending=False).head(top_n).copy()

    def _truncate(label: str, max_len: int = 30) -> str:
        return label if len(label) <= max_len else label[:max_len - 1] + "…"

    x_labels = [_truncate(str(lbl)) for lbl in top["opening_label"]]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name="Wins",
        x=x_labels,
        y=top["wins"],
        marker_color=_GP["moss"],
        marker_line_color=_GP["ebony"],
        marker_line_width=1.5,
        text=top["wins"],
        textposition="outside",
        textfont=dict(family=_GP_MONO, size=11, color=_GP["ebony"]),
        hovertemplate="<b>%{x}</b><br>Wins: %{y}<extra></extra>",
    ))

    fig.add_trace(go.Bar(
        name="Losses",
        x=x_labels,
        y=-top["losses"],
        marker_color=_GP["crimson"],
        marker_line_color=_GP["ebony"],
        marker_line_width=1.5,
        text=top["losses"],
        textposition="outside",
        textfont=dict(family=_GP_MONO, size=11, color=_GP["ebony"]),
        hovertemplate="<b>%{x}</b><br>Losses: %{text}<extra></extra>",
    ))

    fig.update_layout(**_gp_layout(
        title="Most Common Openings — Wins vs Losses",
        barmode="relative",
        xaxis=dict(
            title="Opening",
            tickangle=-50,
            tickfont=dict(family=_GP_MONO, size=11),
        ),
        yaxis=dict(
            title="Games",
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor=_GP["smoke"],
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=70, b=180),
    ))

    return fig


def player_elo_chart(df: pd.DataFrame, recent_days: int = 7) -> go.Figure:
    """Average ELO per player over time."""
    if df.empty:
        return go.Figure()

    # Remove data points where a player's rating dropped more than 100 from
    # the previous reading — these are almost certainly bad/missing data.
    cleaned = []
    for player in df["player"].unique():
        pdata = df[df["player"] == player].sort_values("date").copy()
        pdata = pdata[pdata["rating"].diff().fillna(0) >= -100]
        cleaned.append(pdata)
    df = pd.concat(cleaned) if cleaned else df

    fig = go.Figure()

    for i, player in enumerate(sorted(df["player"].unique())):
        pdata = df[df["player"] == player].sort_values("date")
        color = _GP_COLORWAY[i % len(_GP_COLORWAY)]

        fig.add_trace(
            go.Scatter(
                x=pdata["date"],
                y=pdata["rating"],
                mode="lines",
                name=player,
                line=dict(color=color, width=3.5),
                hovertemplate="%{fullData.name}<br>%{x|%d %b %Y}<br><b>%{y:.0f}</b><extra></extra>",
            )
        )

    rating_min = df["rating"].min()
    rating_max = df["rating"].max()
    padding = max((rating_max - rating_min) * 0.05, 20)
    fig.update_layout(
        **_gp_layout(
            title_text="Average ELO by Player",
            legend_title="Player",
            margin=dict(l=20, r=20, t=56, b=20),
            hovermode="x unified",
            yaxis=dict(
                title="ELO Rating",
                range=[rating_min - padding, rating_max + padding],
            ),
        )
    )
    return fig


def player_accuracy_chart(df: pd.DataFrame, recent_days: int = 7) -> go.Figure:
    """Average accuracy per player over time.

    Y-axis floored at the data minimum for readability.
    """
    if df.empty:
        return go.Figure()

    fig = go.Figure()

    for i, player in enumerate(sorted(df["player"].unique())):
        pdata = df[df["player"] == player].sort_values("date")
        color = _GP_COLORWAY[i % len(_GP_COLORWAY)]

        fig.add_trace(
            go.Scatter(
                x=pdata["date"],
                y=pdata["accuracy"],
                mode="lines",
                name=player,
                line=dict(color=color, width=3.5),
                hovertemplate="%{fullData.name}<br>%{x|%d %b %Y}<br><b>%{y:.1f}%</b><extra></extra>",
            )
        )

    fig.update_layout(
        **_gp_layout(
            title_text="Average Accuracy by Player",
            legend_title="Player",
            margin=dict(l=20, r=20, t=56, b=20),
            hovermode="x unified",
            yaxis=dict(title="Accuracy (%)", range=[max(0, df["accuracy"].min() - 5), 100]),
        )
    )
    return fig
