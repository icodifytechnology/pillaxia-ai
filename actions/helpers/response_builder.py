"""
RESPONSE BUILDER
================
Builds personalized responses by combining templates with user data.

Key:
- Integrates UserProfile for personalization
- Uses TemplateManager for response formatting
- Supports error responses with fallbacks
- All responses include name, time_of_day, tone

Dependencies: .template_manager, .user_profile, logging
Used by: actions.py for all user responses
"""

import logging
from typing import Any
from .template_manager import TemplateManager
from .user_profile import UserProfile

logger = logging.getLogger(__name__)


class ResponseBuilder:
    """Builds personalized responses using templates and user data."""
    
    def __init__(self, token: str, tracker=None):
        """Initialize with user token and optional tracker."""
        self.user_profile = UserProfile(token)
        self.template_manager = TemplateManager()
        self.tracker = tracker
        logger.debug(f"ResponseBuilder initialized for token: {token[:20]}...")
    
    def build_response(self, intent: str, **context: Any) -> str:
        """Build personalized response for intent with context."""
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
        
        return self.template_manager.get_response(intent, tone, **placeholders)
    
    def build_error_response(self, error_type: str = "default", **context) -> str:
        """Build error response. Falls back to default_error if specific intent not found."""
        intent = f"{error_type}_error" if error_type != "default" else "default_error"
        
        if intent not in self.template_manager.get_all_intents():
            intent = "default_error"
        
        return self.build_response(intent, **context)