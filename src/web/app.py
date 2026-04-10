"""
PEA Dashboard — Streamlit web interface for the Protest Event Analysis pipeline.

Provides:
  - Launch tab: configure and trigger pipeline runs via Azure Container Apps Job
  - Events tab: browse, filter, and map extracted events from Azure Blob Storage
  - History tab: monitor recent job executions and their status

Environment variables required:
  AZURE_STORAGE_CONNECTION_STRING  — read results from blob storage
  AZURE_SUBSCRIPTION_ID            — for job trigger API calls
  AZURE_RESOURCE_GROUP             — resource group containing the job
  CONTAINER_APPS_JOB_NAME          — name of the Container Apps Job
  BLOB_CONTAINER_NAME              — blob container (default: pea-outputs)
  BLOB_PREFIX                      — path prefix inside container (default: runs)

For local dev, az login credentials are used automatically via DefaultAzureCredential.
In Azure, the app's managed identity is used.
"""

import json
import os
from datetime import datetime
from io import StringIO
from typing import Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from azure.identity import DefaultAzureCredential, CredentialUnavailableError
from azure.storage.blob import BlobServiceClient

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PEA — Protest Event Analysis",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ─────────────────────────────────────────────────────────────────

COUNTRIES = {
    "Nigeria": "NG",
    "South Africa": "ZA",
    "Uganda": "UG",
    "Algeria": "DZ",
    "Libya": "LY",
    "Angola": "AO",
    "Kenya": "KE",
    "Somalia": "SO",
    "Tanzania": "TZ",
    "Ghana": "GH",
    "Ethiopia": "ET",
    "Senegal": "SN",
    "Zimbabwe": "ZW",
    "Cameroon": "CM",
    "Sudan": "SD",
    "South Sudan": "SS",
    "Mozambique": "MZ",
    "Zambia": "ZM",
    "Mali": "ML",
    "Niger": "NE",
    "Rwanda": "RW",
    "DRC": "CD",
    "Ivory Coast": "CI",
}

EVENT_TYPES = [
    "demonstration_march",
    "strike_boycott",
    "confrontation",
    "occupation_seizure",
    "petition_signature",
    "vigil",
    "hunger_strike",
    "riot",
]

TURMOIL_COLOURS = {
    "high": "#e74c3c",
    "medium": "#f39c12",
    "low": "#2ecc71",
    "unknown": "#95a5a6",
}

# ── Azure helpers ─────────────────────────────────────────────────────────────


@st.cache_resource(ttl=3500)
def _get_credential():
    """Return DefaultAzureCredential (cached for ~1 hour to avoid re-auth)."""
    try:
        cred = DefaultAzureCredential()
        cred.get_token("https://management.azure.com/.default")
        return cred
    except CredentialUnavailableError:
        return None


def _mgmt_token() -> Optional[str]:
    cred = _get_credential()
    if cred is None:
        return None
    try:
        return cred.get_token("https://management.azure.com/.default").token
    except Exception:
        return None


def _blob_client() -> Optional[BlobServiceClient]:
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if not conn_str:
        return None
    try:
        return BlobServiceClient.from_connection_string(conn_str)
    except Exception:
        return None


def trigger_pipeline_job(pipeline_args: list) -> dict:
    """
    Trigger a new Azure Container Apps Job execution with custom pipeline args.
    Uses the Azure Resource Manager REST API.
    Returns the API response dict.
    """
    token = _mgmt_token()
    if not token:
        raise RuntimeError(
            "Azure credentials not available. Run 'az login' locally, "
            "or ensure the app has a Managed Identity with Contributor role on the job."
        )

    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
    resource_group = os.environ.get("AZURE_RESOURCE_GROUP", "")
    job_name = os.environ.get("CONTAINER_APPS_JOB_NAME", "")

    if not all([subscription_id, resource_group, job_name]):
        raise RuntimeError(
            "Missing env vars: AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, "
            "CONTAINER_APPS_JOB_NAME must all be set."
        )

    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.App/jobs/{job_name}/start"
        f"?api-version=2023-05-01"
    )

    container_name = os.environ.get("CONTAINER_APP_CONTAINER_NAME", "pea-pipeline-job")
    payload = {
        "template": {
            "containers": [
                {
                    "name": container_name,
                    # Use `command` (not `args`) so the override replaces the full
                    # container entrypoint+args rather than just the Docker CMD slot.
                    # Without this, Azure ignores the override when the job template
                    # was built with an ENTRYPOINT-only Dockerfile (no CMD).
                    "command": [
                        "python",
                        "-m",
                        "src.acquisition.pipeline",
                    ]
                    + pipeline_args,
                }
            ]
        }
    }

    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def list_job_executions(limit: int = 10) -> list:
    """Return the most recent Container Apps Job executions."""
    token = _mgmt_token()
    if not token:
        return []

    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
    resource_group = os.environ.get("AZURE_RESOURCE_GROUP", "")
    job_name = os.environ.get("CONTAINER_APPS_JOB_NAME", "")

    if not all([subscription_id, resource_group, job_name]):
        return []

    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.App/jobs/{job_name}/executions"
        f"?api-version=2023-05-01"
    )

    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        executions = resp.json().get("value", [])
        return executions[:limit]
    except Exception as e:
        st.warning(f"Could not fetch job history: {e}")
        return []


@st.cache_data(ttl=120)
def load_events_from_blob() -> pd.DataFrame:
    """
    Load all events_*.jsonl files from Azure Blob Storage and return a DataFrame.
    Cached for 2 minutes to avoid hammering storage on every rerender.
    """
    client = _blob_client()
    if client is None:
        return pd.DataFrame()

    container_name = os.environ.get("BLOB_CONTAINER_NAME", "pea-outputs")
    prefix = os.environ.get("BLOB_PREFIX", "runs")

    try:
        container = client.get_container_client(container_name)
        blobs = list(container.list_blobs(name_starts_with=prefix))
        event_blobs = [
            b for b in blobs if b.name.endswith(".jsonl") and "/events_" in b.name
        ]

        if not event_blobs:
            return pd.DataFrame()

        all_events = []
        for blob in event_blobs:
            bc = container.get_blob_client(blob.name)
            content = bc.download_blob().readall().decode("utf-8")
            for line in content.splitlines():
                if line.strip():
                    try:
                        all_events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        if not all_events:
            return pd.DataFrame()

        df = pd.DataFrame(all_events)
        if "event_date" in df.columns:
            df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
        for col in ["participant_groups", "claims", "state_actors"]:
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: "; ".join(x) if isinstance(x, list) else (x or "")
                )
        return df

    except Exception as e:
        st.warning(f"Could not load events from blob storage: {e}")
        return pd.DataFrame()


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title("PEA Pipeline")
st.sidebar.caption("Protest Event Analysis · Global South")
st.sidebar.divider()

# Connection status
conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
job_name = os.environ.get("CONTAINER_APPS_JOB_NAME", "")
cred = _get_credential()

st.sidebar.markdown("**Status**")
st.sidebar.markdown(
    f"{'🟢' if conn_str else '🔴'} Blob Storage {'connected' if conn_str else 'not configured'}"
)
st.sidebar.markdown(
    f"{'🟢' if job_name else '🔴'} Job: `{job_name or 'not configured'}`"
)
st.sidebar.markdown(
    f"{'🟢' if cred else '🟡'} Azure credentials {'ready' if cred else 'unavailable (az login?)'}"
)

st.sidebar.divider()
st.sidebar.caption(
    "Codebook v2.3 · Halterman & Keith 2025\n\n"
    "[GitHub](https://github.com) · [Docs](#)"
)

# ── Main tabs ─────────────────────────────────────────────────────────────────

tab_launch, tab_events, tab_history = st.tabs(
    ["Launch Run", "Events Browser", "Run History"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Launch Run
# ══════════════════════════════════════════════════════════════════════════════

with tab_launch:
    st.header("Launch Pipeline Run")
    st.caption(
        "Configures and triggers a new pipeline execution on Azure Container Apps. "
        "Results are written to Azure Blob Storage and will appear in the Events Browser tab."
    )

    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.subheader("Discovery")

        query = st.text_input(
            "Search keywords",
            value="protest demonstration strike rally march",
            help="Space-separated keywords for GDELT/BBC search",
        )

        selected_countries = st.multiselect(
            "Countries",
            options=list(COUNTRIES.keys()),
            default=["South Africa", "Nigeria"],
            help="Target countries for event discovery",
        )

        source = st.radio(
            "News source",
            options=["gdelt", "bbc", "both"],
            index=0,
            horizontal=True,
            help="GDELT: broad coverage. BBC Monitoring: deeper African coverage. Both: combined + deduplicated.",
        )

        days = st.slider("Days back to search", min_value=1, max_value=90, value=14)
        max_articles = st.slider(
            "Max articles to process", min_value=10, max_value=500, value=50
        )

    with col_right:
        st.subheader("Extraction")

        provider = "azure"

        model = st.text_input(
            "Model / deployment name",
            value="gpt-4.1",
            help="Deployment name in your Azure AI Foundry project",
        )

        stage = st.selectbox(
            "Pipeline stage",
            options=["acquire", "process", "predict", "all"],
            index=0,
            help=(
                "acquire: discover + extract → data/raw/\n"
                "process: dedup + QC → data/processed/\n"
                "predict: PPI estimates → data/predictions/\n"
                "all: run all three stages"
            ),
        )

        geocode = st.checkbox("Geocode events (Nominatim OSM)", value=True)
        translate = st.checkbox("Translate non-English articles", value=True)

        upload_to = os.environ.get("DEFAULT_UPLOAD_TO", "")
        upload_dest = st.text_input(
            "Upload outputs to",
            value=upload_to,
            placeholder="az://pea-outputs/runs",
            help="Azure Blob destination for outputs. Leave blank to skip upload.",
        )

    st.divider()

    # Build the args list preview
    country_codes = ",".join(COUNTRIES[c] for c in selected_countries if c in COUNTRIES)
    args_preview = [
        "--query",
        query,
        "--countries",
        country_codes,
        "--days",
        str(days),
        "--max-articles",
        str(max_articles),
        "--provider",
        provider,
        "--model",
        model,
        "--source",
        source,
        "--stage",
        stage,
    ]
    if not translate:
        args_preview.append("--no-translate")
    if not geocode:
        args_preview.append("--no-geocode")
    if upload_dest:
        args_preview += ["--upload-to", upload_dest]

    with st.expander("Preview CLI command"):
        cmd_str = "python -m src.acquisition.pipeline " + " ".join(
            f'"{a}"' if " " in a else a for a in args_preview
        )
        st.code(cmd_str, language="bash")

    launch_col, status_col = st.columns([1, 2])

    with launch_col:
        if not selected_countries:
            st.warning("Select at least one country to continue.")
            launch_disabled = True
        else:
            launch_disabled = False

        launch_btn = st.button(
            "Launch Run",
            type="primary",
            disabled=launch_disabled,
            use_container_width=True,
        )

    with status_col:
        if launch_btn:
            with st.spinner("Triggering pipeline job..."):
                try:
                    result = trigger_pipeline_job(args_preview)
                    execution_name = result.get("name", "unknown")
                    st.success(
                        f"Job triggered successfully.\n\n"
                        f"Execution: `{execution_name}`\n\n"
                        f"Check the **Run History** tab to monitor progress."
                    )
                except Exception as e:
                    st.error(f"Failed to trigger job: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Events Browser
# ══════════════════════════════════════════════════════════════════════════════

with tab_events:
    st.header("Events Browser")

    refresh_col, info_col = st.columns([1, 4])
    with refresh_col:
        if st.button("Refresh data", use_container_width=True):
            st.cache_data.clear()

    with st.spinner("Loading events from blob storage..."):
        df = load_events_from_blob()

    if df.empty:
        st.info(
            "No events found. Either no pipeline runs have completed yet, "
            "or blob storage is not configured (check AZURE_STORAGE_CONNECTION_STRING)."
        )
    else:
        with info_col:
            st.caption(f"Loaded {len(df)} events from blob storage (cached 2 min)")

        # ── Filters ──
        st.subheader("Filters")
        fcol1, fcol2, fcol3, fcol4 = st.columns(4)

        with fcol1:
            countries_in_data = (
                sorted(df["country"].dropna().unique())
                if "country" in df.columns
                else []
            )
            filter_countries = st.multiselect(
                "Country", options=countries_in_data, default=[]
            )

        with fcol2:
            types_in_data = (
                sorted(df["event_type"].dropna().unique())
                if "event_type" in df.columns
                else []
            )
            filter_types = st.multiselect(
                "Event type", options=types_in_data, default=[]
            )

        with fcol3:
            turmoil_options = ["high", "medium", "low", "unknown"]
            filter_turmoil = st.multiselect(
                "Turmoil level", options=turmoil_options, default=[]
            )

        with fcol4:
            confidence_options = ["high", "medium", "low"]
            filter_confidence = st.multiselect(
                "Confidence", options=confidence_options, default=[]
            )

        # Date range
        if "event_date" in df.columns and df["event_date"].notna().any():
            min_date = df["event_date"].min().date()
            max_date = df["event_date"].max().date()
            date_range = st.date_input(
                "Date range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )
        else:
            date_range = None

        # Apply filters
        filtered = df.copy()
        if filter_countries:
            filtered = filtered[filtered["country"].isin(filter_countries)]
        if filter_types and "event_type" in filtered.columns:
            filtered = filtered[filtered["event_type"].isin(filter_types)]
        if filter_turmoil and "turmoil_level" in filtered.columns:
            filtered = filtered[filtered["turmoil_level"].isin(filter_turmoil)]
        if filter_confidence and "confidence" in filtered.columns:
            filtered = filtered[filtered["confidence"].isin(filter_confidence)]
        if date_range and len(date_range) == 2 and "event_date" in filtered.columns:
            start, end = date_range
            filtered = filtered[
                (filtered["event_date"].dt.date >= start)
                & (filtered["event_date"].dt.date <= end)
            ]

        st.caption(f"Showing {len(filtered)} of {len(df)} events")

        # ── Charts ──
        chart_col1, chart_col2, chart_col3 = st.columns(3)

        if not filtered.empty:
            with chart_col1:
                if "event_type" in filtered.columns:
                    type_counts = filtered["event_type"].value_counts().reset_index()
                    type_counts.columns = ["event_type", "count"]
                    fig = px.bar(
                        type_counts,
                        x="count",
                        y="event_type",
                        orientation="h",
                        title="By Event Type",
                        height=300,
                        color_discrete_sequence=["#3498db"],
                    )
                    fig.update_layout(
                        showlegend=False, margin=dict(l=0, r=0, t=30, b=0)
                    )
                    st.plotly_chart(fig, use_container_width=True)

            with chart_col2:
                if "country" in filtered.columns:
                    country_counts = filtered["country"].value_counts().reset_index()
                    country_counts.columns = ["country", "count"]
                    fig = px.bar(
                        country_counts,
                        x="count",
                        y="country",
                        orientation="h",
                        title="By Country",
                        height=300,
                        color_discrete_sequence=["#9b59b6"],
                    )
                    fig.update_layout(
                        showlegend=False, margin=dict(l=0, r=0, t=30, b=0)
                    )
                    st.plotly_chart(fig, use_container_width=True)

            with chart_col3:
                if "turmoil_level" in filtered.columns:
                    turmoil_counts = (
                        filtered["turmoil_level"].value_counts().reset_index()
                    )
                    turmoil_counts.columns = ["turmoil_level", "count"]
                    colour_map = TURMOIL_COLOURS
                    fig = px.pie(
                        turmoil_counts,
                        names="turmoil_level",
                        values="count",
                        title="Turmoil Level",
                        height=300,
                        color="turmoil_level",
                        color_discrete_map=colour_map,
                    )
                    fig.update_layout(margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig, use_container_width=True)

            # ── Map ──
            if "latitude" in filtered.columns and "longitude" in filtered.columns:
                map_df = filtered.dropna(subset=["latitude", "longitude"]).copy()
                if not map_df.empty:
                    st.subheader("Event Map")
                    map_df["turmoil_colour"] = map_df.get(
                        "turmoil_level", "unknown"
                    ).map(lambda x: TURMOIL_COLOURS.get(x, "#95a5a6"))
                    hover_cols = [
                        c
                        for c in [
                            "country",
                            "city",
                            "event_type",
                            "event_date",
                            "turmoil_level",
                            "confidence",
                        ]
                        if c in map_df.columns
                    ]
                    fig_map = px.scatter_mapbox(
                        map_df,
                        lat="latitude",
                        lon="longitude",
                        color=(
                            "turmoil_level"
                            if "turmoil_level" in map_df.columns
                            else None
                        ),
                        color_discrete_map=TURMOIL_COLOURS,
                        hover_data={col: True for col in hover_cols},
                        zoom=3,
                        height=450,
                        mapbox_style="carto-positron",
                        title=f"Geocoded Events ({len(map_df)} of {len(filtered)} have coordinates)",
                    )
                    fig_map.update_layout(margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig_map, use_container_width=True)

        # ── Data table ──
        st.subheader("Events Table")
        display_cols = [
            c
            for c in [
                "event_date",
                "country",
                "city",
                "event_type",
                "turmoil_level",
                "confidence",
                "organizer",
                "claims",
                "state_response",
                "arrests",
                "fatalities",
                "outcome",
                "article_url",
            ]
            if c in filtered.columns
        ]

        st.dataframe(
            (
                filtered[display_cols].sort_values("event_date", ascending=False)
                if "event_date" in filtered.columns
                else filtered[display_cols]
            ),
            use_container_width=True,
            height=400,
        )

        # ── Download ──
        csv_buf = StringIO()
        filtered.to_csv(csv_buf, index=False)
        st.download_button(
            label="Download filtered events (CSV)",
            data=csv_buf.getvalue(),
            file_name=f"pea_events_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Run History
# ══════════════════════════════════════════════════════════════════════════════

with tab_history:
    st.header("Run History")
    st.caption("Recent Azure Container Apps Job executions.")

    if st.button("Refresh history"):
        st.rerun()

    executions = list_job_executions(limit=20)

    if not executions:
        st.info(
            "No job executions found. Either no runs have been triggered yet, "
            "or Azure credentials / job configuration are not set."
        )
    else:
        status_emoji = {
            "Succeeded": "✅",
            "Failed": "❌",
            "Running": "🔄",
            "Pending": "⏳",
            "Stopped": "⏹",
        }

        rows = []
        for ex in executions:
            props = ex.get("properties", {})
            status = props.get("status", "Unknown")
            start_time = props.get("startTime", "")
            end_time = props.get("endTime", "")

            # Calculate duration
            duration = ""
            if start_time and end_time:
                try:
                    t0 = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                    secs = int((t1 - t0).total_seconds())
                    duration = f"{secs // 60}m {secs % 60}s"
                except Exception:
                    pass

            rows.append(
                {
                    "Status": f"{status_emoji.get(status, '?')} {status}",
                    "Execution": ex.get("name", ""),
                    "Started": start_time[:19].replace("T", " ") if start_time else "",
                    "Duration": duration,
                }
            )

        history_df = pd.DataFrame(rows)
        st.dataframe(history_df, use_container_width=True, hide_index=True)

        # Quick stats
        status_counts = history_df["Status"].value_counts()
        st.caption(" · ".join(f"{v} {k}" for k, v in status_counts.items()))
