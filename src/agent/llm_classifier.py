"""LLM-based intent classification for fallback when rule-based matching is uncertain."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


@dataclass
class ClassificationResult:
    """Result from LLM classification."""
    
    intent: str | None
    confidence: float
    reasoning: str
    needs_human: bool = False
    needs_clarification: bool = False
    clarification: str = ""
    
    @classmethod
    def needs_human_result(cls, reason: str) -> ClassificationResult:
        """Create a result indicating human review is needed."""
        return cls(
            intent=None,
            confidence=0.0,
            reasoning=reason,
            needs_human=True,
        )


@dataclass 
class ClassifierConfig:
    """Configuration for the LLM classifier."""
    
    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens: int = 200


class LLMClassifier:
    """
    LLM-based intent classifier for payer call responses.
    
    Used as Tier 2 fallback when rule-based matching has low confidence.
    Designed to be cost-effective using gpt-4o-mini by default.
    
    The LLM decides whether to classify or hand off to human review.
    """
    
    CLASSIFICATION_PROMPT = """You are classifying a question asked during a phone call to an insurance payer.

Given the question and available intents, you must:
1. Classify the intent if possible
2. Determine if the question needs clarification (e.g., asks for a definition but we have a value)
3. If unclear or needs human judgment, set needs_human to true

Question: "{question}"

Scenario: {scenario}

Available intents:
{intents_list}

Respond with JSON only:
{{
    "intent": "<intent name or null>",
    "confidence": <0.0 to 1.0>,
    "reasoning": "<brief explanation>",
    "needs_human": <true if human review needed>,
    "needs_clarification": <true if the question is ambiguous but you can still classify>,
    "clarification": "<short clarifying prefix if needs_clarification is true, e.g., 'Did you mean the copay amount?'>"
}}

Set needs_clarification to TRUE when:
- User asks "what is X" or "explain X" but likely wants the value (e.g., "what is copay" → likely wants copay amount)
- Question phrasing is informal/unclear but intent is guessable
- You're classifying based on inference rather than explicit match

Set needs_human to TRUE only when:
- Question is truly outside available intents
- Multiple intents equally likely
- Cannot make a reasonable guess"""

    def __init__(self, config: ClassifierConfig | None = None):
        """
        Initialize the classifier.
        
        Args:
            config: Optional configuration. Uses defaults if not provided.
        """
        self.config = config or ClassifierConfig()
        self._client: OpenAI | None = None
    
    @property
    def client(self) -> OpenAI:
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            if OpenAI is None:
                raise ImportError(
                    "openai package not installed. Run: pip install openai"
                )
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY environment variable not set"
                )
            self._client = OpenAI(api_key=api_key)
        return self._client
    
    def classify(
        self,
        question: str,
        scenario: str,
        available_intents: list[str],
    ) -> ClassificationResult:
        """
        Classify a question using the LLM.
        
        Args:
            question: The question to classify
            scenario: The scenario context (e.g., "benefits_verification")
            available_intents: List of valid intent names to choose from
            
        Returns:
            ClassificationResult with intent, confidence, and reasoning
        """
        if not available_intents:
            return ClassificationResult.needs_human_result(
                "No available intents to classify against"
            )
        
        intents_list = "\n".join(f"- {intent}" for intent in available_intents)
        
        prompt = self.CLASSIFICATION_PROMPT.format(
            question=question,
            scenario=scenario,
            intents_list=intents_list,
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            
            content = response.choices[0].message.content
            return self._parse_response(content, available_intents)
            
        except Exception as e:
            return ClassificationResult.needs_human_result(
                f"LLM classification failed: {str(e)}"
            )
    
    def _parse_response(
        self, 
        content: str | None, 
        available_intents: list[str]
    ) -> ClassificationResult:
        """Parse the LLM response into a ClassificationResult."""
        if not content:
            return ClassificationResult.needs_human_result(
                "Empty response from LLM"
            )
        
        try:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            data = json.loads(content)
            
            intent = data.get("intent")
            confidence = float(data.get("confidence", 0.0))
            reasoning = data.get("reasoning", "")
            needs_human = data.get("needs_human", False)
            needs_clarification = data.get("needs_clarification", False)
            clarification = data.get("clarification", "")
            
            if intent and intent not in available_intents:
                return ClassificationResult.needs_human_result(
                    f"LLM returned invalid intent: {intent}"
                )
            
            return ClassificationResult(
                intent=intent,
                confidence=confidence,
                reasoning=reasoning,
                needs_human=needs_human,
                needs_clarification=needs_clarification,
                clarification=clarification,
            )
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return ClassificationResult.needs_human_result(
                f"Failed to parse LLM response: {str(e)}"
            )


class MockLLMClassifier(LLMClassifier):
    """
    Mock LLM classifier for testing without API calls.
    
    Returns predefined responses based on question content.
    """
    
    def __init__(self, config: ClassifierConfig | None = None):
        super().__init__(config)
        self._mock_responses: dict[str, ClassificationResult] = {}
    
    def set_mock_response(self, question_pattern: str, result: ClassificationResult):
        """Set a mock response for questions containing the pattern."""
        self._mock_responses[question_pattern.lower()] = result
    
    def classify(
        self,
        question: str,
        scenario: str,
        available_intents: list[str],
    ) -> ClassificationResult:
        """Return mock classification based on predefined responses."""
        question_lower = question.lower()
        
        for pattern, result in self._mock_responses.items():
            if pattern in question_lower:
                return result
        
        # Check for definition/explanation questions that need clarification
        is_definition_q = any(w in question_lower for w in ["explain", "define", "what is a", "what's a"])
        
        if "copay" in question_lower and "copay" in available_intents:
            return ClassificationResult(
                intent="copay",
                confidence=0.85,
                reasoning="Question mentions copay",
                needs_clarification=is_definition_q,
                clarification="Did you mean the copay amount?" if is_definition_q else "",
            )
        if "active" in question_lower or "valid" in question_lower or "covered" in question_lower:
            if "coverage_active" in available_intents:
                return ClassificationResult(
                    intent="coverage_active",
                    confidence=0.9,
                    reasoning="Question asks about coverage status",
                    needs_clarification=is_definition_q,
                    clarification="Did you mean your coverage status?" if is_definition_q else "",
                )
        if "deductible" in question_lower and "deductible" in available_intents:
            return ClassificationResult(
                intent="deductible",
                confidence=0.85,
                reasoning="Question mentions deductible",
                needs_clarification=is_definition_q,
                clarification="Did you mean the deductible remaining?" if is_definition_q else "",
            )
        if "prior" in question_lower or "auth" in question_lower or "permission" in question_lower:
            if "prior_auth_required" in available_intents:
                return ClassificationResult(
                    intent="prior_auth_required",
                    confidence=0.85,
                    reasoning="Question asks about prior authorization",
                    needs_clarification=is_definition_q,
                    clarification="Did you mean whether prior auth is required?" if is_definition_q else "",
                )
        
        return ClassificationResult.needs_human_result(
            "Mock classifier: no matching pattern found"
        )
