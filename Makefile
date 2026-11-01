# Local development without Docker. Requires uv and Node 20+.
.PHONY: install up mocks api web speech test eval bench load stop reset

install:
	cd backend && uv sync
	cd speech && uv sync  # Apple Silicon only (MLX); skip on other machines
	cd web && npm ci

mocks:
	cd backend && uv run uvicorn mocks.app:app --port 8100

api:
	cd backend && uv run uvicorn orchestrator.app:app --port 8000

web:
	cd web && npm run dev

speech:  ## local speech recognition (Parakeet via MLX, Apple Silicon); the web app falls back to the browser without it
	cd speech && uv run uvicorn speech.app:app --port 8200

up:  ## all three in the background; logs in backend/var/*.log
	mkdir -p backend/var
	cd backend && (uv run uvicorn mocks.app:app --port 8100 > var/mocks.log 2>&1 &)
	cd backend && (uv run uvicorn orchestrator.app:app --port 8000 > var/orchestrator.log 2>&1 &)
	-[ "$$(uname -m)" = "arm64" ] && cd speech && (uv run uvicorn speech.app:app --port 8200 > ../backend/var/speech.log 2>&1 &)
	cd web && (npm run dev > ../backend/var/web.log 2>&1 &)
	@echo "Open http://localhost:3000"

stop:
	-pkill -f "uvicorn mocks.app" ; pkill -f "uvicorn orchestrator.app" ; pkill -f "uvicorn speech.app" ; pkill -f "next dev" ; pkill -f "next start"

test:
	cd backend && uv run pytest -q
	-[ "$$(uname -m)" = "arm64" ] && cd speech && uv run --group dev pytest -q
	cd web && npm test && npm run typecheck && npm run lint

eval:
	cd backend && uv run python evals/run.py

bench:
	cd backend && uv run python bench/journeys.py --runs 20 --cold

load:  ## needs `LLM_MODE=stub TURN_RATE_LIMIT=100000 make api` running
	cd backend && ulimit -n 10240 && uv run locust -f loadtest/locustfile.py --host http://localhost:8000 \
		--headless -u 1000 -r 20 -t 4m --csv var/load/run --only-summary

reset:  ## clear recorded latency, turns, audit and filed requests (stop servers first)
	rm -f backend/var/app.db* backend/var/mocks.db*
