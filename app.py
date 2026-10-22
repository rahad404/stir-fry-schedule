"""Routine maker - build a conflict-free weekly class routine."""

import streamlit as st

st.set_page_config(
    page_title="Routine maker",
    page_icon=":material/calendar_month:",
    layout="wide",
)

page = st.navigation(
    [
        st.Page(
            "app_pages/builder.py",
            title="Routine builder",
            icon=":material/calendar_month:",
            default=True,
        ),
        st.Page(
            "app_pages/explorer.py",
            title="Course explorer",
            icon=":material/travel_explore:",
        ),
        st.Page(
            "app_pages/guide.py",
            title="Filter guide",
            icon=":material/tips_and_updates:",
        ),
    ]
)

page.run()
