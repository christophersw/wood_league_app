# RunPod Serverless Migration — Deployment Guide

## Completed Steps ✓

- [x] Alembic migration applied to PostgreSQL (runpod_job_id, submitted_at columns added)
- [x] stockfish_pipeline copied to woodland_chess_runpod
- [x] job_submitter.py created with lazy env var initialization
- [x] start_workers.py updated to route to job_submitter when RUNPOD_ENDPOINT_ID is set
- [x] RunPod handler.py created (adapted to real GameAnalysis/MoveAnalysis schema)
- [x] Dockerfile and requirements.txt ready
- [x] All imports verified

## Next Steps (Manual)

### 1. Build and Push Docker Image

**Prerequisites:**
- Docker running locally or access to a CI/CD pipeline
- Docker Hub account with access to push images
- Optional: A private Docker registry (ECR, GCR, etc.)

**Commands:**
```bash
cd woodland_chess_runpod

# Build the image locally
docker build -t <your-dockerhub-username>/woodland-chess-runpod:latest .

# Log in to Docker Hub (if not already logged in)
docker login

# Push to Docker Hub
docker push <your-dockerhub-username>/woodland-chess-runpod:latest
```

**Notes:**
- Image size: ~2–3 GB (includes Python, Stockfish binary, dependencies)
- Build time: 5–10 minutes
- The Dockerfile uses multi-stage if needed, but currently is single-stage

### 2. Create RunPod Serverless Endpoint

**In the RunPod Dashboard:**
1. Go to **Console** → **Serverless** (or **Endpoints** in your org)
2. Click **Create New** or **+ New Endpoint**
3. Fill in the settings:

| Field | Value |
|-------|-------|
| **Endpoint Name** | `woodland-chess-analysis` |
| **Container Image** | `<your-dockerhub-username>/woodland-chess-runpod:latest` |
| **Container Disk** | `5 GB` |
| **Container Memory** | Leave default |
| **CPU Type** | `Compute Optimized` |
| **Min Workers (Active)** | `0` |
| **Max Workers (Flex)** | `10` |
| **Idle Timeout** | `5 seconds` |
| **Execution Timeout** | `300 seconds` (5 min) |

4. Under **Environment Variables**, add:
   ```
   DATABASE_URL=postgresql://user:pass@host:5432/db
   STOCKFISH_PATH=/usr/games/stockfish
   ANALYSIS_DEPTH=20
   ANALYSIS_THREADS=8
   ANALYSIS_HASH_MB=2048
   ```

   - Replace `user:pass@host` with your actual PostgreSQL credentials
   - DATABASE_URL must be accessible from RunPod (public IP or VPN)
   - Depth 20 recommended; lower for faster results, higher for deeper analysis

5. Click **Deploy**
6. Wait for the container to be ready (~2–5 min)
7. Note the **Endpoint ID** (visible on the endpoint card or in the test interface)

### 3. Test the RunPod Endpoint

**Via RunPod Dashboard:**
1. On the endpoint card, click the **Test** tab
2. Paste a test payload:
   ```json
   {
     "input": {
       "game_id": "test-001",
       "pgn": "[Event \"Test\"]\n[White \"A\"]\n[Black \"B\"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 1-0",
       "depth": 18
     }
   }
   ```
3. Click **Run**
4. Check the logs for "status: ok" and verify MoveAnalysis rows appear in PostgreSQL

**Via cURL:**
```bash
curl -X POST https://api.runpod.io/v2/<ENDPOINT_ID>/run \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RUNPOD_API_KEY>" \
  -d '{
    "input": {
      "game_id": "test-001",
      "pgn": "[Event \"Test\"]...",
      "depth": 18
    }
  }'
```

### 4. Configure Railway Environment Variables

In the Railway dashboard for the `woodland_stockfish` service:

**Add these new variables:**
```
RUNPOD_ENDPOINT_ID=<your-endpoint-id>
RUNPOD_API_KEY=<your-runpod-api-key>
```

**Update these variables (if using local worker, can now be omitted):**
```
ANALYSIS_DEPTH=20        (optional — forwarded to RunPod)
ANALYSIS_THREADS=8       (optional — forwarded to RunPod)
ANALYSIS_HASH_MB=2048    (optional — forwarded to RunPod)
SF_POLL_INTERVAL=60      (time in seconds between job submission sweeps)
```

**Environment variables to REMOVE (no longer needed):**
- `STOCKFISH_PATH` — RunPod worker has its own
- `SF_ENQUEUE` — job_submitter handles enqueueing
- `SF_ENQUEUE_ONLY` — not relevant
- `SF_NO_POLL` — not relevant

### 5. Deploy Updated Railway Service

**Trigger a redeploy** of `woodland_stockfish`:
```bash
railway up
```

Or in the Railway dashboard:
1. Go to your project
2. Select the `woodland_stockfish` service
3. Click **Deploy**
4. Watch the logs for "Job submitter started — endpoint=..."

### 6. Verify End-to-End Flow

Once Railway is running the job submitter:

1. **Queue a game for analysis:**
   ```sql
   INSERT INTO analysis_jobs (game_id, status, engine, depth, priority, created_at)
   VALUES ('some-game-id', 'pending', 'stockfish', 20, 0, now());
   ```

2. **Watch the job submitter logs** in Railway:
   ```
   INFO: Submitted game_id=some-game-id → runpod_job_id=abcd1234
   ```

3. **Check RunPod logs** (Dashboard → Endpoint → Logs):
   ```
   INFO: Starting analysis: game_id=some-game-id depth=20 threads=8 hash_mb=2048
   INFO: Completed: game_id=some-game-id moves=40 acc_w=85.3 acc_b=79.2
   ```

4. **Verify results in PostgreSQL:**
   ```sql
   SELECT * FROM game_analysis WHERE game_id = 'some-game-id';
   SELECT COUNT(*) FROM move_analysis WHERE analysis_id = <analysis_id>;
   ```

### 7. Monitor Costs

- **$0** when no jobs are queued (scales to zero)
- **$0.000005** per compute unit-second (Flex workers)
- Average game: 10–20s compute → ~$0.00005–0.0001 per game
- Estimate: **1000 games/month ≈ $0.05** (vs. $20–40/month on Railway)

## Troubleshooting

### "status": "error": "ModuleNotFoundError: No module named 'chess'"
- Verify `requirements.txt` includes `chess>=1.10.0`
- Rebuild the image: `docker build --no-cache -t ...`

### "DatabaseURL not found" or connection timeout
- Check `DATABASE_URL` env var is set and valid
- Verify PostgreSQL is accessible from RunPod (public IP, not localhost)
- Test: `psql postgresql://user:pass@host/db`

### Jobs submitted but not appearing in RunPod logs
- Check `RUNPOD_ENDPOINT_ID` and `RUNPOD_API_KEY` are correct
- Verify the endpoint is **active** (not paused or errored)
- Check Railway logs for job_submitter errors

### Slow analysis (>60s per game)
- Reduce `ANALYSIS_DEPTH` (try 18 instead of 20)
- Reduce `ANALYSIS_HASH_MB` (try 1024 instead of 2048)
- Reduce `ANALYSIS_THREADS` (try 4 instead of 8)
- Update in RunPod endpoint environment variables and retest

### Stockfish binary not found in RunPod container
- Verify Dockerfile installs to `/usr/games/stockfish`
- Check `STOCKFISH_PATH` env var matches the installation path
- Rebuild image with `--no-cache` to ensure fresh binary download

## Rollback Plan

If RunPod is down or needs debugging, revert to local Railway worker:

1. **Remove RunPod env vars** from Railway:
   - Delete `RUNPOD_ENDPOINT_ID` and `RUNPOD_API_KEY`
   - Set `STOCKFISH_PATH=/usr/local/bin/stockfish`

2. **Rebuild Railway Dockerfile** with Stockfish:
   ```bash
   # In woodland_stockfish/
   docker build --build-arg INSTALL_STOCKFISH=true -t ...
   ```

3. **Deploy to Railway** — `start_workers.py` will detect missing `RUNPOD_ENDPOINT_ID` and fall back to local worker

## Performance Expectations

After migration:

| Metric | Before (Railway) | After (RunPod) |
|--------|------------------|----------------|
| Time per 14-move game | 90–150s | 10–20s |
| CPU type | Shared burstable | Dedicated compute |
| Idle cost | ~$20–40/month | **$0** |
| Max parallel games | 1 (per replica) | Up to 10 |
| Stockfish threads | 1 (env default) | 8 (dedicated) |
| Hash table | 256 MB | 2048 MB |

## References

- RunPod API Docs: https://docs.runpod.io/
- RunPod Serverless Quickstart: https://docs.runpod.io/serverless/quick-start
- Stockfish SF18: https://github.com/official-stockfish/Stockfish/releases
