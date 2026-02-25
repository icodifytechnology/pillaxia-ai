import re
from dotenv import load_dotenv
from typing import Any, Text, Dict, List, Optional, Tuple, Union
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta
import pandas as pd
from rapidfuzz import process, fuzz
import requests
from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.events import SlotSet, SessionStarted, FollowupAction, ActionExecuted, ActiveLoop
from rasa_sdk.executor import CollectingDispatcher
from rasa.shared.exceptions import RasaException
from .helpers.medication_manager import MedicationManager
from .helpers.medication_analyzer import MedicationAnalyzer
import openai
from openai import OpenAI
import os
import random

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

openai_api_key = os.getenv("openai_api_key")

client = OpenAI(api_key=openai_api_key)

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

# Debug utility function
def debug_separator(title: str = "DEBUG") -> str:
    """Create formatted debug separator"""
    return f"\n{'='*60}\n=== {title} ===\n{'='*60}"

def send_response(response: str):
    '''Send the text response in attachment format'''

    attachment={
                "query_response": response,
                "type": "text",
                "status": "success"
            }
    
    return attachment

def send_response_with_buttons(response: str, buttons: list):
    """
    Send the text response in attachment format with buttons.

    buttons: list of dicts with 'title' and 'payload'
    Example: [{"title": "Once", "payload": "once"}]
    """
    attachment = {
        "query_response": response,
        "type": "buttons-array",
        "status": "success",
        "data": buttons
    }

    return attachment

class BaseAction(Action, ABC):
    """Abstract base class for all actions that need user preferences"""
    
    @abstractmethod
    def name(self) -> Text:
        """Action name - must be implemented by child classes"""
        pass
    
    def ensure_slots_loaded(self, tracker: Tracker) -> List[SlotSet]:
        """
        Ensures user preference slots are loaded.
        Returns empty list if already loaded.
        """
        logger.debug("Checking if slots need loading...")
        
        # Check if ANY of the slots are missing
        required_slots = ["user_name", "user_timezone", "preferred_tone"]
        for slot in required_slots:
            if tracker.get_slot(slot) is None:
                logger.info(f"Slot '{slot}' is missing, loading all slots")
                
                # Import locally to avoid circular issues
                from .helpers.slot_loader import SlotLoader
                if not hasattr(self, '_slot_loader'):
                    self._slot_loader = SlotLoader(tracker.sender_id)
                return self._slot_loader.load_all_slots(tracker)
        
        logger.debug("All slots already loaded")
        return []
    
    @abstractmethod
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                      tracker: Tracker,
                      domain: Dict[Text, Any]) -> List[SlotSet]:
        """
        Template method that ensures slots are loaded before the action logic runs.
        Override this instead of run() in child classes.
        """
        pass
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[SlotSet]:
        
        # Always load slots first if needed
        slot_events = self.ensure_slots_loaded(tracker)
        
        # Run the actual action logic
        action_events = self.run_with_slots(dispatcher, tracker, domain)
        
        # Combine events
        return slot_events + action_events


# Import helpers AFTER defining BaseAction to avoid circular imports
from .helpers.response_builder import ResponseBuilder
from .helpers.slot_loader import SlotLoader


class ActionSessionStart(BaseAction):
    """Initializes session and loads user preferences"""
    
    def name(self) -> Text:
        return "action_session_start"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                  tracker: Tracker,
                  domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
    
        logger.info(debug_separator("ActionSessionStart"))
        
        # Add an action_listen event to create the right state for rule matching
        events = []
        
        # Add a fake action_listen to help rule matching
        events.append(ActionExecuted("action_listen"))
        
        logger.info("Session initialized with action_listen for rule matching")
        return events
    
    def run(self, dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        """
        Override run to handle session start specially
        """
        logger.info("Starting session initialization")
        
        # Load all user slots at session start
        slot_loader = SlotLoader(tracker.sender_id)
        slot_events = slot_loader.load_all_slots(tracker)
        
        # Log loaded slots WITHOUT isinstance check
        for event in slot_events:
            # Directly access attributes - assume they're SlotSet objects
            try:
                logger.debug(f"Loaded slot: {event.key} = {event.value}")
            except AttributeError:
                # If not a SlotSet, log what it is
                logger.debug(f"Loaded event (not SlotSet): {type(event)} - {event}")
        
        # Run the actual action logic
        action_events = self.run_with_slots(dispatcher, tracker, domain)
        
        # Combine all events
        all_events = slot_events + [SessionStarted()] + action_events
        logger.info(f"Session initialization complete with {len(all_events)} events")
        
        return all_events

class ActionGreet(BaseAction):
    """Personalized greeting action"""
    
    def name(self) -> Text:
        return "action_greet"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                      tracker: Tracker,
                      domain: Dict[Text, Any]) -> List[SlotSet]:
        """
        Greet the user (slots are already loaded by base class)
        """
        logger.info(debug_separator("ActionGreet"))
        
        token = tracker.sender_id
        
        # Debug: Show what we have in slots
        logger.debug(f"Slots for greeting:")
        logger.debug(f"  user_name: '{tracker.get_slot('user_name')}'")
        logger.debug(f"  preferred_tone: '{tracker.get_slot('preferred_tone')}'")
        logger.debug(f"  user_timezone: '{tracker.get_slot('user_timezone')}'")
        
        # Build and send greeting
        try:
            builder = ResponseBuilder(token, tracker)
        
            # Simple greeting - no data array
            attachment = builder.build_response("greet")
            dispatcher.utter_message(attachment=attachment)

            logger.info(f"Sent greeting: '{attachment}'")
        except Exception as e:
            logger.error(f"Error building greeting: {e}", exc_info=True)
            response = "Hello! Nice to see you."
            attachment = send_response(attachment)
            dispatcher.utter_message(attachment=attachment)
        
        return []

class ActionGoodbye(BaseAction):
    """Personalized goodbye action"""
    
    def name(self) -> Text:
        return "action_goodbye"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                      tracker: Tracker,
                      domain: Dict[Text, Any]) -> List[SlotSet]:
        """
        Say goodbye to the user
        """
        logger.info(debug_separator("ActionGoodbye"))
        
        token = tracker.sender_id
        
        # Debug current slots
        logger.debug(f"Current slot values:")
        for slot in ["user_name", "preferred_tone", "user_timezone"]:
            logger.debug(f"  {slot}: '{tracker.get_slot(slot)}'")
        
        # Build personalized goodbye
        try:
            builder = ResponseBuilder(token, tracker)
            attachment = builder.build_response("goodbye")
            dispatcher.utter_message(attachment=attachment)
            logger.info(f"Sent goodbye: '{attachment}'")
        except Exception as e:
            logger.error(f"Error building goodbye: {e}", exc_info=True)
            response = "Goodbye! Take care."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
        
        return []
    
class ActionIamabot(Action):
    """Handles questions about bot identity - no personalization needed"""
    
    def name(self) -> Text:
        return "action_iamabot"
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.debug(f"Processing bot identity query from user: {tracker.sender_id[:20]}...")
        
        # Bot identity responses - static as this is meta-conversation
        BOT_IDENTITY_RESPONSES = [
            "I’m an AI health assistant — not a human — but I’m here to help you manage medications and health-related tasks.",
            "You’re chatting with an AI assistant. I’m here to help with medicine reminders, schedules, and related questions.",
            "I’m not a real person, but I can help you stay on track with your medications and health routines.",
            "This is an automated health assistant. I’m here to support you with medication reminders and basic health information.",
            "I’m an AI system designed to understand your messages and help with medicines and healthcare tasks.",
            "I don’t have feelings or consciousness, but I can understand what you’re asking and help where I can.",
            "I’m a virtual assistant focused on medication management and health support.",
            "You’re talking to an AI assistant. My role is to help you manage medicines safely and consistently.",
            "I work by processing your questions and responding with helpful information related to health and medications.",
            "I’m software, not a human — but I’m designed to be clear, helpful, and reliable for health-related support.",
            "I’m an AI health assistant. I can help with reminders, medication tracking, and general guidance.",
            "I’m not able to think or feel like a person, but I can still help you with medication-related needs.",
            "This chat is automated, but I’m here to make managing your medications easier.",
            "I’m an AI assistant created to support people with their medicines and health routines.",
            "I don’t replace a doctor or a human, but I can help you stay organized and informed about your medications.",
            "I’m here to assist with health-related tasks like reminders, schedules, and basic questions.",
            "I understand your messages and respond based on what I’m designed to help with — mainly medications and healthcare support.",
            "I’m an AI assistant built to help with medication reminders and everyday health support."
        ]
        
        try:
            attachment = random.choice(BOT_IDENTITY_RESPONSES)
            logger.debug(f"Selected bot identity response: '{attachment[:50]}...'")
            
            # Only send text response since this is a simple identity message
            dispatcher.utter_message(attachment=attachment)
            
        except Exception as e:
            logger.error(f"Error in action_iamabot: {e}", exc_info=True)
            error_message = "I'm having trouble responding right now. I'm a chatbot here to help you!"
            attachment = send_response(error_message)
            dispatcher.utter_message(attachment=attachment)
        
        logger.debug("Bot identity query handled successfully")
        return []

class ActionAskMedicationName(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_name"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        "Asks medication name to the user"

        # Log recent slot events
        events = tracker.events
        logger.debug("🔍 Recent slot events:")
        for event in events[-20:]:
            if event.get('event') == 'slot':
                logger.debug(f"  {event.get('name')} = {event.get('value')}")
        
        prompt = tracker.get_slot("form_prompt")
        fuzzy_result = tracker.get_slot('fuzzy_result')
        original_input = tracker.get_slot('original_medication_input')

        logger.debug(f'Prompt: {prompt}')
        logger.debug(f'Fuzzy result: {fuzzy_result}')
        logger.debug(f'in action_ask_medication_name original input: {original_input}')
        
        if prompt == "multiple_meds":
            response_text = "Please provide only one medication at a time. Which one would you like to add?"
            dispatcher.utter_message(attachment={
                "query_response": response_text,
                "type": "text",
                "status": "success"
            })
            return [SlotSet("form_prompt", None)]
        
        elif prompt == "fuzzy_match" and fuzzy_result:
            dispatcher.utter_message(attachment={
                "query_response": fuzzy_result, 
                "type": "text", 
                "status": "question"
            })
            
            # CRITICAL FIX: Get the medication_entities from the tracker
            entities = tracker.latest_message.get('entities', [])
            medication_entities = [e.get('value') for e in entities if e.get('entity') == 'medication_name']
            
            events_to_return = [
                SlotSet("form_prompt", None),
                SlotSet("fuzzy_result", None)
            ]
            
            # If we have an entity, use it as original input
            if medication_entities:
                entity_value = medication_entities[0]
                logger.debug(f"SETTING original input from entity: {entity_value}")
                events_to_return.append(SlotSet("original_medication_input", entity_value))
            elif original_input:
                logger.debug(f"PRESERVING original input: {original_input}")
                events_to_return.append(SlotSet("original_medication_input", original_input))
            
            logger.debug(f"Returning events: {events_to_return}")
            return events_to_return
        else:
            builder = ResponseBuilder(tracker.sender_id, tracker)
            response = builder.build_response(intent="ask_medication_name")
            dispatcher.utter_message(attachment=response)

        return [SlotSet("form_prompt", None)]

class ActionAskMedicationType(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_type"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks medication type from the user"""

        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_medication_type")
        dispatcher.utter_message(attachment=response)
        return []

class ActionAskMedicationColour(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_colour"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks medication colour from the user"""

        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_medication_colour")
        dispatcher.utter_message(attachment=response)
        return []

class ActionAskMedicationDose(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_dose"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks medication dose from the user"""

        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_medication_dose")
        dispatcher.utter_message(attachment=response)
        return []

class ActionAskMedicationInstructions(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_instructions"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks medication instructions from the user"""
        
        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_medication_instructions")
        dispatcher.utter_message(attachment=response)
        return []

class ValidateMedicationForm(FormValidationAction):
    def __init__(self):
        # Load medications from CSV
        self.medications_df = pd.read_csv('data/medications.csv')
        self.KNOWN_MEDICATIONS = self.medications_df['medication_name'].tolist()

    def name(self) -> Text:
        return "validate_medication_form"
    
    def _fuzzy_match_medication_name(self, text: str) -> Optional[Union[str, Dict]]:
        """
        Perform fuzzy matching for medication names on the provided text.
        - 100% match: returns the medication name directly (no confirmation)
        - 65-99% match: asks for confirmation
        - Below 65: no match
        """
        try:
            from fuzzywuzzy import process, fuzz
            
            if not text or len(text) < 2:
                return None
                
            # Clean the input
            cleaned_text = text.lower().strip()
            
            # Get the top 3 matches
            matches = process.extract(
                cleaned_text,
                self.KNOWN_MEDICATIONS,
                scorer=fuzz.WRatio,
                limit=3
            )
            
            if not matches:
                return None
                
            # Log all top matches
            logger.debug(f"Top fuzzy matches: {[(m, s) for m, s in matches]}")
            
            # Get the best match
            best_match, best_score = matches[0]
            
            # CASE 1: Perfect match (100%) - accept immediately
            if best_score == 100:
                logger.debug(f"Perfect match found: {best_match} - accepting without confirmation")
                return best_match  # Return string directly
            
            # CASE 2: High confidence match (65-99%) - ask for confirmation
            if best_score >= 65:
                logger.debug(f"Match found: {best_match} ({best_score}) - asking for confirmation")
                return {
                    "type": "confirmation",
                    "question": f"Did you mean {best_match.title()}?",
                    "match": best_match,
                    "score": best_score,
                    "alternatives": [(m, s) for m, s in matches[1:]]  # Store alternatives for debugging
                }
            
            # CASE 3: Low confidence - no match
            logger.debug(f"Low confidence - best match: {best_match} ({best_score}) - no confirmation")
            
            # Check if there's a much better second match (rare case)
            if len(matches) > 1:
                second_match, second_score = matches[1]
                if second_score > best_score + 10:  # If second is much better
                    logger.debug(f"Second match significantly better: {second_match} ({second_score})")
                    return {
                        "type": "confirmation",
                        "question": f"Did you mean {second_match.title()}?",
                        "match": second_match,
                        "score": second_score
                    }
            
            return None
            
        except ImportError:
            logger.warning("fuzzywuzzy not installed - skipping fuzzy matching")
            return None
        except Exception as e:
            logger.error(f"Error in fuzzy matching: {e}")
            return None
        
    async def extract_medication_name(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict
    ) -> Dict[Text, Any]:
        """Extract medication name, handling confirmation responses."""
        
        # CRITICAL: Only run if we're currently asking for medication_name
        requested_slot = tracker.get_slot("requested_slot")
        if requested_slot != "medication_name":
            logger.debug(f"Skipping extract_medication_name - requested slot is '{requested_slot}'")
            return {}
        
        # Check if we're in confirmation mode
        pending = tracker.get_slot("pending_medication_confirmation")
        intent = tracker.latest_message.get('intent', {}).get('name')
        text = tracker.latest_message.get('text', '').lower().strip()
        
        # Get the original user input that triggered the confirmation
        original_input = tracker.get_slot("original_medication_input")
        
        logger.debug(f"extract_medication_name called - Pending: {pending}, Original: {original_input}, Intent: {intent}, Text: '{text}'")
        
        # FIRST: Check for direct medication name in the text (via entities)
        entities = tracker.latest_message.get('entities', [])
        medication_entities = [e.get('value') for e in entities if e.get('entity') == 'medication_name']
        
        # If we have a direct medication entity, use it
        if medication_entities:
            direct_med = medication_entities[0]
            logger.debug(f"Direct medication entity found: {direct_med}")

            # If we're in confirmation mode, clear pending
            if pending:
                return {
                    "medication_name": direct_med,
                    "pending_medication_confirmation": None
                }
            # Not in confirmation mode - save the entity as both name and original
            return {
                "medication_name": direct_med,
                "original_medication_input": direct_med  # 👈 Save original entity
            }
        
        # If we're in confirmation mode
        if pending:
            # User affirms - accept the pending medication
            if intent == "affirm" or text in ["yes", "yeah", "yep", "correct", "right", "sure"]:
                logger.debug(f"Confirmation detected - accepting medication: {pending}")
                
                return {
                    "medication_name": pending,
                    "pending_medication_confirmation": None
                }
            
            # User denies - use their original input instead
            elif intent == "deny" or text.startswith(("no", "nope", "not")):
                logger.debug(f"Denial detected - using original input: {original_input}")
                
                if original_input:
                    
                    return {
                        "medication_name": original_input,
                        "pending_medication_confirmation": None
                    }
                else:
                    # Fallback if original input is missing (shouldn't happen)
                    logger.warning("Original input missing but denial detected")
                    dispatcher.utter_message(attachment={
                        "query_response": "Okay, please tell me the correct medication name.",
                        "type": "text",
                        "status": "question"
                    })
                    return {"pending_medication_confirmation": None}
            
            # User said something else - stay in confirmation mode
            else:
                logger.debug(f"Unclear response in confirmation mode - re-asking")
                dispatcher.utter_message(attachment={
                    "query_response": f"Did you mean {pending}? Please answer yes or no.",
                    "type": "text",
                    "status": "question"
                })
                return {}
        
        # Not in confirmation mode - let normal extraction happen
        logger.debug("Not in confirmation mode - proceeding with normal extraction")
        return {}

    async def validate_medication_name(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        logger.debug('######### VALIDATING MEDICATION NAME #########')
        logger.debug(f"validate_medication_name called with slot_value: {slot_value}, original_medication_input value: {tracker.get_slot('original_medication_input')}")
        
        # CHECK 1: If we have a slot_value AND it came from a denial (original_input exists)
        original_input = tracker.get_slot('original_medication_input')
        intent = tracker.latest_message.get('intent', {}).get('name')
        text = tracker.latest_message.get('text', '').lower().strip()
        
        # If this is a denial response with a valid slot_value, accept it immediately
        if (intent == "deny" or text.startswith(("no", "nope", "not"))) and slot_value:
            logger.debug(f"Denial response with slot_value: {slot_value} - accepting without fuzzy matching")
            return {
                "medication_name": slot_value,
                "pending_medication_confirmation": None,
                "form_prompt": None,
                "fuzzy_result": None,
                "original_medication_input": None,
                "requested_slot": "medication_type"
            }
        
        # If this is an affirmation response with a valid slot_value, accept it immediately
        if (intent == "affirm" or text in ["yes", "yeah", "yep", "correct", "right", "sure"]) and slot_value:
            logger.debug(f"Affirm response with slot_value: {slot_value} - accepting without fuzzy matching")
            return {
                "medication_name": slot_value,
                "pending_medication_confirmation": None,
                "form_prompt": None,
                "fuzzy_result": None,
                "original_medication_input": None,
                "requested_slot": "medication_type"
            }
        
        # CHECK 2: If we're in confirmation mode with a confirmed value
        pending = tracker.get_slot("pending_medication_confirmation")
        if pending and slot_value:
            logger.debug(f"User confirmed medication: {slot_value} - accepting without fuzzy matching")
            return {
                "medication_name": slot_value,
                "pending_medication_confirmation": None,
                "form_prompt": None,
                "fuzzy_result": None,
                "original_medication_input": None,
                "requested_slot": "medication_type"
            }
        
        # Rest of logic only runs if NOT in confirmation mode
        user_text = tracker.latest_message.get('text', '').strip()
        user_text_lower = user_text.lower()
        
        # Rest of logic only runs if NOT in confirmation mode
        user_text = tracker.latest_message.get('text', '').strip()
        user_text_lower = user_text.lower()
        
        entities = tracker.latest_message.get('entities', [])
        medication_entities = [
            e.get('value') for e in entities if e.get('entity') == 'medication_name'
        ]
        
        # Detect multiple medication entities
        if len(medication_entities) > 1:
            logger.debug(f"Multiple medication entities detected: {medication_entities}")
            return {"medication_name": None, "form_prompt": "multiple_meds"}
        
        # Determine what text to run fuzzy matching on
        text_to_match = None
        
        if medication_entities:
            # Use the entity value for fuzzy matching
            text_to_match = medication_entities[0]
            logger.debug(f"Running fuzzy match on entity: '{text_to_match}'")
        else:
            # Use the full user text
            text_to_match = user_text_lower
            logger.debug(f"Running fuzzy match on full text: '{text_to_match}'")
        
        # Run fuzzy matching
        if text_to_match:
            fuzzy_result = self._fuzzy_match_medication_name(text_to_match)
            
            if fuzzy_result:
                if isinstance(fuzzy_result, dict) and fuzzy_result.get("type") == "confirmation":
                    logger.debug(f'Fuzzy logic: {fuzzy_result["question"]}')
                    logger.debug(f'Setting pending_medication_confirmation to: {fuzzy_result["match"].title()}')
                    logger.debug(f'in validate_medication_name 2 original input: {tracker.get_slot("original_medication_input")}')
                    result = {
                        "medication_name": None, 
                        "form_prompt": "fuzzy_match",
                        "fuzzy_result": fuzzy_result["question"],
                        "pending_medication_confirmation": fuzzy_result["match"].title(),
                        "original_medication_input": original_input
                    }
                    logger.debug(f"RETURNING from validate with original_input={original_input}")
                    logger.debug(f"FULL RETURN DICT: {result}")
                    return result
                elif isinstance(fuzzy_result, str):
                    logger.debug(f"Fuzzy match accepted: {fuzzy_result}")
                    return {
                        "medication_name": fuzzy_result.title(),
                        "requested_slot": "medication_type"
                    }
        
        # Fallback to entity value if no fuzzy match
        if medication_entities:
            medication_name_value = medication_entities[0]
            logger.debug(f"Accepting entity value as fallback: {medication_name_value}")
            
            cleaned_name = medication_name_value.strip()
            if len(cleaned_name) < 2:
                return {"medication_name": None}
                
            capitalized_name = cleaned_name.title()
            return {
                "medication_name": capitalized_name,
                "original_medication_input": original_input,  # 👈 Save original entity
                "requested_slot": "medication_type"
            }
        
        # Handle slot_value if present
        if slot_value and isinstance(slot_value, str):
            cleaned = slot_value.strip()
            if len(cleaned) >= 2:
                logger.debug(f"Accepting slot_value: {cleaned}")
                return {
                    "medication_name": cleaned.title(),
                    "original_medication_input": cleaned,  # 👈 Save original slot value
                    "requested_slot": "medication_type"
                }
        
        logger.debug("No valid medication name found")
        return {"medication_name": None}
    
    async def validate_medication_type(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        
        logger.debug('######### VALIDATING MEDICATION TYPE #########')

        if not slot_value or len(slot_value.strip()) < 2:
            return {"medication_type": None}
        
        return {
            "medication_type": slot_value.strip(),
            "requested_slot": "medication_colour"
            }

    async def validate_medication_colour(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate medication colour from categorical values."""
        
        logger.debug('######### VALIDATING MEDICATION COLOUR #########')

        if not slot_value:
            return {"medication_colour": None}
        
        valid_colours = [
            "red", "blue", "white", "yellow", "green", 
            "orange", "purple", "pink", "black", "grey", "brown"
        ]
        
        colour_lower = slot_value.lower().strip()
        
        if colour_lower in valid_colours:
            return {
                "medication_colour": colour_lower,
                "requested_slot": "medication_dose"}
        else:
            return {"medication_colour": None}

    async def validate_medication_dose(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        
        logger.debug('######### VALIDATING MEDICATION DOSE #########')
        if tracker.latest_message.get("entities"):
            for ent in tracker.latest_message["entities"]:
                if ent["entity"] == "quantity":
                    return {"medication_dose": ent["value"]}
        return {}
        

    async def validate_medication_instructions(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Handle medication instructions."""
        
        logger.debug('######### VALIDATING MEDICATION INSTRUCTIONS #########')
        
        # If user explicitly says "none"
        if slot_value and slot_value.lower().strip() == "none":
            result = {
                "medication_instructions": "No instructions provided",
                "requested_slot": None  # Form is complete
            }
            logger.debug(f"Returning (none case): {result}")
            return result
        
        # If user provides instructions
        if slot_value and slot_value.strip():
            result = {
                "medication_instructions": slot_value.strip()
            }
            logger.debug(f"Returning (normal case): {result}")
            return result
        
        # If empty, ask for confirmation
        result = {"medication_instructions": None}
        logger.debug(f"Returning (empty case): {result}")
        return result

class ActionCancelForm(BaseAction):
    """Cancels the active form."""

    def name(self) -> Text:
        return "action_cancel_form"
    
    def run_with_slots(self, dispatcher, tracker, domain):

        logger.debug('CANCEL FORM CALLED')

        active_loop = tracker.active_loop.get('name') if tracker.active_loop else None
        logger.debug(f'Active loop: "{active_loop}"')
        
        if active_loop == "medication_form":
            logger.debug('Cancelling medication form')
            response = "Okay. I've stopped adding the medication. What would you like to do next?"
            attachment = {
                "query_response": response,
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            
            return [
                ActiveLoop(None),
                SlotSet("requested_slot", None),
                SlotSet("medication_name", None),
                SlotSet("medication_type", None),
                SlotSet("medication_colour", None),
                SlotSet("medication_dose", None),
                SlotSet("medication_instructions", None),
                SlotSet("pending_medication_confirmation", None),
                SlotSet("fuzzy_result", None),
                SlotSet("original_medication_input", None)
            ]
            
        elif active_loop == "refill_form":
            logger.debug('Cancelling refill form')
            response = "Okay. I've stopped adding the refill information. What would you like to do next?"
            attachment = {
                "query_response": response,
                "data": [],
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            
            return [
                ActiveLoop(None),
                SlotSet("requested_slot", None),
                SlotSet("stock_level", None),
                SlotSet("refill_day", None)
            ]
            
        elif active_loop == "reminder_form":
            logger.debug('Cancelling reminder form')
            response = "Okay. I have I've stopped adding the reminder. What would you like to do next?"
            attachment = {
                "query_response": response,
                "data": [],
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            
            return [
                ActiveLoop(None),
                SlotSet("requested_slot", None),
                SlotSet("frequency", None),
                SlotSet("frequency", None),
                SlotSet("per_day_frequency", None),
                SlotSet("quantity", None),
                SlotSet("reminder_time", None),
                SlotSet("alert_type", None),
                SlotSet("reminder_day", None)
            ]
            
        else:
            logger.debug(f'No matching form for active_loop: "{active_loop}"')
            response = "Okay. Cancelled."
            attachment = {
                "query_response": response,
                "data": [],
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            
            return [
                ActiveLoop(None),
                SlotSet("requested_slot", None)
            ]

class ActionSubmitMedicationForm(BaseAction):
    """Submits medication form and moves to refill."""

    def name(self) -> Text:
        return "action_submit_medication_form"

    def run_with_slots(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]
    ) -> List[SlotSet]:

        logger.debug("="*80)
        logger.debug("ACTION_SUBMIT_MEDICATION_FORM IS RUNNING!")
        logger.debug(f"Latest intent: {tracker.latest_message.get('intent', {}).get('name')}")
        logger.debug("="*80)

        # Get raw slot values
        raw_name = tracker.get_slot("medication_name") or ""
        raw_type = tracker.get_slot("medication_type") or ""
        raw_colour = tracker.get_slot("medication_colour")
        raw_dose = tracker.get_slot("medication_dose") or ""
        raw_instructions = tracker.get_slot("medication_instructions") or ""

        # Capitalize medication name (title case for multi-word names)
        capitalized_name = raw_name.title()
        logger.debug(f"Capitalized medication name: '{raw_name}' -> '{capitalized_name}'")
        
        # Capitalize medication type (just first letter since it's usually a single word)
        if raw_type:
            capitalized_type = raw_type[0].upper() + raw_type[1:].lower()
        else:
            capitalized_type = ""
        logger.debug(f"Capitalized medication type: '{raw_type}' -> '{capitalized_type}'")
        
        # Capitalize instructions (first letter of each sentence)
        if raw_instructions and raw_instructions.lower() != "none":
            # Simple capitalization - first letter of the string
            capitalized_instructions = raw_instructions[0].upper() + raw_instructions[1:].lower()
        else:
            capitalized_instructions = raw_instructions

        # Collect medication data with capitalized values
        medmanager = MedicationManager(token=tracker.sender_id)
        colour = medmanager.color_to_hex(raw_colour)
        logger.debug(f"Converted colour '{raw_colour}' to hex: {colour}")

        medication_data = {
            "name": capitalized_name,  # Use capitalized name
            "medication_type": capitalized_type,  # Use capitalized type
            "colour": colour,
            "dose": raw_dose,  # Keep dose as-is (might have numbers and units)
            "instructions": capitalized_instructions or "",
            "stock_level": 0,
            "order": 0,
            "status": 1
        }

        logger.info(f"Medication data ready: {medication_data}")

        # Save medication
        medmanager = MedicationManager(token=tracker.sender_id)
        success, message, medication_id = medmanager.save_medication(medication_data)

        # Initialize ResponseBuilder with sender token
        builder = ResponseBuilder(token=tracker.sender_id)

        if not success: 
            response = "Sorry, I couldn't save your medication. Would you like to try again?"
            attachment = {
            "query_response": response,
            "type": "text",
            "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(None),
                SlotSet("current_step", None),
                SlotSet("medication_name", None),
                SlotSet("medication_type", None),
                SlotSet("medication_colour", None),
                SlotSet("medication_dose", None),
                SlotSet("medication_instructions", None),
                SlotSet("form_prompt", None),
                SlotSet("fuzzy_result", None),
                SlotSet("original_medication_input", None),
                SlotSet("pending_medication_confirmation", None)
            ]
        
        # Use ResponseBuilder for success + refill prompt
        response = builder.build_response(intent='submit_medication')
        dispatcher.utter_message(attachment=response)

        return [
            ActiveLoop(None),  # Deactivate medication form
            SlotSet("current_step", "ask_refill"),
            SlotSet("user_medication_id", medication_id),
            # Clear all medication slots for next time
            SlotSet("medication_name", None),
            SlotSet("medication_type", None),
            SlotSet("medication_colour", None),
            SlotSet("medication_dose", None),
            SlotSet("medication_instructions", None),
            SlotSet("form_prompt", None),
            SlotSet("fuzzy_result", None),
            SlotSet("original_medication_input", None),
            SlotSet("pending_medication_confirmation", None)
        ]
    
class ActionHandleFormInterruption(BaseAction):
    def name(self) -> Text:
        return "action_handle_form_interruption"

    def run_with_slots(self, dispatcher, tracker, domain):

        intent = tracker.latest_message.get("intent", {}).get("name")

        if intent == "deny":
            logger.debug("✅ User denied cancellation - returning to form")

            # Get the current requested slot
            requested_slot = tracker.get_slot("requested_slot")

            # Re-activate the form explicitly
            return [
                ActiveLoop("medication_form"),  # Reactivate the form
                FollowupAction("validate_medication_form")  # Run validation
            ]
        
        # Otherwise treat as interruption
        builder = ResponseBuilder(tracker.sender_id, tracker)

        if intent == "greet":
            intent = "greet-form"
            response = builder.build_response(intent)
        else:
            intent = "form-interrupt"
            response = builder.build_response(intent)

        logger.debug(f'Response: {response}')
        dispatcher.utter_message(attachment=response)

        return []

class ActionHandleRefillDeny(BaseAction):
    def name(self) -> Text:
        return "action_handle_refill_deny"

    def run_with_slots(self, dispatcher, tracker, domain):

        intent = tracker.latest_message.get("intent", {}).get("name")
        logger.debug(f"ActionHandleRefillDeny called with intent: {intent}")

        if intent == "deny":
            logger.debug("User denied refill - asking about reminder")
        
            # Otherwise treat as interruption
            builder = ResponseBuilder(tracker.sender_id, tracker)
            response = builder.build_response('refill-deny')
            
            dispatcher.utter_message(attachment=response)

            # Set a slot to track that we're now in reminder-asking phase
            return [SlotSet("current_step", "ask_reminder")]

        return []

class ActionAskStockLevel(BaseAction):
    def name(self) -> Text:
        return "action_ask_stock_level"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        "Asks refill stock level to the user"

        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_stock_level")
        dispatcher.utter_message(attachment=response)
        return []

class ActionAskRefillInDays(BaseAction):
    def name(self) -> Text:
        return "action_ask_refill_day"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        "Asks refill days to the user"

        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_refill_day")
        dispatcher.utter_message(attachment=response)
        return []
    
class ValidateRefillForm(FormValidationAction):
    """Validates slots for refill form."""
    
    def name(self) -> Text:
        return "validate_refill_form"
    
    async def required_slots(
        self,
        domain_slots: List[Text],
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Text]:
        """Determine which slots are still required."""
        # DEBUG: Log current state
        logger.debug("="*80)
        logger.debug("REQUIRED_SLOTS DEBUG:")
        logger.debug(f"Active loop: {tracker.active_loop}")
        logger.debug(f"Requested slot: {tracker.get_slot('requested_slot')}")
        logger.debug(f"Latest intent: {tracker.latest_message.get('intent', {}).get('name')}")
        logger.debug(f"Latest text: '{tracker.latest_message.get('text')}'")
        logger.debug("="*80)
        
        # List of all slots in order
        all_slots = [
            "stock_level",
            "refill_day"
        ]
        
        # Check which slots are still empty
        required = []
        for slot in all_slots:
            slot_value = tracker.get_slot(slot)
            if slot_value is None or slot_value == "":
                required.append(slot)
            else:
                logger.debug(f"Slot '{slot}' is already filled: {slot_value}")
        
        logger.debug(f"Required slots: {required}")
        return required

    async def validate_stock_level(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate stock level, handling wrong intent predictions."""
        
        intent = tracker.latest_message.get("intent", {}).get("name")
        text = tracker.latest_message.get("text", "")
        
        logger.debug(f"Validating stock level with intent: {intent}, value: {slot_value}")
        
        # Try to extract number from text
        import re
        numbers = re.findall(r'\d+', text)
        
        # MINIMAL UPDATE: If no numbers found, reject and ask again
        if not numbers:
            # dispatcher.utter_message(
            #     attachment={
            #         "query_response": "Please enter a valid number for stock level (e.g., 15, 30, 60).",
            #         "type": "text",
            #         "status": "success"
            #     }
            # )
            return {"stock_level": None}
        
        # If we have numbers, use the first one
        try:
            stock = int(numbers[0])
            
            if stock < 0:
                # dispatcher.utter_message(
                #     attachment={
                #         "query_response": "Please enter a positive number for stock level.",
                #         "type": "text",
                #         "status": "success"
                #     }
                # )
                return {"stock_level": None}
            
            if stock < 7:
                # dispatcher.utter_message(
                #     attachment={
                #         "query_response": f"Only {stock} left? You might need a refill soon!",
                #         "type": "text",
                #         "status": "success"
                #     }
                # )
            
                return {"stock_level": stock}
            
        except (ValueError, TypeError):
            # dispatcher.utter_message(
            #     attachment={
            #         "query_response": "Please enter a valid number for stock level.",
            #         "type": "text",
            #         "status": "success"
            #     }
            # )
            return {"stock_level": None}

    async def validate_refill_day(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        
        text = tracker.latest_message.get("text", "")
        entities = tracker.latest_message.get("entities", [])
        
        logger.debug(f"Validating refill_day with text: '{text}'")
        logger.debug(f"Entities found: {entities}")
        
        # FIX: Check if there's a frequency entity that should map to refill_day
        for entity in entities:
            if entity.get("entity") == "frequency":
                frequency_value = entity.get("value")
                logger.debug(f"Found frequency entity: '{frequency_value}' - mapping to refill_day")
                
                # Extract number from the frequency
                import re
                numbers = re.findall(r'\d+', frequency_value)
                if numbers:
                    days = int(numbers[0])
                    if days > 0 and days <= 365:
                        return {"refill_day": days}
        
        # Also check the raw text for numbers
        import re
        numbers = re.findall(r'\d+', text)
        if numbers:
            days = int(numbers[0])
            if days > 0 and days <= 365:
                return {"refill_day": days}
        
        # If no valid number found
        dispatcher.utter_message(
            attachment={
                "query_response": "Please enter a valid number of days (e.g., 7, 30, 90).",
                "type": "text",
                "status": "success"
            }
        )
        return {"refill_day": None}
      
class ActionSubmitRefillForm(BaseAction):
    """Submits refill form and moves to reminders."""
    
    def name(self) -> Text:
        return "action_submit_refill_form"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                       tracker: Tracker,
                       domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.debug("="*80)
        logger.debug("ACTION_SUBMIT_REFILL_FORM IS RUNNING!")
        logger.debug(f"Latest intent: {tracker.latest_message.get('intent', {}).get('name')}")
        logger.debug("="*80)

        # Helper function to extract refill days 
        def extract_refill_days(value):
            """
            Extract numeric value and convert to days if needed.
            Supports:
            - Numeric: 7, 14
            - Text: "7 days", "2 weeks", "1.5 months"
            - Words: "one week", "two months"
            - Short forms: "weekly", "monthly"
            """

            if value is None:
                return None

            # If already numeric → assume days
            if isinstance(value, (int, float)):
                return int(value)

            if isinstance(value, str):
                import re

                value = value.lower().strip()

                # Word-to-number mapping
                word_to_number = {
                    "one": 1,
                    "two": 2,
                    "three": 3,
                    "four": 4,
                    "five": 5,
                    "six": 6,
                    "seven": 7,
                    "eight": 8,
                    "nine": 9,
                    "ten": 10,
                    "a": 1,
                    "an": 1
                }

                # Handle "weekly" / "monthly"
                if "weekly" in value:
                    return 7
                if "monthly" in value:
                    return 30

                # Extract numeric digits (supports decimals)
                match = re.search(r'(\d+(?:\.\d+)?)', value)

                if match:
                    number = float(match.group(1))
                else:
                    # Try extracting number words
                    for word, num in word_to_number.items():
                        if word in value:
                            number = num
                            break
                    else:
                        logger.warning(f"No number found in refill_day: {value}")
                        return None

                # Determine unit
                if "week" in value:
                    return int(number * 7)

                elif "month" in value:
                    return int(number * 30)

                elif "day" in value:
                    return int(number)

                else:
                    # If no unit provided → assume days
                    return int(number)

            logger.warning(f"Unsupported refill_day type: {type(value)}")
            return None

        # Get raw slot values
        raw_stock_level = tracker.get_slot("stock_level")
        raw_refill_day = tracker.get_slot("refill_day")
        user_medication_id = tracker.get_slot("user_medication_id")
        
        logger.debug(f"Raw stock_level: '{raw_stock_level}' (type: {type(raw_stock_level)})")
        logger.debug(f"Raw refill_day: '{raw_refill_day}' (type: {type(raw_refill_day)})")
        
        # Extract numbers
        stock_level = extract_refill_days(raw_stock_level)
        refill_day = extract_refill_days(raw_refill_day)
        
        logger.debug(f"Extracted stock_level: {stock_level}")
        logger.debug(f"Extracted refill_day: {refill_day}")

        # Validate we have valid numbers
        if stock_level is None:
            dispatcher.utter_message(
                attachment={
                    "query_response": "I couldn't understand your stock level. Please try again.",
                    "type": "text",
                    "status": "error"
                }
            )
            return [
                ActiveLoop(None),
                SlotSet("current_step", None)
            ]
        
        logger.debug(f'ActiveLoop: {ActiveLoop}')
        if refill_day is None:
            dispatcher.utter_message(
                attachment={
                    "query_response": "I couldn't understand when you need a refill. Please try again.",
                    "type": "text",
                    "status": "error"
                }
            )
            return [
                ActiveLoop(None),
                SlotSet("current_step", None)
            ]

        # Collect cleaned refill data
        refill_data = {
            "user_medication_id": user_medication_id,
            "stock_level": stock_level,
            "refill_day": refill_day
        }

        logger.debug(f"Cleaned refill_data: {refill_data}")

        # Save refill data
        medmanager = MedicationManager(token=tracker.sender_id)
        success, message = medmanager.save_refill(refill_data)

        if not success: 
            response = "Sorry, I couldn't save your refill information. Would you like to try again?"
            attachment = {
                "query_response": response,
                "type": "text",
                "status": "error"
            }
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(None),
                SlotSet("current_step", None)
            ]
        
        # Success - move to reminders
        builder = ResponseBuilder(token=tracker.sender_id)
        response = builder.build_response(intent='submit_refill')
        dispatcher.utter_message(attachment=response)
        
        return [
            ActiveLoop(None),  # Deactivate refill form
            SlotSet("current_step", "ask_reminder"),
            SlotSet('stock_level', None),
            SlotSet('refill_day', None)
        ]

class ActionHandleReminderDeny(BaseAction):
    def name(self) -> Text:
        return "action_handle_reminder_deny"

    def run_with_slots(self, dispatcher, tracker, domain):

        intent = tracker.latest_message.get("intent", {}).get("name")
        logger.debug(f"ActionHandleReminderDeny called with intent: {intent}")

        if intent == "deny" :
            logger.debug("User denied reminder -- Asking what else can I do")
        
            # Otherwise treat as interruption
            builder = ResponseBuilder(tracker.sender_id, tracker)
            response = builder.build_response('reminder-deny')
            
            dispatcher.utter_message(attachment=response)

            # Set a slot to track that we're now in reminder-asking phase
            return [SlotSet("current_step", None)]

        return []
    
class ActionAskFrequency(BaseAction):
    def name(self) -> Text:
        return "action_ask_frequency"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks frequency from the user"""
        
        prompt = tracker.get_slot('form_prompt')

        if prompt ==  "deny_redo":
            response = 'Okay, What would you like to do next?'
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [SlotSet("form_prompt", None),
                    ActiveLoop(None)]
        
        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_frequency")
        dispatcher.utter_message(attachment=response)
        return []

class ActionAskPerDayFrequency(BaseAction):
    def name(self) -> Text:
        return "action_ask_per_day_frequency"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        """Ask the user how many times a day to remind, with buttons."""

        # The message
        response = "How many times a day should I remind you?"
        
        # Buttons
        buttons = [
            {"title": "Once", "payload": "/inform{\"per_day_frequency\":\"once\"}"},
            {"title": "Twice", "payload": "/inform{\"per_day_frequency\":\"twice\"}"},
            {"title": "Thrice", "payload": "/inform{\"per_day_frequency\":\"thrice\"}"},
        ]

        attachment = send_response_with_buttons(response, buttons)
        # Send the message with buttons
        dispatcher.utter_message(attachment=attachment)

        return []
    
class ActionAskQuantity(BaseAction):
    def name(self) -> Text:
        return "action_ask_quantity"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks Quantity from the user"""
        
        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_quantity")
        dispatcher.utter_message(attachment=response)
        return []
    
class ActionAskReminderTime(BaseAction):
    def name(self) -> Text:
        return "action_ask_reminder_time"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks Reminder time from the user"""
        
        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_reminder_time")
        dispatcher.utter_message(attachment=response)
        return []

class ActionAskAlertType(BaseAction):
    def name(self) -> Text:
        return "action_ask_alert_type"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks Reminder time from the user"""
        
        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_alert_type")
        dispatcher.utter_message(attachment=response)
        return []
    
class ActionAskReminderDay(BaseAction):
    def name(self) -> Text:
        return "action_ask_reminder_day"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks Reminder time from the user"""
        
        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_reminder_day")
        dispatcher.utter_message(attachment=response)
        return []
    
class ValidateReminderForm(FormValidationAction):
    """Validates slots for reminder form with smart dependency handling."""
    
    def name(self) -> Text:
        return "validate_reminder_form"

    async def validate_frequency(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate and normalize frequency (e.g., '30 days', '2 weeks')."""
        requested_slot = tracker.get_slot('requested_slot')
        if requested_slot != "frequency":
            return None
        
        current_step = tracker.get_slot('current_step')
        intent = tracker.latest_message.get("intent", {}).get("name")
        
        
        if current_step == "pending_confirmation":
            if intent == "affirm":
                return {'requested_slot': 'frequency'}
            
            elif intent == "deny":
                return {"form_prompt": "deny_redo"}
            
        if not slot_value:
            return {"frequency": None}

        value = str(slot_value).lower().strip()

        # Handle "a week", "a month"
        value = value.replace("a ", "1 ")

        # Regex: number + time unit
        pattern = r"^(\d+)\s*(day|days|week|weeks|month|months|year|years)$"
        match = re.match(pattern, value)

        # if not match:
        #     dispatcher.utter_message(text="Please enter something like '30 days', '2 weeks', or '1 month'.")
        #     return {"frequency": None}

        number = int(match.group(1))
        unit = match.group(2)

        # if number <= 0:
        #     dispatcher.utter_message(text="The duration must be greater than 0.")
        #     return {"frequency": None}

        # Normalize plural properly
        if number == 1:
            unit = unit.rstrip("s")  # singular
        else:
            if not unit.endswith("s"):
                unit += "s"

        normalized = f"{number} {unit}"

        return {"frequency": normalized}
        
    async def validate_quantity(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate quantity of medication per dose."""
        if slot_value is None:
            return {"quantity": None}
        
        try:
            # Extract number
            import re
            if isinstance(slot_value, str):
                match = re.search(r'(\d+)', slot_value)
                if match:
                    quantity = int(match.group(1))
                else:
                    # Try word to number
                    word_to_number = {
                        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                        "a": 1, "an": 1, "single": 1, "double": 2, "triple": 3
                    }
                    quantity = word_to_number.get(slot_value.lower(), None)
                    if quantity is None:
                        raise ValueError
            else:
                quantity = int(slot_value)
            
            
            # Get medication dose for context
            medication_dose = tracker.get_slot("medication_dose")
            # if medication_dose:
            #     dispatcher.utter_message(f"Perfect! {quantity} pill(s) of {medication_dose} each time.")
            # else:
            #     dispatcher.utter_message(f"Got it! {quantity} pill(s) each time.")
            
            return {"quantity": quantity}
            
        except (ValueError, TypeError):
            # dispatcher.utter_message(
            #     "Please enter a valid number of pills/units. "
            #     "For example: '1 pill', '2 tablets', or just '1'."
            # )
            return {"quantity": None}
    
    # Mappings for spelled-out hours and minutes
    NUMBER_WORDS = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12
    }

    MINUTE_WORDS = {
        "o'clock": 0, "zero": 0, "five": 5, "ten": 10, "fifteen": 15,
        "twenty": 20, "twenty-five": 25, "thirty": 30, "thirty-five": 35,
        "forty": 40, "forty-five": 45, "fifty": 50, "fifty-five": 55
    }

    async def validate_reminder_time(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate and normalize reminder_time to 24-hour HH:MM format."""

        if not slot_value:
            return {"reminder_time": None}

        # Ensure we always work with a list
        times = slot_value if isinstance(slot_value, list) else [slot_value]
        normalized_times: List[str] = []

        for time_str in times:
            value = str(time_str).lower().strip()

            # ------------------------
            # Special phrases
            # ------------------------
            if value == "12 noon":
                normalized_times.append("12:00")
                continue

            # Friendly phrases (e.g., "6 in the morning")
            friendly_match = re.match(r"(\d{1,2})\s+in the\s+(morning|afternoon|evening|night)", value)
            if friendly_match:
                hour = int(friendly_match.group(1))
                period = friendly_match.group(2)

                if period == "morning":
                    if hour == 12:
                        hour = 0
                elif period in ["afternoon", "evening", "night"]:
                    if hour != 12:
                        hour += 12

                normalized_times.append(f"{hour:02d}:00")
                continue

            # 12-hour numeric (e.g., 8 am, 8:30 pm)
            match_12h = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", value)
            if match_12h:
                hour = int(match_12h.group(1))
                minute = int(match_12h.group(2)) if match_12h.group(2) else 0
                period = match_12h.group(3)

                if period == "pm" and hour != 12:
                    hour += 12
                if period == "am" and hour == 12:
                    hour = 0

                normalized_times.append(f"{hour:02d}:{minute:02d}")
                continue

            # 24-hour numeric (e.g., 20:30)
            match_24h = re.match(r"^(\d{2}):(\d{2})$", value)
            if match_24h:
                hour = int(match_24h.group(1))
                minute = int(match_24h.group(2))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    normalized_times.append(f"{hour:02d}:{minute:02d}")
                    continue

            # ------------------------
            # Spelled-out numbers (e.g., "eight thirty am")
            # ------------------------
            spelled_match = re.match(
                r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
                r"(?: (o'clock|zero|five|ten|fifteen|twenty|twenty-five|thirty|thirty-five|forty|forty-five|fifty|fifty-five))?\s*(am|pm)",
                value
            )
            if spelled_match:
                hour_word = spelled_match.group(1)
                minute_word = spelled_match.group(2) or "o'clock"
                period = spelled_match.group(3)

                hour = NUMBER_WORDS.get(hour_word, None)
                minute = MINUTE_WORDS.get(minute_word, None)
                if hour is not None and minute is not None:
                    if period == "pm" and hour != 12:
                        hour += 12
                    if period == "am" and hour == 12:
                        hour = 0
                    normalized_times.append(f"{hour:02d}:{minute:02d}")
                    continue

        if not normalized_times:
            dispatcher.utter_message(
                text="Please enter a valid time like '8 am', '20:30', '6 in the morning', or 'eight thirty am'."
            )
            return {"reminder_time": None}

        # Remove duplicates while preserving order
        seen = set()
        normalized_times = [t for t in normalized_times if not (t in seen or seen.add(t))]

        return {"reminder_time": normalized_times}
    
    async def validate_per_day_frequency(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate per-day frequency (once, twice, thrice)."""
        logger.debug('VALIDATING PER DAY FREQUENCY')
        if not slot_value:
            return {"per_day_frequency": None}

        value = str(slot_value).lower().strip()

        valid_values = {
            "once": "once",
            "twice": "twice",
            "thrice": "thrice",
        }

        if value in valid_values:
            return {"per_day_frequency": valid_values[value]}

        # dispatcher.utter_message(
        #     text="Please choose once, twice, or thrice per day."
        # )
        return {"per_day_frequency": None}

    async def validate_reminder_day(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate reminder days (only for weekly frequency)."""
        
        import re

        if not slot_value:
            return {"reminder_day": None}
        
        # If already a list
        if isinstance(slot_value, list):
            # Validate each day
            valid_days = self._validate_day_list(slot_value)
            if valid_days:
                days_str = ", ".join(valid_days)
                # dispatcher.utter_message(f"Perfect! Weekly reminders on: {days_str}")
                return {"reminder_day": valid_days}
        
        # Parse day input
        days_input = str(slot_value)
        parsed_days = self._parse_days_input(days_input)
        
        if parsed_days:
            days_str = ", ".join(parsed_days)
            # dispatcher.utter_message(f"Great! Reminders on: {days_str}")
            return {"reminder_day": parsed_days}
        else:
            # dispatcher.utter_message(
            #     "Please specify days of the week. "
            #     "Examples: 'Monday, Wednesday, Friday' or 'everyday' or 'weekdays'."
            # )
            return {"reminder_day": None}
    
    async def validate_alert_type(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate alert type (alarm/voice)."""
        if not slot_value:
            return {"alert_type": None}
        
        valid_types = ["alarm", "voice"]
        slot_value_lower = str(slot_value).lower().strip()
        
        # Map variations
        type_mapping = {
            "sound": "alarm",
            "notification": "alarm",
            "ring": "alarm",
            "bell": "alarm",
            "speak": "voice",
            "spoken": "voice",
            "verbal": "voice",
            "audio": "voice"
        }
        
        if slot_value_lower in type_mapping:
            slot_value_lower = type_mapping[slot_value_lower]
        
        if slot_value_lower in valid_types:
            # message = f"Perfect! I'll use {slot_value_lower} alerts for your reminders."
            # dispatcher.utter_message(message)
            return {"alert_type": slot_value_lower}
        else:
            # dispatcher.utter_message(
            #     "Please choose: alarm (sound notification) or voice (spoken reminder)."
            # )
            return {"alert_type": None}
    
    # Helper methods
    def _parse_time_input(self, time_input: str) -> Optional[str]:
        """Parse time input into HH:MM:SS format."""
        import re
        from datetime import datetime
        
        # Common patterns
        patterns = [
            (r'(\d{1,2}):(\d{2})\s*(am|pm)', '%I:%M %p'),  # 8:30 AM
            (r'(\d{1,2})\s*(am|pm)', '%I %p'),            # 8 AM
            (r'(\d{1,2}):(\d{2})', '%H:%M'),              # 14:30
            (r'(\d{1,2})', '%H'),                         # 14
        ]
        
        for pattern, time_format in patterns:
            match = re.match(pattern, time_input, re.IGNORECASE)
            if match:
                try:
                    # Reconstruct time string for parsing
                    if 'am' in time_input.lower() or 'pm' in time_input.lower():
                        # 12-hour format
                        time_str = time_input
                    else:
                        # 24-hour format
                        time_str = f"{match.group(1)}:{match.group(2) if len(match.groups()) > 1 else '00'}"
                    
                    # Parse and format
                    dt = datetime.strptime(time_str, time_format)
                    return dt.strftime('%H:%M:%S')
                except ValueError:
                    continue
        
        return None
    
    def _parse_days_input(self, days_input: str) -> List[str]:
        """Parse days input into list of day names."""
        
        
        days_input = days_input.lower()
        day_mapping = {
            "monday": "monday", "mon": "monday",
            "tuesday": "tuesday", "tue": "tuesday", "tues": "tuesday",
            "wednesday": "wednesday", "wed": "wednesday",
            "thursday": "thursday", "thu": "thursday", "thur": "thursday",
            "friday": "friday", "fri": "friday",
            "saturday": "saturday", "sat": "saturday",
            "sunday": "sunday", "sun": "sunday"
        }
        
        # Special cases
        if "everyday" in days_input or "daily" in days_input:
            return ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        
        if "weekdays" in days_input:
            return ["monday", "tuesday", "wednesday", "thursday", "friday"]
        
        if "weekend" in days_input:
            return ["saturday", "sunday"]
        
        # Parse individual days
        days = []
        for day_name, canonical_name in day_mapping.items():
            if re.search(r'\b' + re.escape(day_name) + r'\b', days_input):
                if canonical_name not in days:
                    days.append(canonical_name)
        
        return days
    
    def _validate_day_list(self, day_list: List[str]) -> List[str]:
        """Validate and canonicalize list of days."""
        canonical_days = []
        day_canonical = {
            "monday": "monday", "mon": "monday",
            "tuesday": "tuesday", "tue": "tuesday", "tues": "tuesday",
            "wednesday": "wednesday", "wed": "wednesday",
            "thursday": "thursday", "thu": "thursday", "thur": "thursday",
            "friday": "friday", "fri": "friday",
            "saturday": "saturday", "sat": "saturday",
            "sunday": "sunday", "sun": "sunday"
        }
        
        for day in day_list:
            day_lower = str(day).lower()
            if day_lower in day_canonical:
                canonical = day_canonical[day_lower]
                if canonical not in canonical_days:
                    canonical_days.append(canonical)
        
        return canonical_days
    
import re
from datetime import datetime

class ActionSubmitReminderForm(BaseAction):
    """Submits reminder form and saves to API."""
    
    def name(self) -> Text:
        return "action_submit_reminder_form"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                       tracker: Tracker,
                       domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        import re

        logger.debug("RUNNING ACTION SUBMIT REMINDER FORM")
        logger.debug(f"Latest intent: {tracker.latest_message.get('intent', {}).get('name')}")
        logger.debug("="*80)
        
        user_medication_id = tracker.get_slot("user_medication_id")
        frequency = tracker.get_slot("frequency")
        per_day_frequency = tracker.get_slot("per_day_frequency")
        quantity = tracker.get_slot("quantity")
        reminder_time = tracker.get_slot("reminder_time")
        alert_type = tracker.get_slot("alert_type")
        reminder_day = tracker.get_slot("reminder_day")

        # -----------------------------
        # Extract frequency_period/type
        # -----------------------------
        frequency_period = None
        frequency_type = None

        if frequency:
            frequency = str(frequency).lower().strip()
            match = re.match(r"(\d+)\s*(day|days|week|weeks|month|months|year|years)", frequency)
            if match:
                frequency_period = int(match.group(1))
                frequency_type = match.group(2)
                unit_mapping = {
                    "days": "day",
                    "weeks": "week",
                    "months": "month",
                    "years": "year"
                }
                frequency_type = unit_mapping.get(frequency_type, frequency_type)

        # -----------------------------
        # Clean reminder_time
        # -----------------------------
        from datetime import datetime

        cleaned_times = []
        if reminder_time:
            if not isinstance(reminder_time, list):
                reminder_time = [reminder_time]

            for t in reminder_time:
                t = t.strip().lower()
                logger.debug(f"Cleaning time: '{t}'")
                
                # 🔥 NEW: Handle natural language time expressions
                original_t = t
                
                # Map common time expressions to hours
                time_expressions = {
                    r'\bmorning\b': 9,
                    r'\bafternoon\b': 14,
                    r'\bevening\b': 18,
                    r'\bnight\b': 21,
                    r'\bmidnight\b': 0,
                    r'\bnoon\b': 12,
                    r'\bmidday\b': 12,
                    r'\bdawn\b': 5,
                    r'\bdusk\b': 19,
                    r'\bsunrise\b': 6,
                    r'\bsunset\b': 18,
                    r'\bbefore noon\b': 11,
                    r'\bafter noon\b': 13,
                    r'\bearly morning\b': 6,
                    r'\blate morning\b': 10,
                    r'\bearly afternoon\b': 13,
                    r'\blate afternoon\b': 16,
                    r'\bearly evening\b': 17,
                    r'\blate evening\b': 20,
                    r'\blate night\b': 23,
                }
                
                # Handle "X in the morning/afternoon/evening" pattern
                in_the_pattern = r'(\d{1,2})\s*(?::\s*(\d{1,2}))?\s*in\s+the\s+(morning|afternoon|evening|night)'
                match = re.search(in_the_pattern, t)
                if match:
                    hour = int(match.group(1))
                    minute = int(match.group(2)) if match.group(2) else 0
                    period = match.group(3)
                    
                    # Adjust hour based on period
                    if period == 'morning':
                        if hour < 12:  # Keep as is for AM
                            pass
                    elif period == 'afternoon':
                        if hour < 12:
                            hour += 12  # Convert to PM
                    elif period == 'evening' or period == 'night':
                        if hour < 12:
                            hour += 12  # Convert to PM
                        if hour < 18:  # Ensure it's evening
                            hour = 18 if hour < 18 else hour
                    
                    try:
                        dt = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M")
                        cleaned_times.append(dt.strftime("%H:%M:%S"))
                        logger.debug(f"Parsed '{original_t}' as {hour:02d}:{minute:02d}")
                        continue
                    except:
                        pass
                
                # Handle "X am/pm" with natural language
                am_pm_pattern = r'(\d{1,2})\s*(?::\s*(\d{1,2}))?\s*(am|pm|a\.m\.|p\.m\.)?'
                match = re.search(am_pm_pattern, t)
                if match:
                    hour = int(match.group(1))
                    minute = int(match.group(2)) if match.group(2) else 0
                    ampm = match.group(3)
                    
                    if ampm:
                        # Convert to 24-hour format
                        if ampm.startswith('p') and hour < 12:
                            hour += 12
                        elif ampm.startswith('a') and hour == 12:
                            hour = 0
                    else:
                        # No AM/PM specified - try to infer from context
                        if 'morning' in t or 'dawn' in t or 'sunrise' in t:
                            if hour == 12:
                                hour = 0
                        elif 'afternoon' in t or 'noon' in t:
                            if hour < 12:
                                hour += 12
                        elif 'evening' in t or 'night' in t or 'dusk' in t or 'sunset' in t:
                            if hour < 12:
                                hour += 12
                            if hour < 18:
                                hour = 18  # Default to 6 PM for evening
                        elif 'midnight' in t:
                            hour = 0
                        elif 'noon' in t:
                            hour = 12
                    
                    try:
                        dt = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M")
                        cleaned_times.append(dt.strftime("%H:%M:%S"))
                        logger.debug(f"Parsed '{original_t}' as {hour:02d}:{minute:02d}")
                        continue
                    except:
                        pass
                
                # Handle standalone time expressions (like "morning")
                for pattern, hour in time_expressions.items():
                    if re.search(pattern, t):
                        # Check if there's also a number
                        number_match = re.search(r'(\d{1,2})', t)
                        if number_match:
                            hour = int(number_match.group(1))
                            if pattern in [r'\bevening\b', r'\bnight\b'] and hour < 12:
                                hour += 12
                        
                        try:
                            dt = datetime.strptime(f"{hour:02d}:00", "%H:%M")
                            cleaned_times.append(dt.strftime("%H:%M:%S"))
                            logger.debug(f"Parsed expression '{original_t}' as {hour:02d}:00")
                            continue
                        except:
                            pass
                
                # Try parsing common formats
                try:
                    # Try "8 am" format
                    dt = datetime.strptime(t, "%I %p")
                    cleaned_times.append(dt.strftime("%H:%M:%S"))
                    continue
                except ValueError:
                    pass
                    
                try:
                    # Try "8:30 pm" format
                    dt = datetime.strptime(t, "%I:%M %p")
                    cleaned_times.append(dt.strftime("%H:%M:%S"))
                    continue
                except ValueError:
                    pass
                    
                try:
                    # Try "20:30" format
                    dt = datetime.strptime(t, "%H:%M")
                    cleaned_times.append(dt.strftime("%H:%M:%S"))
                    continue
                except ValueError:
                    pass
                
                # If we got here, couldn't parse
                logger.warning(f"Could not parse time: '{original_t}'")

        # Remove duplicates while preserving order
        seen = set()
        cleaned_times = [x for x in cleaned_times if not (x in seen or seen.add(x))]

        logger.debug(f"Cleaned times: {cleaned_times}")

        logger.debug(f"Cleaned reminder_time: {cleaned_times}")

        # -----------------------------
        # Validate and normalize reminder_day
        # -----------------------------

        valid_days = {
            "mon": "monday",
            "monday": "monday",
            "mondays": "monday",

            "tue": "tuesday",
            "tues": "tuesday",
            "tuesday": "tuesday",
            "tuesdays": "tuesday",

            "wed": "wednesday",
            "wednesday": "wednesday",
            "wednesdays": "wednesday",

            "thu": "thursday",
            "thurs": "thursday",
            "thursday": "thursday",
            "thursdays": "thursday",

            "fri": "friday",
            "friday": "friday",
            "fridays": "friday",

            "sat": "saturday",
            "saturday": "saturday",
            "saturdays": "saturday",

            "sun": "sunday",
            "sunday": "sunday",
            "sundays": "sunday",
        }

        # Group mappings
        group_mappings = {
            "weekday": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],

            "weekend": ["saturday", "sunday"],
            "weekends": ["saturday", "sunday"],

            "every day": [
                "monday", "tuesday", "wednesday",
                "thursday", "friday", "saturday", "sunday"
            ],
            "everyday": [
                "monday", "tuesday", "wednesday",
                "thursday", "friday", "saturday", "sunday"
            ],
            "daily": [
                "monday", "tuesday", "wednesday",
                "thursday", "friday", "saturday", "sunday"
            ],
        }

        normalized_days = []

        if reminder_day:
            for day in reminder_day:
                day_lower = day.lower().strip()

                # Remove "morning" / "evening"
                day_lower = day_lower.replace("morning", "").replace("evening", "").strip()

                # Handle group expressions
                if day_lower in group_mappings:
                    normalized_days.extend(group_mappings[day_lower])

                # Handle single day values
                elif day_lower in valid_days:
                    normalized_days.append(valid_days[day_lower])

                else:
                    logger.warning(f"Ignoring invalid reminder_day value: '{day}'")

        # Remove duplicates while preserving order
        seen = set()
        normalized_days = [x for x in normalized_days if not (x in seen or seen.add(x))]

        reminder_day = normalized_days

        logger.debug(f"Normalized reminder_day: {reminder_day}")
        # -----------------------------
        # Build final reminder data
        # -----------------------------
        reminder_data = {
            "user_medication_id": user_medication_id,
            "frequency_type": frequency_type,
            "frequency_period": frequency_period,
            "reminder_day": reminder_day,
            "time_period": per_day_frequency,
            "quantity": quantity,
            "snooze": 15,
            "alert_type": alert_type,
            "reminder_time": cleaned_times
        }

        logger.debug(f'Reminder data: {reminder_data}')

        # Save reminder data
        medmanager = MedicationManager(token=tracker.sender_id)
        success, message = medmanager.save_reminder(reminder_data)

        if not success:
            response = "Sorry, I couldn't save your reminder information. Would you like to try again?"
            attachment = {
                "query_response": response,
                "type": "text",
                "status": "error"
            }
            dispatcher.utter_message(attachment=attachment)
            return [
                SlotSet("current_step", "pending_confirmation"),
                SlotSet("frequency", None),
                SlotSet("per_day_frequency", None),
                SlotSet("quantity", None),
                SlotSet("reminder_time", None),
                SlotSet("alert_type", None),
                SlotSet("reminder_day", None)
            ]
        
        # Success 
        dispatcher.utter_message(
            attachment={
                "query_response": "Great! I've set up your reminder. What else can I do for you?",
                "type": "text",
                "status": "success"
            }
        )
        
        return [
            ActiveLoop(None),
            SlotSet("current_step", None),

            # Clear reminder slots
            SlotSet("frequency", None),
            SlotSet("per_day_frequency", None),
            SlotSet("quantity", None),
            SlotSet("reminder_time", None),
            SlotSet("alert_type", None),
            SlotSet("reminder_day", None)
        ]

    
    def _format_reminder_confirmation(self, reminder_data: Dict) -> str:
        """Format reminder data for user confirmation."""
        lines = ["Here's your reminder setup:"]
        
        # Frequency
        freq_type = reminder_data.get("frequency_type")
        freq_period = reminder_data.get("frequency_period")
        if freq_type and freq_period:
            lines.append(f"• Duration: {freq_period} {freq_type}(s)")
        
        # Times
        time_period = reminder_data.get("time_period")
        reminder_times = reminder_data.get("reminder_time")
        if time_period and reminder_times:
            times_str = ", ".join(reminder_times)
            lines.append(f"• {time_period.title()} at: {times_str}")
        
        # Days (if weekly)
        if reminder_data.get("frequency_type") == "week":
            reminder_day = reminder_data.get("reminder_day")
            if reminder_day:
                days_str = ", ".join([day.title() for day in reminder_day])
                lines.append(f"• Days: {days_str}")
        
        # Quantity
        quantity = reminder_data.get("quantity")
        if quantity:
            lines.append(f"• Quantity: {quantity} pill(s) each time")
        
        # Alert type
        alert_type = reminder_data.get("alert_type")
        if alert_type:
            lines.append(f"• Alert: {alert_type}")
        
        return "\n".join(lines)
        
    def _complete_flow(self, success: bool = True, message: str = None):
        """Complete the medication addition flow."""
        if not success and message:
            return [
                ActiveLoop(None),
                SlotSet("awaiting_reminder_confirmation", None),
                {"text": f"Error: {message}"}
            ]
        
        return [
            ActiveLoop(None),
            SlotSet("awaiting_reminder_confirmation", None),
            {"text": "All done! Your medication has been successfully added with reminders."}
        ]
    
class ActionListMedications(Action):
    """List all medication names for the user."""
    
    def name(self) -> Text:
        return "action_list_medications"
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.info("Listing medication names")
        
        try:
            med_manager = MedicationManager(tracker.sender_id)
            medication_names = med_manager.get_medication_names()
            
            if not medication_names:
                logger.debug("No medications found for user")
                builder = ResponseBuilder(tracker.sender_id, tracker)
                attachment = builder.build_response("no_medications")
            else:
                builder = ResponseBuilder(tracker.sender_id, tracker)
                attachment = builder.build_response(
                    "list_medications",
                    medications=", ".join(medication_names),
                    count=len(medication_names)
                )
                logger.debug(f"Found {len(medication_names)} medications")
            
            dispatcher.utter_message(attachment=attachment)
            
        except Exception as e:
            logger.error(f"Error listing medications: {e}", exc_info=True)
            dispatcher.utter_message(text="Sorry, I couldn't retrieve your medication list.")
        
        return []

class ActionMedicationReport(Action):
    """Generate medication tracking report for specified or default timeframe."""
    
    def name(self) -> Text:
        return "action_medication_report"
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.info("Generating medication tracking report")
        
        try:
            # Get period from slot or default
            period = tracker.get_slot("period") or "month"
            logger.debug(f"Generating report for period: {period}")
            
            # Map period to days
            days_map = {
                "today": 1,
                "day": 1,
                "week": 7,
                "month": 30,
                "3 months": 90,
                "year": 365
            }
            days = days_map.get(period.lower(), 30)
            
            med_manager = MedicationManager(tracker.sender_id)
            
            # Get tracking data
            tracking_data = med_manager.get_recent_tracking(days=days)
            
            if not tracking_data:
                logger.debug(f"No tracking data found for last {period}")
                builder = ResponseBuilder(tracker.sender_id, tracker)
                reply = builder.build_response("no_tracking_data", day=period)
                dispatcher.utter_message(text=reply["query_response"])
                return []
            
            # Analyze compliance
            stats = med_manager.analyze_tracking_compliance(tracking_data)
            logger.debug(f"Report stats for {period}: {stats}")
            
            # Get medication names
            medication_names = med_manager.get_medication_names()
            
            # Generate problematic medication note
            problematic_note = med_manager.analyze_problematic_medications(stats, period)
            
            # Build summary response
            builder = ResponseBuilder(tracker.sender_id, tracker)
            response = builder.build_response(
                "medication_report",
                total=stats['total'],
                taken=stats['taken'],
                missed=stats['missed'],
                compliance_rate=stats['compliance_rate'],
                day=period,
                medication_count=len(medication_names),
                problematic_meds="None",
                problematic_note=problematic_note
            )
            
            # Build report data
            max_entries = 15 if period.lower() == "week" else 10
            report_data = med_manager.build_report_data(tracking_data, max_entries, period)
            
            # Add the report data to the response
            response["data"] = report_data
            response["type"] = "array"  # Ensure type is array when we have data
            
            dispatcher.utter_message(attachment=response)
            logger.info(f"✓ {period.capitalize()} report generated: {stats['taken']}/{stats['total']} taken")
            
        except Exception as e:
            logger.error(f"✗ Error generating report: {e}", exc_info=True)
            dispatcher.utter_message(text=f"Sorry, I couldn't generate your medication report.")
        
        return []
    
class ActionGetHealthRecords(Action):
    """Action to fetch and show health records."""
    
    def name(self) -> Text:
        return "action_get_health_records"
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.info("Starting action_get_health_records")
        
        try:
            from .helpers.health_records_manager import HealthRecordsManager
            from .helpers.response_builder import ResponseBuilder
            
            # Create ResponseBuilder ONCE at the beginning
            builder = ResponseBuilder(tracker.sender_id, tracker)
            
            # Get records
            logger.debug("Creating HealthRecordsManager")
            manager = HealthRecordsManager(tracker.sender_id)
            records_data = manager.get_all_records()
            
            # Debug: Log what we got from API
            logger.debug(f"Records data type: {type(records_data)}")
            logger.debug(f"Records data keys: {list(records_data.keys()) if records_data else 'None'}")
            
            # Check if we have any data at all
            if not records_data:
                logger.info("No records data returned from API")
                attachment = builder.build_response("no_health_records")  # Use existing builder
                dispatcher.utter_message(attachment=attachment)
                return [SlotSet("health_records_available", False)]
            
            items = records_data.get("items", [])
            total_count = records_data.get("count", 0)
            
            logger.debug(f"Total count from API: {total_count}")
            logger.debug(f"Items list length: {len(items)}")
            
            # Check if items list is empty
            if not items:
                logger.info("Items list is empty (count might be 0)")
                attachment = builder.build_response("no_health_records")  # Use existing builder
                dispatcher.utter_message(attachment=attachment)
                return [SlotSet("health_records_available", False)]
            
            # Debug: Show first item structure
            if items:
                first_item = items[0]
                logger.debug(f"First item keys: {list(first_item.keys())}")
                logger.debug(f"First item name: {first_item.get('name')}")
                logger.debug(f"First item date: {first_item.get('diagnosis_date')}")
            
            # Prepare data for response
            recent_records = manager.get_recent_records(limit=3)
            
            logger.debug(f"Recent records count: {len(recent_records)}")
            
            # Get unique record types
            record_types = manager.get_record_types()
            logger.debug(f"Record types found: {record_types}")
            
            # Check if records have dates
            has_dates = any(record.get("diagnosis_date") for record in items[:3])
            logger.debug(f"Records have dates: {has_dates}")
            
            # Format records for display
            if recent_records:
                record_strings = []
                for record in recent_records:
                    name = record.get("name", "Health Record")
                    date_str = record.get("diagnosis_date", "")
                    formatted_date = manager.format_record_date(date_str)
                    
                    if formatted_date != "Unknown date":
                        record_strings.append(f"{name} ({formatted_date})")
                    else:
                        record_strings.append(name)
                record_list = ", ".join(record_strings)
                logger.debug(f"Formatted recent records: {record_list}")
            else:
                record_names = [r.get("name", "Record") for r in items[:3]]
                record_list = ", ".join(record_names)
                logger.debug(f"Simple record list: {record_list}")
            
            # Choose template based on context
            logger.debug(f"Choosing template: total_count={total_count}, record_types={len(record_types)}, has_dates={has_dates}")
            
            # NOTE: ResponseBuilder will automatically add 'name' parameter
            # from UserProfile, so we don't need to pass it explicitly
            if total_count == 1:
                logger.debug("Using single record template")
                record = items[0]
                name = record.get("name", "Health Record")
                date_str = record.get("diagnosis_date", "")
                formatted_date = manager.format_record_date(date_str)
                
                if formatted_date != "Unknown date":
                    record_str = f"{name} ({formatted_date})"
                else:
                    record_str = name
                    
                attachment = builder.build_response(
                    "health_records_single_recent",
                    record=record_str  
                )
                
            elif len(record_types) == 1 and len(items) > 1:
                logger.debug(f"Using by-type template: {record_types[0]}")
                attachment = builder.build_response(
                    "health_records_by_type",
                    record_type=record_types[0],
                    records=record_list,
                    count=total_count
                )
                
            elif has_dates and recent_records:
                logger.debug("Using with-dates template")
                attachment = builder.build_response(
                    "health_records_with_dates",
                    records=record_list,
                    count=total_count,
                    recent_count=len(recent_records)
                )
                
            else:
                logger.debug("Using generic list template")
                attachment = builder.build_response(
                    "health_records_list",
                    records=record_list,
                    count=total_count
                )
            
            logger.debug(f"Final response: {attachment}")
            dispatcher.utter_message(attachment=attachment)
            logger.info(f"Successfully returned {total_count} health records")
            return [SlotSet("health_records_available", True)]
            
        except Exception as e:
            logger.error(f"Error getting health records: {e}", exc_info=True)
            dispatcher.utter_message(attachment=builder.build_response("no_health_records"))
            return []
        
class ActionTodaysMedication(Action):
    def name(self):
        return "action_todays_medication"
          
    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]: 
        days = {
            0: "Monday",
            1: "Tuesday",
            2: "Wednesday",
            3: "Thursday",
            4: "Friday",
            5: "Saturday",
            6: "Sunday"
        }
        today = datetime.today()
        day = days[today.weekday()]

        url = 'https://api.pillaxia.com/api/v1/medication-reminders/list'
        header = {
            "Authorization" : f"Bearer {tracker.sender_id}"
        }
        medication_names=[]
        try:
            response = requests.post(url,headers=header)
            data = response.json()
            for item in data["result"]["items"]:
                if day.lower() in item["reminder_day"]:
                    medication_names.append(item["medication"])
            if len(medication_names) == 0:
                reply = "no medication today"
                attachment = {
                            "query_response": reply,
                            "data": [],
                            "type": "text",
                            "status": "success"
                }
            else:
                reply = "Your medications for today: " + ", ".join([str(med) for med in medication_names])
                attachment = {
                                "query_response": reply,
                                "data": [],
                                "type": "text",
                                "status": "success"
                }
        except Exception as e:
            reply = e
            attachment = {
                    "query_response": reply,
                    "data": [],
                    "type": "text",
                    "status": "failed"
            }
        dispatcher.utter_message(attachment=attachment)

        return []
        
class ActionMedicationTracker(Action):
    def name(self):
        return "action_medication_tracker"
    
    def UpdateMedication(self,tracker, id,reminder_id):
        update_url = "https://api.pillaxia.com/api/v1/medication-tracker/update"
        payload ={
            "tracker_id":id,
            "reminder_id": reminder_id,
            "remarks": ""  
        }
        header = {
                "Authorization" : f"Bearer {tracker.sender_id}"
        }
        try:
                response = requests.get(update_url, params = payload, headers=header)
                response_data = response.json()
                return response_data["message"]
        except Exception as e:
            return None

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]: 
        today = datetime.now().date()
        url = f'https://api.pillaxia.com/api/v1/pxdiary?start_date={today}&end_date={today}'
        header = {
                "Authorization" : f"Bearer {tracker.sender_id}"
        }
        try:
                response = requests.get(url, headers=header)
                response_data = response.json()
                data = response_data["result"]
                if len(data) == 1:
                    id = data["id"]
                    reminder_id = data["reminder_id"]
                    result = self.UpdateMedication(id,reminder_id)
                    if result == None:
                        reply = "Failed to update your medication!!"
                        attachment={
                            "query_response": reply,
                            "data": [],
                            "type":"string",
                            "status": "failed"
                        }
                    else:
                        reply = "updated!"
                        attachment={
                            "query_response": result,
                            "data": [],
                            "type":"string",
                            "status": "success"
                        }
                elif len(data) == 0:
                    reply = "No medication to update"
                    attachment={
                            "query_response": reply,
                            "data": [],
                            "type":"string",
                            "status": "success"
                    }
                else:
                    reply = "mutiple medications available! Please choose your medication"
                    attachment={
                            "query_response": reply,
                            "data": data,
                            "type":"array",
                            "status": "success"
                    }
        except Exception as e:
                reply ="failed!"
                attachment = {
		    	    "query_response": reply,
		    	    "data": [],
		    	    "type":"string",
		    	    "status": "failed"
		        }
        dispatcher.utter_message(attachment=attachment)
        return []

class ActionMedicationDosage(Action):
    def name(self):
        return "action_medication_dosage"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
        medication_name = tracker.get_slot('medication')
        url = 'https://api.pillaxia.com/api/v1/user-medications/list'
        header = {
            "Authorization" : f"Bearer {tracker.sender_id}"
        }
        try:
            response = requests.post(url,headers=header)
            response_data = response.json()["result"]["items"]
            for data in response_data:
                if data["code"] == medication_name.lower():
                    dose = data["dose"]
            
            if len(dose) > 0:
                messages = [f"Your dosage for {medication_name} is {dose}",
                            f"Dosage of your medication {medication_name} is {dose}",
                            f"Dose of your medication {medication_name} is {dose}"]
                reply = random.choice(messages)
                attachment = {
                        "query_response": reply,
                        "data": [],
                        "type":"string",
                        "status": "success"
                    }
            else:
                messages = [f"You do not have {medication_name} in your list",
                            f"{medication_name} is not available in your medication list"]
                reply = random.choice(messages)
                attachment = {
                        "query_response": reply,
                        "data": [],
                        "type":"string",
                        "status": "failed"
                    }
        except Exception as ex:
            reply = "Failed to get your medication_dosage"
            attachment = {
		    	    "query_response": reply,
		    	    "data": [],
		    	    "type":"string",
		    	    "status": "failed"
		        }
        dispatcher.utter_message(attachment=attachment)
        return []

class ActionMedicationTaken(Action):
    def name(self):
        return "action_medication_taken"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        medication_name = tracker.get_slot("medication")
        starting_date = date.today()  
        end_date = date.today()

        url = f'https://api.pillaxia.com/api/v1/pxtracker?start_date={starting_date}&end_date={end_date}'
        header = {
            "Authorization": f"Bearer {tracker.sender_id}"
        }
        try:
            response = requests.get(url, headers=header)
            response_data = response.json()["result"]["items"]
            now = datetime.now()
            med_filter = medication_name.lower() if medication_name else None

            taken_parts = []
            missed_parts = []

            for entry in response_data:
                name = entry["reminder"]
                name_lower = name.lower()
                if med_filter and name_lower != med_filter:
                    continue

                rem_dt = datetime.strptime(entry["reminder_at"], DATETIME_FMT)
                time_label = rem_dt.strftime("%-I%p").lower()

                if tracked := entry.get("tracked_at"):
                    taken_dt = datetime.strptime(tracked, DATETIME_FMT)
                    taken_parts.append(
                        f"{time_label} dose of {name} at {taken_dt.strftime('%-I:%M%p').lower()}"
                    )
                elif rem_dt <= now:
                    missed_parts.append(f"{time_label} dose of {name}")

            if medication_name and not (taken_parts or missed_parts):
                return f"{medication_name} is not scheduled for today."

            messages = []
            if taken_parts:
                messages.append("Yes, you took your " + ", ".join(taken_parts) + ".")
            if missed_parts:
                prefix = "But you have missed your " if taken_parts else "You have missed your "
                messages.append(prefix + ", ".join(missed_parts) + ".")
            elif taken_parts:
                messages[-1] += " You're all caught up."

            attachment = {
                        "query_response": " ".join(messages) if messages else "No medication activity recorded.",
                        "data": [],
                        "type": "text",
                        "status": "success"
                    }
        except Exception as ex:
            reply = "Sorry, we couldn't access your medication information."
            attachment = {
                "query_response": reply,
                "data": str(ex),
                "type": "text",
                "status": "failed"
            }
        dispatcher.utter_message(attachment=attachment)
        
        # if medication_name: 
        #     return [SlotSet("medication", None)]
        return []

        
        
# class actionDoseLeft(Action):
#     def name(self):
#         return "action_dose_left"
    
#     def run(self, dispatcher: CollectingDispatcher, 
#             tracker: Tracker, 
#             domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
#         medication_name = tracker.get_slot('medication')
#         url = 'https://api.pillaxia.com/api/v1/user-medications/list'
#         header = {
#                     "Authorization" : f"Bearer {tracker.sender_id}"
#                 }
#         try:
#             response = requests.post(url,headers=header)
#             response_data = response.json()["result"]["items"]
#             for data in response_data:
#                 if data["reminder"] == medication_name.lower():
#                     stock_level = data["stock_level"]

#             if stock_level:
#                 messages = [f"Your remaining dose of {medication_name} is {stock_level}",
#                             f"Amount of {medication_name} left is {stock_level}",
#                             f"Remaining dose you have of {medication_name}: {stock_level}"]
#                 reply = random.choice(messages)
#                 attachment = {
#                     "query_response": reply,
#                     "data": [],
#                     "type": "text",
#                     "status": "success"
#                 }
#             else:
#                 reply = "You do not have any medications for today"
#                 attachment = {
#                     "query_response": reply,
#                     "data": [],
#                     "type": "text",
#                     "status": "failed"
#                 }
            
#         except Exception as ex:
#             reply = "Failed to get information about left dosage. Please try again!!"
#             attachment = {
#                 "query_response": reply,
# 		    	"data":[],
# 		    	"type":"string",
# 		    	"status": "success"
#             }
#         dispatcher.utter_message(attachment=attachment)
#         return []

class ActionNextDose(Action):
    def name(self):
        return "action_next_dose"
  
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
        
        from datetime import datetime
        import requests

        todays_time = datetime.today().strftime("%H:%M:%S")
        current_time = datetime.now().strftime("%H:%M:%S")
        url = "https://api.pillaxia.com/api/v1/medication-reminders/list"
        headers = {"Authorization": f"Bearer {tracker.sender_id}"}
        
        reply = "Sorry, we couldn't access your medication information."  # default reply
        
        try:
            response = requests.post(url, headers=headers)
            response_data = response.json().get("result", {})

            if response_data.get("count", 0) != 0:
                next_med = None
                now = datetime.strptime(current_time, "%H:%M:%S")

                for data in response_data.get("items", []):
                    future_times = [
                        t for t in data.get("reminder_time", [])
                        if t >= todays_time and datetime.strptime(t, "%H:%M:%S") > now
                    ]
                    if future_times:
                        earliest_time = min(future_times, key=lambda t: datetime.strptime(t, "%H:%M:%S"))
                        med_time = datetime.strptime(earliest_time, "%H:%M:%S")

                        if not next_med or med_time < datetime.strptime(next_med["time"], "%H:%M:%S"):
                            next_med = {"name": data["medication"], "time": earliest_time}

                if next_med:
                    time_obj = datetime.strptime(next_med['time'], "%H:%M:%S")
                    formatted_time_full = time_obj.strftime("%-I:%M %p")  # HH:MM AM/PM
                    attachment = f"You're scheduled to take your {next_med['name']} at {formatted_time_full}. I'll remind you when it's time!"
                else:
                    attachment = "Looks like you don’t have any meds scheduled for the rest of today."
            else:
                attachment = "Looks like you don’t have any meds scheduled!"
        
        except Exception as ex:
            # reply already has a default error message
            pass
        
        dispatcher.utter_message(attachment=attachment)
        return []


class ActionRefillInformation(Action):
    def name(self):
        return "action_refill_information"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
            medication_name = tracker.get_slot('medication')
            url = 'https://api.pillaxia.com/api/v1/user-medications/list'
            header = {
                        "Authorization" : f"Bearer {tracker.sender_id}"
                    }
            refill_info = {}
        # try:
            response = requests.post(url,headers=header)
            response_data = response.json()["result"]["items"]
            for data in response_data:
                if data["name"].lower() == medication_name.lower() and len(data["refill_periods"]) > 0:
                        date = data["refill_periods"][0]["refill_date"],
            if date:
                messages = ["Refill date of your medication ", 
                            "Refill date for your prescription ",
                            "Refill date regarding your medication "]
                response = random.choice(messages)
                reply = f"{response} {medication_name} is {' '.join(date)}"
                attachment = {
                    "query_response": reply,
                    "data": [],
                    "type": "text",
                    "status": "success"
                }
            else:
                messages = [f"I'm sorry, but I don't have any recorded refill information for {medication_name}.",
                            f"Unfortunately, there's no refill data available for {medication_name} in your records.",
                            f"I couldn't find any refill details for {medication_name}.",
                            f"There are no recorded refills in your records for {medication_name}.",
                            f"Your records don't show any refill information for {medication_name}."]
                reply = random.choice(messages)
                attachment = {
                    "query_response": reply,
                    "data": [],
                    "type": "text",
                    "status": "failed"
                }
            
        # except Exception as ex:
        #     reply = "Failed to get information about medication refill. Please try again!!"
        #     attachment = {
        #         "query_response": reply,
		#     	"data":[],
		#     	"type":"string",
		#     	"status": "failed"
        #     }
        # finally:
            dispatcher.utter_message(attachment=attachment)
        
            return [SlotSet("medication", None)]
    
# class actionSymtomsOccured(Action):
#     def name(self):
#         return "action_symtoms_occured"
    
#     def run(self, dispatcher: CollectingDispatcher, 
#             tracker: Tracker, 
#             domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
#         symptom = tracker.get_slot('symptom')
#         period = tracker.get_slot('period')
#         today = date.today()
#         if period.lower() == "week":
#                 date = today - timedelta(days = 7)
#         elif period.lower() == "month":
#                 date = today - timedelta(days = 30)


#         url = 'https://api.pillaxia.com/api/v1/pxdiary'
#         header = {
#                     "Authorization" : f"Bearer {tracker.sender_id}"
#                 }
#         params = {
#             "start_date" : date,
#             "end_date" : date,
#             "search_text" : symptom
#         }

#         try:
#             response = requests.get(url, params=params, headers=header)
#             response_data = response.json()
#         except Exception as ex:
#             pass
        
        
class ActionNewSymptom(Action):
    def name(self):
        return "action_new_symptom"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:   
         
        try:
            messages = ["Please fill the following form to record your symptom.",
                       "Use this form to log the symptoms you're experiencing.",
                       "Fill out the following form to report your current symptoms."]
            reply = random.choice(messages)
            attachment = {
		    	"query_response": reply,
		    	"data": "/add-symptom",
		    	"type":"redirect",
		    	"status": "success"
		    }
        except Exception as e:
            reply = "Redirect Failed!"
            attachment = {
		    	"query_response": reply,
		    	"data": [],
		    	"type":"string",
		    	"status": "failed"
		    }
        dispatcher.utter_message(attachment=attachment)
        return[]

class ActionSymptoms(Action):
    def name(self):
        return "action_symptoms"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any])  -> List[Dict[Text, Any]]: 
        period = tracker.get_slot('period')

        if period == None:
            periods = ("week", "month", "week", "month")
            period = random.choice(periods)
        today = date.today()
        Date = today
        if period.lower() == "week":
                Date = today - timedelta(days = 7)
        elif period.lower() == "month":
                Date = today - timedelta(days = 30)
                
        url = f'https://api.pillaxia.com/api/v1/pxdiary?start_date={Date}&end_date={Date}'
        header = {
                    "Authorization" : f"Bearer {tracker.sender_id}"
                }
        
        symptoms = {}
        try:
            response = requests.get(url, headers=header)
            response_data = response.json()["result"]
            if len(response_data) > 0:
                for data in response_data:
                    symptoms_info = {
                        "name" : data["name"],
                        "value" : f"Intensity: {data['intensity']}, Start Date: {data['start_date']}, End Date: {data['end_date']}, Note: {data['note']}"
                    }
                    symptoms.append(symptoms_info)

                reply = f"Here's your list of symptoms you experienced last {period}"
                attachment = {
                    "query_response": reply,
                    "data": symptoms,
                    "type":"array",
                    "status": "success"
                }
            else:
                reply = f"You have no recorded symptoms for last {period}"
                attachment = {
                    "query_response": reply,
                    "data": [],
                    "type":"string",
                    "status": "failed"
                }

        except Exception as ex:
            reply = f"Failed to get your last {period} symptoms"
            attachment = {
                    "query_response": reply,
                    "data": [],
                    "type":"string",
                    "status": "failed"
                }
        dispatcher.utter_message(attachment=attachment)
        return[]
    
class ActionCheckMedication(Action):
    def name(self):
        return "action_check_medication" 
    
    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
        start_date = date.today()
        period = tracker.get_slot("period")
               
        if period.lower() == "week":
                start_date = start_date - timedelta(days = 7)
        elif period.lower() == "month":
                start_date = start_date - timedelta(days = 30)
        url = f'https://api.pillaxia.com/api/v1/pxtracker?start_date={start_date}&end_date={date.today()}'
        header = {
                    "Authorization" : f"Bearer {tracker.sender_id}"
                }
        try:
            response = requests.get(url, headers=header)
            response_data = response.json()["result"]["items"]
            missed_meds = set()
            for item in response_data:
                if item["tracked_at"] is None:
                    missed_meds.add(item["reminder"])

                # else:
                #     tracked_meds.append({"tracked_at":item['tracked_at'],
                #                          "reminder_at":item['reminder_at']})
            if not missed_meds:
                reply = f"You have not missed any medication"
                attachment = {
                    "query_response": reply,
                    "data":[],
                    "type":"string",
                    "status": "success"
                }
            else:
                reply = f"You have missed: {','.join([str(item) for item in list(missed_meds)])}"
                attachment = {
                    "query_response": reply,
                    "data": [],
                    "type":"string",
                    "status": "success"
                }
        except Exception as e:
            reply = f"Failed to get your last {period} data"
            attachment = {
                    "query_response": reply,
                    "data": str(e),
                    "type":"string",
                    "status": "failed"
                }
        dispatcher.utter_message(attachment=attachment)
        return[]
    
class ActionMedicationAdherence(Action):
    """Provide medication adherence insights using analyzer and response builder."""
    
    def name(self):
        return "action_medication_adherence"
    
    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.info("Generating medication adherence insights")
        
        try:
            period = tracker.get_slot("period") or "month"
            logger.debug(f"Adherence period: {period}")
            
            # Map period to days
            days_map = {
                "today": 1, "day": 1, "week": 7, 
                "month": 30, "3 months": 90, "year": 365
            }
            days = days_map.get(period.lower(), 30)
            
            # Initialize managers
            med_manager = MedicationManager(tracker.sender_id)
            analyzer = MedicationAnalyzer(med_manager)
            builder = ResponseBuilder(tracker.sender_id, tracker)
            
            # Get tracking data
            tracking_data = med_manager.get_recent_tracking(days=days)
            
            if not tracking_data:
                logger.debug(f"No tracking data for {period}")
                reply = builder.build_response("no_tracking_data", day=period)
                dispatcher.utter_message(text=reply["query_response"])
                return []
            
            # Analyze insights
            insights = analyzer.analyze_adherence_insights(tracking_data, period)
            
            # Build response
            response = builder.build_medication_insight(insights, include_data=False)
            
            dispatcher.utter_message(attachment=response)
            logger.info(f"✓ {period} adherence insights sent")
            
        except Exception as e:
            logger.error(f"✗ Adherence error: {e}", exc_info=True)
            dispatcher.utter_message(text="Sorry, I couldn't access your medication adherence.")
        
        return []
    
        
class ActionCustomFallback(Action):
    def __init__(self):
        # Load medications from CSV
        self.medications_df = pd.read_csv('data/medications.csv')
        self.KNOWN_MEDICATIONS = self.medications_df['medication_name'].tolist()

    def name(self):
        return "action_custom_fallback"       
    
    UNCERTAINTY_PHRASES = [
        "dont know", "don't know", "do not know", "dunno", "idk", "dk",
        "not sure", "no idea", "no clue", "forgot", "forget",
        "cant remember", "can't remember", "don't recall", "dont recall",
        "i don't know", "i dont know", "i do not know", "i'm not sure",
        "i am not sure", "i have no idea", "i forgot", "i can't remember",
        "not certain", "not really sure", "haven't a clue", "drawing a blank"
    ]

    def _check_uncertainty(self, user_text_lower: str, requested_slot: str, form_name: str, dispatcher) -> Optional[List[Dict]]:
        """
        Check if user is expressing uncertainty and return appropriate response.
        Returns None if no uncertainty detected.
        """
        # Direct uncertainty check
        if user_text_lower in self.UNCERTAINTY_PHRASES or any(phrase == user_text_lower for phrase in self.UNCERTAINTY_PHRASES):
            logger.debug("Direct uncertainty match - providing helpful response")
            response = self.get_uncertainty_response(requested_slot)
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        return None

    def _fuzzy_match_medication(self, user_text_lower: str, requested_slot: str, form_name: str, dispatcher) -> Optional[List[Dict]]:
        """
        Perform fuzzy matching for medication names.
        Returns appropriate actions based on confidence score.
        """
        if requested_slot != "medication_name":
            return None
        
        try:
            from fuzzywuzzy import process, fuzz
            
            match, score= process.extractOne(
                user_text_lower,
                self.KNOWN_MEDICATIONS,
                scorer=fuzz.WRatio
            )
            
            logger.debug(f"Fuzzy match: '{match}' (score: {score})")
            
            # Strong match - let form handle it
            if score >= 85:
                logger.debug("High fuzzy confidence - treating as CERTAIN")
                return [ActiveLoop(form_name)]
            
            # Medium confidence - ask for confirmation
            if 65 <= score < 85:
                logger.debug("Medium fuzzy confidence - asking for confirmation")
                response = f"Did you mean {match.title()}?"
                attachment = send_response(response)
                dispatcher.utter_message(attachment=attachment)
                return [
                    ActiveLoop(form_name),
                    SlotSet("requested_slot", requested_slot),
                    SlotSet('pending_medication_confirmation', match.title()),
                    FollowupAction("action_listen")
                ]
            
            # Low confidence 
            logger.debug("Low fuzzy confidence - storing raw input as medication_name")
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        except ImportError:
            logger.warning("fuzzywuzzy not installed - skipping fuzzy matching")
            return None
        except Exception as e:
            logger.error(f"Error in fuzzy matching: {e}")
            return None
    
    def get_uncertainty_response(self, slot: str) -> str:
        """Get appropriate response for uncertainty based on slot"""
        
        responses = {
            "medication_name": "No problem! You can check the medication bottle or prescription and tell me when you're ready.",
            "medication_type": "That's okay! If you're not sure about the type, common types are tablet, capsule, or liquid.",
            "medication_dose": "No problem! You can check the medication label. Common dosages are like 500mg, 10mg, or 5ml.",
            "medication_colour": "That's fine! You can give me any color. It's just to make it easier for you to recognize the medicine on the app.",
            "medication_instructions": "That's okay! Common instructions include 'take with food' or 'twice daily'. You can give me 'None'",

            # ADD REMINDER FORM SLOTS
            "per_day_frequency": "No problem! Common options are once, twice, or thrice per day. How many times a day would you like to take this medication?",
            "alert_type": "That's okay! You can choose between 'voice' or 'alarm' for your reminder. Which would you prefer?",
            "reminder_day": "No problem! You can tell me which days of the week you need reminders, like 'Monday, Wednesday, Friday' or 'every day'.",
            "frequency": "That's okay! You can tell me how long you need reminders, like '30 days', '6 months', or '1 year'.",
            "quantity": "No problem! The quantity is usually shown on the prescription, like '500mg' or '5ml'. What does it say?",
            "reminder_time": "That's okay! You can tell me what time you'd like to be reminded, like '9 am' or '20:30'."
        }
        
        # Return a string, not a list
        return responses.get(slot, "No problem! Take your time and let me know when you're ready.")

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        logger.debug("="*80)
        logger.debug("🔧 ACTION_CUSTOM_FALLBACK STARTING")
        
        if tracker.active_loop:
            return self.handle_form_fallback(dispatcher, tracker, domain)
        
        return self.handle_openai_fallback(dispatcher, tracker)
    
    def handle_form_fallback(self, dispatcher, tracker, domain):
        logger.debug('Handling Form Fallback!!!')
        form_name = tracker.active_loop.get("name")
        requested_slot = tracker.get_slot("requested_slot")
        user_text = tracker.latest_message.get('text', '').strip()
        user_text_lower = user_text.lower()
        
        # DEBUG: Check ALL pending-related slots
        pending = tracker.get_slot("pending_medication_confirmation")
        logger.debug(f"Pending slot value: {pending}")
        
        # CRITICAL: Handle confirmation mode directly in fallback
        if pending:
            intent = tracker.latest_message.get('intent', {}).get('name')
            
            logger.debug(f"In confirmation mode with pending: {pending}, intent: {intent}")
            
            # Check for affirmation (either intent or text)
            if intent == "affirm" or user_text_lower in ["yes", "yeah", "yep", "correct", "right", "sure"]:
                logger.debug(f"User confirmed medication: {pending}")
                
                # Set the medication name and move to next slot
                return [
                    ActiveLoop(form_name),
                    SlotSet("medication_name", pending),
                    SlotSet("pending_medication_confirmation", None),
                    SlotSet("requested_slot", "medication_type"),
                    FollowupAction("action_listen")
                ]
            
            # Check for denial
            elif intent == "deny" or user_text_lower in ["no", "nope", "not that", "wrong", "incorrect"]:
                logger.debug("User denied the suggested medication")
                
                dispatcher.utter_message(attachment={
                    "query_response": "Okay, please tell me the correct medication name.",
                    "type": "text",
                    "status": "question"
                })
                
                return [
                    ActiveLoop(form_name),
                    SlotSet("pending_medication_confirmation", None),
                    SlotSet("requested_slot", "medication_name"),
                    FollowupAction("action_listen")
                ]
            
            # If user said something else, just keep the form active
            else:
                logger.debug(f"Unclear response in confirmation mode: '{user_text}'")
                return [ActiveLoop(form_name)]
        
        # Rest of your fallback logic for non-confirmation cases...
        logger.debug(f"Form '{form_name}' - Slot: {requested_slot}")
        logger.debug(f"User text: '{user_text}'")
        
        # STEP 1: Check for uncertainty (highest priority)
        uncertainty_result = self._check_uncertainty(user_text_lower, requested_slot, form_name, dispatcher)
        if uncertainty_result:
            return uncertainty_result
        
        # STEP 2: For medication name, try fuzzy matching
        if requested_slot == "medication_name":
            fuzzy_result = self._fuzzy_match_medication(user_text_lower, requested_slot, form_name, dispatcher)
            if fuzzy_result:
                return fuzzy_result
        
        # STEP 3: Handle by form type with slot-specific logic
        if form_name == "medication_form":
            return self.handle_medication_form(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        elif form_name == "refill_form":
            return self.handle_refill_form(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        elif form_name == "reminder_form":
            return self.handle_reminder_form(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # Default: re-activate form
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot)
        ]

    def handle_medication_form(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle fallback for medication form slots."""
        
        # ==================== MEDICATION NAME HANDLING ====================
        if requested_slot == "medication_name":
            return self._handle_medication_name(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== MEDICATION TYPE HANDLING ====================
        elif requested_slot == "medication_type":
            return self._handle_medication_type(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== MEDICATION COLOUR HANDLING ====================
        elif requested_slot == "medication_colour":
            return self._handle_medication_colour(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== MEDICATION DOSE HANDLING ====================
        elif requested_slot == "medication_dose":
            return self._handle_medication_dose(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== MEDICATION INSTRUCTIONS HANDLING ====================
        elif requested_slot == "medication_instructions":
            return self._handle_medication_instructions(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # Default fallback for unknown slots
        logger.debug(f"No specific handler for slot '{requested_slot}' - re-activating form")
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_medication_name(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle medication name slot."""
        import re
        
        # Case 1: User gives medication type instead of name
        common_types = ["pill", "tablet", "capsule", "liquid", "injection", "cream", "ointment", "syrup", "drops", "inhaler", "spray", "patch"]
        for med_type in common_types:
            if med_type in user_text_lower:
                response = f"I understand it's a {med_type}, but I need the specific medication name. What is it called?"
                attachment = send_response(response)
                dispatcher.utter_message(attachment=attachment)
                return [
                    ActiveLoop(form_name),
                    SlotSet("requested_slot", requested_slot),
                    FollowupAction("action_listen")
                ]
        
        # Case 2: User gives colour instead of name
        common_colours = ["red", "blue", "white", "yellow", "green", "orange", "purple", "pink", "black", "grey", "brown", "clear", "translucent"]
        for colour in common_colours:
            if colour in user_text_lower:
                response = f"I see it's {colour}, but I need the medication name first. What's it called?"
                attachment = send_response(response)
                dispatcher.utter_message(attachment=attachment)
                return [
                    ActiveLoop(form_name),
                    SlotSet("requested_slot", requested_slot),
                    FollowupAction("action_listen")
                ]
        
        # Case 3: User asks a question
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "I'm here to help you add a medication. The name is usually printed on the box or bottle. What does it say?"
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Case 4: Check if it looks like a real medication name
        # Patterns that suggest it's a medication name
        medication_patterns = [
            r'[A-Za-z]+[0-9]+',        # Letters followed by numbers (Lisinopril10)
            r'[0-9]+\s*mg',            # Number with mg
            r'[0-9]+\s*mcg',           # Number with mcg
            r'[0-9]+\s*ml',            # Number with ml
            r'[0-9]+\s*mg\s*tablet',   # Number with mg and tablet
            r'[0-9]+\s*mg\s*capsule',  # Number with mg and capsule
        ]
        
        # Common medication names
        common_medications = [
            "lipitor", "lisinopril", "metformin", "amoxicillin", "synthroid",
            "omeprazole", "gabapentin", "amlodipine", "losartan", "albuterol",
            "ibuprofen", "acetaminophen", "paracetamol", "aspirin", "warfarin",
            "clopidogrel", "metoprolol", "prednisone", "fluoxetine", "sertraline"
        ]
        
        # Check if it matches any pattern
        is_medication = any(re.search(pattern, user_text, re.IGNORECASE) for pattern in medication_patterns)
        
        # Check if it contains a common medication name
        contains_common_med = any(med in user_text_lower for med in common_medications)
        
        # Check if it has reasonable length and only contains letters/numbers/spaces
        words = user_text.split()
        looks_reasonable = len(words) <= 4 and all(word.isalnum() or word.isspace() or word in ['.', '-'] for word in user_text)
        
        if is_medication or contains_common_med or looks_reasonable:
            logger.debug(f"Potential medication name detected: '{user_text}' - Filling the slot")
            return [SlotSet("medication_name", user_text.title()),
                    ActiveLoop(form_name)]
        
        # Doesn't look like a medication name, ask again
        response = "I need the name of the medication. What is it called?"
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_medication_type(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle medication type slot."""
        valid_types = ["pill", "tablet", "capsule", "liquid", "injection", "cream", "ointment", "syrup", "drops", "inhaler", "spray", "patch"]
        
        # Check if user gave a valid type
        found_type = None
        for med_type in valid_types:
            if med_type in user_text_lower:
                found_type = med_type
                break
        
        if found_type:
            # User gave a valid type - let form handle it
            logger.debug(f"Valid medication type detected: '{found_type}' - letting form handle it")
            return [ActiveLoop(form_name)]
        
        # Check for uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "That's okay! If you're not sure about the type, you can describe the medication or check the packaging. Common types are tablet, capsule, or liquid."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Check for questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = f"To help me categorize it correctly, could you tell me if it's a {', '.join(valid_types[:5])} or something else?"
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Default response for invalid type
        response = f"I need to know the medication type. Is it a {', '.join(valid_types[:5])}?"
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_medication_colour(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle medication colour slot."""
        valid_colours = ["red", "blue", "white", "yellow", "green", "orange", "purple", "pink", "black", "grey", "brown", "clear", "translucent"]
        
        # Check if user gave a valid colour
        found_colour = None
        for colour in valid_colours:
            if colour in user_text_lower:
                found_colour = colour
                break
        
        if found_colour:
            # User gave a valid colour - let form handle it
            logger.debug(f"Valid colour detected: '{found_colour}' - letting form handle it")
            return [ActiveLoop(form_name)]
        
        # Handle uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "That's fine! You can give me any color. It's not that important."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Handle colour descriptions
        colour_desc = {
            "light": "light colours like white or yellow",
            "dark": "dark colours like blue, brown, or black",
            "bright": "bright colours like red, orange, or pink",
            "pastel": "pastel colours like light blue or light pink"
        }
        
        for desc, suggestion in colour_desc.items():
            if desc in user_text_lower:
                response = f"Could you be more specific about the colour? For example, {suggestion}."
                attachment = send_response(response)
                dispatcher.utter_message(attachment=attachment)
                return [
                    ActiveLoop(form_name),
                    SlotSet("requested_slot", requested_slot),
                    FollowupAction('action_listen')
                ]
        
        # Default response
        response = f"What colour is the medication? Common colours are: {', '.join(valid_colours[:7])}."
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction('action_listen')
        ]

    def _handle_medication_dose(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle medication dose slot."""
        import re
        
        # Check if response contains numbers
        has_numbers = bool(re.search(r'\d+', user_text))
        # Check if response contains common dosage units
        units = ["mg", "ml", "mcg", "g", "gram", "milligram", "milliliter", "microgram", "IU", "puff", "drop", "tablet", "capsule"]
        has_units = any(unit.lower() in user_text_lower for unit in units)
        
        if has_numbers and has_units:
            # Looks like a valid dose - directly set slot and continue
            logger.debug('Looks like valid medication dose')
            return [
                SlotSet("medication_dose", user_text.strip()),
                ActiveLoop(form_name)
            ]
        
        if has_numbers:
            # Contains numbers but no recognizable unit - let form validate
            logger.debug(f"Response contains numbers but no unit - letting form validate dose")
            return [ActiveLoop(form_name)]
        
        # Handle uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "No problem! You can check the medication label for the dosage. Common dosages are like 500mg, 10mg, or 5ml."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Handle questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "The dosage is usually shown on the medication label, like '500mg' or '10ml'. What's the dosage for this medication?"
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction('action_listen')
            ]
        
        # Handle common units without numbers
        if any(unit.lower() in user_text_lower for unit in units):
            response = "I need both the number and unit for the dosage. For example, '500mg' or '10ml'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction('action_listen')
            ]
        
        # Default response
        response = "What's the dosage? Please include both the number and unit, like '500mg' or '10ml'."
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction('action_listen')
        ]

    def _handle_medication_instructions(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle medication instructions slot."""
        
        # Handle special cases
        if "none" in user_text_lower or "no instructions" in user_text_lower or "skip" in user_text_lower:
            # Let the form handle "none" case
            logger.debug("User indicates no instructions - letting form handle")
            return [ActiveLoop(form_name)]
        
        # Handle uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "That's okay! Common instructions include 'take with food' or 'twice daily'. You can give me 'None' if there isn't any."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction('action_listen')
            ]
        
        # Handle questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "Instructions might include when to take it, with or without food, or any special directions. What special instructions apply to this medication?"
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction('action_listen')
            ]
        
        # If response seems like valid instructions, let form handle
        if len(user_text.split()) >= 2:  # At least a couple of words
            logger.debug("Response seems like valid instructions - letting form handle")
            return [ActiveLoop(form_name)]
        
        # Default response
        response = "Are there any special instructions for this medication? (You can say 'none' if there aren't any)"
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction('action_listen')
        ]
    
    def handle_refill_form(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle fallback for refill form slots."""
        
        # ==================== STOCK LEVEL HANDLING ====================
        if requested_slot == "stock_level":
            return self._handle_stock_level(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== REFILL DAY HANDLING ====================
        elif requested_slot == "refill_day":
            return self._handle_refill_day(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # Default fallback for unknown slots
        logger.debug(f"No specific handler for slot '{requested_slot}' in refill form - re-activating form")
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_stock_level(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle stock level slot."""
        import re
        
        # STEP 1: Direct uncertainty check (highest priority)
        direct_uncertainty = [
            "dont know", "don't know", "do not know", "dunno", "idk", "dk",
            "not sure", "no idea", "no clue", "forgot", "forget",
            "cant remember", "can't remember", "don't recall", "dont recall",
            "i don't know", "i dont know", "i do not know", "i'm not sure",
            "i am not sure", "i have no idea", "i forgot", "i can't remember",
            "not certain", "not really sure", "haven't a clue", "drawing a blank"
        ]
        
        if user_text_lower in direct_uncertainty or any(phrase == user_text_lower for phrase in direct_uncertainty):
            logger.debug("Refill stock_level - Direct uncertainty match")
            response = "That's okay! You can check the bottle and tell me approximately how many pills are left. Even a rough estimate helps!"
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # STEP 2: Check for numbers (valid stock level)
        numbers = re.findall(r'\d+', user_text)
        
        if numbers:
            # Has numbers - might be valid stock level, let form validate
            logger.debug(f"Refill stock_level - Contains numbers: {numbers}, letting form handle")
            return [ActiveLoop(form_name)]
        
        # STEP 3: Handle questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            logger.debug("Refill stock_level - Question detected")
            response = "I need to know approximately how many pills you have left. You can check the bottle and give me a rough number."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # STEP 4: Handle vague responses
        vague_phrases = ["few", "some", "several", "couple", "many", "lots", "plenty", "enough", "not many", "a lot", "a few"]
        if any(phrase in user_text_lower for phrase in vague_phrases):
            logger.debug("Refill stock_level - Vague response detected")
            response = "That helps a bit! Could you give me a more specific number? Even an estimate like 'about 10' or 'maybe 20' works."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # STEP 5: Handle units without numbers
        units = ["pills", "tablets", "capsules", "strips", "doses", "units", "ml", "mg"]
        if any(unit in user_text_lower for unit in units) and not numbers:
            logger.debug("Refill stock_level - Units without numbers detected")
            response = "I need both the number and what you're counting. For example, '15 tablets' or '2 strips'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # STEP 6: Default response
        logger.debug("Refill stock_level - No pattern matched, asking again")
        response = "How many pills do you have left? Just give me an approximate number."
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_refill_day(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle refill day slot."""
        import re
        
        # STEP 1: Direct uncertainty check (highest priority)
        direct_uncertainty = [
            "dont know", "don't know", "do not know", "dunno", "idk", "dk",
            "not sure", "no idea", "no clue", "forgot", "forget",
            "cant remember", "can't remember", "don't recall", "dont recall",
            "i don't know", "i dont know", "i do not know", "i'm not sure",
            "i am not sure", "i have no idea", "i forgot", "i can't remember",
            "not certain", "not really sure", "haven't a clue", "drawing a blank"
        ]
        
        if user_text_lower in direct_uncertainty or any(phrase == user_text_lower for phrase in direct_uncertainty):
            logger.debug("Refill refill_day - Direct uncertainty match")
            response = "No problem! When you know approximately how many days until you need a refill, just let me know."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # STEP 2: Check for numbers (valid refill day)
        numbers = re.findall(r'\d+', user_text)
        
        if numbers:
            # Has numbers - might be valid refill day, let form validate
            logger.debug(f"Refill refill_day - Contains numbers: {numbers}, saving the exact text")
            return [
                SlotSet("refill_day", user_text.strip()),
                ActiveLoop(form_name)
            ]
        
        # STEP 3: Handle questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            logger.debug("Refill refill_day - Question detected")
            response = "I need to know when you'll need a refill. For example, 'in 7 days' or 'about 2 weeks'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # STEP 4: Handle vague time expressions
        time_phrases = {
            "soon": "soon, like in a few days?",
            "next week": "next week?",
            "this week": "this week?",
            "next month": "next month?",
            "couple days": "a couple of days?",
            "few days": "a few days?",
            "couple weeks": "a couple of weeks?",
            "few weeks": "a few weeks?"
        }
        
        for phrase, clarification in time_phrases.items():
            if phrase in user_text_lower:
                logger.debug(f"Refill refill_day - Vague time phrase '{phrase}' detected")
                response = f"When you say {clarification} I need the actual number of days to set up the reminder properly."
                attachment = send_response(response)
                dispatcher.utter_message(attachment=attachment)
                return [
                    ActiveLoop(form_name),
                    SlotSet("requested_slot", requested_slot),
                    FollowupAction("action_listen")
                ]
        
        # STEP 5: Handle day of week mentions
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for day in days:
            if day in user_text_lower:
                logger.debug(f"Refill refill_day - Day of week '{day}' detected")
                response = "To set up a refill reminder, I need to know in how many days you'll need a refill, not which day of the week."
                attachment = send_response(response)
                dispatcher.utter_message(attachment=attachment)
                return [
                    ActiveLoop(form_name),
                    SlotSet("requested_slot", requested_slot),
                    FollowupAction("action_listen")
                ]
        
        # STEP 6: Default response
        logger.debug("Refill refill_day - No pattern matched, asking again")
        response = "In how many days will you need a refill? Please give me a number, like '30' or '60'."
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]
    
    def handle_reminder_form(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle fallback for reminder form slots."""
        
        # ==================== PER DAY FREQUENCY HANDLING ====================
        if requested_slot == "per_day_frequency":
            return self._handle_per_day_frequency(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== ALERT TYPE HANDLING ====================
        elif requested_slot == "alert_type":
            return self._handle_alert_type(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== REMINDER DAY HANDLING ====================
        elif requested_slot == "reminder_day":
            return self._handle_reminder_day(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== FREQUENCY HANDLING ====================
        elif requested_slot == "frequency":
            return self._handle_frequency(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== QUANTITY HANDLING ====================
        elif requested_slot == "quantity":
            return self._handle_quantity(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # ==================== REMINDER TIME HANDLING ====================
        elif requested_slot == "reminder_time":
            return self._handle_reminder_time(dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name)
        
        # Default fallback for unknown slots
        logger.debug(f"No specific handler for slot '{requested_slot}' in reminder form - re-activating form")
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_per_day_frequency(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle per day frequency slot."""
        
        # FIRST: Check if this is an /inform command
        if user_text.startswith('/inform{'):
            logger.debug(f"Detected /inform command: {user_text}")
            try:
                import json
                # Extract the JSON part (remove '/inform' prefix)
                json_str = user_text[7:]  # Remove first 7 characters '/inform'
                data = json.loads(json_str)
                
                # Look for per_day_frequency in the JSON
                if 'per_day_frequency' in data:
                    frequency = data['per_day_frequency']
                    logger.debug(f"Extracted frequency from /inform: {frequency}")
                    
                    # Validate the extracted frequency
                    valid_frequencies = ["once", "twice", "thrice", "1", "2", "3", "one", "two", "three"]
                    if frequency in valid_frequencies:
                        return [SlotSet('per_day_frequency', frequency),
                                ActiveLoop(form_name)]
                    else:
                        # Invalid frequency in command
                        response = f"'{frequency}' is not a valid option. Please choose once, twice, or thrice."
                        attachment = send_response(response)
                        dispatcher.utter_message(attachment=attachment)
                        return [
                            ActiveLoop(form_name),
                            SlotSet("requested_slot", requested_slot),
                            FollowupAction("action_listen")
                        ]
            except (json.JSONDecodeError, IndexError) as e:
                logger.error(f"Failed to parse /inform command: {e}")
                # Fall through to normal handling
        
        # Original validation logic (now as fallback)
        valid_frequencies = ["once", "twice", "thrice", "1", "2", "3", "one", "two", "three"]
        
        # Check if user gave a valid frequency
        found_frequency = None
        for freq in valid_frequencies:
            if freq in user_text_lower:
                found_frequency = freq
                break
        
        if found_frequency:
            logger.debug(f"Valid frequency detected: '{found_frequency}' - Filling up the slot")
            return [SlotSet('per_day_frequency', found_frequency ),
                    ActiveLoop(form_name)]
        
        # Check for uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "That's okay! Common options are once, twice, or thrice per day. How many times a day would you like to take this medication?"
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Check for questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "I need to know how many times a day you take this medication. For example, 'once', 'twice', or 'thrice' daily."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Default response
        response = "How many times a day would you like to be reminded? (e.g., once, twice, thrice)"
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_alert_type(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle alert type slot."""
        
        # Valid alert types
        valid_types = ["voice", "alarm", "notification", "sound"]
        
        # Check if user gave a valid type
        found_type = None
        for alert_type in valid_types:
            if alert_type in user_text_lower:
                found_type = alert_type
                break
        
        if found_type:
            logger.debug(f"Valid alert type detected: '{found_type}' - letting form handle")
            return [ActiveLoop(form_name)]
        
        # Check for uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "That's okay! You can choose between 'voice' or 'alarm' for your reminder. Voice reads the medication name, alarm just makes a sound."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Check for questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "You can choose 'voice' for a spoken reminder that says the medication name, or 'alarm' for a standard notification sound."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Default response
        response = "Would you prefer a 'voice' reminder or an 'alarm'?"
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_reminder_day(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle reminder day slot."""
        
        # Valid days
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", 
                "mon", "tue", "wed", "thu", "fri", "sat", "sun", "weekdays", "weekends", "every day", "daily"]
        
        # Check if any day mentioned
        found_days = []
        for day in days:
            if day in user_text_lower:
                found_days.append(day)
        
        if found_days:
            logger.debug(f"Days detected: {found_days} - letting form handle")
            return [
                SlotSet('reminder_day', found_days),
                ActiveLoop(form_name)
            ]
        
        # Check for uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "That's okay! You can tell me which days of the week you need reminders, like 'Monday, Wednesday, Friday' or 'every day'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Check for questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "You can choose specific days like 'Monday and Thursday', or say 'every day' for daily reminders."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Handle vague responses
        vague_phrases = ["some days", "few days", "certain days", "specific days"]
        if any(phrase in user_text_lower for phrase in vague_phrases):
            response = "Which specific days would you like to be reminded? For example, 'Monday, Wednesday, Friday' or 'every day'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Default response
        response = "Which days would you like to be reminded? (e.g., 'Monday, Wednesday, Friday' or 'every day')"
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_frequency(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle frequency slot."""
        import re

        # Regex to find a number + optional space + time unit
        match = re.search(r'(\d+)\s*(day|days|week|weeks|month|months|year|years)', user_text_lower)

        if match:
            # Extract number + unit and save as frequency
            frequency_value = match.group(0)  # e.g., '5 days', '2 weeks'
            logger.debug(f"Frequency - Valid duration detected: {frequency_value}")
            return [
                SlotSet("frequency", frequency_value),
                ActiveLoop(form_name)
            ]

        # Check for numbers without units
        numbers = re.findall(r'\d+', user_text_lower)
        if numbers:
            logger.debug(f"Frequency - Numbers detected but no units: {numbers}")
            response = "Please include the time unit with the number, like '5 days' or '2 weeks'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]

        # Check for units without numbers
        time_units = ["day", "days", "week", "weeks", "month", "months", "year", "years"]
        has_units = any(unit in user_text_lower for unit in time_units)
        if has_units and not numbers:
            logger.debug("Frequency - Units without numbers detected")
            response = "I need both the number and time unit. For example, '30 days', '6 months', or '1 year'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]

        # Check for uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "No problem! You can tell me how long you need reminders, like '30 days', '6 months', or '1 year'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]

        # Check for questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "I need to know how long you'll be taking this medication. For example, '30 days', '6 months', or 'ongoing'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]

        # Handle vague responses
        vague_phrases = ["long time", "short time", "awhile", "a while", "not sure how long"]
        if any(phrase in user_text_lower for phrase in vague_phrases):
            response = "If you know approximately how long, that helps. Like '3 months' or '1 year'. If it's ongoing, just say 'ongoing'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]

        # Default response
        response = "How long would you like to receive reminders? (e.g., '30 days', '6 months', or 'ongoing')"
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_quantity(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle quantity slot."""
        import re
        
        # Check for numbers with units
        quantity_pattern = r'(\d+(?:\.\d+)?)\s*(mg|ml|mcg|g|iu|unit|units|tablet|tablets|capsule|capsules|pill|pills|drop|drops|puff|puffs|spray|sprays|injection|injections)'
        match = re.search(quantity_pattern, user_text, re.IGNORECASE)
        
        if match:
            number = match.group(1)
            unit = match.group(2).lower()

            # Normalize plural to singular
            if unit.endswith("s") and unit not in ["ms", "us"]:  # Avoid special cases
                unit = unit[:-1]

            quantity_value = f"{number} {unit}"
            logger.debug(f"Extracted quantity: {quantity_value}")

            return [
                SlotSet("quantity", quantity_value),
                ActiveLoop(form_name)
            ]
        
        # Check for numbers only
        numbers = re.findall(r'\d+', user_text)
        if numbers:
            logger.debug("Numbers detected but no units - might need clarification")
            response = "I see a number, but I need the unit too. For example, '500mg' or '5ml'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Check for units only
        units = ["mg", "ml", "mcg", "g", "iu", "unit", "tablet", "capsule", "pill", "drop"]
        has_units = any(unit in user_text_lower for unit in units)
        
        if has_units and not numbers:
            logger.debug("Units detected without numbers")
            response = "I need both the number and unit. For example, '500mg' or '5ml'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Check for uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "No problem! The quantity is usually shown on the prescription, like '500mg' or '5ml'. What does it say?"
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Check for questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "The quantity is the dose amount, usually shown with a number and unit like '500mg' or '10ml'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Default response
        response = "What's the quantity or dose? Please include both number and unit, like '500mg' or '5ml'."
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]

    def _handle_reminder_time(self, dispatcher, tracker, requested_slot, user_text, user_text_lower, form_name):
        """Handle reminder time slot."""
        import re
        
        # Check for time patterns
        time_patterns = [
            r'\d{1,2}:\d{2}\s*(am|pm)',  # 9:30 am, 14:30
            r'\d{1,2}\s*(am|pm)',         # 9 am, 2 pm
            r'\d{1,2}:\d{2}',              # 09:30, 14:30
            r'(morning|afternoon|evening|night|noon|midnight)'
        ]
        
        has_time = any(re.search(pattern, user_text, re.IGNORECASE) for pattern in time_patterns)
        
        if has_time:
            logger.debug("Time pattern detected - letting form handle")
            return [ActiveLoop(form_name)]
        
        # Check for multiple times (separated by and/&/,)
        if " and " in user_text_lower or " & " in user_text_lower or "," in user_text:
            logger.debug("Multiple times possible - letting form handle")
            return [ActiveLoop(form_name)]
        
        # Check for uncertainty
        unsure_phrases = ["don't know", "not sure", "no idea", "forget", "cant remember", "can't remember", "dunno"]
        if any(phrase in user_text_lower for phrase in unsure_phrases):
            response = "That's okay! You can tell me what time you'd like to be reminded, like '9 am' or '20:30'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Check for questions
        question_words = ["what", "why", "how", "when", "where", "which", "?"]
        if any(word in user_text_lower for word in question_words):
            response = "You can tell me the time in formats like '9 am', '14:30', or 'morning'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Handle vague time references
        vague_times = ["early", "late", "sometime", "whenever", "anytime"]
        if any(vague in user_text_lower for vague in vague_times):
            response = "I need a specific time for the reminder. For example, '9 am' or '20:30'."
            attachment = send_response(response)
            dispatcher.utter_message(attachment=attachment)
            return [
                ActiveLoop(form_name),
                SlotSet("requested_slot", requested_slot),
                FollowupAction("action_listen")
            ]
        
        # Default response
        response = "What time would you like to be reminded? (e.g., '9 am', '14:30', 'morning')"
        attachment = send_response(response)
        dispatcher.utter_message(attachment=attachment)
        return [
            ActiveLoop(form_name),
            SlotSet("requested_slot", requested_slot),
            FollowupAction("action_listen")
        ]
        
    def handle_openai_fallback(self, dispatcher, tracker):
        # If no form is active, use OpenAI fallback
        logger.debug("No active form - using OpenAI fallback")
        
        prompt = """You are 'Angela,' a helpful, trustworthy, and informative medical assistant. Follow these guidelines:
                    1.Respond to users’ health-related queries by providing clear, concise, and accurate information in a simple text to help them understand their concerns and direct them to appropriate resources.
                    2.Offer general health information and symptom assessments, but do not diagnose illnesses or prescribe medications.
                    3.If a user asks for medication recommendations, respond with: "I'm a simple medical assistant chatbot, and I'm not allowed to suggest any medication. Please consult a doctor or pharmacist for proper guidance."
                    4.Keep responses short, precise, and conversational, mimicking natural human interactions.
                    5.Emphasize the importance of consulting a doctor or pharmacist for medication advice.
                    6.Avoid giving specific dosages to prevent misuse.
                    7.Provide general information about side effects but direct users to reliable sources like medication leaflets or healthcare professionals for detailed guidance.
                    8.Do not assist with non-medical queries.
                    9.Offer only relevant information, ensuring it aligns with the user's needs.
                    10. If a user asks a non-medical question, respond with: "I'm a medical assistant, and I'm unable to help with your query."

                """  
        
        try:
            user_query = tracker.latest_message['text']
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "What's the best medication for my cough?"},
                    {"role": "assistant", "content": "I understand you're looking for relief from your cough. While I can't recommend specific medications, I suggest consulting a doctor if your cough persists."},
                    {"role": "user", "content": user_query}
                ]
            )
            data = response.choices[0].message.content

            reply = data  

            attachment = {
                "query_response": data,
                "data": [],
                "type": "text",
                "status": "success"
            }

        except openai.OpenAIError as e:
            error_message = e.args[0].split("message': '")[1].split("',")[0] if "message" in str(e) else "Unknown error occurred."
            messages = [
                "Sorry, I can't process your request right now due to high demand. Please try again later.",
                "Apologies, but it seems we're experiencing a temporary issue and cannot process your request at the moment. Please try again shortly."
            ]

            reply = random.choice(messages)  

            attachment = {
                "query_response": reply,
                "error": error_message,
                "data": [],
                "type": "text",
                "status": "failed"
            }

        except Exception as e:
            reply = "Can you rephrase it."  

            attachment = {
                "query_response": reply,
                "error": str(e),
                "data": [],
                "type": "text",
                "status": "failed"
            }

        dispatcher.utter_message(attachment=attachment)
        return []