"""
HEALTH RECORDS MANAGER
======================
Simple manager for user health records.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from .api_client import api_client

logger = logging.getLogger(__name__)

class HealthRecordsManager:
    """Simple manager for health records."""
    
    def __init__(self, token: str):
        self.token = token
        self._records_cache = None
    
    def get_all_records(self, page: int = 1, page_size: int = 10) -> Optional[Dict[str, Any]]:
        """Get health records (cached)."""
        if self._records_cache is None:
            self._records_cache = api_client.get_health_records(
                self.token, page=page, page_size=page_size
            )
        return self._records_cache
    
    def get_recent_records(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent health records."""
        records = self.get_all_records()
        if not records:
            return []
        
        items = records.get("items", [])
        # Sort by date (newest first) if available
        try:
            items.sort(key=lambda x: x.get("diagnosis_date", ""), reverse=True)
        except:
            pass
        
        return items[:limit]
    
    def get_record_types(self) -> List[str]:
        """Get unique types of health records."""
        records = self.get_all_records()
        if not records:
            return []
        
        items = records.get("items", [])
        types = set()
        for item in items:
            if "type" in item and item["type"]:
                types.add(item["type"])
        
        return list(types)
    
    def format_record_date(self, date_str: str) -> str:
        """Format diagnosis date for display."""
        if not date_str:
            return "Unknown date"
        
        try:
            # Parse and format: "2023-12-15 00:00:00" -> "Dec 15, 2023"
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%b %d, %Y")
        except:
            return date_str