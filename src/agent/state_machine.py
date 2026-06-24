"""Call state machine for payer phone calls."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CallState(Enum):
    """Possible states during a payer phone call."""
    
    IDLE = "idle"              # Not yet started
    DIALING = "dialing"        # Attempting to connect
    IVR = "ivr"                # In automated menu system
    ON_HOLD = "on_hold"        # Waiting for representative
    CONNECTED = "connected"    # Talking to representative
    TRANSFERRED = "transferred"  # Being transferred to another dept
    DROPPED = "dropped"        # Call disconnected unexpectedly
    UNREACHABLE = "unreachable"  # Could not connect to payer
    COMPLETE = "complete"      # Call finished successfully
    BLOCKED = "blocked"        # Needs human intervention


class TransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    
    def __init__(self, from_state: CallState, to_state: CallState, reason: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        msg = f"Cannot transition from {from_state.value} to {to_state.value}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


@dataclass
class CallStateMachine:
    """
    Explicit state machine for payer phone calls.
    
    Tracks call progress and enforces valid state transitions.
    Provides guards to prevent invalid operations (e.g., asking questions when not connected).
    
    State Flow:
    ```
    IDLE → DIALING → IVR → ON_HOLD → CONNECTED → COMPLETE
                ↓           ↓           ↓
           UNREACHABLE   DROPPED     TRANSFERRED → ON_HOLD
                                        ↓
                                     BLOCKED
    ```
    """
    
    state: CallState = CallState.IDLE
    retry_count: int = 0
    max_retries: int = 3
    question_count: int = 0
    history: list[tuple[CallState, str]] = field(default_factory=list)
    
    # Define all valid transitions
    TRANSITIONS: dict[CallState, list[CallState]] = field(default_factory=lambda: {
        CallState.IDLE: [CallState.DIALING, CallState.UNREACHABLE],
        CallState.DIALING: [CallState.IVR, CallState.UNREACHABLE, CallState.DROPPED],
        CallState.IVR: [CallState.ON_HOLD, CallState.DROPPED],
        CallState.ON_HOLD: [CallState.CONNECTED, CallState.DROPPED, CallState.TRANSFERRED],
        CallState.CONNECTED: [
            CallState.ON_HOLD,      # Put back on hold
            CallState.TRANSFERRED,  # Rep transfers to another dept
            CallState.DROPPED,      # Call disconnected
            CallState.COMPLETE,     # Finished successfully
            CallState.BLOCKED,      # Needs human intervention
        ],
        CallState.TRANSFERRED: [CallState.ON_HOLD, CallState.DROPPED],
        CallState.DROPPED: [CallState.DIALING],  # Can retry
        # Terminal states - no transitions out
        CallState.UNREACHABLE: [],
        CallState.COMPLETE: [],
        CallState.BLOCKED: [],
    })
    
    def transition(self, to_state: CallState, reason: str = "") -> None:
        """
        Transition to a new state if allowed.
        
        Args:
            to_state: The target state
            reason: Why this transition is happening (for logging)
            
        Raises:
            TransitionError: If the transition is not allowed
        """
        allowed = self.TRANSITIONS.get(self.state, [])
        
        if to_state not in allowed:
            raise TransitionError(self.state, to_state, reason)
        
        # Handle retry logic for dropped calls
        if self.state == CallState.DROPPED and to_state == CallState.DIALING:
            if self.retry_count >= self.max_retries:
                raise TransitionError(
                    self.state, to_state, 
                    f"Max retries ({self.max_retries}) exceeded"
                )
            self.retry_count += 1
        
        # Record transition in history
        self.history.append((self.state, reason or f"→ {to_state.value}"))
        self.state = to_state
    
    def can_transition(self, to_state: CallState) -> bool:
        """Check if transition to given state is allowed."""
        return to_state in self.TRANSITIONS.get(self.state, [])
    
    # ─────────────────────────────────────────────────────────────
    # Convenience methods for common operations
    # ─────────────────────────────────────────────────────────────
    
    def start_call(self) -> None:
        """Start dialing the payer."""
        self.transition(CallState.DIALING, "Initiating call")
    
    def enter_ivr(self) -> None:
        """Connected to IVR menu system."""
        self.transition(CallState.IVR, "Reached IVR menu")
    
    def wait_for_rep(self) -> None:
        """Put on hold waiting for representative."""
        self.transition(CallState.ON_HOLD, "Waiting for representative")
    
    def connect_to_rep(self) -> None:
        """Representative answered."""
        self.transition(CallState.CONNECTED, "Representative connected")
    
    def transfer(self, department: str = "") -> None:
        """Being transferred to another department."""
        reason = f"Transferred to {department}" if department else "Transferred"
        self.transition(CallState.TRANSFERRED, reason)
    
    def drop(self, reason: str = "Call disconnected") -> None:
        """Call was dropped unexpectedly."""
        self.transition(CallState.DROPPED, reason)
    
    def complete(self) -> None:
        """Call completed successfully."""
        self.transition(CallState.COMPLETE, "Call completed")
    
    def mark_unreachable(self) -> None:
        """Payer system is unreachable."""
        self.transition(CallState.UNREACHABLE, "Payer unreachable")
    
    def mark_blocked(self, reason: str) -> None:
        """Mark call as needing human intervention."""
        self.transition(CallState.BLOCKED, reason)
    
    def retry(self) -> bool:
        """
        Attempt to retry a dropped call.
        
        Returns:
            True if retry was successful, False if max retries exceeded
        """
        if self.state != CallState.DROPPED:
            return False
        
        try:
            self.transition(CallState.DIALING, f"Retry attempt {self.retry_count + 1}")
            return True
        except TransitionError:
            return False
    
    # ─────────────────────────────────────────────────────────────
    # Guards - check if operations are allowed
    # ─────────────────────────────────────────────────────────────
    
    def can_ask_question(self) -> bool:
        """Check if we can ask the representative a question."""
        return self.state == CallState.CONNECTED
    
    def can_navigate_ivr(self) -> bool:
        """Check if we can send DTMF tones (navigate IVR)."""
        return self.state == CallState.IVR
    
    def can_retry(self) -> bool:
        """Check if we can retry a dropped call."""
        return (
            self.state == CallState.DROPPED and 
            self.retry_count < self.max_retries
        )
    
    def is_terminal(self) -> bool:
        """Check if we're in a terminal state (no more actions possible)."""
        return self.state in {
            CallState.UNREACHABLE,
            CallState.COMPLETE,
            CallState.BLOCKED,
        }
    
    def is_active(self) -> bool:
        """Check if the call is still active (not terminal or dropped)."""
        return self.state in {
            CallState.DIALING,
            CallState.IVR,
            CallState.ON_HOLD,
            CallState.CONNECTED,
            CallState.TRANSFERRED,
        }
    
    # ─────────────────────────────────────────────────────────────
    # Question tracking
    # ─────────────────────────────────────────────────────────────
    
    def record_question(self) -> int:
        """Record that a question was asked. Returns the question number."""
        self.question_count += 1
        return self.question_count
    
    # ─────────────────────────────────────────────────────────────
    # Status and debugging
    # ─────────────────────────────────────────────────────────────
    
    def get_status(self) -> dict:
        """Get current status as a dictionary."""
        return {
            "state": self.state.value,
            "retry_count": self.retry_count,
            "question_count": self.question_count,
            "is_terminal": self.is_terminal(),
            "can_ask": self.can_ask_question(),
            "can_retry": self.can_retry(),
        }
    
    def get_history(self) -> list[str]:
        """Get transition history as readable strings."""
        return [f"{state.value}: {reason}" for state, reason in self.history]
    
    def reset(self) -> None:
        """Reset state machine to initial state."""
        self.state = CallState.IDLE
        self.retry_count = 0
        self.question_count = 0
        self.history = []
