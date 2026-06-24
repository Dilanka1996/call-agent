#!/usr/bin/env python3
"""Interactive CLI for testing the Mock Payer simulator."""
import os
from pathlib import Path

from dotenv import load_dotenv

from src.payer.simulator import MockPayer, load_fixture
from src.agent.knowledge_base import KnowledgeBase
from src.agent.state_machine import CallState

# Load .env file
load_dotenv()

DATA_DIR = Path(__file__).parent / "data"
FIXTURES_DIR = Path(__file__).parent / "tests" / "fixtures"
KB_PATH = DATA_DIR / "knowledge_base.yaml"
DEFAULT_FIXTURE = FIXTURES_DIR / "demo.yaml"

# Config from .env
USE_REAL_LLM = os.getenv("USE_REAL_LLM", "0") == "1"

IVR_MAPPING = {
    "1": "benefits_verification",
    "2": "claim_denial",
    "3": "prior_authorization",
}


def show_available_questions(kb: KnowledgeBase, scenario: str):
    """Show available questions for a scenario."""
    print(f"\n  Questions for {scenario.replace('_', ' ').title()}:")
    print("  " + "-" * 40)
    for intent in kb.get_all_intents(scenario):
        qs = kb.get_questions(scenario, intent)
        if qs:
            print(f"  • {qs.primary}")


def main():
    print("\n" + "=" * 60)
    print("  MOCK PAYER SIMULATOR - Interactive CLI")
    print("=" * 60)
    
    # Load knowledge base and default fixture
    kb = KnowledgeBase.load(KB_PATH)
    fixture = load_fixture(DEFAULT_FIXTURE)
    payer = MockPayer(fixture, knowledge_base=kb, use_mock_llm=not USE_REAL_LLM)
    current_scenario = None
    
    print("\n  [Matching: KB fuzzy]")
    
    # Show LLM mode
    if USE_REAL_LLM:
        print("  [LLM Fallback: OpenAI - understands vague questions]")
    else:
        print("  [LLM Fallback: Mock - use clear questions]")
    
    # Show IVR menu immediately
    print("\n" + "-" * 40)
    print("  IVR MENU")
    print("-" * 40)
    print("  [1] Eligibility / Benefits")
    print("  [2] Claims")
    print("  [3] Prior Authorization")
    print("-" * 40)
    print("  [?] Show available questions")
    print("  [s] Show state machine status")
    print("  [r] Reset call")
    print("  [x] Exit")
    print("-" * 40)
    
    while True:
        # Show full state machine status
        sm = payer.state_machine
        state_str = sm.state.value.upper()
        status_parts = [f"State: {state_str}"]
        
        if sm.question_count > 0:
            status_parts.append(f"Q: {sm.question_count}")
        if sm.retry_count > 0:
            status_parts.append(f"Retries: {sm.retry_count}/{sm.max_retries}")
        if sm.is_terminal():
            status_parts.append("TERMINAL")
        
        print(f"\n[{' | '.join(status_parts)}]")
        
        if current_scenario:
            print(f"[Dept: {current_scenario.replace('_', ' ').title()}]")
        
        cmd = input("> ").strip()
        cmd_lower = cmd.lower()
        
        if cmd_lower == 'x':
            print("\nGoodbye!")
            break
        
        elif cmd_lower == 'r':
            payer.reset()
            current_scenario = None
            print("Call reset. Select 1, 2, or 3.")
        
        elif cmd_lower == '?':
            if current_scenario:
                show_available_questions(kb, current_scenario)
            else:
                print("  Select a department first (1, 2, or 3)")
        
        elif cmd_lower == 's':
            # Show detailed state machine status
            sm = payer.state_machine
            print("\n  State Machine Status")
            print("  " + "-" * 30)
            print(f"  State:          {sm.state.value}")
            print(f"  Questions:      {sm.question_count}")
            print(f"  Retries:        {sm.retry_count}/{sm.max_retries}")
            print(f"  Can ask:        {sm.can_ask_question()}")
            print(f"  Can navigate:   {sm.can_navigate_ivr()}")
            print(f"  Is terminal:    {sm.is_terminal()}")
            print(f"  Is active:      {sm.is_active()}")
            if sm.history:
                print("  " + "-" * 30)
                print("  History:")
                for entry in sm.get_history()[-5:]:  # Last 5 transitions
                    print(f"    • {entry}")
        
        elif cmd in '123':
            payer.send_dtmf(cmd)
            current_scenario = IVR_MAPPING.get(cmd)
            payer.set_scenario(current_scenario)  # Update payer's scenario for intent matching
            print(f"\nConnected to: {current_scenario.replace('_', ' ').title()}")
            show_available_questions(kb, current_scenario)
            print("\nType your question or press ? for help:")
        
        elif cmd:
            if not current_scenario:
                print("  Select a department first (1, 2, or 3)")
            elif payer.state_machine.is_terminal():
                print("  Call has ended. Press [r] to reset.")
            elif payer.state_machine.state == CallState.DROPPED:
                print("  Call dropped! Press [r] to reset or retry.")
            else:
                answer = payer.ask(cmd)
                
                # Check if call dropped during question
                if payer.state_machine.state == CallState.DROPPED:
                    print("\n  *** CALL DROPPED ***")
                    print(f"  Questions asked: {payer.state_machine.question_count}")
                elif answer:
                    print(f"\nRep: {answer}")
                    
                    # Show routing info
                    routing = payer.last_routing_info()
                    if routing:
                        tier = routing["tier"]
                        if tier == "rule_based":
                            print(f"  [Matched by: KB fuzzy ({routing['confidence']:.0%})]")
                        elif tier == "llm_fallback":
                            print(f"  [Matched by: LLM]")
                        elif tier == "needs_human":
                            print(f"  [No match - needs human]")
                else:
                    print("\n  (No response - check call state)")


if __name__ == "__main__":
    main()
