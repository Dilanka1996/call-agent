"""Tests for payer call behavior - failure paths and golden transcripts."""
import pytest
from pathlib import Path

from src.payer.simulator import MockPayer, load_fixture
from src.agent.knowledge_base import KnowledgeBase
from src.agent.state_machine import CallState

FIXTURES_DIR = Path(__file__).parent / "fixtures"
KB_PATH = Path(__file__).parent.parent / "data" / "knowledge_base.yaml"


@pytest.fixture
def kb() -> KnowledgeBase:
    return KnowledgeBase.load(KB_PATH)


# =============================================================================
# GOLDEN TRANSCRIPTS
# =============================================================================

class TestGoldenTranscripts:
    """Golden transcripts: successful calls with expected structured output."""
    
    def test_benefits_verification(self, kb):
        """Scenario 1: Benefits verification - all fields collected successfully"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "golden_benefits.yaml"), knowledge_base=kb)
        payer.send_dtmf("1")
        
        payer.ask("Is the policy active?")
        payer.ask("What's the copay?")
        payer.ask("How much is left on deductible?")
        payer.ask("Any visit limit?")
        payer.ask("Does this need prior auth?")
        
        result = payer.get_result()
        
        assert result["status"] == "success"
        assert result["scenario"] == "benefits_verification"
        assert result["confidence"] == 0.9
        assert result["blocked_reason"] is None
        assert len(result["fields"]) >= 4
    
    def test_claim_denial_followup(self, kb):
        """Scenario 2: Claim denial follow-up - denial info retrieved"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "golden_denial.yaml"), knowledge_base=kb)
        payer.send_dtmf("2")
        
        payer.ask("What's the claim status?")
        payer.ask("What's the denial reason?")
        
        result = payer.get_result()
        
        assert result["status"] == "success"
        assert result["scenario"] == "claim_denial"
        assert result["confidence"] == 0.9
        assert len(result["fields"]) >= 2
    
    def test_prior_auth_followup(self, kb):
        """Scenario 3: Prior auth follow-up - auth status and missing docs retrieved"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "golden_prior_auth.yaml"), knowledge_base=kb)
        payer.send_dtmf("3")
        
        payer.ask("What's the auth status?")
        payer.ask("What documents are missing?")
        payer.ask("What's the reference number?")
        
        result = payer.get_result()
        
        assert result["status"] == "success"
        assert result["scenario"] == "prior_authorization"
        assert result["confidence"] == 0.9
        assert len(result["fields"]) >= 3


# =============================================================================
# FAILURE PATHS
# =============================================================================

class TestFailurePaths:
    """Test all failure scenarios produce correct blocked/failed results."""
    
    def test_call_drop_mid_conversation(self, kb):
        """Call drops after 3 questions -> status=blocked, reason=call_dropped"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "drop_mid_call.yaml"), knowledge_base=kb)
        payer.send_dtmf("1")
        
        payer.ask("Is it active?")
        payer.ask("What's the copay?")
        payer.ask("Visit limit?")
        payer.ask("Prior auth?")  # 4th question triggers drop
        
        result = payer.get_result()
        assert result["status"] == "blocked"
        assert result["blocked_reason"] == "call_dropped"
    
    def test_payer_unreachable(self, kb):
        """Unreachable payer -> status=failed, reason=payer_unreachable"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "unreachable.yaml"), knowledge_base=kb)
        
        assert payer.state_machine.state == CallState.UNREACHABLE
        assert payer.ask("Is coverage active?") == ""
        
        result = payer.get_result()
        assert result["status"] == "failed"
        assert result["blocked_reason"] == "payer_unreachable"
    
    def test_contradictory_answers(self, kb):
        """Rep contradicts themselves -> status=blocked, reason=contradictory"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "contradictory.yaml"), knowledge_base=kb)
        payer.send_dtmf("1")
        
        payer.ask("What's the copay?")      # First: $20
        payer.ask("Confirm the copay?")     # Second: $40 (contradiction)
        
        result = payer.get_result()
        assert result["status"] == "blocked"
        assert "contradictory" in result["blocked_reason"]
    
    def test_rep_transfers_to_another_dept(self, kb):
        """Rep transfers call -> state goes to ON_HOLD"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "transfer.yaml"), knowledge_base=kb)
        payer.send_dtmf("2")
        
        answer = payer.ask("What's the claim status?")
        
        assert "transfer" in answer.lower()
        assert payer.state_machine.state == CallState.ON_HOLD
    
    def test_off_script_unexpected_answer(self, kb):
        """Rep gives confusing answer -> call stays connected (needs human review)"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "off_script.yaml"), knowledge_base=kb)
        payer.send_dtmf("1")
        
        answer = payer.ask("What's the visit limit?")
        
        assert "depends" in answer.lower() or "hold" in answer.lower()
        assert payer.state_machine.state == CallState.CONNECTED


# =============================================================================
# EDGE CASE: LLM fallback for vague questions
# =============================================================================

class TestLLMFallback:
    """Verify LLM fallback handles vague/noisy questions."""
    
    def test_vague_question_still_matches(self, kb):
        """Vague phrasing triggers LLM fallback but still gets correct answer"""
        payer = MockPayer(load_fixture(FIXTURES_DIR / "golden_benefits.yaml"), knowledge_base=kb)
        payer.send_dtmf("1")
        
        answer = payer.ask("Tell me about the copay situation")
        
        assert "20" in answer or "copay" in answer.lower()
