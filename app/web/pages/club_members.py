"""Admin — Club Members management.

Add, edit, and remove players from the club roster.
Invite members to create login accounts.
Restricted to admin users.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st
from sqlalchemy import select

from app.services.auth_service import AuthService
from app.storage.database import get_session, init_db
from app.storage.models import GameParticipant, Player, User
from app.web.components.auth import get_current_user, require_auth

require_auth()
init_db()

# ── Admin guard ───────────────────────────────────────────────────────────────

user = get_current_user()
if user is None or user.role != "admin":
    st.error("This page is restricted to administrators.")
    st.stop()

_auth_service = AuthService()

# ── Data helpers ──────────────────────────────────────────────────────────────


def _str_or_none(val: object) -> str | None:
    """Convert a dataframe cell to a stripped string or None (handles NaN)."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    return s or None


def _load_players() -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(
            select(
                Player.id,
                Player.username,
                Player.display_name,
                Player.name,
                Player.email,
            ).order_by(Player.username)
        ).all()
    return pd.DataFrame([r._asdict() for r in rows]) if rows else pd.DataFrame(
        columns=["id", "username", "display_name", "name", "email"]
    )


def _has_login(email: str | None) -> bool:
    if not email:
        return False
    with get_session() as s:
        return s.execute(select(User.id).where(User.email == email)).first() is not None


def _save_player_edits(original: pd.DataFrame, edited: pd.DataFrame) -> tuple[int, list[str]]:
    saved, errors = 0, []
    for _, orig_row in original.iterrows():
        pid = int(orig_row["id"])
        edit_rows = edited[edited["id"] == pid]
        if edit_rows.empty:
            continue
        edit_row = edit_rows.iloc[0]
        new_name = _str_or_none(edit_row["name"])
        new_email = _str_or_none(edit_row["email"])
        if new_name == orig_row["name"] and new_email == orig_row["email"]:
            continue
        if new_email:
            with get_session() as s:
                clash = s.execute(
                    select(Player.id).where(Player.email == new_email, Player.id != pid)
                ).first()
            if clash:
                errors.append(f"Email '{new_email}' is already used by another member.")
                continue
        with get_session() as s:
            player = s.get(Player, pid)
            if player:
                player.name = new_name
                player.email = new_email
                s.commit()
                saved += 1
    return saved, errors


def _add_player(username: str, display_name: str, name: str, email: str) -> str | None:
    username = username.strip().lower()
    display_name = display_name.strip() or username
    name = _str_or_none(name)
    email = _str_or_none(email)
    if not username:
        return "Username is required."
    with get_session() as s:
        if s.execute(select(Player.id).where(Player.username == username)).first():
            return f"A member with username '{username}' already exists."
        if email and s.execute(select(Player.id).where(Player.email == email)).first():
            return f"Email '{email}' is already used by another member."
        s.add(Player(username=username, display_name=display_name, name=name, email=email))
        s.commit()
    return None


def _game_count(player_id: int) -> int:
    with get_session() as s:
        return s.query(GameParticipant).filter_by(player_id=player_id).count()


def _delete_player(player_id: int) -> None:
    with get_session() as s:
        s.query(GameParticipant).filter_by(player_id=player_id).delete()
        player = s.get(Player, player_id)
        if player:
            s.delete(player)
        s.commit()


# ── Page ──────────────────────────────────────────────────────────────────────

st.title("Club Members")
st.caption("Manage the roster — edit details, invite members to log in, or remove them.")

players_df = _load_players()

# ── Roster ────────────────────────────────────────────────────────────────────

st.subheader("Roster")

if players_df.empty:
    st.info("No members yet. Add one below.")
else:
    st.caption("Edit **Name** and **Email** directly in the table, then click Save.")

    edited_df = st.data_editor(
        players_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "id":           st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "username":     st.column_config.TextColumn("Chess.com Username", disabled=True),
            "display_name": st.column_config.TextColumn("Display Name", disabled=True),
            "name":         st.column_config.TextColumn("Full Name"),
            "email":        st.column_config.TextColumn("Email"),
        },
        key="roster_editor",
    )

    if st.button("Save Changes", type="primary"):
        n_saved, errs = _save_player_edits(players_df, edited_df)
        for e in errs:
            st.error(e)
        if n_saved:
            st.success(f"Saved {n_saved} change{'s' if n_saved != 1 else ''}.")
            st.rerun()
        elif not errs:
            st.info("No changes to save.")

    # ── Login access ─────────────────────────────────────────────────────────

    st.markdown("#### Login Access")
    st.caption("Create login credentials for members who don't have an account yet.")

    for _, row in players_df.iterrows():
        pid = int(row["id"])
        email = _str_or_none(row["email"])
        display = row["name"] or row["display_name"]
        has_login = _has_login(email)

        col_name, col_status, col_action = st.columns([3, 2, 3])
        col_name.markdown(f"**{display}** `{row['username']}`")

        if has_login:
            col_status.success("Has login")
            col_action.caption(email or "")
        elif not email:
            col_status.warning("No email set")
            col_action.caption("Set an email above to enable invite.")
        else:
            col_status.info("No login yet")
            with col_action:
                with st.popover("Invite…"):
                    st.markdown(f"Create login for **{display}** (`{email}`)")
                    with st.form(key=f"invite_{pid}"):
                        tmp_pw = st.text_input("Temporary password", type="password", help="At least 8 characters.")
                        role = st.selectbox("Role", ["member", "admin"], index=0)
                        if st.form_submit_button("Create Login", use_container_width=True):
                            try:
                                _auth_service.create_user(email, tmp_pw, role=role)
                                st.success(f"Login created for {email}.")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))

st.divider()

# ── Add member ────────────────────────────────────────────────────────────────

st.subheader("Add Member")

with st.form("add_member_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        new_username = st.text_input("Chess.com Username *", placeholder="e.g. magnus_carlsen")
        new_name     = st.text_input("Full Name", placeholder="e.g. Magnus Carlsen")
    with col2:
        new_display = st.text_input("Display Name", placeholder="Defaults to username if blank")
        new_email   = st.text_input("Email", placeholder="e.g. magnus@example.com")
    add_submitted = st.form_submit_button("Add Member", type="primary", use_container_width=True)

if add_submitted:
    err = _add_player(new_username, new_display, new_name, new_email)
    if err:
        st.error(err)
    else:
        st.success(f"Added **{new_username.strip().lower()}** to the roster.")
        st.rerun()

st.divider()

# ── Remove member ─────────────────────────────────────────────────────────────

st.subheader("Remove Member")

if players_df.empty:
    st.info("No members to remove.")
else:
    player_options = {
        f"{row['username']} ({row['name'] or row['display_name']})": int(row["id"])
        for _, row in players_df.iterrows()
    }
    selected_label = st.selectbox("Select member to remove", options=list(player_options.keys()))
    selected_id = player_options[selected_label]
    n_games = _game_count(selected_id)

    if n_games:
        st.warning(
            f"**{selected_label}** has **{n_games:,}** game record{'s' if n_games != 1 else ''}. "
            "These will be unlinked (game records themselves are kept)."
        )

    confirm = st.checkbox(f"I confirm I want to remove **{selected_label}**")
    if st.button("Remove Member", type="primary", disabled=not confirm):
        _delete_player(selected_id)
        st.success(f"Removed **{selected_label}** from the roster.")
        st.rerun()
