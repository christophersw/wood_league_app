from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import streamlit as st

from app.config import get_settings
from app.services.auth_service import AuthService, AuthUser

_AUTH_KEY = "auth_user_id"
_USER_CACHE_KEY = "auth_user_obj"
# Set in the session after explicit logout to block cookie re-hydration.
# st.context.cookies reads the initial HTTP request headers, so JavaScript
# cookie changes aren't visible within the same WebSocket session. Without
# this flag, a logout + rerun would re-authenticate from the still-visible
# cookie and immediately log the user back in.
_LOGGED_OUT_KEY = "auth_logged_out"
_COOKIE_NAME = "woodland_auth"


# ---------------------------------------------------------------------------
# Public helpers used by the entrypoint to build dynamic navigation
# ---------------------------------------------------------------------------

def is_authenticated() -> bool:
    """Return True when the current session has a valid logged-in user."""
    settings = get_settings()
    if not settings.auth_enabled:
        return True

    # Explicit logout in this session — ignore the cookie entirely.
    if st.session_state.get(_LOGGED_OUT_KEY):
        return False

    service = AuthService()

    # Fast path: session_state already has the user.
    if _current_user(service) is not None:
        return True

    # Slow path: hydrate from cookie on first run of a new session.
    cookie_token = st.context.cookies.get(_COOKIE_NAME)
    if cookie_token:
        user = service.verify_login_token(str(cookie_token))
        if user is not None:
            st.session_state[_AUTH_KEY] = user.id
            st.session_state[_USER_CACHE_KEY] = user
            return True

    return False


def get_current_user() -> AuthUser | None:
    """Return the current AuthUser or None."""
    if st.session_state.get(_LOGGED_OUT_KEY):
        return None
    return _current_user(AuthService())


# ---------------------------------------------------------------------------
# Page functions — used as st.Page(login_page) / st.Page(logout_page)
# ---------------------------------------------------------------------------

def require_auth() -> None:
    """Page-level auth guard. Call at the top of any protected page.

    If the user is unauthenticated, renders the login form inline and stops
    the page. The URL and query params are preserved, so after login the
    correct page and game_id load automatically.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return
    if not is_authenticated():
        login_page()
        st.stop()


def login_page() -> None:
    """Login form — used both as a standalone page and inline by require_auth()."""
    service = AuthService()
    st.header("Sign In")
    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In", width='stretch')

    if submitted:
        user = service.authenticate(email, password)
        if user is None:
            st.error("Invalid email or password.")
        else:
            token = service.create_login_token(user.id)
            st.session_state[_AUTH_KEY] = user.id
            st.session_state[_USER_CACHE_KEY] = user
            st.session_state.pop(_LOGGED_OUT_KEY, None)
            _set_auth_cookie(token, int(get_settings().auth_token_ttl_seconds))


def logout_page() -> None:
    """Logout page — marks session as logged out, clears state and cookie, reruns."""
    # Mark this session so is_authenticated() ignores the cookie on the rerun.
    # The JS cookie clear fires in this render; new sessions/tabs will see it gone.
    st.session_state[_LOGGED_OUT_KEY] = True
    st.session_state.pop(_AUTH_KEY, None)
    st.session_state.pop(_USER_CACHE_KEY, None)
    _clear_auth_cookie()
    st.rerun()


def render_admin_sidebar() -> None:
    """Render signed-in user info in the sidebar."""
    user = get_current_user()
    if user is None:
        return

    with st.sidebar:
        st.caption(f"Signed in as **{user.email}** ({user.role})")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _current_user(service: AuthService) -> AuthUser | None:
    user_id = st.session_state.get(_AUTH_KEY)
    if user_id is None:
        return None
    # Serve from session cache to avoid a DB round-trip on every render.
    cached = st.session_state.get(_USER_CACHE_KEY)
    if isinstance(cached, AuthUser) and cached.id == user_id:
        return cached
    user = service.get_user(int(user_id))
    if user is None:
        st.session_state.pop(_AUTH_KEY, None)
        st.session_state.pop(_USER_CACHE_KEY, None)
    else:
        st.session_state[_USER_CACHE_KEY] = user
    return user


def _set_auth_cookie(token: str, ttl_seconds: int) -> None:
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    cookie_str = f"{_COOKIE_NAME}={token}; expires={expires}; path=/; SameSite=Lax"
    # Set cookie and reload in the same script so the cookie is committed before
    # the next page load. st.rerun() would trigger a new WebSocket render cycle
    # before the browser processes this delta, so the cookie would never be set.
    st.html(
        f"<script>document.cookie = {json.dumps(cookie_str)}; window.location.reload();</script>",
        unsafe_allow_javascript=True,
    )


def _clear_auth_cookie() -> None:
    cookie_str = (
        f"{_COOKIE_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax"
    )
    st.html(
        f"<script>document.cookie = {json.dumps(cookie_str)};</script>",
        unsafe_allow_javascript=True,
    )
