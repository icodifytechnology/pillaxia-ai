# symptoms_manager.py
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from .api_client import api_client  # Import the singleton instance

logger = logging.getLogger(__name__)

class SymptomsManager:
    """
    Manager class for handling medication symptoms API operations.
    Uses the centralized api_client for all API calls.
    """
    
    def __init__(self):
        """
        Initialize SymptomsManager with the singleton api_client.
        """
        self.api_client = api_client
        logger.debug("SymptomsManager initialized with api_client")
    
    def get_symptoms(self, token: str, page: int = 1, page_size: int = 10) -> Optional[Dict[str, Any]]:
        """
        Get user's medication symptoms using api_client's get_symptoms method.
        
        Args:
            token: User authentication token
            page: Page number (default: 1)
            page_size: Records per page (default: 10)
        
        Returns:
            Symptoms data with items list or None on error
        """
        logger.debug(f"Fetching symptoms via api_client - page: {page}, page_size: {page_size}")
        
        # Use the api_client's get_symptoms method directly
        result = self.api_client.get_symptoms(token, page, page_size)
        
        if result:
            items = result.get("items", [])
            logger.debug(f"Retrieved {len(items)} symptoms via api_client")
            
            # Log first few items to see their date structure
            if items and len(items) > 0:
                for i, item in enumerate(items[:3]):  # Log first 3 items
                    logger.debug(f"Sample item {i+1}: name={item.get('name')}, start_date={item.get('start_date')}, end_date={item.get('end_date')}, createdAt={item.get('createdAt')}")
        else:
            logger.debug("No symptoms data returned from api_client")
        
        return result
    
    def format_symptom_value(self, symptom: Dict[str, Any]) -> str:
        """
        Format a single symptom into a concise value string with most relevant information.
        
        Args:
            symptom: Symptom data dictionary
        
        Returns:
            Formatted string with key information
        """
        parts = []
        
        # Get symptom name (for context, but not included in value)
        name = symptom.get("name") or symptom.get("symptom") or "Unknown"
        
        # Priority 1: Intensity/Severity (most relevant for symptoms)
        if symptom.get("intensity"):
            # Handle different intensity formats (1/10, moderate, etc.)
            intensity = symptom['intensity']
            if isinstance(intensity, (int, float)) or (isinstance(intensity, str) and intensity.replace('/', '').replace('.', '').isdigit()):
                parts.append(f"Intensity: {intensity}")
            else:
                parts.append(f"Intensity: {intensity}")
        elif symptom.get("severity"):
            parts.append(f"Severity: {symptom['severity']}")
        
        # Priority 2: Duration (if both start and end dates exist)
        if symptom.get("start_date") and symptom.get("end_date"):
            try:
                start = datetime.fromisoformat(symptom['start_date'].replace('Z', '+00:00'))
                end = datetime.fromisoformat(symptom['end_date'].replace('Z', '+00:00'))
                
                # Calculate duration
                duration = end - start
                hours = duration.total_seconds() / 3600
                
                # Format duration appropriately
                if hours < 24:
                    if hours < 1:
                        minutes = int(duration.total_seconds() / 60)
                        parts.append(f"Duration: {minutes} min")
                    else:
                        parts.append(f"Duration: {hours:.1f} hours")
                else:
                    days = duration.days
                    if days == 1:
                        parts.append("Duration: 1 day")
                    else:
                        parts.append(f"Duration: {days} days")
                
                # Also show the time range
                start_time = start.strftime('%H:%M')
                end_time = end.strftime('%H:%M')
                parts.append(f"({start_time} to {end_time})")
                
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not calculate duration: {e}")
                # Fallback to just start date
                parts.append(f"Started: {symptom['start_date']}")
        
        # Priority 3: Only start date available
        elif symptom.get("start_date"):
            try:
                start = datetime.fromisoformat(symptom['start_date'].replace('Z', '+00:00'))
                parts.append(f"Started: {start.strftime('%Y-%m-%d %H:%M')}")
            except (ValueError, TypeError):
                parts.append(f"Started: {symptom['start_date']}")
        
        # Priority 4: Only created date available
        elif symptom.get("createdAt"):
            try:
                created_at = datetime.fromisoformat(symptom['createdAt'].replace('Z', '+00:00'))
                parts.append(f"Recorded: {created_at.strftime('%Y-%m-%d %H:%M')}")
            except (ValueError, TypeError):
                pass
        
        # Priority 5: Brief note (truncated if too long)
        if symptom.get("notes") or symptom.get("note"):
            note = symptom.get("notes") or symptom.get("note")
            if len(note) > 50:
                note = note[:47] + "..."
            parts.append(f"Note: {note}")
        
        # If we have parts, join them, otherwise return a default message
        if parts:
            return " | ".join(parts)
        return "No additional details"
    
    def format_symptoms_list(self, symptoms_data: Dict[str, Any], period: str = None, days: int = None) -> List[Dict[str, str]]:
        """
        Format symptoms data into a list of name-value pairs for frontend display.
        
        Args:
            symptoms_data: Raw symptoms data from get_symptoms
            period: Optional period to filter by (day, week, month, 3 months, year)
            days: Optional number of days to look back (more precise filtering)
        
        Returns:
            List of dictionaries with only 'name' and 'value' fields
        """
        if not symptoms_data or not symptoms_data.get("items"):
            logger.debug("No symptoms data or items to format")
            return []
        
        items = symptoms_data.get("items", [])
        logger.debug(f"Formatting symptoms list with {len(items)} total items, period={period}, days={days}")
        
        # Filter by period if specified
        if period or days:
            items = self.filter_symptoms_by_period(symptoms_data, period, days)
        
        formatted_list = []
        for symptom in items:
            # Get symptom name
            name = symptom.get("name") or symptom.get("symptom") or "Unknown Symptom"
            
            # Format the value with most relevant information
            value = self.format_symptom_value(symptom)
            
            # Add only name and value to the list
            formatted_list.append({
                "name": name,
                "value": value
            })
        
        logger.debug(f"Formatted {len(formatted_list)} symptoms into name-value pairs for period: {period}")
        return formatted_list

    def filter_symptoms_by_period(self, symptoms_data: Dict[str, Any], period: str = None, days: int = None) -> List[Dict[str, Any]]:
        """
        Filter symptoms by time period.
        
        Args:
            symptoms_data: Raw symptoms data from get_symptoms
            period: "day", "week", "month", "3 months", or "year"
            days: Number of days to look back (more precise)
        
        Returns:
            Filtered list of symptoms
        """
        if not symptoms_data or not symptoms_data.get("items"):
            logger.debug("No symptoms data or items to filter")
            return []
        
        items = symptoms_data.get("items", [])
        
        # Calculate cutoff date
        today = datetime.now()
        
        if days:
            cutoff_date = today - timedelta(days=days)
        elif period == "day":
            cutoff_date = today - timedelta(days=1)
        elif period == "week":
            cutoff_date = today - timedelta(days=7)
        elif period == "month":
            cutoff_date = today - timedelta(days=30)
        elif period == "3 months":
            cutoff_date = today - timedelta(days=90)
        elif period == "year":
            cutoff_date = today - timedelta(days=365)
        else:
            # No filtering
            logger.debug(f"No valid period/days provided ({period}/{days}), returning all {len(items)} items unfiltered")
            return items
        
        logger.debug(f"Filtering with cutoff_date: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')} (period={period}, days={days})")
        
        filtered = []
        for i, item in enumerate(items):
            # Try different possible date fields
            date_str = item.get("createdAt") or item.get("start_date") or item.get("date")
            
            if date_str:
                try:
                    # Parse ISO format date
                    item_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    logger.debug(f"Item {i+1}: name={item.get('name')}, date_str={date_str}, parsed_date={item_date.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    if item_date >= cutoff_date:
                        logger.debug(f"  ✓ INCLUDED (within period)")
                        filtered.append(item)
                    else:
                        logger.debug(f"  ✗ EXCLUDED (older than {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')})")
                        
                except (ValueError, TypeError) as e:
                    logger.debug(f"Item {i+1}: Could not parse date '{date_str}': {e}, including by default")
                    filtered.append(item)
            else:
                logger.debug(f"Item {i+1}: No date field found, including by default")
                filtered.append(item)
        
        logger.debug(f"Filtered {len(items)} symptoms to {len(filtered)} for period: {period}, days: {days}")
        return filtered

# Create singleton instance
symptoms_manager = SymptomsManager()