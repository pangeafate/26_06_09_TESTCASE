"""Ingestion package.

`loaders/` (SP_002, Agent 1) normalizes raw `data/` files into the frozen
`Document` + `Chunk` contracts. Downstream extraction/embedding/pipeline modules
(Agent 2) consume that output through the `Chunk` contract only.
"""
