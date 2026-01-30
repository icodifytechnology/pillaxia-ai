# helpers/template_manager.py
import json
import random
import os
import re

class TemplateManager:
    """Manages response templates with safe placeholder formatting"""
    
    def __init__(self):
        self.templates = self._load_templates()
    
    def _load_templates(self):
        """Load templates from JSON file, fallback to defaults if file not found"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(current_dir, '..', 'templates', 'responses.json')
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Return minimal fallback templates if file can't be loaded
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
    
    def get_response(self, intent, tone="casual", **placeholders):
        """
        Get a random response template for the given intent and tone,
        safely formatting it with available placeholders.
        
        Args:
            intent: The intent name (e.g., "greet", "goodbye")
            tone: Response tone ("casual" or "formal")
            **placeholders: Key-value pairs for template placeholders
        
        Returns:
            Formatted response string
        """
        # Get templates for intent and tone, default to greet/casual if not found
        templates = self.templates.get(intent, {}).get(tone, [])
        if not templates:
            templates = ["Hello!"]  # Ultimate fallback
        
        # Select random template
        template = random.choice(templates)
        
        # Safely format template with placeholders
        return self._safe_format(template, **placeholders)
    
    def _safe_format(self, template, **placeholders):
        """
        Format template string safely, providing defaults for missing placeholders.
        
        Args:
            template: String with {placeholder} markers
            **placeholders: Values for placeholders
        
        Returns:
            Formatted string
        """
        # Find all placeholders in the template using regex
        found_placeholders = re.findall(r'\{(\w+)\}', template)
        
        # Build values dictionary with defaults for missing placeholders
        values = {}
        for placeholder in found_placeholders:
            if placeholder in placeholders:
                values[placeholder] = placeholders[placeholder]
            else:
                # Use default value if placeholder is missing
                values[placeholder] = self._get_default_value(placeholder)
        
        # Format and return the template
        return template.format(**values)
    
    def _get_default_value(self, placeholder_name):
        """Return default values for common placeholders"""
        defaults = {
            "name": "there",           # Default when user name is unknown
            "time_of_day": "day",      # Default when time calculation fails
            "medications": "your medications"  # Default medication list
        }
        return defaults.get(placeholder_name, "")
    
    def get_all_intents(self):
        """Return list of all available intent names"""
        return list(self.templates.keys())