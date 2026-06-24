"""Fixture-driven mock payer simulator."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from src.agent.state_machine import CallState, CallStateMachine

if TYPE_CHECKING:
    from src.agent.knowledge_base import KnowledgeBase


@dataclass
class InjectionConfig:
    """Configuration for injecting failures/edge cases."""
    drop_after_question: int | None = None
    unreachable: bool = False
    contradict: dict[str, Any] | None = None  # {field, second_answer}
    transfer_on: str | None = None  # question_id that triggers transfer
    off_script_on: str | None = None  # question_id that returns unexpected answer
    off_script_response: str | None = None


@dataclass
class Fixture:
    """A test fixture defining payer behavior."""
    scenario: str
    name: str
    ivr: dict[str, str]  # path -> prompt mapping
    rep_answers: dict[str, str]  # question_intent -> answer
    user_context: dict[str, Any] = field(default_factory=dict)  # member context from DB
    inject: InjectionConfig = field(default_factory=InjectionConfig)
    initial_state: CallState = "connected"
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fixture:
        inject_data = data.get("inject", {})
        inject = InjectionConfig(
            drop_after_question=inject_data.get("drop_after_question"),
            unreachable=inject_data.get("unreachable", False),
            contradict=inject_data.get("contradict"),
            transfer_on=inject_data.get("transfer_on"),
            off_script_on=inject_data.get("off_script_on"),
            off_script_response=inject_data.get("off_script_response"),
        )
        
        behavior = data.get("call_behavior", {})
        
        return cls(
            scenario=data["scenario"],
            name=data.get("name", "unnamed"),
            ivr=data.get("ivr", {}),
            rep_answers=data.get("rep_answers", {}),
            user_context=data.get("user_context", {}),
            inject=inject,
            initial_state=behavior.get("initial_state", "connected"),
        )


def _get_user_contexts_path(fixture_path: Path) -> Path:
    """Get path to user_contexts.yaml (always in data/ relative to project root)."""
    # fixtures are in tests/fixtures/, so go up 3 levels to project root
    return fixture_path.parent.parent.parent / "data" / "user_contexts.yaml"


def load_fixture(path: str | Path, user_contexts_path: str | Path | None = None) -> Fixture:
    """
    Load a fixture from a YAML file.
    
    If the fixture has a `user_id` field instead of inline `user_context`,
    the user context is loaded from user_contexts.yaml (in data/ or fixture dir).
    """
    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f)
    
    if "user_id" in data and "user_context" not in data:
        if user_contexts_path is None:
            user_contexts_path = _get_user_contexts_path(path)
        
        with open(user_contexts_path) as f:
            all_contexts = yaml.safe_load(f)
        
        user_id = data["user_id"]
        if user_id in all_contexts:
            data["user_context"] = all_contexts[user_id]
        else:
            data["user_context"] = {}
    
    return Fixture.from_dict(data)


class MockPayer:
    """
    Fixture-driven mock payer simulator.
    
    Simulates an insurance payer's phone system including:
    - IVR menu navigation
    - Representative Q&A
    - Injected failures (drops, contradictions, transfers, etc.)
    
    When a KnowledgeBase is provided, automatically creates an IntentRouter
    with LLM fallback for robust intent matching.
    
    Uses CallStateMachine for explicit state management with transition guards.
    """
    
    def __init__(
        self,
        fixture: Fixture,
        knowledge_base: "KnowledgeBase | None" = None,
        use_mock_llm: bool = True,
    ):
        self._fixture = fixture
        self._kb = knowledge_base
        self._router = None
        
        if knowledge_base is not None:
            from src.agent.intent_router import IntentRouter
            self._router = IntentRouter(
                knowledge_base,
                use_mock_llm=use_mock_llm,
            )
        
        self._ivr_path: list[str] = []  # Track navigation path
        self._questions_by_intent: dict[str, int] = {}  # Track how many times each intent asked
        self._transferred = False
        self._in_ivr = True  # Start in IVR mode
        self._current_scenario = fixture.scenario  # Can be changed via set_scenario()
        self._last_routing_result = None  # Track last routing result for debugging
        
        # Initialize state machine
        self._state_machine = CallStateMachine()
        self._init_state_from_fixture(fixture)
    
    def _init_state_from_fixture(self, fixture: Fixture) -> None:
        """Initialize state machine based on fixture configuration."""
        if fixture.inject.unreachable:
            # Start in unreachable state
            self._state_machine.state = CallState.UNREACHABLE
        elif fixture.initial_state == "connected":
            # Skip to connected state for testing convenience
            self._state_machine.state = CallState.CONNECTED
        elif fixture.initial_state == "on_hold":
            self._state_machine.state = CallState.ON_HOLD
        elif fixture.initial_state == "dropped":
            self._state_machine.state = CallState.DROPPED
        else:
            # Default: start in IVR (simulating we just dialed)
            self._state_machine.state = CallState.IVR
    
    @property
    def state_machine(self) -> CallStateMachine:
        """Access the underlying state machine for advanced operations."""
        return self._state_machine
    
    def set_scenario(self, scenario: str) -> None:
        """Set the current scenario (used when navigating IVR to different departments)."""
        self._current_scenario = scenario
    
    def ivr_prompt(self) -> str:
        """Get current IVR prompt based on navigation path."""
        if self._state_machine.state == CallState.UNREACHABLE:
            return ""
        
        if not self._in_ivr:
            return ""
        
        path_key = ",".join(self._ivr_path) if self._ivr_path else "root"
        
        if path_key in self._fixture.ivr:
            return self._fixture.ivr[path_key]
        
        # Check if we've reached the end of menu (on hold)
        if self._ivr_path:
            parent_key = ",".join(self._ivr_path[:-1]) if len(self._ivr_path) > 1 else "root"
            if parent_key in self._fixture.ivr:
                # We navigated past the last menu
                self._in_ivr = False
                self._state_machine.state = CallState.ON_HOLD
                return "Please hold for the next available representative..."
        
        return self._fixture.ivr.get("root", "")
    
    def send_dtmf(self, digit: str) -> None:
        """Navigate IVR by pressing a digit."""
        if self._state_machine.state == CallState.UNREACHABLE:
            return
        
        self._ivr_path.append(digit)
        
        # Check if this path exists in fixture
        path_key = ",".join(self._ivr_path)
        if path_key in self._fixture.ivr:
            prompt = self._fixture.ivr[path_key]
            # If prompt indicates hold, transition to on_hold
            if "hold" in prompt.lower() or "representative" in prompt.lower():
                self._in_ivr = False
                self._state_machine.state = CallState.ON_HOLD
    
    def ask(self, question: str) -> str:
        """
        Ask the representative a question.
        
        The question is matched against configured intents using fuzzy matching.
        """
        if self._state_machine.state in (CallState.UNREACHABLE, CallState.DROPPED):
            return ""
        
        # Transition from on_hold to connected when asking first question
        if self._state_machine.state == CallState.ON_HOLD:
            self._state_machine.state = CallState.CONNECTED
        
        # Record question in state machine
        question_num = self._state_machine.record_question()
        
        # Check for mid-call drop injection
        inject = self._fixture.inject
        if inject.drop_after_question and question_num > inject.drop_after_question:
            self._state_machine.state = CallState.DROPPED
            return ""
        
        # Find matching intent
        intent = self._match_intent(question)
        
        if intent is None:
            return "I'm sorry, could you repeat that?"
        
        # Track question count per intent
        self._questions_by_intent[intent] = self._questions_by_intent.get(intent, 0) + 1
        ask_count = self._questions_by_intent[intent]
        
        # Check for transfer injection
        if inject.transfer_on and inject.transfer_on == intent:
            self._transferred = True
            self._in_ivr = True
            self._ivr_path = []
            self._state_machine.state = CallState.ON_HOLD
            return "Let me transfer you to another department for that..."
        
        # Check for off-script injection
        if inject.off_script_on and inject.off_script_on == intent:
            return inject.off_script_response or "Hmm, that's a good question. Let me see... I'm not sure about that."
        
        # Check for contradiction injection
        if inject.contradict and inject.contradict.get("field") == intent:
            trigger_on = inject.contradict.get("on_question", 2)
            if ask_count >= trigger_on:
                return inject.contradict.get("second_answer", "Actually, let me check that again...")
        
        # Return answer (from rep_answers override or KB template)
        answer = self._get_answer_for_intent(intent)
        
        # Add clarification prefix if LLM suggested one
        if self._last_routing_result and self._last_routing_result.needs_clarification:
            clarification = self._last_routing_result.clarification
            if clarification:
                answer = f"{clarification} {answer}"
        
        return answer
    
    def last_routing_info(self) -> dict | None:
        """Get info about how the last question was routed (for debugging)."""
        if self._last_routing_result is None:
            return None
        result = self._last_routing_result
        return {
            "tier": result.tier.value,
            "intent": result.intent,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "needs_clarification": result.needs_clarification,
            "clarification": result.clarification,
        }
    
    def _match_intent(self, question: str) -> str | None:
        """
        Match a question to a configured intent.
        
        Priority:
        1. IntentRouter (KB + LLM fallback) if available
        2. KnowledgeBase fuzzy matching if available
        3. Keyword matching fallback
        
        When using router/KB, intents with answer_templates are available.
        """
        available_intents = self._get_available_intents_with_kb() if self._kb else None
        
        if self._router is not None:
            result = self._router.route(
                question=question,
                scenario=self._current_scenario,
                available_intents=available_intents,
            )
            self._last_routing_result = result  # Store for debugging
            return result.intent if result.success else None
        
        if self._kb is not None:
            return self._kb.find_matching_intent(
                scenario=self._current_scenario,
                question=question,
                available_intents=available_intents,
            )
        
        return None
    
    def _get_available_intents_with_kb(self) -> list[str]:
        """Get intents available from KB for this scenario."""
        if not self._kb:
            return []
        
        available = []
        for intent in self._kb.get_all_intents(self._current_scenario):
            qs = self._kb.get_questions(self._current_scenario, intent)
            if qs and qs.answer_template:
                available.append(intent)
        
        return available
    
    def _get_answer_for_intent(self, intent: str) -> str:
        """
        Get the answer for an intent.
        
        Priority:
        1. Fixture rep_answers override (if present)
        2. KB template filled with user_context
        3. Default fallback message
        """
        if intent in self._fixture.rep_answers:
            return self._fixture.rep_answers[intent]
        
        if self._kb:
            qs = self._kb.get_questions(self._current_scenario, intent)
            if qs and qs.answer_template:
                return qs.generate_answer(self._fixture.user_context)
        
        return "I don't have that information available."
    
    
    def get_result(self) -> dict[str, Any]:
        """
        Build a structured result from the call.
        
        Returns a dict with:
        - status: "success" | "blocked" | "failed"
        - scenario: the scenario name
        - fields: collected answers
        - confidence: overall confidence score
        - blocked_reason: why blocked (if applicable)
        - transcript: list of Q&A exchanges
        """
        state = self._state_machine.state
        scenario = self._current_scenario
        
        # Collect answers from questions asked
        fields = {}
        transcript = []
        for intent, count in self._questions_by_intent.items():
            answer = self._get_answer_for_intent(intent)
            fields[intent] = answer
            transcript.append({"intent": intent, "answer": answer})
        
        # Check failure states
        if state == CallState.UNREACHABLE:
            return {
                "status": "failed",
                "scenario": scenario,
                "fields": {},
                "confidence": 0.0,
                "blocked_reason": "payer_unreachable",
                "transcript": [],
            }
        
        if state == CallState.DROPPED:
            return {
                "status": "blocked",
                "scenario": scenario,
                "fields": fields,
                "confidence": 0.0,
                "blocked_reason": "call_dropped",
                "transcript": transcript,
            }
        
        # Check for contradictions
        inject = self._fixture.inject
        if inject.contradict:
            field = inject.contradict.get("field")
            if field and self._questions_by_intent.get(field, 0) >= inject.contradict.get("on_question", 2):
                return {
                    "status": "blocked",
                    "scenario": scenario,
                    "fields": fields,
                    "confidence": 0.0,
                    "blocked_reason": f"contradictory: {field}",
                    "transcript": transcript,
                }
        
        # Success
        confidence = 0.9 if fields else 0.0
        return {
            "status": "success",
            "scenario": scenario,
            "fields": fields,
            "confidence": confidence,
            "blocked_reason": None,
            "transcript": transcript,
        }
    
    def reset(self) -> None:
        """Reset the simulator to initial state."""
        self._ivr_path = []
        self._questions_by_intent = {}
        self._transferred = False
        self._in_ivr = True
        
        # Reset state machine and reinitialize from fixture
        self._state_machine.reset()
        self._init_state_from_fixture(self._fixture)
