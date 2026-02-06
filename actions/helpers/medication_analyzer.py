"""
MEDICATION ANALYZER
===================
Analyzes medication patterns, trends, and adherence insights.

Key:
- Pattern analysis from tracking data
- Trend comparison logic
- Adherence level categorization
- Consistent insight generation

Dependencies: .medication_manager, logging
Used by: actions.py for analysis logic
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class MedicationAnalyzer:
    """Analyzes medication data for patterns and trends."""
    
    def __init__(self, medication_manager):
        """Initialize with medication manager."""
        self.med_manager = medication_manager
        logger.debug("MedicationAnalyzer initialized")
    
    def analyze_adherence_insights(self, tracking_data: List[Dict], period: str) -> Dict[str, Any]:
        """Generate comprehensive adherence insights."""
        
        if not tracking_data:
            return {"error": "No tracking data"}
        
        # Get compliance stats
        stats = self.med_manager.analyze_tracking_compliance(tracking_data)
        medication_names = self.med_manager.get_medication_names()
        
        # Calculate key metrics
        compliance_rate = stats['compliance_rate']
        medication_count = len(medication_names)
        taken = stats['taken']
        total = stats['total']
        
        # Generate insights
        pattern_insight = self._get_pattern_insight(tracking_data, compliance_rate)
        trend_insight = self._get_trend_insight(period, compliance_rate)
        adherence_level = self._get_adherence_level(compliance_rate)
        
        return {
            "period": period,
            "compliance_rate": compliance_rate,
            "medication_count": medication_count,
            "taken": taken,
            "total": total,
            "pattern_insight": pattern_insight,
            "trend_insight": trend_insight,
            "adherence_level": adherence_level,
            "stats": stats
        }
    
    def _get_pattern_insight(self, tracking_data: List[Dict], compliance_rate: float) -> str:
        """Get pattern insight for adherence."""
        
        if compliance_rate < 30:
            return "You're struggling with medication consistency"
        
        # Analyze time patterns for taken medications
        time_counts = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
        
        for item in tracking_data:
            if item.get('tracked_at'):  # Only count taken medications
                reminder_at = item.get("reminder_at", "")
                if reminder_at:
                    try:
                        # Extract hour
                        hour_str = ""
                        if 'T' in reminder_at:
                            hour_str = reminder_at.split('T')[1].split(':')[0]
                        elif ' ' in reminder_at:
                            hour_str = reminder_at.split(' ')[1].split(':')[0]
                        
                        if hour_str and hour_str.isdigit():
                            hour = int(hour_str)
                            if 5 <= hour < 12:
                                time_counts["morning"] += 1
                            elif 12 <= hour < 17:
                                time_counts["afternoon"] += 1
                            elif 17 <= hour < 22:
                                time_counts["evening"] += 1
                            else:
                                time_counts["night"] += 1
                                
                    except (ValueError, IndexError):
                        continue
        
        # Find most common time
        total_taken = sum(time_counts.values())
        if total_taken > 0:
            most_common = max(time_counts, key=time_counts.get)
            percentage = (time_counts[most_common] / total_taken) * 100
            
            if percentage > 40:
                if most_common == "morning":
                    return "You're most consistent with morning doses"
                elif most_common == "afternoon":
                    return "Afternoon doses work best for you"
                elif most_common == "evening":
                    return "Evening is your most reliable time"
                else:
                    return "Nighttime medications suit your routine"
        
        return "Your medication times vary throughout the day"
    
    def _get_trend_insight(self, period: str, current_compliance: float) -> str:
        """Get trend comparison insight that works grammatically in all templates."""
        trend_period = "week" if period.lower() in ["today", "day", "week"] else "month"
        
        try:
            trend_data = self.med_manager.analyze_tracking_trends(period=trend_period)
            change = trend_data.get("change", 0)
            
            # Make all responses complete noun phrases
            if current_compliance >= 70:  # Good adherence
                if change > 5:
                    return f"showing an improvement of {abs(change):.1f}% from last {trend_period}"
                elif change > 2:
                    return f"showing slight improvement from last {trend_period}"
                elif change < -5:
                    return f"at a decline of {abs(change):.1f}% from last {trend_period}"
                elif change < -2:
                    return f"at a slight decline from last {trend_period}"
                else:
                    return f"consistent with last {trend_period}, maintaining good habits"
            
            elif current_compliance >= 40:  # Moderate adherence
                if change > 5:
                    return f"showing an improvement of {abs(change):.1f}% from last {trend_period}"
                elif change > 2:
                    return f"showing improvement from last {trend_period}"
                elif change < -5:
                    return f"at a decline of {abs(change):.1f}% from last {trend_period}"
                elif change < -2:
                    return f"at a decline from last {trend_period}"
                else:
                    return f"taking medications similar to last {trend_period}"
            
            else:  # Poor adherence (<40%)
                if change > 5:
                    return f"showing improvement of {abs(change):.1f}% from last {trend_period}"
                elif change > 2:
                    return f"showing small improvements from last {trend_period}"
                elif change < -5:
                    return f"at a further decline of {abs(change):.1f}% from last {trend_period}"
                elif change < -2:
                    return f"continuing to struggle compared to last {trend_period}"
                else:
                    return f"still inconsistent, similar to last {trend_period}"
                    
        except Exception as e:
            logger.debug(f"Trend analysis unavailable: {e}")
            if current_compliance >= 70:
                return f"maintaining consistency from last {trend_period}"
            elif current_compliance >= 40:
                return f"building consistency from last {trend_period}"
            else:
                return f"facing similar challenges as last {trend_period}"
                
    def _get_adherence_level(self, percentage: float) -> str:
        """Categorize adherence level."""
        if percentage >= 90:
            return "excellent"
        elif percentage >= 80:
            return "very_good"
        elif percentage >= 70:
            return "good"
        elif percentage >= 60:
            return "moderate"
        elif percentage >= 50:
            return "fair"
        elif percentage >= 40:
            return "needs_improvement"
        elif percentage >= 30:
            return "poor"
        else:
            return "very_poor"