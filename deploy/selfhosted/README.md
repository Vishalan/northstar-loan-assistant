# Self-hosted models on one GPU box

Every model the assistant uses can run on our own hardware instead of a cloud API. Nothing else changes: the
orchestrator, packs, grounding check and web app are the same; only three settings point elsewhere.

| Role | Runs on the GPU box | Talks | Northstar setting |
|---|---|---|---|
| Planner LLM | Ollama, Qwen3 14B (Q4_K_M, 9.3 GB) | Anthropic Messages API on `:11434` | `LLM_PROVIDER=selfhosted`, `SELFHOSTED_LLM_URL` |
| Speech recognition | this repo's speech service, faster-whisper large-v3-turbo (fp16, CUDA) | same WebSocket protocol as the Mac build, `:8201` | web `NEXT_PUBLIC_STT_URL` |
| Assistant voice | Kokoro-82M (Kokoro-FastAPI), proxied by the speech service | `POST /v1/tts` on `:8201` | web `NEXT_PUBLIC_TTS_URL` |

The box is reached over **Tailscale**: ports bind to its tailnet address only, never the LAN or the internet.
That also means it only works from a machine on the same tailnet. So this mode is for a live demo from the
build machine. Anyone else runs the default setup (Claude API or the deterministic planner, local or browser
speech).

## The box we use

| | |
|---|---|
| GPU | NVIDIA GeForce RTX 3090, 24 GB VRAM, driver 595.99. **Power-capped at 300 W, SM clock locked to 1350 MHz** (of 2100) for thermal and PSU reasons, so these numbers are below what an uncapped 3090 does |
| CPU / RAM | AMD Ryzen 5 3600X, 6 cores / 12 threads; 62 GiB |
| Storage | 1 TB NVMe |
| OS | Ubuntu 24.04 LTS, Docker with the NVIDIA container toolkit, Ollama 0.32 on the host |
| Network | Wi-Fi to the home router; Tailscale (direct peer-to-peer link to the build machine) |
| Shared | The GPU also runs other workloads (about 7 GB in use before ours), so the planner model has to fit in ~16 GB |

## Measured (from the build machine over Tailscale)

| | |
|---|---|
| Speech recognition, decode per utterance | ~280 ms for a 2–4 s question (`decode_ms` in the final message), live partials every 400 ms |
| Voice, synthesis per sentence | 300–380 ms for a 90-character sentence (MP3, fetched in parallel, played in order) |
| Planner call, thinking off | ~0.8 s per step with a 1.5k-token prompt; 2.9 s with Qwen3's thinking phase on |
| Golden eval, 46 cases | thinking off: **40/46**, turn p50 7.7 s, p95 11.5 s ([report](../../docs/evals/selfhosted-qwen3-14b.md)); thinking on: **42/46**, turn p50 31.6 s ([report](../../docs/evals/selfhosted-qwen3-14b-thinking.md)) |

What the numbers say: on a single, capped consumer GPU, open-weight speech is as fast as the Mac's on-device
recogniser and the cloud voices, while the 14B planner is the weak link: several times slower than Claude Haiku
and less accurate (it misses dates and one action proposal). Turning its thinking phase on recovers only two
questions and costs four times the latency, which no voice call can afford. That's the reason the default stays a hosted Claude model with the deterministic planner
as fallback. Self-hosting the LLM makes sense when data must not leave the premises, on a bigger model and a GPU
that isn't shared.

## Set it up

On the GPU box (Ubuntu with Docker, the NVIDIA container toolkit, Ollama and Tailscale):

```bash
ollama pull qwen3:14b
sudo tailscale serve --bg --tcp 11434 tcp://localhost:11434    # Ollama, tailnet only
```

From the build machine (repo root), with Tailscale up:

```bash
make selfhosted-deploy GPU_HOST=<box name on the tailnet>  # copies speech/ + deploy/, builds, starts
# first time: on the box, create deploy/selfhosted/.env with
#   TAILNET_IP=<the box's 100.x address>
#   TTS_URL=http://host.docker.internal:8880    # a Kokoro already on the host; or run ours:
#   (docker compose --profile kokoro up -d, and leave TTS_URL unset)
make selfhosted-check GPU_HOST=<box>                          # both should say ok
make selfhosted GPU_HOST=<box>                                # mocks + API + web here, models there
```

Open http://localhost:3000. `GET localhost:8000/readyz` shows `"provider": "selfhosted"`, and the voice bar shows
the server voice. Switch back with `make stop && make up`.

## Pieces that make this work

- `backend/src/orchestrator/providers.yaml`: the `selfhosted` provider. Ollama speaks the Anthropic Messages
  API, so it is the same client with a different base URL. It accepts any model id (`SELFHOSTED_MODEL`), sends
  no Claude-only parameters, and turns Qwen3's thinking off (`request_params`).
- `speech/src/speech/engines.py`: `faster-whisper` for recognition on CUDA, and `openai` for synthesis from any
  OpenAI-compatible `/v1/audio/speech` server (Kokoro here).
- `speech/Dockerfile.cuda` and `docker-compose.yml` here.
- `web/lib/speech-output.ts`: the server voice, with a per-sentence fallback to the browser voice if the box is
  slow or unreachable.
