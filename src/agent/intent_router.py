"""Intent routing with tiered fallback from rules to LLM to human."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .knowledge_base import KnowledgeBase, MatchResult
from .llm_classifier import ClassificationResult, LLMClassifier, MockLLMClassifier


class RoutingTier(Enum):
    """Which tier handled the routing decision."""
    
    RULE_BASED = "rule_based"
    LLM_FALLBACK = "llm_fallback"
    NEEDS_HUMAN = "needs_human"


@dataclass
class RouterConfig:
    """Configuration for intent routing thresholds."""
    
    rule_confidence_threshold: float = 0.6


@dataclass
class RoutingResult:
    """Result of intent routing with tier information."""
    
    intent: str | None
    confidence: float
    tier: RoutingTier
    reasoning: str
    rule_match: MatchResult | None = None
    llm_result: ClassificationResult | None = None
    
    @property
    def success(self) -> bool:
        """Check if routing was successful (intent found with confidence)."""
        return self.intent is not None and self.tier != RoutingTier.NEEDS_HUMAN
    
    @property
    def needs_human(self) -> bool:
        """Check if human review is needed."""
        return self.tier == RoutingTier.NEEDS_HUMAN
    
    @property
    def needs_clarification(self) -> bool:
        """Check if clarification should be added to response."""
        if self.llm_result:
            return self.llm_result.needs_clarification
        return False
    
    @property
    def clarification(self) -> str:
        """Get clarification prefix for response."""
        if self.llm_result and self.llm_result.clarification:
            return self.llm_result.clarification
        return ""


class IntentRouter:
    """
    Routes intent classification through tiered fallback system.
    
    Tier 1 (Rule-based): Use KB fuzzy matching if confidence >= threshold
    Tier 2 (LLM): Ask LLM to classify - LLM decides whether to answer or hand off
    
    The LLM itself decides whether it can confidently classify or needs human review.
    """
    
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        config: RouterConfig | None = None,
        classifier: LLMClassifier | None = None,
        use_mock_llm: bool = False,
    ):
        """
        Initialize the router.
        
        Args:
            knowledge_base: Knowledge base for rule-based matching
            config: Router configuration with thresholds
            classifier: Optional LLM classifier (created lazily if not provided)
            use_mock_llm: Use mock classifier for testing (no API calls)
        """
        self.kb = knowledge_base
        self.config = config or RouterConfig()
        self._classifier = classifier
        self._use_mock_llm = use_mock_llm
    
    @property
    def classifier(self) -> LLMClassifier:
        """Lazy initialization of LLM classifier."""
        if self._classifier is None:
            if self._use_mock_llm:
                self._classifier = MockLLMClassifier()
            else:
                self._classifier = LLMClassifier()
        return self._classifier
    
    def route(
        self,
        question: str,
        scenario: str,
        available_intents: list[str] | None = None,
    ) -> RoutingResult:
        """
        Route a question to the appropriate intent using tiered fallback.
        
        Flow:
        1. Try rule-based matching
        2. If confident (>= threshold) → return rule result
        3. Otherwise → ask LLM, LLM decides to classify or hand off
        
        Args:
            question: The question to classify
            scenario: The scenario context (e.g., "benefits_verification")
            available_intents: Optional list of valid intents to consider
            
        Returns:
            RoutingResult with intent, confidence, tier used, and reasoning
        """
        if available_intents is None:
            available_intents = self.kb.get_all_intents(scenario)
        
        rule_result = self.kb.find_matching_intent_with_confidence(
            scenario, question, available_intents
        )
        
        if rule_result.confidence >= self.config.rule_confidence_threshold:
            return RoutingResult(
                intent=rule_result.intent,
                confidence=rule_result.confidence,
                tier=RoutingTier.RULE_BASED,
                reasoning=f"Rule-based match to '{rule_result.matched_question}'",
                rule_match=rule_result,
            )
        
        llm_result = self.classifier.classify(
            question, scenario, available_intents
        )
        
        if llm_result.needs_human:
            return RoutingResult(
                intent=None,
                confidence=0.0,
                tier=RoutingTier.NEEDS_HUMAN,
                reasoning=f"LLM decided: {llm_result.reasoning}",
                rule_match=rule_result,
                llm_result=llm_result,
            )
        
        return RoutingResult(
            intent=llm_result.intent,
            confidence=llm_result.confidence,
            tier=RoutingTier.LLM_FALLBACK,
            reasoning=llm_result.reasoning,
            rule_match=rule_result,
            llm_result=llm_result,
        )
