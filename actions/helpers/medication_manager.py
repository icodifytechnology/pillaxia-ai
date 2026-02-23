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
        success, message, medication_id = api_client.save_user_medication(self.token, medication_data)
        
        if success:
            self._medications_cache = None  # Clear cache
        
        logger.debug(f"save_medication result: success={success}, message={message}")
        return success, message, medication_id
    
    def save_refill(self, medication_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Save new or update existing refill (clears cache)."""
        success, message = api_client.save_medication_refill(self.token, medication_data)
        
        if success:
            self._medications_cache = None  # Clear cache
        
        logger.debug(f'save_refill result: success = {success}, message={message}')
        return success, message
    
    def save_reminder(self, reminder_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Save new or update existing reminder (clears cache)."""
        success, message = api_client.save_medication_reminder(self.token, reminder_data)
        
        if success:
            self._medications_cache = None  # Clear cache
        logger.debug(f'save_reminder result: success = {success}, message={message}')
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
        elif percent_problematic >= 80:
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
    
    def analyze_tracking_trends(self, period: str = "month") -> Dict[str, Any]:
        """
        Minimal trend analysis comparing current period to previous period.
        Focuses on: adherence comparison, medication changes, and on-time tracking.
        """
        
        # Map period to days
        period_days = {
            "week": 7,
            "month": 30,
            "quarter": 90
        }
        
        days_to_analyze = period_days.get(period.lower(), 30)
        
        # Get current period data
        current_end = datetime.now()
        current_start = current_end - timedelta(days=days_to_analyze)
        
        current_data = self.get_medication_tracking(
            start_date=current_start.strftime("%Y-%m-%d"),
            end_date=current_end.strftime("%Y-%m-%d")
        )
        current_items = current_data.get("items", []) if current_data else []
        
        # Get previous period data
        prev_start = current_start - timedelta(days=days_to_analyze)
        prev_end = current_start
        
        prev_data = self.get_medication_tracking(
            start_date=prev_start.strftime("%Y-%m-%d"),
            end_date=prev_end.strftime("%Y-%m-%d")
        )
        prev_items = prev_data.get("items", []) if prev_data else []
        
        # Get current and previous medication lists
        current_meds = self.get_medication_names()
        
        # Temporarily cache previous medications
        self._temp_cache = self._medications_cache
        self._medications_cache = None  # Force refresh for previous period
        prev_meds = self.get_medication_names()
        self._medications_cache = self._temp_cache
        
        # Calculate compliance for both periods
        current_stats = self.analyze_tracking_compliance(current_items)
        prev_stats = self.analyze_tracking_compliance(prev_items)
        
        # Compare adherence
        current_rate = current_stats.get("compliance_rate", 0)
        prev_rate = prev_stats.get("compliance_rate", 0)
        
        # Determine change
        if prev_rate > 0:
            change = current_rate - prev_rate
            change_percent = (change / prev_rate) * 100
        else:
            change = current_rate
            change_percent = 100 if current_rate > 0 else 0
        
        # Find medications added/removed
        added_meds = [med for med in current_meds if med not in prev_meds]
        removed_meds = [med for med in prev_meds if med not in current_meds]
        
        # Find medications taken on time vs missed (using current stats)
        on_time_meds = []
        missed_meds = []
        
        med_stats = current_stats.get("medication_stats", {})
        for med_name, stats in med_stats.items():
            if stats.get("total", 0) > 0:
                compliance = (stats.get("taken", 0) / stats.get("total", 0)) * 100
                if compliance >= 80:
                    on_time_meds.append(med_name)
                elif compliance < 50:
                    missed_meds.append(med_name)
        
        # Generate simple insights
        insights = []
        
        if abs(change) >= 5:  # Significant change
            if change > 0:
                insights.append(f"Your adherence improved by {abs(change):.1f}% compared to last {period}")
            else:
                insights.append(f"Your adherence decreased by {abs(change):.1f}% compared to last {period}")
        
        if added_meds:
            insights.append(f"New medications added: {', '.join(added_meds)}")
        
        if removed_meds:
            insights.append(f"Medications removed: {', '.join(removed_meds)}")
        
        if on_time_meds:
            insights.append(f"You're doing well with: {', '.join(on_time_meds[:3])}")
        
        if missed_meds:
            insights.append(f"Need more consistency with: {', '.join(missed_meds[:3])}")
        
        return {
            "period": period,
            "current_compliance": round(current_rate, 1),
            "previous_compliance": round(prev_rate, 1),
            "change": round(change, 1),
            "change_percent": round(change_percent, 1),
            "medications_added": added_meds,
            "medications_removed": removed_meds,
            "medications_on_time": on_time_meds,
            "medications_needing_attention": missed_meds,
            "insights": insights,
            "current_medication_count": len(current_meds),
            "previous_medication_count": len(prev_meds)
        }

    def color_to_hex(self, color_name: str) -> str:
        """
        Convert a color name to a HEX code.
        Defaults to black (#000000) if the color is unknown.
        """
        if not color_name:
            return "#000000"  # default fallback

        color_map = {
            "aliceblue": "#F0F8FF",
            "antiquewhite": "#FAEBD7",
            "aqua": "#00FFFF",
            "aquamarine": "#7FFFD4",
            "azure": "#F0FFFF",
            "beige": "#F5F5DC",
            "bisque": "#FFE4C4",
            "black": "#000000",
            "blanchedalmond": "#FFEBCD",
            "blue": "#0000FF",
            "blueviolet": "#8A2BE2",
            "brown": "#A52A2A",
            "burlywood": "#DEB887",
            "cadetblue": "#5F9EA0",
            "chartreuse": "#7FFF00",
            "chocolate": "#D2691E",
            "coral": "#FF7F50",
            "cornflowerblue": "#6495ED",
            "cornsilk": "#FFF8DC",
            "crimson": "#DC143C",
            "cyan": "#00FFFF",
            "darkblue": "#00008B",
            "darkcyan": "#008B8B",
            "darkgoldenrod": "#B8860B",
            "darkgray": "#A9A9A9",
            "darkgreen": "#006400",
            "darkgrey": "#A9A9A9",
            "darkkhaki": "#BDB76B",
            "darkmagenta": "#8B008B",
            "darkolivegreen": "#556B2F",
            "darkorange": "#FF8C00",
            "darkorchid": "#9932CC",
            "darkred": "#8B0000",
            "darksalmon": "#E9967A",
            "darkseagreen": "#8FBC8F",
            "darkslateblue": "#483D8B",
            "darkslategray": "#2F4F4F",
            "darkslategrey": "#2F4F4F",
            "darkturquoise": "#00CED1",
            "darkviolet": "#9400D3",
            "deeppink": "#FF1493",
            "deepskyblue": "#00BFFF",
            "dimgray": "#696969",
            "dimgrey": "#696969",
            "dodgerblue": "#1E90FF",
            "firebrick": "#B22222",
            "floralwhite": "#FFFAF0",
            "forestgreen": "#228B22",
            "fuchsia": "#FF00FF",
            "gainsboro": "#DCDCDC",
            "ghostwhite": "#F8F8FF",
            "gold": "#FFD700",
            "goldenrod": "#DAA520",
            "gray": "#808080",
            "green": "#008000",
            "greenyellow": "#ADFF2F",
            "grey": "#808080",
            "honeydew": "#F0FFF0",
            "hotpink": "#FF69B4",
            "indianred": "#CD5C5C",
            "indigo": "#4B0082",
            "ivory": "#FFFFF0",
            "khaki": "#F0E68C",
            "lavender": "#E6E6FA",
            "lavenderblush": "#FFF0F5",
            "lawngreen": "#7CFC00",
            "lemonchiffon": "#FFFACD",
            "lightblue": "#ADD8E6",
            "lightcoral": "#F08080",
            "lightcyan": "#E0FFFF",
            "lightgoldenrodyellow": "#FAFAD2",
            "lightgray": "#D3D3D3",
            "lightgreen": "#90EE90",
            "lightgrey": "#D3D3D3",
            "lightpink": "#FFB6C1",
            "lightsalmon": "#FFA07A",
            "lightseagreen": "#20B2AA",
            "lightskyblue": "#87CEFA",
            "lightslategray": "#778899",
            "lightslategrey": "#778899",
            "lightsteelblue": "#B0C4DE",
            "lightyellow": "#FFFFE0",
            "lime": "#00FF00",
            "limegreen": "#32CD32",
            "linen": "#FAF0E6",
            "magenta": "#FF00FF",
            "maroon": "#800000",
            "mediumaquamarine": "#66CDAA",
            "mediumblue": "#0000CD",
            "mediumorchid": "#BA55D3",
            "mediumpurple": "#9370DB",
            "mediumseagreen": "#3CB371",
            "mediumslateblue": "#7B68EE",
            "mediumspringgreen": "#00FA9A",
            "mediumturquoise": "#48D1CC",
            "mediumvioletred": "#C71585",
            "midnightblue": "#191970",
            "mintcream": "#F5FFFA",
            "mistyrose": "#FFE4E1",
            "moccasin": "#FFE4B5",
            "navajowhite": "#FFDEAD",
            "navy": "#000080",
            "oldlace": "#FDF5E6",
            "olive": "#808000",
            "olivedrab": "#6B8E23",
            "orange": "#FFA500",
            "orangered": "#FF4500",
            "orchid": "#DA70D6",
            "palegoldenrod": "#EEE8AA",
            "palegreen": "#98FB98",
            "paleturquoise": "#AFEEEE",
            "palevioletred": "#DB7093",
            "papayawhip": "#FFEFD5",
            "peachpuff": "#FFDAB9",
            "peru": "#CD853F",
            "pink": "#FFC0CB",
            "plum": "#DDA0DD",
            "powderblue": "#B0E0E6",
            "purple": "#800080",
            "rebeccapurple": "#663399",
            "red": "#FF0000",
            "rosybrown": "#BC8F8F",
            "royalblue": "#4169E1",
            "saddlebrown": "#8B4513",
            "salmon": "#FA8072",
            "sandybrown": "#F4A460",
            "seagreen": "#2E8B57",
            "seashell": "#FFF5EE",
            "sienna": "#A0522D",
            "silver": "#C0C0C0",
            "skyblue": "#87CEEB",
            "slateblue": "#6A5ACD",
            "slategray": "#708090",
            "slategrey": "#708090",
            "snow": "#FFFAFA",
            "springgreen": "#00FF7F",
            "steelblue": "#4682B4",
            "tan": "#D2B48C",
            "teal": "#008080",
            "thistle": "#D8BFD8",
            "tomato": "#FF6347",
            "turquoise": "#40E0D0",
            "violet": "#EE82EE",
            "wheat": "#F5DEB3",
            "white": "#FFFFFF",
            "whitesmoke": "#F5F5F5",
            "yellow": "#FFFF00",
            "yellowgreen": "#9ACD32"
        }

        normalized = color_name.strip().lower()
        return color_map.get(normalized, "#000000")  # fallback to black if unknown