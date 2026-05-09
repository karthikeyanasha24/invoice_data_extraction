import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger("zodiac-api.conversational_state")

@dataclass
class AnalyticState:
    thread_id: str
    filters: Dict[str, Any]
    time_grain: str
    metrics: List[str]
    dimensions: List[str]
    
class ConversationalSessionManager:
    """
    Phase 10: Conversational Memory & Follow-up State
    Maintains explicit analytic state across sessions.
    """
    
    def __init__(self):
        self.sessions: Dict[str, AnalyticState] = {}
        
    def get_state(self, thread_id: str) -> Optional[AnalyticState]:
        return self.sessions.get(thread_id)
        
    def update_state(self, thread_id: str, new_intent: Dict[str, Any]) -> AnalyticState:
        """Apply deterministic diff to previous state."""
        state = self.sessions.get(thread_id)
        
        if not state:
            state = AnalyticState(
                thread_id=thread_id,
                filters={},
                time_grain="monthly",
                metrics=[],
                dimensions=[]
            )
            self.sessions[thread_id] = state
            
        # Apply diffs
        if "new_filters" in new_intent:
            state.filters.update(new_intent["new_filters"])
        if "remove_filters" in new_intent:
            for f in new_intent["remove_filters"]:
                state.filters.pop(f, None)
                
        if "time_grain" in new_intent:
            state.time_grain = new_intent["time_grain"]
            
        if "metrics" in new_intent:
            state.metrics = new_intent["metrics"]
            
        if "dimensions" in new_intent:
            state.dimensions = new_intent["dimensions"]
            
        logger.info("Updated analytical state for thread %s", thread_id)
        return state

session_manager = ConversationalSessionManager()
