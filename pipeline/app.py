"""
PRAL Drone System -- Pipeline Navigator

Run: streamlit run pipeline/app.py
"""
import streamlit as st

st.set_page_config(
    page_title="PRAL Drone System",
    page_icon="🚁",
    layout="wide",
)

pages = [
    st.Page("stage1b_page.py",       title="Stage 1 -- AOI Annotation",    icon=":material/my_location:"),
    st.Page("visualize_stage2.py",  title="Stage 2 -- Survey & Geometry",  icon=":material/straighten:"),
    st.Page("visualize_stage3.py",  title="Stage 3 -- Orbit & 3DGS",       icon=":material/rotate_right:"),
    st.Page("stage4_streamlit.py",  title="Stage 4 -- Interest Field",     icon=":material/local_fire_department:"),
    st.Page("stage5_visualize.py",  title="Stage 5 -- Path Optimization",  icon=":material/route:"),
]

pg = st.navigation(pages)
pg.run()
