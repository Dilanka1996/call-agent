# Payer Call Agent Core

Multi-scenario AI agent for automating insurance payer phone calls. A single reusable core serves three scenarios (benefits verification, claim denial follow-up, prior authorization) through configuration.

> **Optional — real LLM for CLI:** By default, `python main.py` uses mock LLM fallback when KB matching is uncertain. To use OpenAI for vague or paraphrased questions, copy `.env.example` to `.env`, set `USE_REAL_LLM=1`, and add your `OPENAI_API_KEY`. See [Enable Real LLM](#enable-real-llm) for details.

## Quick Start

```bash
./run.sh
```

This creates a `.venv`, installs dependencies, and runs tests.

## Features

- **Single Core, Multiple Scenarios**: One agent core serves all scenarios via YAML configuration
- **Tiered Intent Classification**: Rule-based matching → LLM fallback → Human escalation
- **Fixture-Driven Simulation**: Mock payer with injectable failures (drops, contradictions, transfers)
- **Explicit State Machine**: Tracks call progress with transition guards and retry logic
- **Sensitive Data Protection**: Member IDs use reference tokens, never cross payer boundary

## Setup

```bash
# Install dependencies
python -m pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Run interactive CLI
python main.py
```

**Test Coverage:** 9 focused tests covering failure paths (drop, unreachable, contradictory, transfer, off-script) and golden transcripts for all 3 scenarios.

## Run Interactive CLI

The CLI lets you interactively test the mock payer simulator.

```bash
python main.py
```

### CLI Usage

```
============================================================
  MOCK PAYER SIMULATOR - Interactive CLI
============================================================

  [Matching: KB fuzzy]
  [LLM Fallback: Mock - use clear questions]

----------------------------------------
  IVR MENU
----------------------------------------
  [1] Eligibility / Benefits
  [2] Claims
  [3] Prior Authorization
----------------------------------------
  [?] Show available questions
  [s] Show state machine status
  [r] Reset call
  [x] Exit
----------------------------------------

[State: IVR | Q: 0]
> 1

Connected to: Benefits Verification

  Questions for Benefits Verification:
  ----------------------------------------
  • Is the coverage active for this member?
  • What is the copay amount?
  • How much is left on the deductible?
  • Is there a visit limit?
  • Does this service require prior authorization?

Type your question or press ? for help:

[State: CONNECTED | Q: 0]
[Dept: Benefits Verification]
> What's the copay?

Rep: Copay is 25 dollars.
  [Matched by: KB fuzzy (85%)]
```

### CLI Commands

| Command | Description |
|---------|-------------|
| `1`, `2`, `3` | Navigate IVR menu |
| `?` | Show available questions for current department |
| `s` | Show detailed state machine status |
| `r` | Reset call to initial state |
| `x` | Exit |

### Enable Real LLM

By default, `python main.py` uses **mock LLM** fallback when KB fuzzy matching is uncertain. For real OpenAI classification of vague or paraphrased questions:

```bash
cp .env.example .env
```

Then in `.env`:

```bash
USE_REAL_LLM=1
OPENAI_API_KEY=sk-your-key-here
```

Restart the CLI — you should see `[LLM Fallback: OpenAI - understands vague questions]`.

## Project Structure

```
├── main.py                    # Interactive CLI for testing
├── DESIGN.md                  # Architecture decisions, diagrams, trade-offs
│
├── src/
│   ├── agent/
│   │   ├── context.py         # UserContext with sensitive data handling
│   │   ├── intent_router.py   # Tiered routing (KB → LLM → Human)
│   │   ├── knowledge_base.py  # Q&A patterns and fuzzy matching
│   │   ├── llm_classifier.py  # OpenAI integration + mock
│   │   └── state_machine.py   # Call state machine with transitions
│   │
│   └── payer/
│       └── simulator.py       # MockPayer + Fixture loading + get_result()
│
├── data/
│   ├── knowledge_base.yaml    # Question patterns for all scenarios
│   └── user_contexts.yaml     # Test user data (member contexts)
│
└── tests/
    ├── fixtures/              # Test scenario YAML files
    │   ├── golden_*.yaml      # Happy path scenarios (3 scenarios)
    │   ├── drop_mid_call.yaml # Failure: call drops
    │   ├── unreachable.yaml   # Failure: payer unreachable
    │   ├── contradictory.yaml # Ambiguity: rep contradicts
    │   ├── off_script.yaml    # Ambiguity: unexpected answer
    │   └── transfer.yaml      # Failure: rep transfers
    │
    └── test_payer.py          # 9 focused tests (failures + golden transcripts)
```

## Scenarios

### 1. Benefits Verification
Confirm insurance is active before a patient visit.
- Coverage active?
- Copay amount?
- Deductible remaining?
- Visit limit?
- Prior auth required?

### 2. Claim Denial Follow-up
Investigate why a submitted bill was rejected.
- Claim status?
- Denial reason/code?
- Amount owed?
- Appeal process?
- Next steps?

### 3. Prior Authorization Follow-up
Check status of a pre-approval request.
- Auth status?
- Reference number?
- Missing documents?
- Decision timeline?
- Next steps?

## Adding a Fourth Scenario

No code changes required - only configuration:

1. Add questions to `data/knowledge_base.yaml`
2. Create fixture in `tests/fixtures/`
3. Add user context to `data/user_contexts.yaml`

See `DESIGN.md` Section 9 for detailed example.

## Documentation

- **[DESIGN.md](DESIGN.md)** - Architecture decisions, system diagrams, LLM boundaries, trade-offs
