import streamlit as st
import pandas as pd
from app.services.db import list_events, list_cameras

st.set_page_config(page_title="Video Intelligence", page_icon="◉", layout="wide")
st.markdown("""
<style>
[data-testid="stAppViewContainer"] {background:#070b12;color:#eef3f8;}
[data-testid="stSidebar"] {background:#0b111b;}
.block-container {max-width:1400px;}
.card {background:#101925;border:1px solid #203044;border-radius:16px;padding:18px;margin-bottom:14px;}
</style>
""", unsafe_allow_html=True)

st.title("◉ Intelligent Video Intelligence")
st.caption("Multi-entity classification • multi-camera tracking • contextual analysis • temporal incident review")

cameras = list_cameras()
rows = list_events(500)

st.subheader("Cameras")
if cameras:
    cam_df = pd.DataFrame(cameras)
    st.dataframe(cam_df[["camera_id", "name", "group", "status", "last_seen", "last_error"]],
                 use_container_width=True, hide_index=True)
else:
    st.info("No cameras have reported in yet. Start run.py (single camera) or run_multi.py (multi-camera).")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Incidents (all types)", len(rows))
col2.metric("Incident candidates", sum(r["event_type"] == "INCIDENT_CANDIDATE" for r in rows))
col3.metric("Review events", sum(r["event_type"] == "REVIEW" for r in rows))
col4.metric("Cameras reporting", len(set(r["camera_id"] for r in rows)) if rows else 0)

if rows:
    df = pd.DataFrame(rows)

    st.subheader("Incidents by type")
    by_type = df["incident_type"].value_counts() if "incident_type" in df else df["event_type"].value_counts()
    st.bar_chart(by_type)

    st.subheader("Incidents by camera")
    by_camera = df["camera_id"].value_counts()
    st.bar_chart(by_camera)

    st.subheader("Incident timeline")
    cols = [c for c in ["id", "camera_id", "incident_type", "event_type", "confidence", "timestamp",
                         "track_ids", "reasoning", "cross_camera_links"] if c in df.columns]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)

    for r in rows[:20]:
        title = f"{r.get('incident_type', r['event_type'])} · {r['camera_id']} · {r['timestamp']}"
        with st.expander(title):
            st.json(r)
else:
    st.info("No candidate incidents have been stored yet.")
