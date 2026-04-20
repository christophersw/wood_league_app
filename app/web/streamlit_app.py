import streamlit as st

from app.config import get_settings
from app.services.auth_service import AuthService
from app.storage.database import init_db
from app.web.components.auth import (
    is_authenticated,
    login_page,
    logout_page,
    render_admin_sidebar,
)

_GENTLEMAN_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,600;0,700;1,600;1,700&family=EB+Garamond:wght@400;500&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  /* ── Gentleman's Palette — Light Mode ── */
  :root {
    --c-parchment: #F5EDD8;
    --c-linen:     #EDE0C4;
    --c-ebony:     #1C1C1C;
    --c-forest:    #1E3D2F;
    --c-moss:      #3A5C45;
    --c-whisky:    #C17F24;
    --c-peat:      #7B4F2E;
    --c-smoke:     #4A4A4A;
    --c-gilt:      #B8962E;
    --c-best:      #4A7C59;
    --c-mistake:   #C4762A;
    --c-blunder:   #9B3A3A;
    --c-best-bg:   rgba(74, 124, 89, 0.16);
    --c-mistake-bg: rgba(196, 118, 42, 0.16);
    --c-blunder-bg: rgba(155, 58, 58, 0.16);
    --c-inaccuracy-bg: rgba(184, 150, 46, 0.16);
  }

  /* ── Base typography ── */
  html, body, [class*="css"] {
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 17px;
    line-height: 1.75;
    color: var(--c-ebony) !important;
  }
  html, body, .stApp, [data-testid="stAppViewContainer"], .main {
    background-color: #FDFCFB !important;
  }

  /* ── Headings ── */
  h1, [data-testid="stHeading"] h1, .stApp h1 {
    font-family: 'Cormorant Garamond', Georgia, serif !important;
    font-size: 2.5rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.01em;
    color: var(--c-forest) !important;
  }
  h2, [data-testid="stHeading"] h2, .stApp h2 {
    font-family: 'Cormorant Garamond', Georgia, serif !important;
    font-size: 1.875rem !important;
    font-weight: 600 !important;
    color: var(--c-forest) !important;
  }
  h3, [data-testid="stHeading"] h3, .stApp h3 {
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 1.375rem !important;
    font-weight: 500 !important;
    color: var(--c-forest) !important;
  }

  /* ── DM Mono accents ── */
  small, .stCaption, [data-testid="stCaptionContainer"],
  code, pre, .stCode,
  [data-testid="stMetricLabel"],
  [data-testid="stMetricDelta"] {
    font-family: 'DM Mono', 'Courier New', monospace !important;
    font-size: 0.8125rem !important;
    color: var(--c-peat) !important;
  }
  [data-testid="stCaptionContainer"] p {
    font-family: 'DM Mono', 'Courier New', monospace !important;
    font-size: 0.8125rem !important;
    letter-spacing: 0.02em;
    color: var(--c-peat) !important;
  }

  /* ── Metric values ── */
  [data-testid="stMetricValue"] {
    font-family: 'Cormorant Garamond', Georgia, serif !important;
    font-size: 1.45rem !important;
    font-weight: 700 !important;
    color: var(--c-whisky) !important;
    line-height: 1.2 !important;
  }
  [data-testid="stMetricLabel"] {
    font-size: 0.7rem !important;
    color: var(--c-ebony) !important;
  }
  [data-testid="stMetric"] {
    background: rgba(245, 237, 216, 0.32) !important;
    border: 1px solid var(--c-gilt) !important;
    border-radius: 4px;
    padding: 0.45rem 0.65rem !important;
    min-height: 5.5rem !important;
    height: 5.5rem !important;
    box-sizing: border-box !important;
  }

  /* ── Analysis stat cards ── */
  .analysis-stat {
    display: grid;
    grid-template-columns: 1rem 1fr;
    align-items: stretch;
    column-gap: 0.3rem;
  }
  .analysis-stat--compact {
    grid-template-columns: 0.72rem auto;
    column-gap: 0.2rem;
    width: max-content;
    margin-left: auto;
    align-self: start;
  }
  .analysis-stat--top-row-compact {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    grid-template-columns: unset;
    column-gap: unset;
    margin-top: 0.7rem;
    margin-bottom: 0.75rem;
  }
  .analysis-stat--top-row-compact .analysis-stat__label {
    writing-mode: horizontal-tb;
    transform: none;
    white-space: nowrap;
    text-align: right;
    font-size: 0.55rem;
    letter-spacing: 0.08em;
    margin-bottom: 0.18rem;
    justify-content: flex-end;
  }
  .analysis-stat--top-row-compact .analysis-stat-card {
    margin-left: auto;
  }
  .analysis-stat__label {
    writing-mode: vertical-rl;
    transform: rotate(180deg);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'DM Mono', 'Courier New', monospace !important;
    font-size: 0.65rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    text-align: center;
    color: var(--c-ebony);
    line-height: 1.1;
    white-space: nowrap;
  }
  .analysis-stat--compact .analysis-stat__label {
    writing-mode: horizontal-tb;
    transform: none;
    white-space: nowrap;
    text-align: right;
    align-items: center;
    justify-content: flex-end;
    font-size: 0.55rem;
    letter-spacing: 0.08em;
  }
  .analysis-stat-card {
    min-height: 5.5rem;
    height: 5.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    overflow: hidden;
    border: 1px solid var(--c-gilt);
    background: rgba(245, 237, 216, 0.32);
    box-sizing: border-box;
  }
  .analysis-stat--compact .analysis-stat-card {
    min-height: 2.05rem;
    height: 2.05rem;
    min-width: 4.2rem;
    padding: 0 0.35rem;
  }
  .analysis-stat-card__value {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0.45rem 0.5rem;
    font-family: 'DM Mono', 'Courier New', monospace !important;
    font-size: 1.55rem;
    font-weight: 700;
    line-height: 1;
    text-align: center;
    color: var(--c-ebony);
  }
  .analysis-stat--compact .analysis-stat-card__value {
    font-size: 0.96rem;
    letter-spacing: 0.01em;
  }
  .analysis-stat-card--best {
    border-color: var(--c-best);
    background: var(--c-best-bg);
    color: var(--c-best);
  }
  .analysis-stat-card--mistake {
    border-color: var(--c-mistake);
    background: var(--c-mistake-bg);
    color: var(--c-mistake);
  }
  .analysis-stat-card--blunder {
    border-color: var(--c-blunder);
    background: var(--c-blunder-bg);
    color: var(--c-blunder);
  }
  .analysis-stat-card--inaccuracy {
    border-color: var(--c-gilt);
    background: var(--c-inaccuracy-bg);
    color: var(--c-gilt);
  }
  .analysis-stat-card--accuracy {
    border-color: var(--c-smoke);
    background: rgba(74, 74, 74, 0.1);
    color: var(--c-smoke);
  }

  .analysis-player-divider {
    width: 1px;
    height: 100%;
    min-height: 13.5rem;
    margin: 0 auto;
    background: linear-gradient(
      to bottom,
      rgba(28, 28, 28, 0.0) 0%,
      rgba(28, 28, 28, 0.18) 18%,
      rgba(28, 28, 28, 0.18) 82%,
      rgba(28, 28, 28, 0.0) 100%
    );
  }

  /* ── Player section stacks earlier on mid-size screens ── */
  @media (max-width: 1400px) {
    [data-testid="stHorizontalBlock"]:has(.analysis-player-divider) {
      flex-wrap: wrap !important;
    }
    [data-testid="stHorizontalBlock"]:has(.analysis-player-divider) > [data-testid="stColumn"] {
      flex: 0 0 100% !important;
      width: 100% !important;
      min-width: 100% !important;
    }
    .analysis-player-divider {
      display: none;
    }
  }

  @media (max-width: 1100px) {
    [data-testid="stMetric"] {
      min-height: 4.8rem !important;
      height: 4.8rem !important;
    }
    .analysis-stat-card {
      min-height: 4.8rem;
      height: 4.8rem;
    }
    .analysis-stat-card__value {
      font-size: 1.35rem;
    }
  }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {
    background-color: var(--c-forest) !important;
    border-right: 1px solid var(--c-gilt) !important;
  }
  [data-testid="stSidebar"] * {
    color: var(--c-parchment) !important;
  }
  [data-testid="stSidebar"] [data-testid="stSidebarNavItems"] a {
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 1.0625rem;
    color: var(--c-parchment) !important;
  }
  [data-testid="stSidebar"] [data-testid="stSidebarNavItems"] a:hover,
  [data-testid="stSidebar"] [data-testid="stSidebarNavItems"] a[aria-current="page"] {
    color: var(--c-gilt) !important;
  }

  /* ── Buttons ── */
  .stButton > button[kind="primary"],
  .stButton > button {
    background: transparent !important;
    border: 1px solid var(--c-gilt) !important;
    color: var(--c-forest) !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.8125rem !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    border-radius: 3px;
    padding: 0.5rem 1.25rem;
    transition: background 0.2s, color 0.2s;
  }
  .stButton > button:hover {
    background: var(--c-ebony) !important;
    color: var(--c-parchment) !important;
    border-color: var(--c-ebony) !important;
  }

  /* ── Form labels / selectboxes ── */
  .stSelectbox label, .stTextInput label, .stNumberInput label,
  .stMultiSelect label, .stDateInput label, .stSlider label {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--c-peat) !important;
  }

  /* ── Dividers ── */
  hr {
    border-color: var(--c-gilt) !important;
    opacity: 0.4;
    margin: 1.5rem 0;
  }

  /* ── Tabs ── */
  [data-testid="stTabs"] button[role="tab"] {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--c-smoke) !important;
  }
  [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    border-bottom-color: var(--c-whisky) !important;
    color: var(--c-forest) !important;
  }

  /* ── Dataframes ── */
  [data-testid="stDataFrame"] th {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    background: var(--c-linen) !important;
    color: var(--c-forest) !important;
    border-bottom: 1px solid var(--c-gilt) !important;
  }

  /* ── Link color ── */
  a, a:visited {
    color: var(--c-whisky) !important;
  }
  a:hover {
    color: var(--c-peat) !important;
  }
</style>
"""


def main() -> None:
    st.set_page_config(page_title="Woodland Chess", page_icon="♟", layout="wide")
    st.html(_GENTLEMAN_CSS)
    init_db()

    settings = get_settings()
    if settings.auth_enabled:
        AuthService().bootstrap_admin_if_needed()

    # Always register all pages so that direct URL navigation (e.g. from
    # LinkColumn clicks opening a new tab) resolves correctly. Auth is enforced
    # inside each page via require_auth(), not by hiding pages from the router.
    opening_analysis_page = st.Page(
        "app/web/pages/opening_analysis.py",
        title="Opening Analysis",
        icon="🧭",
        url_path="opening-analysis",
        default=True,
    )
    analysis_page = st.Page(
        "app/web/pages/game_analysis.py",
        title="Game Analysis",
        icon="🔎",
        url_path="game-analysis",
    )
    search_page = st.Page(
        "app/web/pages/game_search.py",
        title="Game Search",
        icon="🧠",
        url_path="game-search",
    )
    status_page = st.Page(
        "app/web/pages/analysis_status.py",
        title="Analysis Status",
        icon="📊",
        url_path="analysis-status",
    )

    authenticated = not settings.auth_enabled or is_authenticated()

    if settings.auth_enabled:
        if authenticated:
            _logout = st.Page(logout_page, title="Sign Out", icon="🚪", url_path="logout")
            pages: dict | list = {
                "": [opening_analysis_page, analysis_page, search_page],
                "Admin": [status_page],
                "Account": [_logout],
            }
        else:
            _login = st.Page(login_page, title="Sign In", icon="🔑", url_path="login")
            pages = {
                "": [opening_analysis_page, analysis_page, search_page],
                "Admin": [status_page],
                "Account": [_login],
            }
    else:
        pages = {
            "": [opening_analysis_page, analysis_page, search_page],
            "Admin": [status_page],
        }

    nav = st.navigation(pages, position="sidebar")
    render_admin_sidebar()
    nav.run()
