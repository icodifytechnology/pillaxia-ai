# helpers/user_profile.py
import logging
from .api_client import api_client
from typing import Optional
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class UserProfile:
    """Manages user profile data including name, timezone, and preferences"""
    
    def __init__(self, token: str):
        self.token = token
        self._profile = None  # Cache for profile data
    
    def get_profile(self) -> Optional[dict]:
        """Get user profile from API, cached to avoid repeated calls"""
        if self._profile is None:
            self._profile = api_client.get_user_profile(self.token)
        return self._profile
    
    def get_user_name(self) -> Optional[str]:
        """
        Extract user's first name from profile data.
        Tries multiple fields in order of preference.
        
        Returns:
            User's first name or None if not found
        """
        profile = self.get_profile()
        if not profile:
            return None

        # Fields to check for name, in order of preference
        name_fields = ["full_name", "user_name", "name", "username", "email"]

        for field in name_fields:
            if field in profile and profile[field]:
                raw_name = str(profile[field]).strip()

                # Skip empty or null values
                if not raw_name or raw_name.lower() in ["null", "none"]:
                    continue

                # Extract first part from email if needed
                if "@" in raw_name:
                    raw_name = raw_name.split("@")[0]

                # Take only first name (first word)
                first_name = raw_name.split()[0]

                # Capitalize properly (e.g., "anu" -> "Anu")
                return first_name.capitalize()

        return None  # No name found
    
    def get_timezone(self) -> str:
        """
        Get user's timezone from profile.
        
        Returns:
            Timezone string, defaults to "UTC" if not found
        """
        profile = self.get_profile()
        if profile and "timezone" in profile:
            tz = profile["timezone"]
            # Validate timezone is not empty/null
            if tz and str(tz).strip().lower() not in ["null", "none", ""]:
                return str(tz).strip()
        return "UTC"  # Default to UTC
    
    def get_local_time_of_day(self) -> str:
        """
        Calculate time of day (morning/afternoon/evening/night) 
        based on user's timezone.
        
        Returns:
            Time of day string, defaults to "day" if calculation fails
        """
        try:
            tz_str = self.get_timezone()
            
            # Convert "Nepal Time" to pytz-compatible format
            if tz_str == "Nepal Time":
                tz_str = "Asia/Kathmandu"
            
            # Get timezone object, default to UTC if invalid
            if tz_str in pytz.all_timezones:
                user_tz = pytz.timezone(tz_str)
            else:
                user_tz = pytz.timezone("UTC")
            
            # Get current time in user's timezone
            user_time = datetime.now(user_tz)
            hour = user_time.hour
            
            # Determine time of day based on hour
            if 5 <= hour < 12:
                return "morning"
            elif 12 <= hour < 17:
                return "afternoon"
            elif 17 <= hour < 21:
                return "evening"
            else:
                return "night"
                
        except Exception:
            # Log error but return safe default
            logger.error("Failed to calculate local time of day", exc_info=True)
            return "day"
    
    def get_preferred_tone(self) -> str:
        """
        Get user's preferred communication tone.
        
        Note: Currently defaults to "casual" - can be extended to read
        from user preferences when API supports it.
        
        Returns:
            "casual" or "formal"
        """
        return "casual"  # Default for now