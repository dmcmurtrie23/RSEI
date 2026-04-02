"""
Catapult OpenField – Streamlit Dashboard
========================================
Run with:
    pip install streamlit requests pandas numpy plotly
    streamlit run catapult_app.py
"""

import time
import requests
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import date, timedelta, datetime

st.set_page_config(page_title="Catapult Dashboard", page_icon="⚡", layout="wide")
st.title("⚡ Catapult OpenField Dashboard")
st.markdown("Velocity metrics and high-speed distance analysis per athlete per session.")

BASE_URL = "https://connect-au.catapultsports.com/api/v6"

TARGET_SLUGS = [
    "max_vel",
    "velocity2_band6_total_distance",
    "velocity2_band7_total_distance",
    "velocity2_band8_total_distance",
]

# ── SESSION STATE INIT ────────────────────────────────────────────────────────
if "df" not in st.session_state:
    st.session_state.df = None

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔑 Connection Settings")
    api_token = st.text_input("API Token", type="password", placeholder="Paste your OpenField API token")
    st.markdown("---")
    st.header("📅 Date Range")
    date_from = st.date_input("From", value=date.today() - timedelta(days=90))
    date_to   = st.date_input("To",   value=date.today())
    fetch_btn = st.button("🔄 Fetch Data", use_container_width=True, type="primary")
    if st.button("🗑️ Clear Data", use_container_width=True):
        st.session_state.df = None
        st.rerun()
    st.markdown("---")
    st.caption("OpenField Cloud → Settings → API Tokens → Create")

# ── API HELPERS ───────────────────────────────────────────────────────────────
def api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def fetch_athletes(token):
    r = requests.get(f"{BASE_URL}/athletes", headers=api_headers(token), timeout=15)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])

def fetch_stats_for_athlete(token, athlete_id, start_dt, end_dt):
    payload = {
        "source": "cached_stats",
        "filters": [
            {"name": "athlete_id", "comparison": "=",  "values": [athlete_id]},
            {"name": "date",       "comparison": ">=", "values": [start_dt.strftime("%d/%m/%Y")]},
            {"name": "date",       "comparison": "<=", "values": [end_dt.strftime("%d/%m/%Y")]},
        ],
        "parameters": TARGET_SLUGS,
        "group_by": ["athlete", "activity"],
    }
    r = requests.post(f"{BASE_URL}/stats", headers=api_headers(token), json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])

def build_dataframe(rows):
    df = pd.DataFrame(rows)
    df["athlete_name"]  = df["athlete_name"].astype(str)
    df["activity_name"] = df["activity_name"].astype(str)

    df.rename(columns={
        "max_vel":                        "max_velocity",
        "velocity2_band6_total_distance": "band6_distance",
        "velocity2_band7_total_distance": "band7_distance",
        "velocity2_band8_total_distance": "band8_distance",
    }, inplace=True)

    for col in ["max_velocity", "band6_distance", "band7_distance", "band8_distance"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # All-time max velocity per athlete
    max_vel = (
        df.groupby("athlete_name")["max_velocity"]
        .max().reset_index()
        .rename(columns={"max_velocity": "max_velocity_alltime"})
    )
    df = df.merge(max_vel, on="athlete_name", how="left")

    # Total band distance
    df["total_band_distance"] = (
        df["band6_distance"].fillna(0) +
        df["band7_distance"].fillna(0) +
        df["band8_distance"].fillna(0)
    )

    # RSEI = (session max vel / all-time max vel) × total band 6+7+8 distance
    df["RSEI"] = (df["max_velocity"] / df["max_velocity_alltime"]) * df["total_band_distance"]

    return df

# ── FETCH DATA (only runs when button clicked) ────────────────────────────────
if fetch_btn:
    if not api_token:
        st.error("Please enter your API token.")
    else:
        try:
            start_dt = datetime.combine(date_from, datetime.min.time())
            end_dt   = datetime.combine(date_to,   datetime.max.time())

            athletes = fetch_athletes(api_token)
            st.info(f"**Step 1 – Athletes:** {len(athletes)} found.")

            rows     = []
            progress = st.progress(0, text="Fetching stats…")

            for i, ath in enumerate(athletes):
                progress.progress((i + 1) / len(athletes),
                                  text=f"Fetching: {ath.get('name') or ath.get('first_name', '')}")
                ath_id   = ath.get("id")
                ath_name = (
                    ath.get("name") or
                    f"{ath.get('first_name', '')} {ath.get('last_name', '')}".strip() or
                    f"Athlete {ath_id}"
                )

                try:
                    sessions = fetch_stats_for_athlete(api_token, ath_id, start_dt, end_dt)
                except requests.HTTPError as e:
                    if e.response.status_code == 429:
                        st.warning(f"Rate limited on {ath_name} — waiting 60s then retrying…")
                        time.sleep(60)
                        try:
                            sessions = fetch_stats_for_athlete(api_token, ath_id, start_dt, end_dt)
                        except Exception as e2:
                            st.warning(f"Still could not fetch {ath_name}: {e2}")
                            continue
                    else:
                        st.warning(f"Could not fetch {ath_name}: {e}")
                        continue
                except Exception as e:
                    st.warning(f"Could not fetch {ath_name}: {e}")
                    continue

                if i == 0 and sessions:
                    with st.expander("🔬 Raw API row (first athlete) — shows actual field names"):
                        st.json(sessions[0])

                for s in sessions:
                    activity_name = (
                        s.get("activity_name") or s.get("name") or
                        s.get("session_name")  or s.get("activity") or "Unknown"
                    )
                    rows.append({
                        "athlete_name":                   ath_name,
                        "activity_name":                  str(activity_name),
                        "date":                           s.get("date") or s.get("start_time"),
                        "max_vel":                        s.get("max_vel"),
                        "velocity2_band6_total_distance": s.get("velocity2_band6_total_distance"),
                        "velocity2_band7_total_distance": s.get("velocity2_band7_total_distance"),
                        "velocity2_band8_total_distance": s.get("velocity2_band8_total_distance"),
                    })

                time.sleep(1.5)

            progress.empty()

            if not rows:
                st.error("No data rows returned. Open the raw API row expander above to check field names.")
            else:
                st.session_state.df = build_dataframe(rows)
                st.success(f"✅ Loaded {len(st.session_state.df)} rows across {st.session_state.df['activity_name'].nunique()} activities.")

        except requests.HTTPError as e:
            st.error(f"API error: {e.response.status_code} – {e.response.text}")
        except Exception as e:
            import traceback
            st.error(f"Unexpected error: {e}")
            st.code(traceback.format_exc())

# ── DASHBOARD (renders from session_state — survives widget interactions) ─────
if st.session_state.df is not None:
    df = st.session_state.df

    # ── Player & session selectors ────────────────────────────────────────────
    st.markdown("### 🔎 Select Players & Sessions")
    c1, c2 = st.columns(2)
    with c1:
        athlete_opts = sorted(df["athlete_name"].dropna().unique())
        sel_athletes = st.multiselect(
            "👤 Athletes to Display",
            options=athlete_opts,
            default=athlete_opts,
            key="chart_athletes",
        )
    with c2:
        activity_opts = sorted(df["activity_name"].dropna().unique())
        sel_activities = st.multiselect(
            "📅 Sessions to Display",
            options=activity_opts,
            default=activity_opts,
            key="chart_activities",
        )

    if not sel_athletes or not sel_activities:
        st.warning("Please select at least one athlete and one session.")
    else:
        filtered = df[
            df["athlete_name"].isin(sel_athletes) &
            df["activity_name"].isin(sel_activities)
        ]

        # ── KPI cards ─────────────────────────────────────────────────────────
        st.markdown("### 📊 Summary")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Athletes",    filtered["athlete_name"].nunique())
        k2.metric("Sessions",    filtered["activity_name"].nunique())
        k3.metric("Avg Max Vel", f"{filtered['max_velocity'].mean():.2f} m/s")
        k4.metric("Avg RSEI",    f"{filtered['RSEI'].mean():.1f}")
        st.markdown("---")

        # ── Chart 1: RSEI by athlete & session ────────────────────────────────
        st.markdown("### 🏃 RSEI by Athlete & Session")
        st.caption("(Session Max Velocity ÷ Athlete All-Time Max Velocity) × Total Band 6+7+8 Distance")
        fig1 = px.bar(
            filtered.sort_values("activity_name"),
            x="athlete_name", y="RSEI",
            color="activity_name", barmode="group",
            labels={"athlete_name": "Athlete", "RSEI": "RSEI", "activity_name": "Session"},
            color_discrete_sequence=px.colors.qualitative.Bold,
        )
        fig1.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(size=13), legend_title="Session",
        )
        st.plotly_chart(fig1, use_container_width=True)

        # ── Chart 2: Max Vel vs all-time max ──────────────────────────────────
        st.markdown("### ⚡ Session Max Velocity vs All-Time Max Velocity")
        fig2 = go.Figure()
        for athlete in sel_athletes:
            ath_df = filtered[filtered["athlete_name"] == athlete].sort_values("activity_name")
            if ath_df.empty:
                continue
            fig2.add_trace(go.Scatter(
                x=ath_df["activity_name"], y=ath_df["max_velocity"],
                mode="lines+markers", name=f"{athlete} – Max Vel", line=dict(width=2),
            ))
            fig2.add_trace(go.Scatter(
                x=ath_df["activity_name"], y=ath_df["max_velocity_alltime"],
                mode="lines", name=f"{athlete} – All-Time Max",
                line=dict(width=2, dash="dash"),
            ))
        fig2.update_layout(
            xaxis_title="Session", yaxis_title="Velocity (m/s)",
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(size=13), legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig2, use_container_width=True)

        # ── Chart 3: Band breakdown ────────────────────────────────────────────
        st.markdown("### 📏 High-Speed Distance Breakdown (Bands 6 / 7 / 8)")
        band_df = (
            filtered.groupby("athlete_name")[["band6_distance", "band7_distance", "band8_distance"]]
            .sum().reset_index()
            .melt(id_vars="athlete_name", var_name="Band", value_name="Distance (m)")
        )
        band_df["Band"] = band_df["Band"].map({
            "band6_distance": "Band 6",
            "band7_distance": "Band 7",
            "band8_distance": "Band 8",
        })
        fig3 = px.bar(
            band_df, x="athlete_name", y="Distance (m)",
            color="Band", barmode="stack",
            labels={"athlete_name": "Athlete"},
            color_discrete_map={"Band 6": "#3B82F6", "Band 7": "#F59E0B", "Band 8": "#EF4444"},
        )
        fig3.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(size=13),
        )
        st.plotly_chart(fig3, use_container_width=True)

        # ── Data table ────────────────────────────────────────────────────────
        st.markdown("### 📋 Full Results Table")
        table_athlete_opts = sorted(filtered["athlete_name"].unique())
        table_sel = st.multiselect(
            "Filter table by athlete",
            options=table_athlete_opts,
            default=table_athlete_opts,
            key="table_athletes",
        )
        table_data = filtered[filtered["athlete_name"].isin(table_sel)]

        display_df = table_data[[
            "athlete_name", "activity_name", "date",
            "max_velocity", "max_velocity_alltime",
            "band6_distance", "band7_distance", "band8_distance",
            "total_band_distance", "RSEI",
        ]].copy()
        display_df.columns = [
            "Athlete", "Session", "Date",
            "Max Velocity", "All-Time Max Vel",
            "Band 6 Dist", "Band 7 Dist", "Band 8 Dist",
            "Total Band Dist", "RSEI",
        ]
        st.dataframe(
            display_df.style.format({
                "Max Velocity":    "{:.2f}",
                "All-Time Max Vel":"{:.2f}",
                "Band 6 Dist":     "{:.1f}",
                "Band 7 Dist":     "{:.1f}",
                "Band 8 Dist":     "{:.1f}",
                "Total Band Dist": "{:.1f}",
                "RSEI":            "{:.1f}",
            }).background_gradient(subset=["RSEI"], cmap="YlOrRd"),
            use_container_width=True,
            height=450,
        )

        csv = display_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download CSV", data=csv,
            file_name="catapult_results.csv", mime="text/csv",
        )

else:
    st.info("👈 Enter your API token in the sidebar and click **Fetch Data** to get started.")
