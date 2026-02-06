import json
import os
import random
import re
import logging

logger = logging.getLogger(__name__)

class TemplateManager:
    """Manages response templates with safe placeholder formatting and tone variation."""
    
    def __init__(self):
        """Load templates from JSON file on initialization."""
        self.templates = self._load_templates()
        logger.debug(f"Loaded {len(self.templates)} intents")
    
    def _load_templates(self):
        """Load templates from responses.json, fallback if fails."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(current_dir, '..', 'templates', 'responses.json')
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load templates: {e}")
            return self._get_fallback_templates()
    
    def _get_fallback_templates(self):
        """Basic templates if JSON file missing or invalid."""
        logger.warning("Using fallback templates")
        return {
            "greet": {
                "casual": ["Hello!", "Hi there!"],
                "formal": ["Greetings.", "Hello."]
            },
            "default_error": {
                "casual": ["Something went wrong."],
                "formal": ["An error occurred."]
            }
        }
    
    def get_response(self, intent: str, tone: str = "casual", **placeholders) -> str:
        """
        Get formatted response for intent and tone.
        Falls back: missing intent → "greet", missing tone → "casual"
        """
        # Validate intent and tone
        if intent not in self.templates:
            intent = "greet"
        if tone not in self.templates[intent]:
            tone = "casual"
        
        # Select random template and format
        template = random.choice(self.templates[intent][tone])
        return self._safe_format(template, **placeholders)

    
    def _safe_format(self, template: str, **placeholders) -> str:
        """Format template with defaults for missing placeholders."""
        # Pre-process placeholders to handle .capitalize() etc.
        processed_placeholders = {}
        
        for key, value in placeholders.items():
            if isinstance(value, str):
                processed_placeholders[key] = value
                # Also add capitalized version
                processed_placeholders[f"{key}_capitalize"] = value.capitalize()
            else:
                processed_placeholders[key] = value
        
        values = {}
        for placeholder in re.findall(r'\{(\w+)\}', template):
            if placeholder in processed_placeholders:
                values[placeholder] = processed_placeholders[placeholder]
            else:
                values[placeholder] = self._get_default_value(placeholder)
        
        return template.format(**values)
    
    def _get_default_value(self, placeholder_name: str) -> str:
        """Default values for common placeholders."""
        defaults = {
            "name": "there",
            "time_of_day": "day",
            "medications": "your medications",
            "count": "0",
            "medication": "your medication",
            "pattern_insight": "your medication pattern varies",
            "trend_insight": "maintaining consistency",
            "encouragement": "Keep up the good work!"
        }
        return defaults.get(placeholder_name, "")
    
    def get_all_intents(self):
        """Get list of all available intent names."""
        return list(self.templates.keys())