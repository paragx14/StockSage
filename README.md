# StockSage 📦

**Seasonal inventory replenishment planning for small shops.**

StockSage is a Streamlit dashboard that uses inventory, seasonal demand, supplier lead times, and budget limits to suggest reorder quantities.

## Features

- Inventory dashboard with stock status and charts
- Seasonal demand scenarios
- Reorder recommendations with priority levels
- Budget-aware quantity planning
- CSV inventory upload and recommendation export
- Optional supplier lead-time feed
- Optional AI assistant for inventory questions
- Optional FalkorDB connection check and recommendation snapshot

## FalkorDB Integration

StockSage can optionally connect to FalkorDB and save the latest recommendations as a JSON snapshot. The current version does not create or query product, season, or supplier graph nodes.

The dashboard works without FalkorDB. Configure the connection with environment variables such as `FALKORDB_HOST` and, if needed, `FALKORDB_PORT`, `FALKORDB_USERNAME`, `FALKORDB_PASSWORD`, `FALKORDB_SSL`, and `FALKORDB_GRAPH`.

## Run Locally

The app uses sample inventory data by default. To upload your own inventory, use a CSV with the same columns as the sample table.

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
