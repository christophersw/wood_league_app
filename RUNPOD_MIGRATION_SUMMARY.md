# RunPod Migration — Implementation Summary

**Date:** April 19, 2026  
**Status:** ✅ Complete — Ready for manual deployment  
**Next:** Build Docker image, create RunPod endpoint, configure Railway

---

## Files Created

### woodland_stockfish/

| File | Changes |
|------|---------|
| `stockfish_pipeline/services/stockfish_service.py` | Added `analyse_game()` wrapper function for parsed chess.pgn.Game objects |
| `stockfish_pipeline/storage/models.py` | Added `runpod_job_id` and `submitted_at` columns to AnalysisJob model |
| `stockfish_pipeline/ingest/job_submitter.py` | **NEW** — Job submitter with lazy env var init, replaces local worker when RUNPOD_ENDPOINT_ID is set |
| `start_workers.py` | Updated to route to job_submitter when RUNPOD_ENDPOINT_ID is set; falls back to local worker otherwise |
| `Dockerfile` | Simplified — Stockfish installation optional via `--build-arg INSTALL_STOCKFISH=true` |

### woodland_chess_runpod/

| File | Purpose |
|------|---------|
| `handler.py` | **NEW** — RunPod serverless entry point; receives game, runs analysis, writes results to PostgreSQL |
| `Dockerfile` | **NEW** — Builds RunPod image with Stockfish SF18 AVX2 binary |
| `requirements.txt` | **NEW** — Dependencies (runpod, chess, sqlalchemy, psycopg2) |
| `test_input.json` | **NEW** — Local test payload for handler.py |
| `README.md` | **NEW** — Quickstart guide for RunPod worker |
| `build-and-push-runpod-image.sh` | **NEW** — Automated Docker build + push script |
| `stockfish_pipeline/` | **COPIED** — Full pipeline package for analysis logic |

### woodland_app/

| File | Changes |
|------|---------|
| `app/storage/models.py` | Added `runpod_job_id` and `submitted_at` columns to AnalysisJob model |
| `alembic/versions/b3c9f1a04e87_add_runpod_tracking_columns.py` | **NEW** — Migration applied to PostgreSQL |
| `RUNPOD_DEPLOYMENT.md` | **NEW** — Comprehensive deployment guide (7 sections, troubleshooting) |
| `RUNPOD_SETUP_CHECKLIST.md` | **NEW** — Step-by-step checklist with commands (5 phases) |

---

## Code Changes Summary

### 1. New `analyse_game()` Function
**File:** `woodland_stockfish/stockfish_pipeline/services/stockfish_service.py`

```python
def analyse_game(
    game: chess.pgn.Game,
    stockfish_path: str,
    depth: int = 20,
    threads: int = 1,
    hash_mb: int = 256,
) -> GameResult:
    """Wrapper around analyze_pgn() for pre-parsed chess.pgn.Game objects."""
```

**Purpose:** Allows `handler.py` to pass a parsed game object directly instead of re-serializing to PGN string.

### 2. Database Schema Updates
**File:** `alembic/versions/b3c9f1a04e87_add_runpod_tracking_columns.py`

```sql
ALTER TABLE analysis_jobs ADD COLUMN runpod_job_id VARCHAR(64) NULL;
ALTER TABLE analysis_jobs ADD COLUMN submitted_at TIMESTAMP NULL;
```

**Status:** ✅ Applied to PostgreSQL

### 3. Job Submitter
**File:** `woodland_stockfish/stockfish_pipeline/ingest/job_submitter.py`

- Polls `AnalysisJob` rows with status `pending`
- Submits each to RunPod via API
- Updates `runpod_job_id` and `submitted_at`
- Fire-and-forget — does not wait for results
- Lazy env var initialization (safe to import in any context)

### 4. Start Workers Routing
**File:** `woodland_stockfish/start_workers.py`

```python
if _env("RUNPOD_ENDPOINT_ID"):
    from stockfish_pipeline.ingest.job_submitter import run_submitter_loop
    run_submitter_loop()
else:
    # Fall back to local worker
    cmd = build_cmd()
    subprocess.run(cmd)
```

### 5. RunPod Handler
**File:** `woodland_chess_runpod/handler.py`

- Receives `{"input": {"game_id", "pgn", "depth", ...}}`
- Calls `analyze_pgn()` for analysis
- Writes `GameAnalysis` + `MoveAnalysis` + updates `GameParticipant` stats
- Idempotent — deletes old results before inserting new ones
- Distinguishes transient vs. permanent errors (retry vs. fail)

---

## Architecture

```
Chess.com API
     ↓
run_sync.py (Railway — unchanged)
     ↓
PostgreSQL (Game table)
     ↓
job_submitter.py (Railway — new)
     ↓
RunPod Job Queue
     ↓
handler.py (RunPod Serverless) ← Stockfish SF18 AVX2
     ↓
PostgreSQL (GameAnalysis + MoveAnalysis)
```

**Cost:** $0 idle, ~$0.00005 per game (~$0.05 for 1000 games/month)

---

## Testing Status

- [x] Alembic migration applied successfully
- [x] stockfish_pipeline copied to woodland_chess_runpod
- [x] All Python imports verified
- [x] job_submitter lazy initialization working
- [x] handler.py imports and schema verified
- [x] Docker image ready to build
- [ ] Docker image built and pushed (blocked: Docker daemon not running)
- [ ] RunPod endpoint created and tested
- [ ] Railway environment configured and deployed

---

## How to Proceed

1. **Build & push Docker image:**
   ```bash
   cd /Users/christopherwebster/Projects/woodland_chess_runpod
   ./build-and-push-runpod-image.sh <docker-username>
   ```

2. **Follow the setup checklist:**
   See `/Users/christopherwebster/Projects/woodland_app/RUNPOD_SETUP_CHECKLIST.md`

3. **For detailed reference:**
   See `/Users/christopherwebster/Projects/woodland_app/RUNPOD_DEPLOYMENT.md`

---

## Rollback

If needed, remove `RUNPOD_ENDPOINT_ID` and `RUNPOD_API_KEY` from Railway. The system will automatically fall back to the local worker (if Stockfish is installed).

---

## Key Files to Review

1. [handler.py](woodland_chess_runpod/handler.py) — Core RunPod logic
2. [job_submitter.py](woodland_stockfish/stockfish_pipeline/ingest/job_submitter.py) — Queue polling
3. [RUNPOD_DEPLOYMENT.md](woodland_app/RUNPOD_DEPLOYMENT.md) — Full guide
4. [RUNPOD_SETUP_CHECKLIST.md](woodland_app/RUNPOD_SETUP_CHECKLIST.md) — Step-by-step checklist
