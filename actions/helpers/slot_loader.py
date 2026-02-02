"""
Slot Loader for user profile slots
"""

import logging
from typing import Dict, Any, List, Text, Optional
from rasa_sdk import Tracker
from rasa_sdk.events import SlotSet
from .user_profile import UserProfile

logger = logging.getLogger(__name__)


class SlotLoader:
    """Handles loading and caching of user profile slots"""
    
    def __init__(self, token: str):
        self.token = token
        self.profile = UserProfile(token)
        self._profile_data = None
        logger.debug(f"SlotLoader initialized with token: {token[:20]}...")
    
    def load_all_slots(self, tracker: Tracker) -> List[SlotSet]:
        """
        Load all user preference slots in one efficient call
        Returns: List of SlotSet events
        """
        logger.info("Loading all user preference slots")
        
        events = []
        
        # Get profile once (cached)
        profile_data = self.profile.get_profile()
        
        if not profile_data:
            logger.warning("Could not load profile data, setting defaults")
            events = [
                SlotSet("user_name", None),
                SlotSet("user_timezone", "UTC"),
                SlotSet("preferred_tone", "casual")
            ]
            return events
        
        # Load name
        name = self._extract_name(profile_data)
        events.append(SlotSet("user_name", name))
        logger.debug(f"Set user_name slot: '{name}'")
        
        # Load timezone
        timezone = self._extract_timezone(profile_data)
        events.append(SlotSet("user_timezone", timezone))
        logger.debug(f"Set user_timezone slot: '{timezone}'")
        
        # Load tone preference
        tone = self._extract_tone(profile_data)
        events.append(SlotSet("preferred_tone", tone))
        logger.debug(f"Set preferred_tone slot: '{tone}'")
        
        logger.info(f"Loaded {len(events)} slots")
        return events
    
    def _extract_name(self, profile_data: Dict) -> Optional[str]:
        """Extract name from profile data"""
        name_fields = ["full_name", "user_name", "name", "username", "email"]
        for field in name_fields:
            if field in profile_data and profile_data[field]:
                raw_name = str(profile_data[field]).strip()
                if raw_name and raw_name.lower() not in ["null", "none"]:
                    if "@" in raw_name:
                        raw_name = raw_name.split("@")[0]
                    return raw_name.split()[0].capitalize()
        return None
    
    def _extract_timezone(self, profile_data: Dict) -> str:
        """Extract timezone from profile data"""
        tz = profile_data.get("timezone", "UTC")
        if tz and str(tz).strip().lower() not in ["null", "none", ""]:
            return str(tz).strip()
        return "UTC"
    
    def _extract_tone(self, profile_data: Dict) -> str:
        """Extract preferred tone from profile data"""
        tone = profile_data.get("preferred_tone", "casual")
        if tone in ["casual", "formal"]:
            return tone
        return "casual"