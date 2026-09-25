# Sample documents (ALL FICTIONAL)
Made-up test files for the attachment feature; "SAMPLE - FICTIONAL" is printed on each. Regenerate with `uv run python scripts/make_samples.py`.
- Live/manual (real Gemini or local Ollama via `scripts/live_llm_smoke.py`; PNGs have an alpha channel on purpose, the Ollama provider flattens them onto white): `sick-note-sample.pdf` (Amy Lau, 24-25 Sep 2026), `receipt-sample.png` (HK$ 83.60, 20 Sep 2026), `receipt-incomplete.png` (no date), `unreadable-blurry.png` (not readable).
- Offline (`LLM_PROVIDER=fake`): the `*.fake.pdf` files are valid PDFs that carry a `FAKE-DOC:` JSON line the fake provider turns into a document extraction (see `app/llm/fake.py`).
- Every file is under 200 KB and has genuine PDF/PNG signatures; no real names, clinics or merchants.
