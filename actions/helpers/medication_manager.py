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
    
    def get_medication_tracking(self, start_date: str = None, end_date: str = None) -> Optional[Dict[str, Any]]:
        """Get medication tracking data with date filtering"""
        logger.debug(f"Getting tracking data from {start_date} to {end_date}")
        
        tracking_data = api_client.get_medication_tracking(
            self.token, 
            start_date=start_date, 
            end_date=end_date
        )
        
        if tracking_data:
            items = tracking_data.get("items", [])
            logger.debug(f"Got {len(items)} tracking entries")
            
            # Log sample for debugging
            if items:
                sample = items[0]
                logger.debug(f"Sample entry: {sample.get('reminder')} - "
                            f"Tracked: {'Yes' if sample.get('tracked_at') else 'No'}")
        
        return tracking_data

    def get_recent_tracking(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get recent tracking data (last N days)"""
        logger.debug(f"Getting last {days} days of tracking")
        
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        tracking_data = self.get_medication_tracking(start_date=start_date, end_date=end_date)
        if tracking_data:
            return tracking_data.get("items", [])
        return []

    def analyze_tracking_compliance(self, tracking_data: List[Dict] = None) -> Dict[str, Any]:
        """Analyze tracking data and return compliance statistics"""
        logger.debug("Analyzing tracking compliance")
        
        if tracking_data is None:
            tracking_data = self.get_recent_tracking(days=30)
        
        if not tracking_data:
            logger.debug("No tracking data to analyze")
            return {"total": 0, "taken": 0, "missed": 0, "compliance_rate": 0}
        
        total = len(tracking_data)
        taken = sum(1 for item in tracking_data if item.get('tracked_at'))
        missed = total - taken
        compliance_rate = (taken / total * 100) if total > 0 else 0
        
        # Group by medication
        medication_stats = {}
        for item in tracking_data:
            med_name = item.get('reminder', 'Unknown')
            if med_name not in medication_stats:
                medication_stats[med_name] = {'total': 0, 'taken': 0}
            
            medication_stats[med_name]['total'] += 1
            if item.get('tracked_at'):
                medication_stats[med_name]['taken'] += 1
        
        logger.debug(f"Compliance analysis: {taken}/{total} taken ({compliance_rate:.1f}%)")
        
        return {
            'total': total,
            'taken': taken,
            'missed': missed,
            'compliance_rate': round(compliance_rate, 1),
            'medication_stats': medication_stats,
            'data_points': total
        }

    def get_todays_tracking(self) -> List[Dict[str, Any]]:
        """Get today's medication tracking data"""
        logger.debug("Fetching today's tracking data")
        tracking_data = self.get_medication_tracking()
        if tracking_data:
            return tracking_data.get("items", [])
        return []

    def _get_auth_headers(self) -> Dict[str, str]:
        """Helper to get authentication headers"""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "Pillaxia-Rasa-Bot/1.0"
        }