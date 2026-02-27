# RavenX AI x Spark Intelligence

**Spark + Made in Heaven = a trading agent that gets smarter every session.**

---

## What This Integration Does

[Made in Heaven](https://github.com/DeadByDawn101/made-in-heaven) is RavenX AI's Claude Code agent tool suite — 36 tools covering Solana RPC, DexScreener, Jupiter swaps, pump.fun bonding curves, and wallet forensics.

Spark watches every Made in Heaven tool call via the OpenClaw tailer, learns from outcomes, and surfaces advisory context before the next trade decision.

**The loop:**
```
MIH tool call → Spark captures → Spark distills → Spark advises → better next call
```

After 10 sessions: Spark knows which curve velocities graduate. Which wallet patterns dump. Which DD signals are real.

After 100 sessions: Spark is a degen trading AI that learned from your actual on-chain history.

---

## Setup

### 1. Install Spark

```bash
git clone https://github.com/DeadByDawn101/vibeship-spark-intelligence
cd vibeship-spark-intelligence
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[services]
```

### 2. Start Spark

```bash
python -m spark.cli up
python -m spark.cli health
```

### 3. Start the OpenClaw Tailer

```bash
# Tails your OpenClaw session logs → feeds to Spark
python3 adapters/openclaw_tailer.py --sparkd http://127.0.0.1:8787 --agent camila-prime
```

### 4. Enable the RavenX Degen Chip

Add to `~/.spark/tuneables.json`:
```json
{
  "feature_flags": {
    "premium_tools": true,
    "chips_enabled": true
  },
  "chips": {
    "enabled_chips": ["ravenx-degen"]
  }
}
```

### 5. Wire Made in Heaven

In your MIH session (Claude Code), Spark advisory context appears automatically in `CLAUDE.md` / `AGENTS.md` as insights are promoted.

You can also query Spark directly:
```bash
python -m spark.cli learnings          # see what Spark has learned
python -m spark.cli status             # pipeline health
```

---

## The RavenX Degen Chip

`chips/ravenx-degen/chip.yaml` teaches Spark to observe and learn from:

| Trigger | What Spark Captures |
|---------|-------------------|
| Bonding curve checks | SOL amount, fill %, outcome |
| Jupiter swaps | Token, SOL in, price impact, success |
| Degen DD sessions | Score, verdict, red flags, MC |
| Wallet forensics | Classification, win rate, risk level |
| Token launches | Bundle execution, curve response |

**Questions Spark learns to answer:**
- At what curve velocity do tokens graduate vs. die?
- Which DD score threshold best predicts rugs vs. moonshots?
- Which wallet classifications buying a token predict price action?
- What SOL sizing leads to best realized PnL?

---

## Made in Heaven Tool Map

| MIH Tool | Spark Trigger | What Spark Learns |
|----------|--------------|-------------------|
| `get_bonding_curve` | `bonding_curve_check` | Curve velocity patterns |
| `degen_dd` | `token_dd_session` | DD signal accuracy |
| `jupiter_swap` | `jupiter_swap` | Trade sizing + slippage |
| `wallet_forensics` | `wallet_forensics_session` | Wallet behavior prediction |
| `swarm_attack` | `token_launch_event` | Bundle strategy outcomes |

---

## Files

```
chips/ravenx-degen/chip.yaml    — RavenX degen domain chip
docs/ravenx/README.md           — This file
adapters/openclaw_tailer.py     — OpenClaw session tailer (upstream)
```

---

Built by [RavenX AI](https://github.com/DeadByDawn101) on top of [Vibeship Spark Intelligence](https://github.com/vibeforge1111/vibeship-spark-intelligence).
