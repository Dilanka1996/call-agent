"""User context for payer calls."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class UserContext:
    """
    Patient/member context for payer calls.
    
    Contains both identity information and benefit values from the database.
    This context is used by the LLM tier to interpret ambiguous responses
    and validate parsed values.
    
    SECURITY NOTE: member_id_token is a reference token, not the raw member ID.
    The raw ID must never cross the payer boundary.
    """
    
    member_id_token: str
    plan_type: str = "unknown"
    state: str = "unknown"
    
    # Benefits verification fields
    coverage_active: bool | None = None
    copay: int | None = None
    deductible_remaining: int | None = None
    visit_limit: int | None = None
    prior_auth_required: bool | None = None
    
    # Claim denial fields
    claim_denied: bool | None = None
    denial_code: str | None = None
    denial_reason: str | None = None
    claim_amount: int | None = None
    appeal_deadline_days: int | None = None
    
    # Prior auth fields
    auth_status: str | None = None
    reference_number: str | None = None
    decision_eta_days: int | None = None
    missing_documents: list[str] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserContext:
        """Create UserContext from a dictionary (e.g., from YAML fixture)."""
        return cls(
            member_id_token=data.get("member_id_token", "unknown"),
            plan_type=data.get("plan_type", "unknown"),
            state=data.get("state", "unknown"),
            # Benefits
            coverage_active=data.get("coverage_active"),
            copay=data.get("copay"),
            deductible_remaining=data.get("deductible_remaining"),
            visit_limit=data.get("visit_limit"),
            prior_auth_required=data.get("prior_auth_required"),
            # Claims
            claim_denied=data.get("claim_denied"),
            denial_code=data.get("denial_code"),
            denial_reason=data.get("denial_reason"),
            claim_amount=data.get("claim_amount"),
            appeal_deadline_days=data.get("appeal_deadline_days"),
            # Prior auth
            auth_status=data.get("auth_status"),
            reference_number=data.get("reference_number"),
            decision_eta_days=data.get("decision_eta_days"),
            missing_documents=data.get("missing_documents", []),
        )
    
    @classmethod
    def _get_user_contexts_path(cls, fixture_path: Path) -> Path:
        """Get path to user_contexts.yaml (always in data/ relative to project root)."""
        return fixture_path.parent.parent.parent / "data" / "user_contexts.yaml"
    
    @classmethod
    def from_fixture(cls, path: str | Path) -> UserContext:
        """
        Load UserContext from a fixture YAML file.
        
        Supports both inline user_context and user_id reference to user_contexts.yaml.
        """
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        
        if "user_id" in data and "user_context" not in data:
            user_contexts_path = cls._get_user_contexts_path(path)
            with open(user_contexts_path) as f:
                all_contexts = yaml.safe_load(f)
            
            user_id = data["user_id"]
            user_context_data = all_contexts.get(user_id, {})
        else:
            user_context_data = data.get("user_context", {})
        
        return cls.from_dict(user_context_data)
    
    def get_field(self, field_name: str) -> Any:
        """Get a field value by name, for dynamic access."""
        return getattr(self, field_name, None)
    
    def to_prompt_context(self) -> str:
        """Format context for inclusion in LLM prompts."""
        lines = [
            f"Plan type: {self.plan_type}",
            f"State: {self.state}",
        ]
        
        if self.coverage_active is not None:
            lines.append(f"Coverage active: {self.coverage_active}")
        if self.copay is not None:
            lines.append(f"Expected copay: ${self.copay}")
        if self.deductible_remaining is not None:
            lines.append(f"Deductible remaining: ${self.deductible_remaining}")
        if self.visit_limit is not None:
            lines.append(f"Visit limit: {self.visit_limit}")
        if self.prior_auth_required is not None:
            lines.append(f"Prior auth required: {self.prior_auth_required}")
        
        return "\n".join(lines)
