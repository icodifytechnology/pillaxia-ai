"""
Template Manager for response templates with safe placeholder formatting
"""

import json
import random
import os
import re
import logging

logger = logging.getLogger(__name__)


class TemplateManager:
    """Manages response templates with safe placeholder formatting"""
    
    def __init__(self):
        self.templates = self._load_templates()
        logger.debug(f"TemplateManager initialized with {len(self.templates)} intents")
    
    def _load_templates(self):
        """Load templates from JSON file"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(current_dir, '..', 'templates', 'responses.json')
        
        logger.debug(f"Loading templates from: {template_path}")
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                templates = json.load(f)
                logger.info(f"Successfully loaded templates with {len(templates)} intents")
                return templates
        except FileNotFoundError:
            logger.error(f"Template file not found at {template_path}")
            return self._get_fallback_templates()
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing templates JSON: {e}")
            return self._get_fallback_templates()
    
    def _get_fallback_templates(self):
        """Fallback templates if JSON loading fails"""
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
        Get a random response template for the given intent and tone.
        """
        logger.debug(f"Getting response for intent: '{intent}', tone: '{tone}'")
        logger.debug(f"Placeholders: {placeholders}")
        
        # Check if intent exists
        if intent not in self.templates:
            logger.warning(f"Intent '{intent}' not found, using 'greet'")
            intent = "greet"
        
        # Check if tone exists for this intent
        if tone not in self.templates[intent]:
            logger.warning(f"Tone '{tone}' not found for intent '{intent}', using 'casual'")
            tone = "casual"
        
        # Get templates
        templates = self.templates[intent][tone]
        logger.debug(f"Found {len(templates)} templates for {intent}/{tone}")
        
        # Pick random template
        template = random.choice(templates)
        logger.debug(f"Selected template: '{template}'")
        
        # Format template
        formatted = self._safe_format(template, **placeholders)
        logger.debug(f"Formatted result: '{formatted}'")
        
        return formatted
    
    def _safe_format(self, template: str, **placeholders) -> str:
        """Format template string safely"""
        logger.debug(f"Safe formatting template: '{template}'")
        
        found_placeholders = re.findall(r'\{(\w+)\}', template)
        logger.debug(f"Placeholders found in template: {found_placeholders}")
        
        values = {}
        for placeholder in found_placeholders:
            if placeholder in placeholders:
                values[placeholder] = placeholders[placeholder]
                logger.debug(f"Using provided '{placeholder}': '{placeholders[placeholder]}'")
            else:
                default = self._get_default_value(placeholder)
                values[placeholder] = default
                logger.debug(f"Using default for '{placeholder}': '{default}'")
        
        logger.debug(f"Final values for formatting: {values}")
        return template.format(**values)
    
    def _get_default_value(self, placeholder_name: str) -> str:
        """Return default values for common placeholders"""
        defaults = {
            "name": "there",
            "time_of_day": "day",
            "medications": "your medications"
        }
        return defaults.get(placeholder_name, "")
    
    def get_all_intents(self):
        """Return list of all available intent names"""
        return list(self.templates.keys())