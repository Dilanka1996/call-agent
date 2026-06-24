# DESIGN.md - Payer Call Agent Core

## Overview

This document describes the architecture, design decisions, and trade-offs for the Multi-Scenario Payer Call Agent Core. The system automates insurance payer phone calls across three scenarios (benefits verification, claim denial follow-up, prior authorization).

---

## 1. Architecture Overview

The system is built around a single agent core that serves all scenarios through configuration, not code duplication. Adding a fourth scenario requires only a new YAML configuration section.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AGENT (Caller)                                  │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────────────────────┐ │
│  │ UserContext │    │   Prompts    │    │         IntentRouter            │ │
│  │ (patient    │    │ (3 scenario  │    │  ┌─────────┐    ┌───────────┐  │ │
│  │  data)      │    │  templates)  │    │  │   KB    │───▶│    LLM    │  │ │
│  └─────────────┘    └──────────────┘    │  │ Matcher │    │ Classifier│  │ │
│                                          │  └────┬────┘    └─────┬─────┘  │ │
│                                          │       │               │        │ │
│                                          │       ▼               ▼        │ │
│                                          │  [confidence >= 0.6] [fallback]│ │
│                                          └───────────────┬────────────────┘ │
└──────────────────────────────────────────────────────────┼──────────────────┘
                                                           │
                              question                     │
                                 │                         │
                                 ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PAYER BOUNDARY                                     │
│                    (Sensitive data must NOT cross)                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                          MockPayer                                      │ │
│  │  ┌─────────┐    ┌─────────────┐    ┌────────────────────────────────┐  │ │
│  │  │   IVR   │───▶│  Rep Q&A    │───▶│      Injection Engine          │  │ │
│  │  │  Menu   │    │  (answers)  │    │  • drop_after_question         │  │ │
│  │  │ (DTMF)  │    │             │    │  • contradict                  │  │ │
│  │  └─────────┘    └─────────────┘    │  • transfer_on                 │  │ │
│  │                                     │  • off_script_on              │  │ │
│  │                                     │  • unreachable                │  │ │
│  │                                     └────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Components:**
- **IntentRouter**: Tiered classification system (rule-based → LLM → human)
- **KnowledgeBase**: Question patterns, variations, and answer templates per scenario
- **MockPayer**: Fixture-driven simulator with failure injection
- **UserContext**: Holds member data (copay, deductible, etc.) for answer generation

---

## 2. Intent Classification Flow

The system uses a tiered approach to classify user questions, minimizing LLM calls while handling real-world ambiguity.

```
                    Question: "What's the copay?"
                              │
                              ▼
                    ┌─────────────────┐
                    │  IntentRouter   │
                    └────────┬────────┘
                             │
                             ▼
                   ┌─────────────────┐
                   │ KB Fuzzy Match  │
                   │ (SequenceMatcher│
                   │  + keywords)    │
                   └────────┬────────┘
                            │
                   ┌────────┴────────┐
                   │ confidence?     │
                   └────────┬────────┘
                            │
               ┌────────────┴────────────┐
               │                         │
            >= 0.6                     < 0.6
               │                         │
               ▼                         ▼
          ┌─────────┐          ┌──────────────────┐
          │ RETURN  │          │  LLM Classify    │
          │ RULE    │          │  (gpt-4o-mini)   │
          │ BASED   │          └────────┬─────────┘
          └─────────┘                   │
                                        │
                              ┌─────────┴─────────┐
                              │ LLM needs_human?  │
                              └─────────┬─────────┘
                                        │
                            ┌───────────┴───────────┐
                            │                       │
                          false                   true
                            │                       │
                            ▼                       ▼
                       ┌─────────┐           ┌───────────┐
                       │ RETURN  │           │  RETURN   │
                       │ LLM     │           │  NEEDS    │
                       │ FALLBACK│           │  HUMAN    │
                       └─────────┘           └───────────┘
```

**Three Possible Outcomes:**
1. **RULE_BASED** (Tier 1): KB confidence >= 0.6, no LLM call needed
2. **LLM_FALLBACK** (Tier 2): LLM classified successfully
3. **NEEDS_HUMAN** (Tier 3): LLM determined question is outside scope or ambiguous

---

## 3. Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA (data/)                             │
│  ┌──────────────────┐         ┌──────────────────┐              │
│  │ knowledge_base   │         │  user_contexts   │              │
│  │     .yaml        │         │      .yaml       │              │
│  │                  │         │                  │              │
│  │ • questions      │         │ • ref-10001      │              │
│  │ • variations     │         │ • ref-20001      │              │
│  │ • answer_        │         │ • ref-30001      │              │
│  │   templates      │         │   ...            │              │
│  └────────┬─────────┘         └────────┬─────────┘              │
└───────────┼────────────────────────────┼────────────────────────┘
            │                            │
            ▼                            ▼
┌───────────────────────┐         ┌────────────────┐
│    KnowledgeBase      │         │  UserContext   │
│                       │         │                │
│ find_matching_intent()│         │ • copay: 20    │
│ generate_answer()     │         │ • deductible   │
└───────────┬───────────┘         │ • coverage     │
            │                     └────────┬───────┘
            │                              │
            └───────────┬──────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │      MockPayer        │
            │   (+ fixture IVR)     │
            │                       │
            │  ask("copay?")        │
            │       │               │
            │       ▼               │
            │  "Copay is 20 dollars"│
            └───────────────────────┘
```

---

## 4. LLM vs Deterministic Boundary

A core requirement is being **deterministic-first**: use LLM only where genuine reasoning is required.

| Step | Method | Rationale |
|------|--------|-----------|
| IVR navigation | **Deterministic** | Fixed menu tree, press 1/2/3 |
| Intent matching (confidence >= 0.6) | **Rule-based** (KB fuzzy match) | Fast, free, predictable |
| Intent matching (confidence < 0.6) | **LLM fallback** | Handles vague/noisy questions |
| Answer generation | **Template-based** | Simple fill-in-the-blank |
| Off-script response parsing | **LLM** | Requires semantic understanding |

**What calls the LLM:**
- `LLMClassifier.classify()` in `src/agent/llm_classifier.py`
- Only invoked when `IntentRouter` detects KB confidence < 0.6

**What does NOT call the LLM:**
- IVR navigation (`send_dtmf`)
- High-confidence intent matching
- Answer template filling
- State management (connected/dropped/unreachable)

---

## 5. Design Decisions

### Fuzzy Matching Over Semantic Embeddings

**Choice:** `SequenceMatcher` + keyword boosting instead of vector embeddings.

**Rationale:** For this assignment, fuzzy string matching provides sufficient accuracy with zero external dependencies. A semantic embedding approach (e.g., `sentence-transformers` with a local model) would improve matching quality for paraphrased questions but adds complexity.

**Future upgrade path:** Replace `_similarity_score()` in `knowledge_base.py` with cosine similarity on embeddings. The interface remains identical.

### Simple Response Generation

**Choice:** Template-based answers, not conversational LLM responses.

**Rationale:** The system's goal is structured data extraction, not human-like conversation. When a rep asks "What's the copay?", returning `"Copay is {copay} dollars."` is sufficient. Highly realistic responses would add latency and cost without improving data quality.

### LLM for Noisy World Scenarios

**Choice:** Use LLM classification when rule-based confidence is low.

**Rationale:** Real payer representatives give messy, ambiguous answers. Questions like "tell me about the copay situation" or "what's the deal with coverage?" don't match KB patterns well but are clearly asking about specific intents. The LLM excels at this semantic classification task.

---

## 6. Model Selection and Cost Trade-offs

**Selected Model:** `gpt-4o-mini`

| Factor | Value | Notes |
|--------|-------|-------|
| Input cost | ~$0.15 / 1M tokens | Negligible per-call cost |
| Output cost | ~$0.60 / 1M tokens | ~200 tokens per classification |
| Latency | 200-500ms | Acceptable for phone call pace |
| Accuracy | High | Sufficient for intent classification |

---

## 7. Sensitive Data Boundary

**Requirement:** The patient's insurance member ID must not cross the `MockPayer.ask()` boundary.

**Implementation:**
```python
# In UserContext (src/agent/context.py)
class UserContext:
    """
    SECURITY NOTE: member_id_token is a reference token, not the raw member ID.
    The raw ID must never cross the payer boundary.
    """
    member_id_token: str  # e.g., "ref-10001", not actual SSN/member ID
```

**How it works:**
1. Real member IDs are stored in a secure database (not implemented in mock)
2. Fixtures use reference tokens (`ref-10001`, `ref-20001`, etc.)
3. The `MockPayer.ask()` boundary represents an external vendor - tokens only
4. Answer templates use context values, but identifiers remain tokenized

This approach treats the payer boundary as untrusted, consistent with real-world vendor integrations.

---

## 8. Deferred Work

The following items were deferred due to time constraints. Each includes a brief approach for future implementation.

### Contradiction Detection (IMPLEMENTED)
**Status:** Briefly integrated into `MockPayer.get_result()`

- Checks fixture's `inject.contradict` configuration
- If contradiction was triggered (same intent asked multiple times with different configured answers), returns `status="blocked"` with `blocked_reason="contradictory: {field}"`
- Simple and sufficient for the fixture-driven testing approach

### Retry Logic and Timeouts
**Current:** No retry on failure.
**Deferred:** Configurable retry policy with exponential backoff.
**Approach:** Wrap call loop in retry decorator with max_attempts and timeout parameters.

### Semantic Embeddings Upgrade
**Current:** SequenceMatcher fuzzy matching.
**Deferred:** Local embedding model for better paraphrase handling.
**Approach:** Use `sentence-transformers` with `all-MiniLM-L6-v2` (free, runs locally). Replace `_similarity_score()` with cosine similarity.

### LLM-Based Answer Analysis (Production)
**Current:** Off-script responses and contradictions are simulated via fixture injection for testing.
**Deferred:** In production, the LLM would analyze actual rep responses to detect:
- **Off-script/ambiguous answers:** Hedging language ("I think", "maybe"), unrelated responses
- **Contradictions:** Compare extracted value against previous answers for same intent
- **Value extraction:** Parse messy speech-to-text into structured data with confidence scores

This extends the existing Tier 2 LLM classifier to handle both question intent and answer validation in a single pass.

---

## 9. Adding a Fourth Scenario

The architecture is designed so adding a new scenario requires **no code changes** - only configuration.

**Steps to add "Pharmacy Benefits" scenario:**

1. **Add to `data/knowledge_base.yaml`:**
```yaml
pharmacy_benefits:
  medication_coverage:
    questions:
      primary: "Is this medication covered?"
      variations:
        - "Does the plan cover this drug?"
        - "Is this on formulary?"
    answer_field: medication_covered
    answer_template: "Yes, {medication_name} is covered under tier {tier_level}."
  
  prior_auth_required:
    questions:
      primary: "Does this medication require prior authorization?"
      # ... etc
```

2. **Add fixture file `tests/fixtures/golden_pharmacy.yaml`:**
```yaml
scenario: pharmacy_benefits
user_id: ref-40001
ivr:
  root: "Press 1 eligibility, 2 claims, 3 auth, 4 pharmacy"
  "4": "Hold for pharmacy benefits..."
rep_answers:
  medication_coverage: "Yes, that's a tier 2 drug."
```

3. **Add user context to `data/user_contexts.yaml`:**
```yaml
ref-40001:
  member_id_token: "ref-40001"
  plan_type: "ppo"
  medication_name: "Lipitor"
  tier_level: 2
```

**No changes needed to:**
- `MockPayer` class
- `IntentRouter`
- `KnowledgeBase` loader
- Test infrastructure

---

## 10. AI Tooling Disclosure

**Time spent:** ~20 hours

AI assistance (Claude) was used during development for:
- Boilerplate code generation (dataclasses, pytest fixtures)
- Documentation drafting
- Debugging fuzzy matching edge cases

The core architecture decisions (tiered classification, deterministic-first approach etc.) were made independently based on the assignment requirements.

---