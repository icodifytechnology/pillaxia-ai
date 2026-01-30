# helpers/response_builder.py
from typing import Dict, Any
from .template_manager import TemplateManager
from .user_profile import UserProfile

class ResponseBuilder:
    """Builds personalized responses by combining templates with user data"""
    
    def __init__(self, token: str):
        self.user_profile = UserProfile(token)
        self.template_manager = TemplateManager()
    
    def build_response(self, intent: str, **context: Any) -> str:
        """
        Build a personalized response for the given intent.
        
        Args:
            intent: The intent name (matches templates/responses.json)
            **context: Additional context data for placeholders
        
        Returns:
            Personalized response string with name and time of day
        """
        # Get user's preferred tone (casual/formal)
        tone = self.user_profile.get_preferred_tone()
        
        # Get user's first name (or empty string if not found)
        user_name = self.user_profile.get_user_name() or ""
        
        # Get time of day based on user's timezone
        time_of_day = self.user_profile.get_local_time_of_day() or "day"
        
        # Prepare placeholders for template formatting
        placeholders = {
            "name": user_name,
            "time_of_day": time_of_day,
            **context  # Additional context can override defaults
        }
        
        # Get and return formatted response from templates
        return self.template_manager.get_response(intent, tone, **placeholders)
    
    def build_error_response(self, error_type: str = "default", **context) -> str:
        """
        Build error response with appropriate error template.
        
        Args:
            error_type: Specific error type (e.g., "api_error", "timeout_error")
            **context: Additional context for error message
        
        Returns:
            Formatted error response string
        """
        # Try to find specific error template, fallback to default
        intent = f"{error_type}_error" if error_type != "default" else "default_error"
        
        # Check if specific error template exists
        if intent not in self.template_manager.get_all_intents():
            intent = "default_error"
        
        # Build response with error context
        return self.build_response(intent, **context)