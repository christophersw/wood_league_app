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
<style>
  @font-face {
    font-family: 'Playfair Display SC';
    font-style: normal;
    font-weight: 400;
    font-display: swap;
    src: url('/app/static/fonts/PlayfairDisplaySC-Regular.woff2') format('woff2');
  }
  @font-face {
    font-family: 'Playfair Display SC';
    font-style: normal;
    font-weight: 700;
    font-display: swap;
    src: url('/app/static/fonts/PlayfairDisplaySC-Bold.woff2') format('woff2');
  }
  @font-face {
    font-family: 'Cormorant Garamond';
    font-style: normal;
    font-weight: 600;
    font-display: swap;
    src: url('/app/static/fonts/CormorantGaramond-SemiBold.woff2') format('woff2');
  }
  @font-face {
    font-family: 'Cormorant Garamond';
    font-style: normal;
    font-weight: 700;
    font-display: swap;
    src: url('/app/static/fonts/CormorantGaramond-SemiBold.woff2') format('woff2');
  }
  @font-face {
    font-family: 'Cormorant Garamond';
    font-style: italic;
    font-weight: 600;
    font-display: swap;
    src: url('/app/static/fonts/CormorantGaramond-SemiBoldItalic.woff2') format('woff2');
  }
  @font-face {
    font-family: 'Cormorant Garamond';
    font-style: italic;
    font-weight: 700;
    font-display: swap;
    src: url('/app/static/fonts/CormorantGaramond-SemiBoldItalic.woff2') format('woff2');
  }
  @font-face {
    font-family: 'EB Garamond';
    font-style: normal;
    font-weight: 400;
    font-display: swap;
    src: url('/app/static/fonts/EBGaramond-Regular.woff2') format('woff2');
  }
  @font-face {
    font-family: 'EB Garamond';
    font-style: normal;
    font-weight: 500;
    font-display: swap;
    src: url('/app/static/fonts/EBGaramond-Regular.woff2') format('woff2');
  }
  @font-face {
    font-family: 'DM Mono';
    font-style: normal;
    font-weight: 400;
    font-display: swap;
    src: url('/app/static/fonts/DMMono-Regular.woff2') format('woff2');
  }
  @font-face {
    font-family: 'DM Mono';
    font-style: normal;
    font-weight: 500;
    font-display: swap;
    src: url('/app/static/fonts/DMMono-Medium.woff2') format('woff2');
  }
</style>
<style>
  /* ── Du Bois Palette — After the 1900 Paris Exposition plates ── */
  :root {
    --c-parchment: #F2E6D0;
    --c-linen:     #E8D5B0;
    --c-ebony:     #1A1A1A;
    --c-forest:    #1A3A2A;
    --c-moss:      #4A6554;
    --c-whisky:    #D4A843;
    --c-peat:      #8B3A2A;
    --c-smoke:     #5A5A5A;
    --c-gilt:      #B8922A;
    --c-steel:     #4A6E8A;
    --c-best:      #1A3A2A;
    --c-brilliant: #2C6B4A;
    --c-great:     #5A9E7A;
    --c-blunder:   #B53541;
    --c-mistake:   #CE3A4A;
    --c-inaccuracy:#E07B7B;
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
    font-family: 'Playfair Display SC', 'Cormorant Garamond', Georgia, serif !important;
    font-size: 2.2rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em;
    color: var(--c-forest) !important;
  }
  h2, [data-testid="stHeading"] h2, .stApp h2 {
    font-family: 'Playfair Display SC', 'Cormorant Garamond', Georgia, serif !important;
    font-size: 1.6rem !important;
    font-weight: 400 !important;
    letter-spacing: 0.03em;
    color: var(--c-forest) !important;
  }
  h3, [data-testid="stHeading"] h3, .stApp h3 {
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 1.25rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em;
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
    background: rgba(242, 230, 208, 0.35) !important;
    border: 1.5px solid var(--c-ebony) !important;
    border-radius: 2px;
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
    border-radius: 2px;
    overflow: hidden;
    border: 1.5px solid var(--c-ebony);
    background: rgba(242, 230, 208, 0.35);
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
    border-width: 3.75px;
    background: transparent;
    color: var(--c-best);
  }
  .analysis-stat-card--brilliant {
    border-color: var(--c-brilliant);
    border-width: 3.75px;
    background: transparent;
    color: var(--c-brilliant);
  }
  .analysis-stat-card--great {
    border-color: var(--c-great);
    border-width: 3.75px;
    background: transparent;
    color: var(--c-great);
  }
  .analysis-stat-card--mistake {
    border-color: var(--c-mistake);
    border-width: 3.75px;
    background: transparent;
    color: var(--c-mistake);
  }
  .analysis-stat-card--blunder {
    border-color: var(--c-blunder);
    border-width: 3.75px;
    background: transparent;
    color: var(--c-blunder);
  }
  .analysis-stat-card--inaccuracy {
    border-color: var(--c-inaccuracy);
    border-width: 3.75px;
    background: transparent;
    color: var(--c-inaccuracy);
  }
  .analysis-stat-card--accuracy {
    border-color: var(--c-smoke);
    background: rgba(74, 74, 74, 0.1);
    color: var(--c-smoke);
  }

  .analysis-stat-row-gap {
    height: 1rem;
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
    border-right: 2px solid var(--c-ebony) !important;
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
    border: 1.5px solid var(--c-ebony) !important;
    color: var(--c-forest) !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.8125rem !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    border-radius: 1px;
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
    border-color: var(--c-ebony) !important;
    opacity: 0.25;
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
    border-bottom-color: var(--c-crimson) !important;
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
    border-bottom: 2px solid var(--c-ebony) !important;
  }

  /* ── Link color ── */
  a, a:visited {
    color: var(--c-blunder) !important;
  }
  a:hover {
    color: var(--c-whisky) !important;
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
    welcome_page = st.Page(
        "app/web/pages/welcome.py",
        title="Welcome",
        icon="♟",
        url_path="welcome",
        default=True,
    )
    opening_analysis_page = st.Page(
        "app/web/pages/opening_analysis.py",
        title="Opening Analysis",
        icon="🧭",
        url_path="opening-analysis",
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
    members_page = st.Page(
        "app/web/pages/club_members.py",
        title="Club Members",
        icon="♟",
        url_path="club-members",
    )

    authenticated = not settings.auth_enabled or is_authenticated()

    if settings.auth_enabled:
        if authenticated:
            _logout = st.Page(logout_page, title="Sign Out", icon="🚪", url_path="logout")
            pages: dict | list = {
                "": [welcome_page, opening_analysis_page, analysis_page, search_page],
                "Admin": [status_page, members_page],
                "Account": [_logout],
            }
        else:
            _login = st.Page(login_page, title="Sign In", icon="🔑", url_path="login")
            pages = {
                "": [welcome_page, opening_analysis_page, analysis_page, search_page],
                "Admin": [status_page, members_page],
                "Account": [_login],
            }
    else:
        pages = {
            "": [welcome_page, opening_analysis_page, analysis_page, search_page],
            "Admin": [status_page, members_page],
        }

    nav = st.navigation(pages, position="sidebar")
    render_admin_sidebar()
    nav.run()
