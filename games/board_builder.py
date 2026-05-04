"""Generate the SVG board viewer HTML for a game analysis page.

All SVG frames are generated server-side and embedded as JSON in a <script>
tag. JS controls play/pause/scrubber/move-list without any round trips.
Plotly charts (WDL stacked area, SF centipawn bar) are rendered inline using
the Plotly.js already loaded in base.html.
"""

from __future__ import annotations

import io
import json
import re
from uuid import uuid4

import chess
import chess.pgn
import chess.svg

from games.services import GameAnalysisData, MoveRow

_BOARD_COLORS = {
    "square light": "#F2E6D0",
    "square dark": "#4A8C62",
    "margin": "#1A1A1A",
    "coord": "#D4A843",
}

_SF_ARROW_COLORS = ["#D4A843CC", "#D4A84377", "#D4A84333"]
_LC0_ARROW_COLORS = ["#4A6E8ACC", "#4A6E8A77", "#4A6E8A33"]


def build_board_viewer_html(
    data: GameAnalysisData,
    size: int = 480,
    orientation: str = "white",
) -> str:
    """Return self-contained HTML+JS board viewer string for embedding with |safe."""
    viewer_id = f"svg_{uuid4().hex}"
    game = chess.pgn.read_game(io.StringIO(data.pgn))
    if game is None:
        return "<p>Could not parse PGN.</p>"

    flipped = orientation == "black"
    board = game.board()
    start_ply_offset = board.ply()
    moves_played: list[chess.Move] = list(game.mainline_moves())

    # Build ply → MoveRow lookup for Stockfish
    sf_by_ply: dict[int, MoveRow] = {}
    for row in data.moves:
        sf_by_ply[row.ply] = row

    # Build ply → MoveRow lookup for Lc0
    lc0_by_ply: dict[int, MoveRow] = {}
    if data.lc0_moves:
        for row in data.lc0_moves:
            lc0_by_ply[row.ply] = row

    # Build tier maps: ply → [{uci, score}, ...]
    def _tier_map(by_ply: dict[int, MoveRow], use_cp_equiv: bool) -> dict[int, list]:
        result: dict[int, list] = {}
        for ply, row in by_ply.items():
            entries = []
            ucis = [row.arrow_uci, row.arrow_uci_2, row.arrow_uci_3]
            scores = [row.arrow_score_1, row.arrow_score_2, row.arrow_score_3]
            if use_cp_equiv:
                scores = [row.cp_equiv, None, None]
            for uci, score in zip(ucis, scores):
                if uci:
                    entries.append({"uci": uci, "score": score})
            if entries:
                result[ply] = entries
        return result

    sf_tier_map = _tier_map(sf_by_ply, use_cp_equiv=False) if sf_by_ply else None
    lc0_tier_map = _tier_map(lc0_by_ply, use_cp_equiv=True) if lc0_by_ply else None

    # Build played-score maps for arrow label generation
    sf_played: dict[int, float] = {}
    for ply, row in sf_by_ply.items():
        if row.cp_eval is not None:
            sf_played[ply] = row.cp_eval

    lc0_played: dict[int, float] = {}
    for ply, row in lc0_by_ply.items():
        if row.cp_equiv is not None:
            lc0_played[ply] = row.cp_equiv

    # -- Build SVG frames ------------------------------------------------------
    san_list: list[str] = []
    arrow_labels_by_ply: dict[int, list] = {}
    is_best_map: dict[int, bool] = {}
    frames: list[str] = []

    # Frame 0: starting position
    frames.append(chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS))

    board = game.board()
    for ply_i, move in enumerate(moves_played, start=1):
        abs_ply = ply_i + start_ply_offset
        san_list.append(board.san(move))
        board.push(move)

        arrows: list[chess.svg.Arrow] = []

        def _add_arrows(
            tier_map: dict | None,
            played_scores: dict,
            colors: list[str],
            engine_prefix: str,
        ) -> None:
            if tier_map is None:
                return
            tier_entries = tier_map.get(abs_ply) or tier_map.get(ply_i) or []
            scores = [e.get("score") for e in tier_entries]
            ucis = [e.get("uci", "") for e in tier_entries]

            played_score = played_scores.get(abs_ply) or played_scores.get(ply_i)
            base = scores[0] if scores and scores[0] is not None else None

            for i, uci in enumerate(ucis):
                if not (uci and len(uci) >= 4):
                    continue
                try:
                    rgba = colors[i] if i < len(colors) else colors[-1]
                    arrows.append(
                        chess.svg.Arrow(
                            chess.parse_square(uci[:2]),
                            chess.parse_square(uci[2:4]),
                            color=rgba,
                        )
                    )
                    score = scores[i] if i < len(scores) else None
                    label = ""
                    if played_score is not None and score is not None:
                        gain = float(score) - float(played_score)
                        if "lc0" in engine_prefix.lower():
                            bps = int(round((gain / 100.0) * 4))
                            label = f"{bps:+d}%" if bps != 0 else "±0%"
                        else:
                            label = f"{int(round(gain)):+d}"
                    elif base is not None and score is not None and i > 0:
                        gap = float(base) - float(score)
                        if "lc0" in engine_prefix.lower():
                            bps = int(round((gap / 100.0) * 4))
                            label = f"{bps:+d}%" if bps != 0 else "±0%"
                        else:
                            label = f"{int(round(gap)):+d}"
                    if label:
                        arrow_labels_by_ply.setdefault(ply_i, []).append(
                            {
                                "engine": engine_prefix.lower(),
                                "label": label,
                                "from_sq": uci[:2],
                                "to_sq": uci[2:4],
                            }
                        )
                except ValueError:
                    pass

        _add_arrows(sf_tier_map, sf_played, _SF_ARROW_COLORS, "sf")
        _add_arrows(lc0_tier_map, lc0_played, _LC0_ARROW_COLORS, "lc0")

        # Best-move match tracking for eval chart
        sf_entry = (sf_tier_map or {}).get(abs_ply) or (sf_tier_map or {}).get(ply_i)
        sf_best_uci = sf_entry[0].get("uci", "") if sf_entry else ""
        if sf_best_uci:
            is_best_map[ply_i] = move.uci() == sf_best_uci

        svg = chess.svg.board(
            board,
            size=size,
            lastmove=move,
            arrows=arrows,
            flipped=flipped,
            colors=_BOARD_COLORS,
        )
        svg = _inject_arrow_labels(svg, arrow_labels_by_ply.get(ply_i, []), size, flipped)
        frames.append(svg)

    total_frames = len(frames)
    start_ply = total_frames - 1

    # -- Move list HTML --------------------------------------------------------
    move_spans: list[str] = []
    for i, san in enumerate(san_list):
        ply = i + 1
        if ply % 2 == 1:
            move_spans.append(f'<span class="move-num">{(ply + 1) // 2}.</span>')
        move_spans.append(f'<span class="move" data-ply="{ply}" onclick="goTo{viewer_id}({ply})">{san}</span>')
    moves_html = " ".join(move_spans)

    # -- Serialize frames + labels ---------------------------------------------
    frames_json = json.dumps(frames)
    arrow_labels_json = json.dumps(arrow_labels_by_ply)

    top_player = data.black if not flipped else data.white
    top_sym = "♟" if not flipped else "♙"
    top_side = "Black" if not flipped else "White"
    bottom_player = data.white if not flipped else data.black
    bottom_sym = "♙" if not flipped else "♟"
    bottom_side = "White" if not flipped else "Black"

    has_sf_js = "true" if data.has_sf else "false"
    has_lc0_js = "true" if data.has_lc0 else "false"
    sf_checked = "checked" if data.has_sf else ""
    lc0_checked = "checked" if data.has_lc0 else ""
    sf_disabled = "" if data.has_sf else "disabled"
    lc0_disabled = "" if data.has_lc0 else "disabled"
    toggles_display = "flex" if (data.has_sf or data.has_lc0) else "none"

    # -- WDL chart data --------------------------------------------------------
    wdl_data: list[dict] | None = None
    if data.lc0_moves:
        wdl_data = [
            {
                "ply": r.ply,
                "wdl_win": r.wdl_win or 0,
                "wdl_draw": r.wdl_draw or 0,
                "wdl_loss": r.wdl_loss or 0,
                "san": r.san,
                "classification": r.classification or "",
            }
            for r in data.lc0_moves
            if r.wdl_win is not None
        ]

    # -- SF eval chart data ----------------------------------------------------
    eval_data: list[dict] | None = None
    if data.has_sf and data.moves:
        eval_data = [
            {
                "ply": r.ply,
                "cp_eval": r.cp_eval,
                "san": r.san,
                "classification": r.classification or "",
            }
            for r in data.moves
            if r.cp_eval is not None
        ]

    white_json = json.dumps(data.white)
    black_json = json.dumps(data.black)
    wdl_json = json.dumps(wdl_data) if wdl_data else "null"
    eval_json = json.dumps(eval_data) if eval_data else "null"
    is_best_json = json.dumps(is_best_map)
    wdl_height = max(240, min(400, 160 + len(wdl_data or []) * 4))
    sf_height = max(300, 210 + len(eval_data or []) * 7)

    return f"""
<style>
#{viewer_id} {{font-family:Georgia,serif;background:transparent;}}
#{viewer_id} .viewer-grid {{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;align-items:start;}}
#{viewer_id} .board-pane {{display:flex;flex-direction:column;gap:0;min-width:0;}}
#{viewer_id} .board-wrap {{border-left:2px solid #1A1A1A;border-right:2px solid #1A1A1A;}}
#{viewer_id} .board-wrap svg {{display:block;margin:0 auto;}}
#{viewer_id} .player-label {{display:flex;align-items:center;justify-content:space-between;border-top:2.5px solid #1A1A1A;border-bottom:1px solid #1A1A1A;padding:5px 4px;margin:0;}}
#{viewer_id} .player-label .player-side {{font-family:monospace;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:#8B3A2A;}}
#{viewer_id} .player-label .player-name {{font-family:Georgia,serif;font-size:15px;font-weight:600;color:#1A1A1A;letter-spacing:.02em;}}
#{viewer_id} .controls {{display:flex;align-items:center;gap:5px;padding:8px 0 6px;justify-content:center;border-top:1px solid #D4C4A0;}}
#{viewer_id} .controls button {{background:transparent;color:#1A1A1A;border:1.5px solid #1A1A1A;border-radius:0;padding:4px 10px;cursor:pointer;font-family:monospace;font-size:13px;min-width:32px;transition:background .15s,color .15s;}}
#{viewer_id} .controls button:hover {{background:#1A1A1A;color:#F2E6D0;}}
#{viewer_id} .controls input[type=range] {{flex:1;max-width:260px;accent-color:#D4A843;}}
#{viewer_id} .ply-label {{font-family:monospace;font-size:11px;color:#8B3A2A;min-width:72px;text-align:center;letter-spacing:.04em;}}
#{viewer_id} .analysis-pane {{display:flex;flex-direction:column;gap:8px;min-width:0;}}
#{viewer_id} .move-list {{max-height:220px;overflow-y:auto;padding:5px 6px;font-family:monospace;font-size:12px;line-height:2.0;border-top:2.5px solid #1A1A1A;border-bottom:1.5px solid #1A1A1A;background:rgba(242,230,208,.45);}}
#{viewer_id} .move-list .move-num {{color:#8B3A2A;font-size:11px;margin-left:4px;}}
#{viewer_id} .move-list .move {{cursor:pointer;padding:1px 5px;color:#1A1A1A;transition:background .1s;}}
#{viewer_id} .move-list .move:hover {{background:rgba(212,168,67,.20);}}
#{viewer_id} .move-list .move.active {{background:#1A3A2A;color:#F2E6D0;font-weight:600;}}
#{viewer_id} .arrow-toggles {{display:{toggles_display};gap:14px;align-items:center;padding:5px 2px 2px;font-family:'DM Mono',monospace;font-size:.72rem;letter-spacing:.04em;}}
#{viewer_id} .arrow-toggle-label {{display:inline-flex;align-items:center;gap:5px;cursor:pointer;user-select:none;}}
#{viewer_id} .arrow-swatch {{display:inline-block;width:18px;height:4px;border-radius:2px;vertical-align:middle;}}
@media(max-width:900px){{#{viewer_id} .viewer-grid{{grid-template-columns:1fr;}}#{viewer_id} .move-list{{max-height:160px;}}}}
</style>

<div id="{viewer_id}">
  <div class="viewer-grid">
    <div class="board-pane">
      <div class="player-label">
        <span class="player-side">{top_sym} {top_side}</span>
        <span class="player-name">{top_player}</span>
      </div>
      <div class="board-wrap" id="{viewer_id}-board"></div>
      <div class="player-label">
        <span class="player-side">{bottom_sym} {bottom_side}</span>
        <span class="player-name">{bottom_player}</span>
      </div>
      <div class="controls">
        <button onclick="goTo{viewer_id}(0)" title="Start">&#x23EE;</button>
        <button onclick="goTo{viewer_id}(Math.max(0,cur{viewer_id}-1))" title="Back">&#x25C0;</button>
        <button id="{viewer_id}-playbtn" onclick="togglePlay{viewer_id}()" title="Play/Pause">&#x25B6;</button>
        <button onclick="goTo{viewer_id}(Math.min({total_frames - 1},cur{viewer_id}+1))" title="Forward">&#x25B6;&#xFE0E;</button>
        <button onclick="goTo{viewer_id}({total_frames - 1})" title="End">&#x23ED;</button>
        <input type="range" id="{viewer_id}-slider" min="0" max="{total_frames - 1}" value="{start_ply}" oninput="goTo{viewer_id}(parseInt(this.value))">
        <span class="ply-label" id="{viewer_id}-label"></span>
      </div>
      <div class="move-list" id="{viewer_id}-moves">{moves_html}</div>
      <div class="arrow-toggles">
        <label class="arrow-toggle-label" style="color:#D4A843">
          <input type="checkbox" id="{viewer_id}-sf-toggle" {sf_checked} {sf_disabled} onchange="toggleArrows{viewer_id}()">
          <span class="arrow-swatch" style="background:linear-gradient(90deg,#D4A843EE,#D4A84308)"></span>SF
        </label>
        <label class="arrow-toggle-label" style="color:#4A6E8A">
          <input type="checkbox" id="{viewer_id}-lc0-toggle" {lc0_checked} {lc0_disabled} onchange="toggleArrows{viewer_id}()">
          <span class="arrow-swatch" style="background:linear-gradient(90deg,#4A6E8AEE,#4A6E8A08)"></span>Lc0
        </label>
      </div>
    </div>
    <div class="analysis-pane">
      <div id="{viewer_id}-wdl"></div>
      <div id="{viewer_id}-eval"></div>
    </div>
  </div>
</div>

<script>
(function() {{
  const frames = {frames_json};
  const arrowLabels = {arrow_labels_json};
  const totalFrames = frames.length;
  const startPlyOffset = {start_ply_offset};
  window.cur{viewer_id} = {start_ply};
  let playing{viewer_id} = false;
  let timer{viewer_id} = null;

  const boardEl = document.getElementById('{viewer_id}-board');
  const slider = document.getElementById('{viewer_id}-slider');
  const label = document.getElementById('{viewer_id}-label');
  const playBtn = document.getElementById('{viewer_id}-playbtn');
  const movesEl = document.getElementById('{viewer_id}-moves');
  const sfToggle = document.getElementById('{viewer_id}-sf-toggle');
  const lc0Toggle = document.getElementById('{viewer_id}-lc0-toggle');
  const allMoveSpans = movesEl.querySelectorAll('.move');
  let showSF = {has_sf_js};
  let showLc0 = {has_lc0_js};

  function applyArrowVisibility() {{
    boardEl.querySelectorAll('line[stroke*="D4A843"],polygon[fill*="D4A843"]').forEach(el => el.style.display = showSF ? '' : 'none');
    boardEl.querySelectorAll('line[stroke*="4A6E8A"],polygon[fill*="4A6E8A"]').forEach(el => el.style.display = showLc0 ? '' : 'none');
  }}

  window.toggleArrows{viewer_id} = function() {{
    if (sfToggle) showSF = sfToggle.checked;
    if (lc0Toggle) showLc0 = lc0Toggle.checked;
    applyArrowVisibility();
  }};

  function render() {{
    const ply = window.cur{viewer_id};
    boardEl.innerHTML = frames[ply];
    applyArrowVisibility();
    slider.value = ply;
    label.textContent = ply === 0 ? 'Start' : Math.ceil(ply/2) + '.' + (ply%2===1?'':'..') + ' ply ' + ply;
    allMoveSpans.forEach(s => s.classList.remove('active'));
    if (ply > 0) {{
      const active = movesEl.querySelector('.move[data-ply="' + ply + '"]');
      if (active) {{ active.classList.add('active'); active.scrollIntoView({{block:'nearest'}}); }}
    }}
    if (typeof window.updateEvalHighlight{viewer_id} === 'function') window.updateEvalHighlight{viewer_id}(ply);
    if (typeof window.updateWdlHighlight{viewer_id} === 'function') window.updateWdlHighlight{viewer_id}(ply);
  }}

  window.goTo{viewer_id} = function(ply) {{
    window.cur{viewer_id} = Math.max(0, Math.min(totalFrames-1, ply));
    render();
  }};

  window.togglePlay{viewer_id} = function() {{
    if (playing{viewer_id}) {{
      clearInterval(timer{viewer_id});
      playing{viewer_id} = false;
      playBtn.innerHTML = '\\u25B6';
    }} else {{
      if (window.cur{viewer_id} >= totalFrames-1) window.cur{viewer_id} = 0;
      playing{viewer_id} = true;
      playBtn.innerHTML = '\\u23F8';
      timer{viewer_id} = setInterval(() => {{
        if (window.cur{viewer_id} >= totalFrames-1) {{
          clearInterval(timer{viewer_id}); playing{viewer_id} = false; playBtn.innerHTML = '\\u25B6'; return;
        }}
        window.cur{viewer_id}++;
        render();
      }}, 800);
    }}
  }};

  render();

  // -- Lc0 WDL chart ----------------------------------------------------------
  const wdlData = {wdl_json};
  if (wdlData && typeof Plotly !== 'undefined') {{
    const plies = wdlData.map(d => Number(d.ply));
    const wins  = wdlData.map(d => Number(d.wdl_win)  / 10);
    const draws = wdlData.map(d => Number(d.wdl_draw) / 10);
    const losses= wdlData.map(d => Number(d.wdl_loss) / 10);
    const wdlHighlight = {{x:[null,null],y:[0,100],mode:'lines',showlegend:false,hoverinfo:'skip',line:{{color:'#C17F24',width:2,dash:'dot'}}}};
    const allTraces = [
      {{x:plies,y:wins,name:'♙ White Win',type:'scatter',mode:'lines',stackgroup:'wdl',fill:'tozeroy',fillcolor:'rgba(242,230,208,0.90)',line:{{color:'#D4C4A0',width:1.5}},hovertemplate:'White win: %{{y:.1f}}%<extra></extra>'}},
      {{x:plies,y:draws,name:'Draw',type:'scatter',mode:'lines',stackgroup:'wdl',fill:'tonexty',fillcolor:'rgba(139,58,42,0.50)',line:{{color:'#8B3A2A',width:1}},hovertemplate:'Draw: %{{y:.1f}}%<extra></extra>'}},
      {{x:plies,y:losses,name:'♟ Black Win',type:'scatter',mode:'lines',stackgroup:'wdl',fill:'tonexty',fillcolor:'rgba(26,26,26,0.85)',line:{{color:'#1A1A1A',width:1.5}},hovertemplate:'Black win: %{{y:.1f}}%<extra></extra>'}},
      wdlHighlight
    ];
    const wdlHighlightIdx = allTraces.length - 1;
    const wdlDiv = document.getElementById('{viewer_id}-wdl');
    Plotly.newPlot(wdlDiv, allTraces, {{
      xaxis:{{title:{{text:'Ply',font:{{size:11,color:'#1C1C1C',family:'DM Mono,monospace'}}}},zeroline:false,gridcolor:'#EDE0C4',tickfont:{{size:11,color:'#1C1C1C',family:'DM Mono,monospace'}}}},
      yaxis:{{title:{{text:'Win/Draw/Loss (%)',font:{{size:11,color:'#1C1C1C',family:'DM Mono,monospace'}}}},range:[0,100],ticksuffix:'%',gridcolor:'#EDE0C4',tickfont:{{size:11,color:'#1C1C1C',family:'DM Mono,monospace'}}}},
      legend:{{orientation:'h',y:-0.22,font:{{color:'#1C1C1C',family:'EB Garamond,serif',size:12}},bgcolor:'rgba(0,0,0,0)'}},
      margin:{{l:55,r:20,t:56,b:60}},height:{wdl_height},
      paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(237,224,196,0.2)',
      font:{{color:'#1C1C1C',family:'EB Garamond,serif'}},hovermode:'x unified',
      annotations:[{{text:{white_json}+' vs '+{black_json}+' — Win / Draw / Loss',xref:'paper',yref:'paper',x:0.5,y:1.13,xanchor:'center',showarrow:false,font:{{size:15,color:'#1A1A1A',family:'Georgia,serif'}}}}],
    }}, {{displaylogo:false,responsive:true}}).then(() => {{
      wdlDiv.on('plotly_click', d => {{ if (d.points && d.points.length) window.goTo{viewer_id}(d.points[0].x); }});
      window.updateWdlHighlight{viewer_id} = function(ply) {{
        Plotly.restyle(wdlDiv, {{x:[[ply,ply]],y:[[0,100]]}}, [wdlHighlightIdx]);
      }};
      window.updateWdlHighlight{viewer_id}(window.cur{viewer_id});
    }});
  }}

  // -- Stockfish eval chart ---------------------------------------------------
  const evalData = {eval_json};
  const isBestMap = {is_best_json};
  if (evalData && typeof Plotly !== 'undefined') {{
    const MATE_THRESHOLD = 9000, DISPLAY_CAP = 1200;
    const points = evalData.map(d => {{
      const cp = Number(d.cp_eval ?? 0);
      const isMate = Math.abs(cp) >= MATE_THRESHOLD;
      const display = isMate ? (cp >= 0 ? DISPLAY_CAP : -DISPLAY_CAP) : Math.max(-DISPLAY_CAP, Math.min(DISPLAY_CAP, cp));
      return {{ply:Number(d.ply),cp,display,isMate,san:d.san||'',cls:d.classification||''}};
    }});
    const sfHighlight = {{x:[null,null],y:[-DISPLAY_CAP,DISPLAY_CAP],mode:'lines',showlegend:false,hoverinfo:'skip',line:{{color:'#C17F24',width:2,dash:'dot'}}}};
    const barColors = points.map((p,i) => isBestMap[p.ply] ? '#4A6554' : (p.display >= 0 ? '#D4A843' : '#8B3A2A'));
    const barTrace = {{
      x:points.map(p=>p.ply), y:points.map(p=>p.display),
      type:'bar', marker:{{color:barColors}},
      customdata:points.map(p=>[p.san, p.cp>=0?'+':'',(p.cp/100).toFixed(2)]),
      hovertemplate:'Ply %{{x}}: %{{customdata[0]}} %{{customdata[1]}}%{{customdata[2]}} pawns<extra></extra>',
      name:'Eval',showlegend:false,
    }};
    const sfDiv = document.getElementById('{viewer_id}-eval');
    Plotly.newPlot(sfDiv, [barTrace, sfHighlight], {{
      xaxis:{{title:{{text:'Ply',font:{{size:11,color:'#1C1C1C',family:'DM Mono,monospace'}}}},zeroline:false,gridcolor:'#EDE0C4',tickfont:{{size:11,color:'#1C1C1C',family:'DM Mono,monospace'}}}},
      yaxis:{{title:{{text:'Centipawns (White +)',font:{{size:11,color:'#1C1C1C',family:'DM Mono,monospace'}}}},zeroline:true,zerolinecolor:'#1A1A1A',gridcolor:'#EDE0C4',tickfont:{{size:11,color:'#1C1C1C',family:'DM Mono,monospace'}}}},
      margin:{{l:55,r:20,t:50,b:50}},height:{sf_height},
      paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(237,224,196,0.2)',
      font:{{color:'#1C1C1C',family:'EB Garamond,serif'}},hovermode:'x unified',
      annotations:[{{text:'Stockfish Evaluation',xref:'paper',yref:'paper',x:0.5,y:1.10,xanchor:'center',showarrow:false,font:{{size:15,color:'#1A1A1A',family:'Georgia,serif'}}}}],
    }}, {{displaylogo:false,responsive:true}}).then(() => {{
      sfDiv.on('plotly_click', d => {{ if (d.points && d.points.length) window.goTo{viewer_id}(d.points[0].x); }});
      const sfHighlightIdx = 1;
      window.updateEvalHighlight{viewer_id} = function(ply) {{
        Plotly.restyle(sfDiv, {{x:[[ply,ply]],y:[[-{sf_height},{sf_height}]]}}, [sfHighlightIdx]);
      }};
      window.updateEvalHighlight{viewer_id}(window.cur{viewer_id});
    }});
  }}
}})();
</script>
"""


def _inject_arrow_labels(svg: str, labels: list[dict], size: int, flipped: bool) -> str:
    """Inject evaluation labels on top of move arrows in the SVG board."""
    if not labels or not svg:
        return svg
    _MARGIN = 15
    _SQ = 45

    def sq_to_px(sq: str) -> tuple[float, float]:
        """Convert square coordinate (e.g., 'e4') to pixel position."""
        if not sq or len(sq) < 2:
            return (0.0, 0.0)
        try:
            f = ord(sq[0]) - ord("a")
            r = int(sq[1]) - 1
            if flipped:
                f = 7 - f
                r = 7 - r
            return (_MARGIN + (f + 0.5) * _SQ, _MARGIN + (7 - r + 0.5) * _SQ)
        except (ValueError, IndexError):
            return (0.0, 0.0)

    by_sq: dict[str, list[dict]] = {}
    for label_data in labels:
        to_sq = label_data.get("to_sq", "")
        if to_sq and label_data.get("label"):
            by_sq.setdefault(to_sq, []).append(label_data)

    font_size = 11
    line_h = font_size + 3
    text_elements: list[str] = []
    for to_sq, sq_labels in by_sq.items():
        cx, cy = sq_to_px(to_sq)
        base_y = cy - _SQ * 0.22
        n = len(sq_labels)
        start_y = base_y - (n - 1) * line_h / 2
        for idx, ld in enumerate(sq_labels):
            engine = str(ld.get("engine", "sf")).lower()
            fg = "#FFE082" if "sf" in engine else "#80CBC4"
            lx, ly = cx, start_y + idx * line_h
            text = str(ld.get("label", ""))
            text_elements.append(
                f'<rect x="{lx-18:.1f}" y="{ly-font_size+1:.1f}" width="36" height="{font_size+2}" rx="2" fill="#1A1A1A" fill-opacity="0.72" pointer-events="none"/>'
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" dominant-baseline="auto" font-size="{font_size}" font-weight="bold" font-family="monospace" fill="{fg}" pointer-events="none">{text}</text>'
            )

    if not text_elements:
        return svg
    return re.sub(r"</svg>", "\n".join(text_elements) + "\n</svg>", svg, count=1)
