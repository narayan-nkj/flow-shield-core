"""FastAPI service endpoints for central edge ingestion and advisory queries.

Endpoints:
- POST /edges/ingest : Ingest pseudonymous cross-bank edges
- GET /risk/score/{token} : Query advisory case score and signed explanations
- GET /health : Service health check
"""
