"""
Response Builder for personalized responses
"""

import logging
from typing import Dict, Any
from .template_manager import TemplateManager
from .user_profile import UserProfile

logger = logging.getLogger(__name__)


class ResponseBuilder:
    """Builds personalized responses by combining templates with user data"""
    
    def __init__(self, token: str, tracker=None):
        self.user_profile = UserProfile(token)
        self.template_manager = TemplateManager()
        self.tracker = tracker
        logger.debug(f"ResponseBuilder initialized with token: {token[:20]}...")
    
    def build_response(self, intent: str, **context: Any) -> str:
        """
        Build a personalized response for the given intent.
        """
        logger.debug(f"Building response for intent: '{intent}'")
        logger.debug(f"Context: {context}")
        
        # Get user's preferred tone
        tone = self.user_profile.get_preferred_tone(self.tracker)
        logger.debug(f"Using tone: '{tone}'")
        
        # Get user's first name
        user_name = self.user_profile.get_user_name(self.tracker) or ""
        logger.debug(f"Using name: '{user_name}'")
        
        # Get time of day
        time_of_day = self.user_profile.get_local_time_of_day(self.tracker) or "day"
        logger.debug(f"Using time_of_day: '{time_of_day}'")
        
        # Prepare placeholders
        placeholders = {
            "name": user_name,
            "time_of_day": time_of_day,
            **context
        }
        logger.debug(f"Final placeholders: {placeholders}")
        
        # Get and return formatted response
        response = self.template_manager.get_response(intent, tone, **placeholders)
        logger.debug(f"Final response: '{response}'")
        
        return response
    
    def build_error_response(self, error_type: str = "default", **context) -> str:
        """
        Build error response with appropriate error template.
        """
        logger.debug(f"Building error response for: '{error_type}'")
        
        intent = f"{error_type}_error" if error_type != "default" else "default_error"
        
        if intent not in self.template_manager.get_all_intents():
            logger.warning(f"Intent '{intent}' not found, using 'default_error'")
            intent = "default_error"
        
        return self.build_response(intent, **context)