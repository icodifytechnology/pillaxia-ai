import logging
from typing import Dict, Any, List, Optional, Tuple
from .api_client import api_client

logger = logging.getLogger(__name__)

class MedicationManager:
    """Manages user medication data"""

    def __init__(self, token: str):
        self.token = token
        self._medications_cache = None
        logger.debug(f"MedicationManager initialized for token: {token[:20]}...")

    def get_all_medications(self) -> Optional[Dict[str, Any]]:
        """Get all user medications, cached"""
        if self._medications_cache is None:
            logger.debug("Cache miss - fetching medications from API")
            self._medications_cache = api_client.get_user_medications(self.token)
            if self._medications_cache:
                logger.debug(f"Fetched {self._medications_cache.get('count', 0)} medications")
            else:
                logger.warning("No medications data received")
        else:
            logger.debug("Cache hit - using cached medications")
        
        return self._medications_cache
    
    def get_medication_by_name(self, medication_name: str) -> Optional[Dict[str, Any]]:
        """Get specific medication by name (case-insensitive)"""
        logger.debug(f"Looking for medication: '{medication_name}'")
        
        medications_data = self.get_all_medications()
        if not medications_data:
            return None
        
        items = medications_data.get("items", [])
        for med in items:
            if med.get("name", "").lower() == medication_name.lower():
                logger.debug(f"Found medication: {med.get('name')}")
                return med
        
        logger.debug(f"Medication '{medication_name}' not found")
        return None
    
    def get_medication_names(self) -> List[str]:
        """Get list of all medication names"""
        medications_data = self.get_all_medications()
        if not medications_data:
            return []
        
        items = medications_data.get("items", [])
        names = [med.get("name", "") for med in items if med.get("name")]
        logger.debug(f"Extracted {len(names)} medication names")
        return names
    
    def save_medication(self, medication_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Save a new medication or update existing"""
        logger.info(f"Saving medication: {medication_data.get('name', 'Unnamed')}")
        success, message = api_client.save_user_medication(self.token, medication_data)
        
        if success:
            # Clear cache since data has changed
            self._medications_cache = None
            logger.info("Medication saved, cache cleared")
        else:
            logger.error(f"Failed to save medication: {message}")
        
        return success, message