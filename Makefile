# Local development without Docker. Requires uv and Node 20+.
.PHONY: install up mocks api web speech test eval eval-heldout bench load stop reset selfhosted selfhosted-check selfhosted-deploy

install:
	cd backend && uv sync
	cd speech && uv sync  # Apple Silicon only (MLX); skip on other machines
	cd web && npm ci

mocks:
	cd backend && uv run uvicorn mocks.app:app --port 8100

# local runs are demos: on-screen OTP codes and chaos controls. Set DEMO_MODE=false (and real secrets) otherwise.
export DEMO_MODE ?= true

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

eval-heldout:  ## reworded questions never used to tune the intents -> docs/evals/heldout-<planner>.md
	cd backend && uv run python evals/run.py --set heldout

bench:
	cd backend && uv run python bench/journeys.py --runs 20 --cold

load:  ## needs `LLM_MODE=stub TURN_RATE_LIMIT=100000 make api` running
	cd backend && ulimit -n 10240 && uv run locust -f loadtest/locustfile.py --host http://localhost:8000 \
		--headless -u 1000 -r 20 -t 4m --csv var/load/run --only-summary

# ---- Self-hosted models on a GPU box over Tailscale (see deploy/selfhosted/README.md)
GPU_HOST ?= commoncreed-server

selfhosted-check:  ## are the GPU box's LLM and speech services reachable from here?
	@curl -sf -m 4 http://$(GPU_HOST):11434/api/version >/dev/null && echo "LLM     ok  http://$(GPU_HOST):11434" || echo "LLM     unreachable (Tailscale up? Ollama running?)"
	@curl -sf -m 4 http://$(GPU_HOST):8201/healthz && echo "  <- speech ok  http://$(GPU_HOST):8201" || echo "speech  unreachable"

selfhosted:  ## everything local except the models: LLM, speech recognition and voice on the GPU box
	mkdir -p backend/var
	cd backend && (uv run uvicorn mocks.app:app --port 8100 > var/mocks.log 2>&1 &)
	cd backend && (LLM_PROVIDER=selfhosted LLM_MODE=llm SELFHOSTED_LLM_URL=http://$(GPU_HOST):11434 \
		uv run uvicorn orchestrator.app:app --port 8000 > var/orchestrator.log 2>&1 &)
	cd web && (NEXT_PUBLIC_STT_URL=http://$(GPU_HOST):8201 NEXT_PUBLIC_TTS_URL=http://$(GPU_HOST):8201 \
		npm run dev > ../backend/var/web.log 2>&1 &)
	@echo "Open http://localhost:3000  (models on $(GPU_HOST))"

GPU_SSH ?= $(USER)@$(GPU_HOST)

selfhosted-deploy:  ## copy the speech service to the GPU box and (re)start its stack
	rsync -az --delete --exclude .venv --exclude __pycache__ --exclude tests speech deploy $(GPU_SSH):~/northstar/
	ssh $(GPU_SSH) 'cd ~/northstar/deploy/selfhosted && docker compose up -d --build'

reset:  ## clear recorded latency, turns, audit and filed requests (stop servers first)
	rm -f backend/var/app.db* backend/var/mocks.db*
