# StockSage 📦

**Graph-powered seasonal inventory replenishment for small shops.**

StockSage helps small businesses make smarter restocking decisions using seasonal demand, inventory levels, supplier relationships, lead times, and budget constraints.

## Features

- Seasonal demand scenarios
- Inventory dashboard
- Reorder recommendations
- Budget-aware replenishment planning
- CSV inventory upload
- FalkorDB graph connecting products, seasons, and suppliers

## Graph Data Model

StockSage uses FalkorDB to represent inventory knowledge as a graph.

**Nodes**
- `Product` — product name and current stock
- `Season` — seasonal demand scenario
- `Supplier` — supplier name and delivery lead time

**Relationships**
- `(Product)-[:IN_DEMAND_DURING]->(Season)`
- `(Product)-[:SUPPLIED_BY]->(Supplier)`

This graph connects seasonal demand with product and supplier information to support replenishment planning.

## Cypher Queries

Example query to inspect the product–season–supplier graph:

```cypher
MATCH (a)-[r]->(b)
RETURN a, r, b
```

Example query to find products associated with a seasonal demand scenario:

```cypher
MATCH (p:Product)-[:IN_DEMAND_DURING]->(s:Season)
RETURN p, s
```

Example query to find each product's supplier:

```cypher
MATCH (p:Product)-[:SUPPLIED_BY]->(s:Supplier)
RETURN p, s
```

These queries illustrate the graph structure. The application should be tested to confirm which queries it executes directly.

## Run Locally

Requirements: Python 3.10 or later.

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Configure FalkorDB credentials using Streamlit secrets or environment variables before launching the application if required. Never commit credentials to GitHub.

## Demo

Add the link to the StockSage demo video here.

## Project Status

StockSage is an early-stage prototype. Future plans include conversational AI, natural-language inventory queries, and more advanced graph-powered recommendations.

**Built solo for Graph Hacks.**
