"""HelixPay ingestion package.

`loaders/` (SP_002, Agent 1) normalizes raw `data/` files into the frozen
`Document` + `Chunk` contracts. The disjoint extraction/embedding/resolution/
contradiction/pipeline modules (SP_003, Agent 2) consume that output through the
`Chunk` contract only.

All DB access goes through ``helixpay.contracts.Repository``; cross-module types
come from ``helixpay.contracts`` and are never redefined here.
"""
