"""StockSage: inventory and seasonal replenishment dashboard.

Run with: streamlit run app.py

Optional integrations:
  FALKORDB_HOST, FALKORDB_PORT, FALKORDB_USERNAME, FALKORDB_PASSWORD,
  FALKORDB_GRAPH (defaults to stocksage)
  SUPPLIER_API_URL (JSON endpoint returning supplier lead times)

The dashboard remains usable without either integration. Supplier API format:
  {"suppliers": [{"supplier": "Acme", "lead_days": 5}]}
or {"Acme": 5, "Northwind": 8}.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
except ImportError:  # Dashboard can still render its table without charts.
    px = None

try:
    import requests
except ImportError:
    requests = None


st.set_page_config(page_title="StockSage | Inventory Planner", page_icon="📦", layout="wide")

SEED_INVENTORY = pd.DataFrame([
    {"Product": "Rain Jacket", "Category": "Apparel", "Stock": 18, "Daily Demand": 3.2, "Unit Cost": 42.00, "Supplier": "Northwind", "Lead Time (days)": 7, "Seasonal Factor": 1.45, "Season": "Monsoon"},
    {"Product": "Umbrella", "Category": "Accessories", "Stock": 34, "Daily Demand": 4.1, "Unit Cost": 12.50, "Supplier": "Acme Supply", "Lead Time (days)": 5, "Seasonal Factor": 1.30, "Season": "Monsoon"},
    {"Product": "Water Bottle", "Category": "Outdoors", "Stock": 42, "Daily Demand": 2.0, "Unit Cost": 9.00, "Supplier": "Northwind", "Lead Time (days)": 7, "Seasonal Factor": 1.10, "Season": "Summer"},
    {"Product": "Wool Scarf", "Category": "Apparel", "Stock": 11, "Daily Demand": 1.7, "Unit Cost": 18.00, "Supplier": "Cozy Goods", "Lead Time (days)": 10, "Seasonal Factor": 1.55, "Season": "Winter"},
    {"Product": "Camping Lantern", "Category": "Outdoors", "Stock": 25, "Daily Demand": 1.4, "Unit Cost": 24.00, "Supplier": "Acme Supply", "Lead Time (days)": 5, "Seasonal Factor": 1.20, "Season": "Summer"},
    {"Product": "Thermal Mug", "Category": "Kitchen", "Stock": 9, "Daily Demand": 1.1, "Unit Cost": 16.00, "Supplier": "Cozy Goods", "Lead Time (days)": 10, "Seasonal Factor": 1.25, "Season": "Winter"},
])

NUMERIC_COLUMNS = ["Stock", "Daily Demand", "Unit Cost", "Lead Time (days)", "Seasonal Factor"]


def load_supplier_lead_times() -> tuple[dict[str, int], str | None]:
    """Fetch optional supplier lead times; errors fall back to table values."""
    url = os.getenv("SUPPLIER_API_URL", "").strip()
    if not url:
        return {}, None
    if requests is None:
        return {}, "Install `requests` to use SUPPLIER_API_URL. Using inventory lead times."
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        payload = response.json()
        raw = payload.get("suppliers", payload) if isinstance(payload, dict) else payload
        result: dict[str, int] = {}
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("supplier") is not None:
                    result[str(item["supplier"])] = max(0, int(float(item["lead_days"])))
        elif isinstance(raw, dict):
            for name, days in raw.items():
                if isinstance(days, (int, float, str)):
                    result[str(name)] = max(0, int(float(days)))
        return result, None
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        return {}, f"Supplier delivery feed unavailable ({exc}). Using inventory lead times."


def clean_inventory(frame: pd.DataFrame) -> pd.DataFrame:
    required = list(SEED_INVENTORY.columns)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))
    frame = frame[required].copy()
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=NUMERIC_COLUMNS + ["Product", "Supplier"])
    frame["Product"] = frame["Product"].astype(str).str.strip()
    frame["Supplier"] = frame["Supplier"].astype(str).str.strip()
    frame["Category"] = frame["Category"].fillna("Other").astype(str)
    frame["Season"] = frame["Season"].fillna("All year").astype(str)
    frame = frame[(frame["Product"] != "") & (frame["Supplier"] != "")]
    frame["Stock"] = frame["Stock"].clip(lower=0).round().astype(int)
    frame["Daily Demand"] = frame["Daily Demand"].clip(lower=0)
    frame["Unit Cost"] = frame["Unit Cost"].clip(lower=0)
    frame["Lead Time (days)"] = frame["Lead Time (days)"].clip(lower=0).round().astype(int)
    frame["Seasonal Factor"] = frame["Seasonal Factor"].clip(lower=0.1, upper=5)
    return frame.reset_index(drop=True)


def recommend(frame: pd.DataFrame, budget: float, horizon: int, safety_days: int,
              selected_season: str, supplier_times: dict[str, int]) -> pd.DataFrame:
    result = frame.copy()
    result["Effective Lead Time (days)"] = result.apply(
        lambda row: supplier_times.get(row["Supplier"], int(row["Lead Time (days)"])), axis=1
    )
    factor = result["Seasonal Factor"].where(
        (selected_season == "All seasons") | (result["Season"] == selected_season), 1.0
    )
    result["Forecast Daily Demand"] = result["Daily Demand"] * factor
    result["Reorder Point"] = (result["Forecast Daily Demand"] *
                               (result["Effective Lead Time (days)"] + safety_days)).apply(lambda n: int(round(n)))
    result["Target Stock"] = (result["Forecast Daily Demand"] *
                              (result["Effective Lead Time (days)"] + horizon + safety_days)).apply(lambda n: int(round(n)))
    result["Suggested Qty"] = (result["Target Stock"] - result["Stock"]).clip(lower=0).astype(int)
    result["Priority"] = result.apply(
        lambda row: "Critical" if row["Stock"] <= row["Effective Lead Time (days)"] * row["Forecast Daily Demand"]
        else ("Reorder" if row["Stock"] <= row["Reorder Point"] else "Healthy"), axis=1
    )
    # Triage urgent products first, then allocate available budget to the strongest demand risk.
    result["Priority Rank"] = result["Priority"].map({"Critical": 0, "Reorder": 1, "Healthy": 2})
    result["Risk Score"] = (result["Forecast Daily Demand"] /
                            (result["Stock"] + 1) * (result["Effective Lead Time (days)"] + 1))
    result = result.sort_values(["Priority Rank", "Risk Score"], ascending=[True, False]).reset_index(drop=True)
    remaining = max(0.0, float(budget))
    allocated, costs, notes = [], [], []
    for _, row in result.iterrows():
        wanted = int(row["Suggested Qty"])
        unit_cost = float(row["Unit Cost"])
        affordable = wanted if unit_cost <= 0 else min(wanted, int(remaining // unit_cost))
        spend = affordable * unit_cost
        allocated.append(affordable)
        costs.append(spend)
        if wanted == 0:
            notes.append("No order needed")
        elif affordable == wanted:
            notes.append("Fully funded")
        elif affordable > 0:
            notes.append("Partial: budget limited")
        else:
            notes.append("Not funded: budget limited")
        remaining = max(0.0, remaining - spend)
    result["Recommended Qty"] = allocated
    result["Estimated Cost"] = costs
    result["Budget Note"] = notes
    result["Expected Arrival"] = [date.today() + timedelta(days=int(days)) for days in result["Effective Lead Time (days)"]]
    return result.drop(columns=["Priority Rank", "Risk Score"])


def save_to_falkordb(rows: pd.DataFrame) -> tuple[bool, str]:
    """Best-effort optional snapshot write. No credentials are required by the UI."""
    host = os.getenv("FALKORDB_HOST", "").strip()
    if not host:
        return False, "FalkorDB is not configured; the dashboard is using local session data."
    try:
        from redis import Redis
        from redis.exceptions import RedisError
    except ImportError:
        return False, "Install `redis` to enable FalkorDB. Dashboard remains available locally."
    try:
        port = int(os.getenv("FALKORDB_PORT", "6379"))
        client = Redis(host=host, port=port,
                       username=os.getenv("FALKORDB_USERNAME") or None,
                       password=os.getenv("FALKORDB_PASSWORD") or None,
                       decode_responses=True, socket_connect_timeout=3, socket_timeout=5,
                       ssl=os.getenv("FALKORDB_SSL", "false").lower() in {"1", "true", "yes"})
        client.ping()
        graph_name = os.getenv("FALKORDB_GRAPH", "stocksage")
        # Verify the FalkorDB graph module, not only the Redis-compatible PING.
        client.execute_command("GRAPH.QUERY", graph_name, "RETURN 1", "--compact")
        # Store compact JSON snapshot in a Redis key as well, so the basic connection
        # check does not depend on a particular graph query language/version.
        snapshot = rows[["Product", "Stock", "Recommended Qty", "Priority", "Estimated Cost"]].to_json(orient="records")
        client.set(f"{graph_name}:latest_recommendations", snapshot)
        return True, f"Connected to FalkorDB at {host}:{port} (graph '{graph_name}'); snapshot saved."
    except Exception as exc:  # Connection/config/plugin versions vary; report gracefully.
        return False, f"FalkorDB unavailable ({exc}). Dashboard remains available locally."


st.markdown("""<style>
  .block-container {padding-top: 1.7rem; padding-bottom: 2rem; max-width: 1500px;}
  [data-testid="stMetric"] {
    background: #f5f8fc;
    border: 1px solid #dbe3ee;
    padding: 1rem;
    border-radius: 12px;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"] {
    color: #1f2937 !important;
}
  .small-muted {color:#667085;font-size:.9rem}
</style>""", unsafe_allow_html=True)
st.title("📦 StockSage")
st.caption("Inventory visibility and budget-aware seasonal replenishment planning")

with st.sidebar:
    st.header("Planning settings")
    budget = st.number_input("Reorder budget", min_value=0.0, value=1500.0, step=100.0, format="%.2f")
    horizon = st.slider("Planning horizon (days)", min_value=7, max_value=90, value=30)
    safety_days = st.slider("Safety stock (days)", min_value=0, max_value=30, value=5)
    uploaded = st.file_uploader("Upload inventory CSV", type=["csv"], help="Use the same column names as the sample inventory table.")
    st.caption("FalkorDB and supplier feeds are optional. Set their environment variables before launching Streamlit.")

try:
    inventory = pd.read_csv(uploaded) if uploaded is not None else SEED_INVENTORY.copy()
    inventory = clean_inventory(inventory)
except Exception as exc:
    st.error(f"Could not load inventory: {exc}")
    st.info("Required columns: " + ", ".join(SEED_INVENTORY.columns))
    st.stop()

supplier_times, supplier_warning = load_supplier_lead_times()
if supplier_warning:
    st.warning(supplier_warning)
seasons = ["All seasons"] + sorted(inventory["Season"].dropna().astype(str).unique().tolist())
season = st.selectbox("Seasonal demand scenario", seasons, index=0, help="Applies seasonal factors only to matching products.")
plan = recommend(inventory, budget, horizon, safety_days, season, supplier_times)

total_units = int(inventory["Stock"].sum())
critical_count = int((plan["Priority"] == "Critical").sum())
reorder_count = int((plan["Suggested Qty"] > 0).sum())
spend = float(plan["Estimated Cost"].sum())
col1, col2, col3, col4 = st.columns(4)
col1.metric("Products", f"{len(inventory)}")
col2.metric("Units on hand", f"{total_units:,}")
col3.metric("Items needing reorder", f"{reorder_count}", delta=f"{critical_count} critical", delta_color="inverse")
col4.metric("Recommended spend", f"${spend:,.2f}", delta=f"${max(0, budget-spend):,.2f} budget left")

st.subheader("Reorder recommendations")
display_columns = ["Product", "Category", "Supplier", "Stock", "Forecast Daily Demand", "Effective Lead Time (days)", "Reorder Point", "Suggested Qty", "Recommended Qty", "Priority", "Expected Arrival", "Unit Cost", "Estimated Cost", "Budget Note"]
display = plan[display_columns].copy()
for col in ["Forecast Daily Demand"]:
    display[col] = display[col].round(2)
for col in ["Unit Cost", "Estimated Cost"]:
    display[col] = display[col].map(lambda value: f"${value:,.2f}")
st.dataframe(display, use_container_width=True, hide_index=True,
             column_config={"Priority": st.column_config.TextColumn("Priority"),
                            "Expected Arrival": st.column_config.DateColumn("Expected arrival")})

chart_col, status_col = st.columns([1.5, 1])
with chart_col:
    st.subheader("Stock vs. target")
    if px is not None and not plan.empty:
        chart_data = plan.sort_values("Stock", ascending=True)
        chart = px.bar(chart_data, x="Product", y=["Stock", "Target Stock"], barmode="group",
                       color_discrete_sequence=["#2f6fed", "#9db8f5"],
                       labels={"value": "Units", "variable": "Measure"})
        chart.update_layout(legend_title_text="", margin=dict(l=10, r=10, t=25, b=10), height=360)
        st.plotly_chart(chart, use_container_width=True)
    else:
        st.info("Install plotly to show the stock chart. The table and CSV export still work.")
with status_col:
    st.subheader("Inventory status")
    counts = plan["Priority"].value_counts().reindex(["Critical", "Reorder", "Healthy"], fill_value=0)
    st.write(f"🔴 **Critical:** {counts['Critical']} products")
    st.write(f"🟠 **Reorder:** {counts['Reorder']} products")
    st.write(f"🟢 **Healthy:** {counts['Healthy']} products")
    if supplier_times:
        st.success(f"Supplier delivery feed applied to {len(supplier_times)} supplier(s).")
    else:
        st.caption("Lead times use the values in your inventory data.")

st.subheader("Ask StockSage AI")
st.caption("Optional AI assistant for inventory, reorder, seasonality, and small-business questions. Configure OPENAI_API_KEY to enable it.")
with st.expander("Open AI assistant", expanded=False):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        except Exception:
            api_key = ""

    if not api_key:
        st.info("AI is optional and currently off. Add OPENAI_API_KEY to your environment or Streamlit secrets, then restart the app. The dashboard works without it.")
    else:
        st.caption("Your question and a compact summary of the current inventory recommendations are sent to the OpenAI API to answer. Do not include sensitive customer or business secrets.")
        if "stocksage_ai_messages" not in st.session_state:
            st.session_state["stocksage_ai_messages"] = []
        for message in st.session_state["stocksage_ai_messages"]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        question = st.chat_input("Ask about stock, reorder priorities, suppliers, or your plan...")
        if question:
            history = st.session_state["stocksage_ai_messages"]
            history.append({"role": "user", "content": question})
            st.session_state["stocksage_ai_messages"] = history
            with st.chat_message("user"):
                st.markdown(question)
            context_cols = ["Product", "Category", "Supplier", "Stock", "Forecast Daily Demand",
                            "Effective Lead Time (days)", "Reorder Point", "Recommended Qty", "Priority", "Estimated Cost"]
            inventory_context = plan[context_cols].head(40).to_json(orient="records")
            instructions = (
                "You are StockSage AI, a practical inventory planning helper for a small business. "
                "Answer clearly and concisely. Use the supplied live dashboard context when relevant. "
                "Do not invent inventory facts. State when a question needs data that is not provided. "
                "Recommendations are decision support, not guaranteed forecasts.\n\n"
                f"Dashboard context (JSON): {inventory_context}\n"
                f"Budget: {budget:.2f}; planning horizon: {horizon} days; safety stock: {safety_days} days; "
                f"selected season: {season}."
            )
            input_messages = [{"role": item["role"], "content": item["content"]} for item in history[-10:]]
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key, timeout=30.0, max_retries=1)
                response = client.responses.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-6-astra"),
                    instructions=instructions,
                    input=input_messages,
                    store=False,
                )
                answer = response.output_text.strip() or "I couldn't generate a text answer. Please try again."
                st.session_state["stocksage_ai_messages"].append({"role": "assistant", "content": answer})
                with st.chat_message("assistant"):
                    st.markdown(answer)
            except ImportError:
                st.error("The OpenAI package is missing. Install the dependencies from requirements.txt and restart Streamlit.")
            except Exception as exc:
                st.error(f"AI request failed: {exc}. Check the API key, model setting, network, and API account access.")
        if st.session_state.get("stocksage_ai_messages") and st.button("Clear AI chat", key="clear_stocksage_chat"):
            st.session_state["stocksage_ai_messages"] = []
            st.rerun()

csv_bytes = plan.to_csv(index=False).encode("utf-8-sig")
st.download_button("⬇️ Download recommendations (CSV)", data=csv_bytes,
                   file_name="stocksage_recommendations.csv", mime="text/csv")

with st.expander("Inventory data"):
    st.dataframe(inventory, use_container_width=True, hide_index=True)

with st.expander("Optional FalkorDB status / snapshot"):
    if st.button("Check connection and save recommendation snapshot", key="falkordb_check"):
        ok, message = save_to_falkordb(plan)
        if ok:
            st.success(message)
        else:
            st.warning(message)
    st.caption("Set FALKORDB_HOST (and optional port, username, password, SSL, graph) to enable. Install the redis Python package.")
