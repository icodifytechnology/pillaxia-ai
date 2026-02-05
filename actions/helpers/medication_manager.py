"""
MEDICATION MANAGER
==================
Manages user medication data with caching, tracking, and compliance analysis.

Key:
- Cached medication access
- Tracking data retrieval
- Compliance analysis
- Case-insensitive medication lookup

Dependencies: .api_client, logging, datetime
Used by: actions.py for medication-related operations
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from .api_client import api_client

logger = logging.getLogger(__name__)


class MedicationManager:
    """Manages user medication data with caching and analysis."""
    
    def __init__(self, token: str):
        """Initialize with user token for medication access."""
        self.token = token
        self._medications_cache = None
        logger.debug(f"MedicationManager initialized for token: {token[:20]}...")

    def get_all_medications(self) -> Optional[Dict[str, Any]]:
        """Get all user medications (cached)."""
        if self._medications_cache is None:
            self._medications_cache = api_client.get_user_medications(self.token)
        return self._medications_cache
    
    def get_medication_by_name(self, medication_name: str) -> Optional[Dict[str, Any]]:
        """Find medication by name (case-insensitive)."""
        data = self.get_all_medications()
        if not data:
            return None
        
        for med in data.get("items", []):
            if med.get("name", "").lower() == medication_name.lower():
                return med
        return None
    
    def get_medication_names(self) -> List[str]:
        """Get list of all medication names."""
        data = self.get_all_medications()
        if not data:
            return []
        
        return [med.get("name", "") for med in data.get("items", []) if med.get("name")]
    
    def save_medication(self, medication_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Save new or update existing medication (clears cache)."""
        success, message = api_client.save_user_medication(self.token, medication_data)
        
        if success:
            self._medications_cache = None  # Clear cache
        
        return success, message
    
    def get_medication_tracking(self, start_date: str = None, end_date: str = None) -> Optional[Dict[str, Any]]:
        """Get tracking data with optional date filtering."""
        return api_client.get_medication_tracking(
            self.token, 
            start_date=start_date, 
            end_date=end_date
        )

    def get_recent_tracking(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get tracking data for last N days."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        tracking_data = self.get_medication_tracking(start_date=start_date, end_date=end_date)
        if tracking_data:
            return tracking_data.get("items", [])
        return []

    def analyze_tracking_compliance(self, tracking_data: List[Dict] = None) -> Dict[str, Any]:
        """Analyze tracking data and return compliance statistics."""
        if tracking_data is None:
            tracking_data = self.get_recent_tracking(days=30)
        
        if not tracking_data:
            return {"total": 0, "taken": 0, "missed": 0, "compliance_rate": 0}
        
        # Calculate overall compliance
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
        
        return {
            'total': total,
            'taken': taken,
            'missed': missed,
            'compliance_rate': round(compliance_rate, 1),
            'medication_stats': medication_stats,
            'data_points': total
        }

    def get_todays_tracking(self) -> List[Dict[str, Any]]:
        """Get today's tracking data."""
        tracking_data = self.get_medication_tracking()
        if tracking_data:
            return tracking_data.get("items", [])
        return []
    
    # NEW CONSOLIDATED METHODS
    def analyze_problematic_medications(self, stats: Dict[str, Any], period: str = "month") -> str:
        """
        Analyze which medications need attention based on compliance.
        Returns a human-readable note about problematic medications.
        """
        if not stats.get('medication_stats'):
            return ""
        
        medication_stats = stats['medication_stats']
        total_meds = len(medication_stats)
        problematic_meds = []
        
        # Identify medications with low compliance (<70%)
        for med_name, med_stats in medication_stats.items():
            if med_stats.get('total', 0) > 0:
                compliance = (med_stats['taken'] / med_stats['total']) * 100
                if compliance < 70:
                    problematic_meds.append((med_name, compliance))
        
        if not problematic_meds:
            return ""
        
        # Sort by worst compliance first
        problematic_meds.sort(key=lambda x: x[1])
        num_problematic = len(problematic_meds)
        med_names = [m[0] for m in problematic_meds]
        percent_problematic = (num_problematic / total_meds) * 100
        
        # Generate appropriate note based on severity
        if percent_problematic == 100:
            return f"It seems you haven't been taking any of your medications on time this {period}. Let's try to improve that!"
        elif percent_problematic >= 70:
            return f"Almost all of your medications ({', '.join(med_names)}) need more attention this {period}."
        elif percent_problematic >= 40:
            if num_problematic == 1:
                return f"Try to be more consistent with your {med_names[0]} this {period}."
            elif num_problematic == 2:
                return f"Focus on taking {med_names[0]} and {med_names[1]} more regularly this {period}."
            else:
                return f"Pay special attention to: {', '.join(med_names[:-1])} and {med_names[-1]} this {period}."
        else:
            if num_problematic == 1:
                return f"You mostly did well this {period}, but keep an eye on your {med_names[0]}."
            else:
                return f"You mostly took your medications on time this {period}. A few like {', '.join(med_names[:-1])} and {med_names[-1]} could use more consistency."
    
    def format_tracking_entry(self, item: Dict[str, Any]) -> Dict[str, str]:
        """
        Format a tracking entry for display.
        Returns: {'name': medication_name, 'value': formatted_entry}
        """
        med_name = item.get('reminder', 'Unknown medication')
        reminder_at = item.get('reminder_at', '')
        tracked_at = item.get('tracked_at')
        
        # Format reminder time
        if reminder_at and ' ' in reminder_at:
            date_part, time_part = reminder_at.split(' ', 1)
            time_short = time_part[:5] if len(time_part) >= 5 else time_part
            reminder_str = f"{date_part} {time_short}"
        else:
            reminder_str = reminder_at or "Unknown time"
        
        # Determine status
        if tracked_at:
            if ' ' in tracked_at:
                _, tracked_time = tracked_at.split(' ', 1)
                time_short = tracked_time[:5] if len(tracked_time) >= 5 else tracked_time
                status = f"Taken at {time_short}"
            else:
                status = "Taken"
        else:
            status = "Medication not taken"
        
        return {
            'name': med_name,
            'value': f"Reminded at {reminder_str}, {status}"
        }
    
    def build_report_data(self, tracking_data: List[Dict], max_entries: int = 10, period: str = "month") -> List[Dict]:
        """
        Build formatted report data from tracking entries.
        
        Args:
            tracking_data: List of tracking entries
            max_entries: Maximum number of entries to include
            period: Time period for context
            
        Returns:
            List of formatted entries for display
        """
        report_data = []
        recent_entries = tracking_data[:max_entries]
        
        for item in recent_entries:
            report_data.append(self.format_tracking_entry(item))
        
        # Add truncation note if needed
        if len(tracking_data) > max_entries:
            report_data.append({
                'name': 'Note',
                'value': f"... and {len(tracking_data) - max_entries} more entries this {period}"
            })
        
        return report_data