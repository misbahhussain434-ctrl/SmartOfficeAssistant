from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from office_assistant.db_sqlite import (
    add_calendar_event,
    add_email,
    add_tasks,
    conn_scope,
    count_rows,
    get_email,
    iter_tasks_with_email,
    list_calendar_events,
    list_tasks,
    set_task_status,
)
from office_assistant.scheduler import events_from_db_rows, suggest_meeting_time
from office_assistant.summarizer import format_preview, parse_tasks, summarize_text


st.set_page_config(page_title="Smart Office Assistant", layout="wide")
st.title("Smart Office Assistant")
st.caption("Upload an email dataset, summarize messages, create tasks, and suggest meeting times.")


@st.cache_data(show_spinner=False)
def load_csv_from_upload(file_bytes: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(file_bytes))


def _pick_column(columns: list[str], candidates: list[str]) -> str | None:
    lower = {c.lower(): c for c in columns}
    for cand in candidates:
        for c in columns:
            if cand in c.lower():
                return c
        if cand in lower:
            return lower[cand]
    return None


def assistant_reply(prompt: str, db_path: str) -> str:
    p = (prompt or "").lower().strip()
    if not p:
        return "Ask me to summarize an email, create tasks, or suggest a meeting time."

    if "meeting" in p or "schedule" in p or "calendar" in p:
        with conn_scope(db_path) as conn:
            events = list_calendar_events(conn)
        try:
            slot = suggest_meeting_time(
                events=events_from_db_rows(events),
                duration_hours=1,
            )
            return f"Next available 1-hour slot: {slot.strftime('%Y-%m-%d %H:%M')}."
        except Exception as e:
            return f"Couldn't find a free slot in the search window: {e}"

    if "task" in p or "todo" in p:
        with conn_scope(db_path) as conn:
            pending = len(list_tasks(conn, filter_status="Pending"))
        return f"You currently have {pending} pending task(s). Use the Tasks tab to update them."

    return (
        "Use the Email tab to upload a CSV or paste an email, then click “Generate summary”. "
        "After that, add tasks in the same tab, or manage tasks in the Tasks tab."
    )


if "selected_email_id" not in st.session_state:
    st.session_state.selected_email_id = None
if "last_uploaded_df" not in st.session_state:
    st.session_state.last_uploaded_df = None
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []


with st.sidebar:
    st.header("Settings")
    db_path = st.text_input("SQLite DB path", value="office_assistant.db")

    if st.button("Show DB info"):
        with conn_scope(db_path) as conn:
            st.write(count_rows(conn))


tabs = st.tabs(["Email", "Tasks", "Calendar", "Assistant Chat"])


with tabs[0]:
    st.subheader("Email -> Summary + Tasks")

    csv_file = st.file_uploader("Upload a CSV with email data (optional)", type=["csv"])

    if csv_file is not None:
        uploaded_df = load_csv_from_upload(csv_file.getvalue())
        st.session_state.last_uploaded_df = uploaded_df
        st.write(
            f"Loaded rows: {len(uploaded_df)} | Columns: {', '.join(map(str, uploaded_df.columns))}"
        )

    df = st.session_state.last_uploaded_df if st.session_state.last_uploaded_df is not None else None

    default_body_col = None
    default_sender_col = None
    default_subject_col = None
    default_id_col = None
    if df is not None:
        cols = [str(c) for c in df.columns]
        default_body_col = _pick_column(cols, ["body", "message", "text", "content"])
        default_sender_col = _pick_column(cols, ["from", "sender"])
        default_subject_col = _pick_column(cols, ["subject"])
        default_id_col = _pick_column(cols, ["id", "email_id", "message_id"])

    if df is not None and default_body_col is not None:
        cols = [str(c) for c in df.columns]
        body_col = st.selectbox(
            "Body/Text column",
            options=cols,
            index=cols.index(default_body_col),
        )
        sender_col = st.selectbox(
            "Sender column (optional)",
            options=["(none)"] + cols,
            index=(1 + cols.index(default_sender_col)) if default_sender_col in cols else 0,
        )
        subject_col = st.selectbox(
            "Subject column (optional)",
            options=["(none)"] + cols,
            index=(1 + cols.index(default_subject_col)) if default_subject_col in cols else 0,
        )
        id_col = st.selectbox(
            "Row ID column (optional)",
            options=["(none)"] + cols,
            index=(1 + cols.index(default_id_col)) if default_id_col in cols else 0,
        )

        row_idx = st.slider("Pick a row", min_value=0, max_value=max(0, len(df) - 1), value=0)
        row = df.iloc[row_idx]

        body = str(row.get(body_col, "") if hasattr(row, "get") else row[body_col])
        preview = format_preview(body)
        st.text_area("Body preview (read-only)", value=preview, height=110)

        sender = None if sender_col == "(none)" else str(
            row.get(sender_col, "") if hasattr(row, "get") else row[sender_col]
        )
        subject = None if subject_col == "(none)" else str(
            row.get(subject_col, "") if hasattr(row, "get") else row[subject_col]
        )
        source_row_id = None if id_col == "(none)" else str(
            row.get(id_col, "") if hasattr(row, "get") else row[id_col]
        )
    else:
        st.info("No CSV uploaded (or could not detect a body column). Paste an email below.")
        sender = st.text_input("Sender (optional)")
        subject = st.text_input("Subject (optional)")
        source_row_id = st.text_input("Source row id (optional)", value="")
        body = st.text_area("Email body", height=200)

    st.divider()
    with st.expander("Summarization settings", expanded=False):
        model_name = st.selectbox(
            "Summarization model",
            options=[
                "sshleifer/distilbart-cnn-12-6",
                "facebook/bart-large-cnn",
            ],
            index=0,
        )
        max_new_tokens = st.slider("max_new_tokens", 60, 220, 160, step=10)
        min_new_tokens = st.slider("min_new_tokens", 10, 120, 30, step=5)

    if st.button("Generate summary", type="primary"):
        if not (body or "").strip():
            st.warning("Please provide an email body first.")
        else:
            with st.spinner("Summarizing..."):
                summary = summarize_text(
                    text=body,
                    model_name=model_name,
                    max_new_tokens=max_new_tokens,
                    min_new_tokens=min_new_tokens,
                )
            with conn_scope(db_path) as conn:
                email_id = add_email(
                    conn,
                    source_row_id=(source_row_id or None) or None,
                    sender=sender or None,
                    receiver=None,
                    subject=subject or None,
                    body=body,
                    summary=summary,
                )
            st.session_state.selected_email_id = email_id
            st.success("Summary generated and saved to the database.")
            st.write("**Summary**")
            st.write(summary)

    st.subheader("Create tasks for the selected email")

    if st.session_state.selected_email_id is None:
        st.caption("Generate a summary first to create tasks tied to an email.")
    else:
        with conn_scope(db_path) as conn:
            email_row = get_email(conn, int(st.session_state.selected_email_id))

        if email_row is None:
            st.warning("Selected email not found in DB.")
        else:
            st.caption(f"Email: {email_row.get('subject') or '(no subject)'} (id={email_row.get('id')})")

            default_tasks = ""
            if email_row.get("summary"):
                default_tasks = str(email_row["summary"])[:1200]

            tasks_str = st.text_area(
                "Tasks (comma-separated)",
                value=default_tasks,
                height=90,
                help="Example: 'Send report, Book meeting, Follow up with team'",
            )
            priorities_str = st.text_input(
                "Priorities (comma-separated: low, medium, high)",
                value="medium, medium, medium",
            )
            assigned_to = st.text_input("Assigned to (optional)", value="")

            if st.button("Create tasks from this input"):
                parsed = parse_tasks(tasks_str, priorities_str)
                parsed = [t for t in parsed if t.get("task")]
                if not parsed:
                    st.warning("Please enter at least one task.")
                else:
                    with conn_scope(db_path) as conn:
                        added = add_tasks(
                            conn,
                            email_id=int(email_row["id"]),
                            tasks=parsed,
                            assigned_to=(assigned_to or None) or None,
                        )
                    st.success(f"Added {added} task(s).")


with tabs[1]:
    st.subheader("Task Management")
    filter_status = st.selectbox("Filter status", options=["All", "Pending", "Completed"], index=0)

    with conn_scope(db_path) as conn:
        tasks = list(iter_tasks_with_email(conn, filter_status=filter_status))

    if not tasks:
        st.caption("No tasks yet. Create them from the Email tab.")
    else:
        for task in tasks:
            title = task.get("title") or ""
            task_id = int(task.get("id"))
            status = task.get("status") or ""
            priority = task.get("priority") or ""
            assigned_to = task.get("assigned_to")
            email_subject = task.get("email_subject")

            st.markdown(f"**{title}**")
            meta = f"Priority: `{priority}` | Status: `{status}`"
            if assigned_to:
                meta += f" | Assigned to: `{assigned_to}`"
            st.caption(meta)
            if email_subject:
                st.caption(f"Email: {email_subject}")

            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if status != "Completed" and st.button("Mark completed", key=f"complete_{task_id}"):
                    with conn_scope(db_path) as conn:
                        set_task_status(conn, task_id=task_id, status="Completed")
                    st.rerun()
            with col2:
                if status != "Pending" and st.button("Reopen", key=f"reopen_{task_id}"):
                    with conn_scope(db_path) as conn:
                        set_task_status(conn, task_id=task_id, status="Pending")
                    st.rerun()
            with col3:
                st.caption(f"Task id: {task_id}")
            st.divider()


with tabs[2]:
    st.subheader("Calendar")
    duration_hours = st.slider("Duration (hours)", min_value=1, max_value=4, value=1)

    with conn_scope(db_path) as conn:
        events = list_calendar_events(conn)

    if not events:
        st.caption("No calendar events yet.")
    else:
        for ev in events:
            st.markdown(f"**{ev.get('title') or ''}**")
            st.caption(f"{ev.get('start_iso')} -> {ev.get('end_iso')}")
            st.divider()

    st.subheader("Suggest next available slot")
    if st.button("Suggest & add meeting"):
        slot_start = suggest_meeting_time(
            events=events_from_db_rows(events),
            duration_hours=duration_hours,
        )
        slot_end = slot_start + timedelta(hours=duration_hours)
        title = f"Meeting ({duration_hours}h)"
        with conn_scope(db_path) as conn:
            add_calendar_event(
                conn,
                start_iso=slot_start.isoformat(timespec="minutes"),
                end_iso=slot_end.isoformat(timespec="minutes"),
                title=title,
            )
        st.success(f"Added: {slot_start.strftime('%Y-%m-%d %H:%M')} ({duration_hours}h)")
        st.rerun()


with tabs[3]:
    st.subheader("Assistant Chat")

    prompt = st.chat_input("Ask about meetings or tasks...")
    if prompt is not None:
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        reply = assistant_reply(prompt, db_path=db_path)
        st.session_state.chat_messages.append({"role": "assistant", "content": reply})

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

