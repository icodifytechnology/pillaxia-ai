from typing import Any, Dict, List, Optional, TypedDict
from .user_profile import UserProfile
from .template_manager import TemplateManager
import logging

logger = logging.getLogger(__name__)

class ResponseBuilder:
    """Builds personalized responses using templates and user data."""
    
    def __init__(self, token: str, tracker=None):
        """Initialize with user token and optional tracker."""
        self.user_profile = UserProfile(token)
        self.template_manager = TemplateManager()
        self.tracker = tracker
        logger.debug(f"ResponseBuilder initialized for token: {token[:20]}...")
    
    def build_response(self, intent: str, data: Optional[List[Dict[str, Any]]] = None, **context: Any) -> Dict[str, Any]:
        """
        Build structured response in consistent attachment format.
        """
        # Get personalization data
        tone = self.user_profile.get_preferred_tone(self.tracker)
        name = self.user_profile.get_user_name(self.tracker) or ""
        time_of_day = self.user_profile.get_local_time_of_day(self.tracker) or "day"
        
        # Combine with action context
        placeholders = {
            "name": name,
            "time_of_day": time_of_day,
            **context
        }
        
        # Get text response from template
        text_response = self.template_manager.get_response(intent, tone, **placeholders)
        
        # Build consistent attachment structure
        response = {
            "query_response": text_response,
            "type": "array" if data is not None else "text",
            "status": "success"
        }
        
        # Add data array if provided
        if data is not None:
            response["data"] = data
        
        return response
    
    def build_medication_insight(self, insight_data: Dict[str, Any], include_data: bool = False) -> Dict[str, Any]:
        """Build medication adherence insight response."""
        # Determine which template to use based on what's available
        intent = "medication_adherence_insight"
        
        # Prepare context with proper formatting
        pattern_insight = insight_data.get("pattern_insight", "")
        trend_insight = insight_data.get("trend_insight", "")
        
        # Capitalize pattern_insight for the template
        pattern_insight_cap = pattern_insight.capitalize() if pattern_insight else ""
        
        # Generate encouragement based on adherence level
        compliance_rate = insight_data.get("compliance_rate", 0)
        encouragement = self._get_encouragement(compliance_rate)
        
        response = self.build_response(
            intent,
            period=insight_data.get("period", ""),
            medication_count=insight_data.get("medication_count", 0),
            taken=insight_data.get("taken", 0),
            total=insight_data.get("total", 0),
            compliance_rate=compliance_rate,
            trend_period=insight_data.get("trend_period", ""),
            pattern_insight=pattern_insight_cap,  # Already capitalized
            trend_insight=trend_insight,
            encouragement=encouragement
        )
        
        # Add data if requested and available
        if include_data and "tracking_data" in insight_data:
            response["data"] = insight_data.get("tracking_data", [])
            response["type"] = "array"
        
        return response

    def _get_encouragement(self, compliance_rate: float) -> str:
        """Get appropriate encouragement based on adherence level."""
        if compliance_rate >= 80:
            return "Keep up the amazing work!"
        elif compliance_rate >= 60:
            return "You're doing great!"
        elif compliance_rate >= 40:
            return "Every small improvement counts!"
        elif compliance_rate >= 20:
            return "Let's work on this together!"
        else:
            return "I'm here to help you succeed!"
        
    def build_error_response(self, error_type: str = "default", **context) -> Dict[str, Any]:
        """Build error response."""
        intent = f"{error_type}_error" if error_type != "default" else "default_error"
        
        if intent not in self.template_manager.get_all_intents():
            intent = "default_error"
        
        return self.build_response(intent, **context)