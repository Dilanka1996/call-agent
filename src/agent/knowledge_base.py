"""Knowledge base for payer Q&A scenarios."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MatchResult:
    """Result of intent matching with confidence score."""
    
    intent: str | None
    confidence: float
    matched_question: str | None = None
    
    @property
    def is_confident(self) -> bool:
        """Check if match confidence is above typical threshold (0.6)."""
        return self.confidence >= 0.6


@dataclass
class QuestionSet:
    """A set of questions for a specific intent."""
    
    primary: str
    variations: list[str]
    answer_field: str
    answer_template: str = ""
    
    def all_questions(self) -> list[str]:
        """Return all questions including primary and variations."""
        return [self.primary] + self.variations
    
    def generate_answer(self, context: dict[str, Any]) -> str:
        """
        Generate an answer by filling the template with context values.
        
        Args:
            context: Dictionary of field values (typically from user_context)
            
        Returns:
            The filled answer template, or empty string if no template
        """
        if not self.answer_template:
            return ""
        
        try:
            return self.answer_template.format(**context)
        except KeyError:
            return self.answer_template
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuestionSet:
        """Create QuestionSet from dictionary."""
        questions = data.get("questions", {})
        return cls(
            primary=questions.get("primary", ""),
            variations=questions.get("variations", []),
            answer_field=data.get("answer_field", ""),
            answer_template=data.get("answer_template", ""),
        )


@dataclass
class KnowledgeBase:
    """
    Central knowledge base for payer Q&A.
    
    Contains question sets organized by scenario (benefits, claims, prior_auth)
    and intent (copay, denial_reason, etc.).
    """
    
    categories: dict[str, dict[str, QuestionSet]] = field(default_factory=dict)
    
    @classmethod
    def load(cls, path: str | Path) -> KnowledgeBase:
        """Load knowledge base from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        
        categories: dict[str, dict[str, QuestionSet]] = {}
        
        for scenario, intents in data.items():
            categories[scenario] = {}
            for intent, intent_data in intents.items():
                categories[scenario][intent] = QuestionSet.from_dict(intent_data)
        
        return cls(categories=categories)
    
    def get_questions(self, scenario: str, intent: str) -> QuestionSet | None:
        """Get the question set for a specific scenario and intent."""
        scenario_data = self.categories.get(scenario)
        if scenario_data is None:
            return None
        return scenario_data.get(intent)
    
    def get_all_intents(self, scenario: str) -> list[str]:
        """Get all intent names for a scenario."""
        scenario_data = self.categories.get(scenario, {})
        return list(scenario_data.keys())
    
    def get_scenarios(self) -> list[str]:
        """Get all scenario names."""
        return list(self.categories.keys())
    
    def find_matching_intent(
        self, 
        scenario: str, 
        question: str,
        available_intents: list[str] | None = None
    ) -> str | None:
        """
        Find the intent that best matches the given question.
        
        Uses fuzzy string matching against all question variations.
        
        Args:
            scenario: The scenario category (e.g., "benefits_verification")
            question: The question text to match
            available_intents: Optional list of intents to consider (filters results)
            
        Returns:
            The matching intent name, or None if no match found
        """
        result = self.find_matching_intent_with_confidence(
            scenario, question, available_intents
        )
        return result.intent if result.is_confident else None
    
    def find_matching_intent_with_confidence(
        self, 
        scenario: str, 
        question: str,
        available_intents: list[str] | None = None,
    ) -> MatchResult:
        """
        Find the intent that best matches the given question with confidence score.
        
        Uses SequenceMatcher for fuzzy matching with keyword boosting.
        
        Args:
            scenario: The scenario category (e.g., "benefits_verification")
            question: The question text to match
            available_intents: Optional list of intents to consider (filters results)
            
        Returns:
            MatchResult with intent, confidence, and matched question
        """
        scenario_data = self.categories.get(scenario, {})
        question_lower = question.lower()
        
        best_match = None
        best_score = 0.0
        best_question = None
        
        for intent, qs in scenario_data.items():
            if available_intents and intent not in available_intents:
                continue
            
            for q in qs.all_questions():
                score = self._similarity_score(question_lower, q.lower())
                if score > best_score:
                    best_score = score
                    best_match = intent
                    best_question = q
        
        return MatchResult(
            intent=best_match,
            confidence=best_score,
            matched_question=best_question,
        )
    
    def _similarity_score(self, query: str, target: str) -> float:
        """
        Calculate similarity score between query and target (0-1).
        
        Uses SequenceMatcher with keyword boosting for domain-specific terms.
        """
        base_score = SequenceMatcher(None, query, target).ratio()
        
        query_words = set(query.split())
        target_words = set(target.split())
        common_words = query_words & target_words
        
        important_words = {
            "copay", "deductible", "active", "coverage", "limit", "visit",
            "prior", "auth", "authorization", "claim", "denied", "denial",
            "appeal", "status", "reference", "number", "missing", "documents",
            "decision", "amount", "owed", "eligible", "policy"
        }
        
        keyword_boost = 0.0
        for word in common_words:
            if word in important_words:
                keyword_boost += 0.1
        
        return min(1.0, base_score + keyword_boost)
