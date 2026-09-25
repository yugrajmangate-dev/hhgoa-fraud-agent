# Social post drafts

> Draft only. Before posting, replace `[GITHUB_URL]`, `[VIDEO_URL]` and `[DEMO_URL]`. Every figure below comes from the project's own verification output. Customer replies, actions, approvals and suspicious activity reports (SARs) in this project are **simulated**; nothing touches real cards, customers or regulators. This is a hackathon prototype, not a production system, and it makes no claim of real-world fraud accuracy.

---

## Main post (LinkedIn / long-form)

We built an agentic fraud-investigation prototype on **TigerGraph Savanna** for the TigerGraph × Hacker House Goa 2026 challenge. @TigerGraphDB @247pmstudio

It takes each of the 20 benchmark alerts, investigates it through graph queries, and decides under the bank's written policy (rules R1–R10). It then writes every case back into TigerGraph as memory for later investigations.

What we focused on: trust and verifiability.
🔹 Every graph read goes through our gateway to the **official TigerGraph MCP server**. The gateway injects the alert's `as_of` time and rejects any row from the future.
🔹 Every evidence claim in an answer points to a specific graph call (a provenance envelope with a result hash).
🔹 Every run is a hash-chained audit log, and every case written to the graph is read back and matched byte for byte against the answer file.
🔹 Fully deterministic `--llm off` mode: the decisions come from tested code, not a language model.

Where it stands:
✅ 20/20 answer files pass an independent verifier (schema, IDs against the raw data, the time cut-off, policy reproduction, audit chain, provenance, graph read-back)
✅ 77 tests passing · 51/51 architecture checks passing
📊 Outcomes: 8 fraud · 11 uncertain · 1 legitimate

Honest caveats:
⚠️ Customer replies, actions, approvals and SARs are simulated.
⚠️ We have no answer key, so no accuracy claim. Our scorer was calibrated on closed cases (held-out AUC 0.596), and we deliberately rejected a higher-scoring fit because it contradicted the dataset's own evidence rules.
⚠️ One legitimate verdict out of 20 is far below the challenge's "half are legitimate", so there is more work to do.

Code: [GITHUB_URL]
Demo video: [VIDEO_URL]
Live demo: [DEMO_URL]

#TigerGraph #GraphDatabase #FraudDetection #MCP #HackerHouseGoa

---

## Variation A (team member, short)

Our TigerGraph × Hacker House Goa 2026 entry: a fraud investigator on TigerGraph Savanna that queries the graph only through the official TigerGraph MCP, with an `as_of` time cut-off enforced on every read. 20/20 case files independently verified, 77 tests green. Customer responses are simulated. @TigerGraphDB @247pmstudio

Code: [GITHUB_URL] · Video: [VIDEO_URL]

---

## Variation B (team member, short)

What I learned building on @TigerGraphDB for @247pmstudio's Hacker House Goa: make every claim traceable. Each evidence item cites a graph call, each run is a hash-chained audit log, and each case written to the graph is read back byte for byte. 8 fraud / 11 uncertain / 1 legitimate across 20 alerts, and we're open about the gaps. All actions are simulated.

Demo: [DEMO_URL] · Video: [VIDEO_URL]
