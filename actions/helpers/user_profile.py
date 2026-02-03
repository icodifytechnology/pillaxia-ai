"""
User Profile Manager with caching and timezone handling
"""

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
        logger.debug(f"UserProfile initialized with token: {token[:20]}...")
    
    def get_profile(self) -> Optional[dict]:
        """Get user profile from API, cached to avoid repeated calls"""
        if self._profile is None:
            logger.debug(f"Cache miss - fetching profile from API")
            self._profile = api_client.get_user_profile(self.token)
            if self._profile:
                logger.debug(f"Profile fetched and cached successfully")
            else:
                logger.warning(f"Failed to fetch profile")
        else:
            logger.debug(f"Cache hit - using cached profile data")
        return self._profile
    
    def get_user_name(self, tracker=None) -> Optional[str]:
        """
        Get user's name with priority:
        1. Existing slot value
        2. API call
        3. Default
        """
        logger.debug(f"Getting user name (tracker provided: {tracker is not None})")
        
        # Check slot first if tracker provided
        if tracker:
            slot_value = tracker.get_slot("user_name")
            if slot_value:
                logger.debug(f"Using name from slot: '{slot_value}'")
                return slot_value
        
        # If no tracker or empty slot, check API
        profile = self.get_profile()
        if not profile:
            logger.debug(f"No profile available for name extraction")
            return None
        
        logger.debug(f"Extracting name from profile fields")
        name_fields = ["full_name", "user_name", "name", "username", "email"]
        
        for field in name_fields:
            if field in profile and profile[field]:
                raw_name = str(profile[field]).strip()
                logger.debug(f"Found '{field}' in profile: '{raw_name}'")
                
                if not raw_name or raw_name.lower() in ["null", "none"]:
                    logger.debug(f"'{field}' is empty/null, skipping")
                    continue
                
                if "@" in raw_name:
                    raw_name = raw_name.split("@")[0]
                    logger.debug(f"Extracted from email: '{raw_name}'")
                
                first_name = raw_name.split()[0].capitalize()
                logger.info(f"Extracted name: '{first_name}'")
                return first_name
        
        logger.debug(f"No name found in profile")
        return None
    
    def get_timezone(self, tracker=None) -> str:
        """
        Get user's timezone, checking slot first, then API.
        """
        logger.debug(f"Getting timezone (tracker provided: {tracker is not None})")
        
        # 1. Check slot first
        if tracker:
            tz_from_slot = tracker.get_slot("user_timezone")
            if tz_from_slot:
                logger.debug(f"Using timezone from slot: '{tz_from_slot}'")
                return tz_from_slot
        
        # 2. Check API profile
        profile = self.get_profile()
        if profile and "timezone" in profile:
            tz = profile["timezone"]
            if tz and str(tz).strip().lower() not in ["null", "none", ""]:
                cleaned_tz = str(tz).strip()
                logger.debug(f"Using timezone from API: '{cleaned_tz}'")
                return cleaned_tz
            else:
                logger.debug(f"Timezone in profile is empty/null")
        
        logger.debug(f"No valid timezone found, defaulting to UTC")
        return "UTC"
    
    def get_local_time_of_day(self, tracker=None) -> str:
        """
        Calculate time of day based on user's timezone.
        """
        logger.debug(f"Calculating local time of day")
        
        try:
            tz_str = self.get_timezone(tracker)
            logger.debug(f"Raw timezone: '{tz_str}'")
            
            # Convert "Nepal Time" to pytz-compatible format
            if tz_str == "Nepal Time":
                tz_str = "Asia/Kathmandu"
                logger.debug(f"Converted 'Nepal Time' to '{tz_str}'")
            
            # Get timezone object
            if tz_str in pytz.all_timezones:
                user_tz = pytz.timezone(tz_str)
                logger.debug(f"Valid timezone: '{tz_str}'")
            else:
                logger.warning(f"Invalid timezone '{tz_str}', defaulting to UTC")
                user_tz = pytz.timezone("UTC")
            
            # Get current time in user's timezone
            user_time = datetime.now(user_tz)
            hour = user_time.hour
            logger.debug(f"User's local time: {user_time.strftime('%Y-%m-%d %H:%M:%S')} (hour: {hour})")
            
            # Determine time of day
            if 5 <= hour < 12:
                result = "morning"
            elif 12 <= hour < 17:
                result = "afternoon"
            elif 17 <= hour < 21:
                result = "evening"
            else:
                result = "night"
            
            logger.debug(f"Time of day calculation: {hour} -> {result}")
            return result
                
        except Exception as e:
            logger.error(f"Error calculating time of day: {e}", exc_info=True)
            return "day"
    
    def get_preferred_tone(self, tracker=None) -> str:
        """
        Get user's preferred communication tone.
        """
        logger.debug(f"Getting preferred tone (tracker provided: {tracker is not None})")
        
        # 1. Check slot first
        if tracker:
            tone_from_slot = tracker.get_slot("preferred_tone")
            if tone_from_slot in ["casual", "formal"]:
                logger.debug(f"Using tone from slot: '{tone_from_slot}'")
                return tone_from_slot
        
        # 2. Check API (when backend adds preferred_tone field)
        profile = self.get_profile()
        if profile and "preferred_tone" in profile:
            tone = str(profile["preferred_tone"]).strip().lower()
            if tone in ["casual", "formal"]:
                logger.debug(f"Using tone from API: '{tone}'")
                return tone
        
        # 3. Default
        logger.debug(f"Using default tone: 'casual'")
        return "casual"