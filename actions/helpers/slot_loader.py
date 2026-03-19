"""
SLOT LOADER
===========
Loads user profile data into Rasa conversation slots.

Key:
- Extracts name, timezone, tone from profile
- Returns SlotSet events for Rasa
- Safe defaults for missing data

Slots set: user_name, user_timezone, preferred_tone
Dependencies: rasa_sdk, .user_profile, logging
"""

import logging
from typing import Dict, List, Optional
from rasa_sdk import Tracker
from rasa_sdk.events import SlotSet
from .user_profile import UserProfile

logger = logging.getLogger(__name__)


class SlotLoader:
    """Loads user profile data into Rasa slots."""
    
    def __init__(self, token: str):
        """Initialize with user token for profile access."""
        self.profile = UserProfile(token)
        logger.debug(f"SlotLoader initialized for token: {token}...")
    
    def load_all_slots(self, tracker: Tracker) -> List[SlotSet]:
        """Load name, timezone, and tone slots from profile."""
        events = []
        profile_data = self.profile.get_profile()
        
        if not profile_data:
            logger.warning("No profile data, using defaults")
            return [
                SlotSet("user_name", None),
                SlotSet("user_timezone", "UTC"),
                SlotSet("preferred_tone", "casual")
            ]
        
        # Extract and set slots
        events.append(SlotSet("user_name", self._extract_name(profile_data)))
        events.append(SlotSet("user_timezone", self._extract_timezone(profile_data)))
        events.append(SlotSet("preferred_tone", self._extract_tone(profile_data)))
        
        logger.info(f"Profile fetched for token: {self.profile.token}...")
        logger.info(f"Name extracted: {self._extract_name(profile_data)}")
        logger.info(f"Loaded {len(events)} slots")
        return events
    
    def _extract_name(self, profile_data: Dict) -> Optional[str]:
        """Extract name from profile fields in priority order."""
        name_fields = ["full_name", "user_name", "name", "username", "email"]
        
        for field in name_fields:
            if field in profile_data and profile_data[field]:
                raw_name = str(profile_data[field]).strip()
                
                if not raw_name or raw_name.lower() in ["null", "none"]:
                    continue
                
                # Extract from email if needed
                if "@" in raw_name:
                    raw_name = raw_name.split("@")[0]
                
                # Return capitalized first name
                return raw_name.split()[0].capitalize()
        
        return None
    
    def _extract_timezone(self, profile_data: Dict) -> str:
        """Extract timezone, default to UTC if invalid."""
        tz = profile_data.get("timezone", "UTC")
        if tz and str(tz).strip().lower() not in ["null", "none", ""]:
            return str(tz).strip()
        return "UTC"
    
    def _extract_tone(self, profile_data: Dict) -> str:
        """Extract tone preference, default to casual."""
        tone = profile_data.get("preferred_tone", "casual")
        if tone in ["casual", "formal"]:
            return tone
        return "casual"