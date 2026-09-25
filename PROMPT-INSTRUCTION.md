# Prompt Instruction Log

This file records the real, step-by-step use of AI coding agents during this assignment. It is not a transcript of every conversation. Do not invent prompts, agent outputs, test results, or commits after the fact.

## Recording rules

For every material agent task, append an entry containing:

1. Date and phase.
2. The actual prompt given to the agent.
3. Scope boundaries and files the agent was allowed to change.
4. The agent result and the human review decision.
5. Commands run and their result.
6. The resulting Git commit hash.

Never record API keys, access tokens, private data, or full prompts containing sensitive material.

## Product brief

Create an Internal Operations AI Assistant with a mock Google SSO login and unified chat interface. It must use Python and a multi-agent orchestration framework to identify Leave Application or Staff Claim intent, collect the required fields through follow-up questions, show API loading, require confirmation, and send the request to the ReqRes mock endpoint. The submission must include a public Git repository, clear agent context documentation, meaningful commit history, unit tests, modular code, a README, and this prompt log.

The PoC uses Nuxt 3, FastAPI, LangGraph, Pydantic, SQLite/SQLAlchemy, Google Gemini API (`gemini-3.8-flash` with low thinking), pytest, Playwright, and Docker Compose.

## Entry 00 - Phase 0 planning (KEN)

- **Date:** 2026-09-25
- **Actual task:** Create project-level agent instructions, a prompt-log template, and a phase checklist before application code is created.
- **Result:** `AGENTS.md`, `PROMPT-INSTRUCTION.md`, and `PHASE-CHECKLIST.md` were created. No application code, credentials, or real data were created or added.
- **Human review:** Accepted as the baseline for subsequent agent tasks.
- **Commit:** Pending repository initialization.

## Entry template

### Entry NN - [phase and short task name]

- **Date:** YYYY-MM-DD
- **Actual prompt:**
  ```text
  Paste the exact safe prompt here.
  ```
- **Allowed scope:**
- **Agent result:**
- **Human review / changes requested:**
- **Verification commands and results:**
- **Commit:**
