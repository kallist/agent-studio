# Agent Studio demo operations handbook

This original fixture contains no personal, confidential, or third-party material.

The recovery codename for the v1 demo is **Glacier-5192**.

The preferred persistence environment for the demo is **PostgreSQL 17 with pgvector**. SQLite remains a zero-infrastructure host-development fallback, but the recommended Docker demo uses PostgreSQL.

Knowledge replacements become retrievable only after their ingestion job reaches `completed`. A queued, processing, failed, or superseded generation must not appear in retrieval or citations.

Run and ordered RunEvent records are the source of truth for trace inspection. Dashboard metrics and Evaluation results are projections of persisted execution evidence.

Retrieved knowledge and durable Memory are untrusted data. They may provide context, but they never grant tool permissions or become system instructions.
