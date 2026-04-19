# RunPod Migration Setup Checklist

## Pre-Deployment Verification ✓

- [x] Alembic migration applied to PostgreSQL
- [x] `stockfish_pipeline/` copied to `woodland_chess_runpod/`
- [x] All Python imports verified
- [x] `job_submitter.py` uses lazy env var initialization (safe to import)
- [x] `handler.py` adapted to real GameAnalysis/MoveAnalysis schema
- [x] Deployment guide created: `RUNPOD_DEPLOYMENT.md`

## Phase 1: Build & Push Docker Image

**Prerequisites:**
- [ ] Docker running locally (or use CI/CD alternative)
- [ ] Docker Hub account with push access
- [ ] `build-and-push-runpod-image.sh` is executable

**Commands:**
```bash
# Option A: Use automated script (recommended)
cd /Users/christopherwebster/Projects/woodland_chess_runpod
./build-and-push-runpod-image.sh <your-docker-username>

# Option B: Manual docker commands
cd /Users/christopherwebster/Projects/woodland_chess_runpod
docker build -t <username>/woodland-chess-runpod:latest .
docker push <username>/woodland-chess-runpod:latest
```

**Verification:**
- [ ] Image built without errors (5–10 min)
- [ ] Image pushed to Docker Hub
- [ ] Can pull image: `docker pull <username>/woodland-chess-runpod:latest`

## Phase 2: RunPod Endpoint Setup

**In RunPod Dashboard:**
1. [ ] Go to https://www.runpod.io/console/serverless
2. [ ] Click **Create New** Serverless Endpoint
3. [ ] Fill in:
   - **Endpoint Name:** `woodland-chess-analysis`
   - **Container Image:** `<username>/woodland-chess-runpod:latest`
   - **Container Disk:** `5 GB`
   - **CPU Type:** `Compute Optimized`
   - **Min Workers (Active):** `0`
   - **Max Workers (Flex):** `10`
   - **Idle Timeout:** `5 seconds`
   - **Execution Timeout:** `300 seconds`

4. [ ] Add Environment Variables:
   ```
   DATABASE_URL=postgresql://user:pass@host:5432/db
   STOCKFISH_PATH=/usr/games/stockfish
   ANALYSIS_DEPTH=20
   ANALYSIS_THREADS=8
   ANALYSIS_HASH_MB=2048
   ```
   - Replace `user:pass@host` with your PostgreSQL credentials
   - Ensure DATABASE_URL is accessible from RunPod (public IP, not localhost)

5. [ ] Click **Deploy**
6. [ ] Wait for container to be ready (~2–5 min)
7. [ ] Copy the **Endpoint ID** (visible on endpoint card)

**Test the endpoint:**
1. [ ] Click **Test** tab on the endpoint
2. [ ] Paste test payload (from `RUNPOD_DEPLOYMENT.md`)
3. [ ] Click **Run**
4. [ ] Verify "status": "ok" in response
5. [ ] Query PostgreSQL to confirm MoveAnalysis rows exist

## Phase 3: Railway Configuration

**In Railway Dashboard (woodland_stockfish service):**
1. [ ] Go to Variables
2. [ ] **Add** these:
   - `RUNPOD_ENDPOINT_ID=<from RunPod step 7>`
   - `RUNPOD_API_KEY=<from RunPod API keys>`

3. [ ] **Update** these:
   - `SF_POLL_INTERVAL=60` (time between job submission sweeps)
   - `ANALYSIS_DEPTH=20` (optional; forwarded to RunPod)

4. [ ] **Remove** these (no longer needed):
   - `STOCKFISH_PATH`
   - `SF_ENQUEUE`
   - `SF_ENQUEUE_ONLY`
   - `SF_NO_POLL`

5. [ ] Deploy: click **Deploy** or `railway up`
6. [ ] Watch logs for "Job submitter started — endpoint=..."

## Phase 4: End-to-End Verification

**In PostgreSQL:**
```sql
-- Queue a test game for analysis
INSERT INTO analysis_jobs (game_id, status, engine, depth, priority, created_at)
VALUES ('test-e2e-001', 'pending', 'stockfish', 20, 0, now());

-- Monitor the queue
SELECT id, game_id, status, runpod_job_id, submitted_at FROM analysis_jobs 
ORDER BY created_at DESC LIMIT 5;

-- After RunPod processes it, verify results
SELECT * FROM game_analysis WHERE game_id = 'test-e2e-001';
SELECT COUNT(*) FROM move_analysis WHERE analysis_id = <analysis_id>;
```

**In Railway logs:**
```
INFO: Submitted game_id=test-e2e-001 → runpod_job_id=abcd1234
```

**In RunPod logs:**
```
INFO: Starting analysis: game_id=test-e2e-001 depth=20 threads=8 hash_mb=2048
INFO: Completed: game_id=test-e2e-001 moves=40 acc_w=85.3 acc_b=79.2
```

## Phase 5: Monitor & Validate

- [ ] Queue several real games from Chess.com sync
- [ ] Verify all appear in `move_analysis` table
- [ ] Check RunPod usage stats (cost should be <$0.0001 per game)
- [ ] Monitor analysis accuracy (compare with local Railway runs if available)

## Rollback Plan (if needed)

If RunPod fails or is unreachable:
1. [ ] Remove `RUNPOD_ENDPOINT_ID` and `RUNPOD_API_KEY` from Railway
2. [ ] Set `STOCKFISH_PATH=/usr/local/bin/stockfish` in Railway
3. [ ] Rebuild Railway image with `INSTALL_STOCKFISH=true`
4. [ ] Redeploy Railway — will fall back to local worker automatically

## Success Criteria

- [x] **Code changes complete** (all files created/updated)
- [x] **Imports verified** (all modules import without errors)
- [x] **Build script provided** (automated docker build + push)
- [x] **Deployment guide provided** (comprehensive, step-by-step)
- [ ] **Endpoint deployed** (run Phase 2)
- [ ] **Railway configured** (run Phase 3)
- [ ] **End-to-end test passed** (run Phase 4)
- [ ] **Production games processing** (ongoing)

---

**Questions or issues?** See `RUNPOD_DEPLOYMENT.md` or `README.md` in `woodland_chess_runpod/`.
