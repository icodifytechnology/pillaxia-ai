"""
USER PROFILE MANAGER
====================
Manages user profile with caching, timezone handling, and personalization.

Key: 
- Cached profile access
- Timezone-aware greetings
- Name extraction with fallbacks
- Tone preference handling

Connected to: actions.py (personalization), domain.yml (slots)
"""

import logging
from .api_client import api_client
from typing import Optional
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)


class UserProfile:
    """Manages user profile data with caching and personalization."""
    
    def __init__(self, token: str):
        """Initialize with user token. Token masked in logs."""
        self.token = token
        self._profile = None  # Profile cache
        logger.debug(f"UserProfile initialized with token: {token[:20]}...")
    
    def get_profile(self) -> Optional[dict]:
        """Get profile from API (cached)."""
        if self._profile is None:
            logger.debug("Cache miss - fetching profile")
            self._profile = api_client.get_user_profile(self.token)
            logger.debug(f"Profile {'fetched' if self._profile else 'failed'}")
        return self._profile
    
    def get_user_name(self, tracker=None) -> Optional[str]:
        """
        Get user's name.
        Priority: 1. Slot value, 2. Profile fields, 3. None
        """
        # Check slot first
        if tracker:
            slot_name = tracker.get_slot("user_name")
            if slot_name:
                return slot_name
        
        # Check profile
        profile = self.get_profile()
        if not profile:
            return None
        
        # Try name fields in order
        name_fields = ["full_name", "user_name", "name", "username", "email"]
        for field in name_fields:
            if field in profile and profile[field]:
                raw_name = str(profile[field]).strip()
                if not raw_name or raw_name.lower() in ["null", "none"]:
                    continue
                
                # Extract from email if needed
                if "@" in raw_name:
                    raw_name = raw_name.split("@")[0]
                
                # Return capitalized first name
                return raw_name.split()[0].capitalize()
        
        return None
    
    def get_timezone(self, tracker=None) -> str:
        """
        Get user's timezone.
        Priority: 1. Slot, 2. Profile, 3. UTC
        """
        # Check slot
        if tracker:
            tz_slot = tracker.get_slot("user_timezone")
            if tz_slot:
                return tz_slot
        
        # Check profile
        profile = self.get_profile()
        if profile and "timezone" in profile:
            tz = profile["timezone"]
            if tz and str(tz).strip().lower() not in ["null", "none", ""]:
                return str(tz).strip()
        
        # Default
        return "UTC"
    
    def get_local_time_of_day(self, tracker=None) -> str:
        """
        Calculate local time of day based on user's timezone.
        Returns: "morning", "afternoon", "evening", or "night"
        """
        try:
            tz_str = self.get_timezone(tracker)
            
            # Handle "Nepal Time" special case
            if tz_str == "Nepal Time":
                tz_str = "Asia/Kathmandu"
            
            # Get timezone object
            if tz_str in pytz.all_timezones:
                user_tz = pytz.timezone(tz_str)
            else:
                user_tz = pytz.timezone("UTC")
            
            # Calculate hour and determine time of day
            hour = datetime.now(user_tz).hour
            if 5 <= hour < 12:
                return "morning"
            elif 12 <= hour < 17:
                return "afternoon"
            elif 17 <= hour < 21:
                return "evening"
            else:
                return "night"
                
        except Exception as e:
            logger.error(f"Error calculating time of day: {e}")
            return "day"
    
    def get_preferred_tone(self, tracker=None) -> str:
        """
        Get user's preferred communication tone.
        Returns: "casual" or "formal" (defaults to casual)
        """
        # Check slot
        if tracker:
            tone_slot = tracker.get_slot("preferred_tone")
            if tone_slot in ["casual", "formal"]:
                return tone_slot
        
        # Check profile
        profile = self.get_profile()
        if profile and "preferred_tone" in profile:
            tone = str(profile["preferred_tone"]).strip().lower()
            if tone in ["casual", "formal"]:
                return tone
        
        # Default
        return "casual"