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
                slot_loader = SlotLoader(tracker.sender_id)
                return slot_loader.load_all_slots(tracker)
        
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
        
        events = []
        
        # CRITICAL: Check for and deactivate any active forms
        if tracker.active_loop:
            form_name = tracker.active_loop.get("name")
            logger.info(f"Found active form '{form_name}' from previous session - deactivating")
            events.append(ActiveLoop(None))  # Deactivate the form
        
        # Reset all form-related slots to ensure clean state
        form_slots = [
            "medication_name", "medication_type", "medication_colour", 
            "medication_dose", "medication_instructions", "form_prompt",
            "fuzzy_result", "original_medication_input", 
            "pending_medication_confirmation", "stock_level", "refill_day",
            "frequency", "per_day_frequency", "quantity", "reminder_time",
            "alert_type", "reminder_day", "current_step", "requested_slot"
        ]
        
        for slot in form_slots:
            current_value = tracker.get_slot(slot)
            if current_value is not None:
                logger.debug(f"Clearing slot '{slot}' (was: {current_value})")
                events.append(SlotSet(slot, None))
        
        # Add action_listen for rule matching
        events.append(ActionExecuted("action_listen"))
        
        logger.info(f"Session initialized - active forms cleared, {len(events)} events created")
        logger.info(f"ActionSessionStart fired for sender: {tracker.sender_id}")
        return events
    
    def run(self, dispatcher, tracker, domain):
        logger.info("Starting session initialization")
        
        # SessionStarted MUST be first — it resets slots, 
        # so anything before it gets wiped
        events = [SessionStarted()]
        
        # Now load slots AFTER SessionStarted
        slot_loader = SlotLoader(tracker.sender_id)
        slot_events = slot_loader.load_all_slots(tracker)
        
        for event in slot_events:
            logger.debug(f"Loaded slot: {event}")
        
        events.extend(slot_events)
        
        # Run form cleanup and other session logic
        action_events = self.run_with_slots(dispatcher, tracker, domain)
        events.extend(action_events)
        
        logger.info(f"Session initialization complete with {len(events)} events")
        return events

class ActionHandleAppClosed(BaseAction):
    def name(self) -> Text:
        return "action_handle_app_closed"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        logger.info(f"App closed for sender: {tracker.sender_id}")
        
        events = []
        
        # Deactivate any active forms
        if tracker.active_loop:
            events.append(ActiveLoop(None))
        
        # Clear form slots (same list as above)
        form_slots = [
            "medication_name", "medication_type", "medication_colour", 
            "medication_dose", "medication_instructions", "form_prompt",
            "fuzzy_result", "original_medication_input", 
            "pending_medication_confirmation", "stock_level", "refill_day",
            "frequency", "per_day_frequency", "quantity", "reminder_time",
            "alert_type", "reminder_day", "current_step", "requested_slot",
            "pending_flow_type"
        ] 

        for slot in form_slots:
            if tracker.get_slot(slot) is not None:
                events.append(SlotSet(slot, None))
        
        return events
    
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
        logger.info(f"sender_id received: '{tracker.sender_id}'")
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

class ActionInitializeMedicationList(Action):

    def name(self) -> Text:
        return "action_initialize_medication_list"

    async def run(
        self, dispatcher, tracker, domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        logger.debug('ACTION INITIALIZE MEDICATION LIST')
        # Initialize MedManager with user's token
        medmanager = MedicationManager(token=tracker.sender_id)

        # Fetch all medications using your existing method
        all_meds = medmanager.get_all_medications() or {}
        logger.debug(f'FETCHED MED:  {all_meds}')

        # Extract medication names (assuming dict format)
        # e.g., {"medications": [{"name": "Paracetamol"}, {"name": "Ibuprofen"}]}
        medicine_list = [med.get("name") for med in all_meds.get("items", []) if med.get("name")]

        logger.debug(f'SLOTSET medicine_list : {medicine_list}')
        # Fill the slot so validate_medication_name can use it
        return [SlotSet("medicine_list", medicine_list),
                SlotSet('current_step', "medication_form")]
    
class ActionAskMedicationName(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_name"
    
    def _get_slot_from_events(self, tracker, slot_name, max_events=20):
        """Get slot value from events as fallback"""
        for event in reversed(tracker.events[-max_events:]):
            if event.get('event') == 'slot' and event.get('name') == slot_name:
                return event.get('value')
        return None
    
    def run_with_slots(self, dispatcher, tracker, domain):
        "Asks medication name to the user"

        # Log recent slot events
        events = tracker.events
        logger.debug("🔍 Recent slot events:")
        for event in events[-20:]:
            if event.get('event') == 'slot':
                logger.debug(f"  {event.get('name')} = {event.get('value')}")
        
        # Try to get prompt from current slot
        prompt = tracker.get_slot("form_prompt")
        
        # If not in current slot, check recent events
        if not prompt:
            prompt = self._get_slot_from_events(tracker, "form_prompt")
            logger.debug(f"Recovered prompt from events: {prompt}")
        
        # If still no prompt, infer from state
        if not prompt:
            # Check if medication was just set to None (duplicate case)
            med_name = tracker.get_slot("medication_name")
            last_med_events = []
            for event in reversed(tracker.events[-10:]):
                if event.get('event') == 'slot' and event.get('name') == 'medication_name':
                    last_med_events.append(event.get('value'))
            
            # If medication_name was recently set to None after having a value
            if None in last_med_events and any(v for v in last_med_events if v):
                logger.debug("Detected medication_name cleared - likely duplicate")
                prompt = "duplicate_name"

        fuzzy_result = tracker.get_slot('fuzzy_result')
        original_input = tracker.get_slot('original_medication_input')

        logger.debug(f'Prompt: {prompt}')
        logger.debug(f'Fuzzy result: {fuzzy_result}')
        logger.debug(f'in action_ask_medication_name original input: {original_input}')
        
        # Track if we need to clear the prompt
        clear_prompt = True
        
        if prompt == "multiple_meds":
            response_text = "Please provide only one medication at a time. Which one would you like to add?"
            dispatcher.utter_message(attachment={
                "query_response": response_text,
                "type": "text",
                "status": "success"
            })
            # Keep clear_prompt = True since we're done with this prompt
            
        elif prompt == "duplicate_name":
            response_text = "You already have this medicine saved. Can you give me a different medication name?"
            dispatcher.utter_message(attachment={
                "query_response": response_text,
                "type": "text",
                "status": "success"
            })
            # Keep clear_prompt = True since we're done with this prompt

        elif prompt == "fuzzy_match" and fuzzy_result:
            dispatcher.utter_message(attachment={
                "query_response": fuzzy_result, 
                "type": "text", 
                "status": "question"
            })
            
            # CRITICAL FIX: Get the medication_entities from the tracker
            entities = tracker.latest_message.get('entities', [])
            medication_entities = [e.get('value') for e in entities if e.get('entity') == 'medication_name']
            
            events_to_return = []
            # DON'T clear form_prompt here - we need it for the next validation
            clear_prompt = False  # ← Don't clear the prompt
            
            # If we have an entity, use it as original input
            if medication_entities:
                entity_value = medication_entities[0]
                logger.debug(f"SETTING original input from entity: {entity_value}")
                events_to_return.append(SlotSet("original_medication_input", entity_value))
            elif original_input:
                logger.debug(f"PRESERVING original input: {original_input}")
                events_to_return.append(SlotSet("original_medication_input", original_input))
            
            # Clear fuzzy_result but NOT form_prompt
            events_to_return.append(SlotSet("fuzzy_result", None))
            
            logger.debug(f"Returning events: {events_to_return}")
            
            # Return early with our events
            return events_to_return
        elif prompt == "fuzzy_match":
            response_text = "You already have this medicine saved. Can you give me a different medication name?"
            dispatcher.utter_message(attachment={
                "query_response": response_text,
                "type": "text",
                "status": "success"
            })
            
        else:
            builder = ResponseBuilder(tracker.sender_id, tracker)
            response = builder.build_response(intent="ask_medication_name")
            dispatcher.utter_message(attachment=response)
            # Keep clear_prompt = True for normal flow

        # Only clear form_prompt if we're done with it
        if clear_prompt:
            return [SlotSet("form_prompt", None)]
        else:
            return []  # Don't clear form_prompt

class ActionAskMedicationType(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_type"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks medication type from the user"""

        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_medication_type")
        
        # Buttons
        buttons = [
            {"title": "Antibiotic", "payload": "Antibiotic"},
            {"title": "Antidepressant", "payload": "Antidepressant"},
            {"title": "Painkiller", "payload": "Painkiller"},
        ]

        # attachment = send_response(response)
        attachment = send_response_with_buttons(response, buttons)
        dispatcher.utter_message(attachment=attachment)
        return []

class ActionAskMedicationColour(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_colour"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        """Asks medication colour from the user"""

        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_medication_colour")
        
        # Buttons
        buttons = [
            {"title": "Red", "payload": "Red"},
            {"title": "Blue", "payload": "Blue"},
            {"title": "Green", "payload": "Green"},
        ]

        # attachment = send_response(response)
        attachment = send_response_with_buttons(response, buttons)

        dispatcher.utter_message(attachment=attachment)
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
    
    def _is_duplicate_medication(self, medication_name: str, tracker: Tracker) -> bool:
        """Check if medication already exists in medicine_list slot (exact match, case-insensitive)."""
        medicine_list = tracker.get_slot("medicine_list") or []
        
        # Normalize for safe comparison
        normalized_existing = [m.lower().strip() for m in medicine_list]
        return medication_name.lower().strip() in normalized_existing
    
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

            # DUPLICATE CHECK
            if self._is_duplicate_medication(direct_med, tracker):
                logger.debug(f'DUPLICATE MED FOUND!')
                return {"medication_name": None, "form_prompt": "duplicate_name"}
            
            logger.debug('No duplicate med found')
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
        logger.debug(f"validate_medication_name called with slot_value: {slot_value}, original_medication_input value: {tracker.get_slot('original_medication_input')}, form_prompt: {tracker.get_slot('form_prompt')}")
        
        # CHECK 1: If we have a slot_value AND it came from a denial (original_input exists)
        original_input = tracker.get_slot('original_medication_input')
        intent = tracker.latest_message.get('intent', {}).get('name')
        text = tracker.latest_message.get('text', '').lower().strip()
        form_prompt = tracker.get_slot('form_prompt')

        # Skip validation if duplicate detected
        if form_prompt == "duplicate_name":
            logger.debug(f"RETURNING from validate with form_prompt=duplicate_name")
            logger.debug(f"Stack trace for debugging:", exc_info=True)  # This will show the call stack
            return {
                "medication_name": None,
                "form_prompt": "duplicate_name",
                "original_medication_input": original_input
            }
        
        # If this is a denial response with a valid slot_value, accept it immediately
        if (intent == "deny" or text.startswith(("no", "nope", "not"))) and slot_value:
            logger.debug(f"Denial response with slot_value: {slot_value} - running duplicate checking")
            final_name = slot_value.title()

            if self._is_duplicate_medication(final_name, tracker):
                return {
                    "medication_name": None,
                    "form_prompt": "duplicate_name",
                    "pending_medication_confirmation": None
                }
            
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
            logger.debug(f"Affirm response with slot_value: {slot_value} - running duplicate checking")
            final_name = slot_value.title()

            if self._is_duplicate_medication(final_name, tracker):
                return {
                    "medication_name": None,
                    "form_prompt": "duplicate_name",
                    "pending_medication_confirmation": None
                }
            
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
                    final_name = fuzzy_result.title()

                    # DUPLICATE CHECK
                    if self._is_duplicate_medication(final_name, tracker):
                        return {
                            "medication_name": None,
                            "form_prompt": "duplicate_name"
                        }

                    logger.debug(f"Fuzzy match accepted: {final_name}")
                    return {
                        "medication_name": final_name,
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
            
            # DUPLICATE CHECK
            if self._is_duplicate_medication(capitalized_name, tracker):
                return {
                    "medication_name": None,
                    "form_prompt": "duplicate_name"
                }

            return {
                "medication_name": capitalized_name,
                "original_medication_input": original_input,
                "requested_slot": "medication_type"
            }
        
        # Handle slot_value if present
        if slot_value and isinstance(slot_value, str):
            cleaned = slot_value.strip()
            if len(cleaned) >= 2:
                logger.debug(f"Accepting slot_value: {cleaned}")
                final_name = cleaned.title()

                # DUPLICATE CHECK
                if self._is_duplicate_medication(final_name, tracker):
                    return {
                        "medication_name": None,
                        "form_prompt": "duplicate_name"
                    }

                return {
                    "medication_name": final_name,
                    "original_medication_input": cleaned,
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
        
    async def extract_medication_instructions(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict
    ) -> Dict[Text, Any]:
        """Extract medication instructions."""
        
        # CRITICAL: Only run if we're currently asking for medication_instructions
        requested_slot = tracker.get_slot("requested_slot")
        logger.debug(f"extract_medication_instructions - requested_slot: '{requested_slot}'")
        
        if requested_slot != "medication_instructions":
            logger.debug(f"Skipping extract_medication_instructions - requested slot is '{requested_slot}'")
            return {}
        
        logger.debug('extract_medication_instructions called')
        
        # Get the raw user text
        user_text = tracker.latest_message.get('text', '').strip()
        user_text_lower = user_text.lower()
        logger.debug(f"extract_medication_instructions - user_text: '{user_text}'")
        
        # Comprehensive list of phrases that indicate no instructions (same as validation)
        none_patterns = [
            # Direct "none" variations
            'none', 'n/a', 'na', 'nil', 'null', 'zero', 'nope', 'no',
            
            # "No X" variations
            'no instructions', 'no instruction', 'no special instructions', 'no special instruction',
            'no specific instructions', 'no specific instruction', 'no particular instructions',
            'no particular instruction', 'no special', 'no specific', 'no particular',
            'no need', 'no needs', 'no required', 'no requirements', 'no requirement',
            
            # "Not X" variations
            'not needed', 'not required', 'not necessary', 'not applicable', 'not really',
            'not any', 'not anything', 'not special', 'not specific', 'not particular',
            'not really needed', 'not really required', 'not really necessary',
            "don't need", "don't have", "don't require", "don't want",
            "doesn't need", "doesn't have", "doesn't require", "doesn't want",
            "do not need", "do not have", "do not require", "do not want",
            "does not need", "does not have", "does not require", "does not want",
            
            # "Nothing" variations
            'nothing', 'nothing special', 'nothing specific', 'nothing particular',
            'nothing needed', 'nothing required', 'nothing to add', 'nothing else',
            'nothing more', 'nothing really', 'nothing at all',
            
            # "Skip" variations
            'skip', 'skip it', 'skip this', 'skip that', 'skipping', 'skip instructions',
            'skip the instructions', 'skip this step', 'skip that step',
            
            # "Without" variations
            'without instructions', 'without any instructions', 'without special instructions',
            'without anything', 'without any',
            
            # "I don't know" variations
            "i don't know", "i dont know", "i do not know", "dunno", "idk", "not sure",
            "i'm not sure", "i am not sure", "i don't think so", "i dont think so",
            "i don't think there are", "i dont think there are", "not that i know",
            
            # Short/common responses
            'none thanks', 'no thanks', 'no thank you', 'no thx',
            'none for me', 'not for me', 'nothing for me',
            'just none', 'just no', 'just skip',
            'leave blank', 'leave empty', 'blank', 'empty',
            
            # Casual
            'nah', 'naw', 'naa', 'no way', 'not at all',
            'none whatsoever', 'absolutely none', 'absolutely not',
            'definitely not', 'certainly not', 'surely not',
            'i have none', "i don't have any", "i dont have any",
            'there are none', "there aren't any", 'there are not any',
            
            # Medication-specific
            'no special directions', 'no special direction', 'no directions',
            'no direction', 'no special notes', 'no notes', 'no note',
            'no special considerations', 'no considerations',
            'just take it', 'just take', 'just consume', 'just use',
            'take as directed', 'take normally', 'use normally',
            'standard instructions', 'regular instructions', 'usual instructions',
            'follow prescription', 'follow label', 'follow bottle',
            'as prescribed', 'as directed', 'as usual', 'as normal',
            'like usual', 'like normal', 'same as always',
            
            # With "any"
            'any instructions? no', 'any special? no', 'any? no',
            'not any instructions', 'not any special', 'not any specific',
        ]
        
        # Check if user indicates no instructions
        if any(pattern in user_text_lower for pattern in none_patterns) or user_text_lower in none_patterns:
            logger.debug(f"User indicated no instructions with: '{user_text}' - returning as slot value")
            return {"medication_instructions": user_text}
        
        # For any other text, let the normal extraction happen
        # The form will automatically use the text as the slot value
        logger.debug("No special handling - letting form extract normally")
        return {}

    async def validate_medication_instructions(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Handle medication instructions."""
        
        logger.debug('######### VALIDATING MEDICATION INSTRUCTIONS STARTED #########')
        logger.debug(f"validate_medication_instructions called with slot_value: '{slot_value}', type: {type(slot_value)}")
        
        # Get the raw user text as well
        user_text = tracker.latest_message.get('text', '').lower().strip()
        
        logger.debug(f"User text: '{user_text}', Slot value: '{slot_value}'")
        
        # If slot_value is None, return None
        if slot_value is None:
            logger.debug("slot_value is None - returning None")
            return {"medication_instructions": None}
        
        # Words/phrases that indicate no instructions (your long list)
        none_phrases = [
        # Direct "none" variations
        'none', 'n/a', 'na', 'nil', 'null', 'zero', 'nope', 'no',
        
        # "No X" variations
        'no instructions', 'no instruction', 'no special instructions', 'no special instruction',
        'no specific instructions', 'no specific instruction', 'no particular instructions',
        'no particular instruction', 'no special', 'no specific', 'no particular',
        'no need', 'no needs', 'no required', 'no requirements', 'no requirement',
        
        # "Not X" variations
        'not needed', 'not required', 'not necessary', 'not applicable', 'not really',
        'not any', 'not anything', 'not special', 'not specific', 'not particular',
        'not really needed', 'not really required', 'not really necessary',
        "don't need", "don't have", "don't require", "don't want",
        "doesn't need", "doesn't have", "doesn't require", "doesn't want",
        "do not need", "do not have", "do not require", "do not want",
        "does not need", "does not have", "does not require", "does not want",
        
        # "Nothing" variations
        'nothing', 'nothing special', 'nothing specific', 'nothing particular',
        'nothing needed', 'nothing required', 'nothing to add', 'nothing else',
        'nothing more', 'nothing really', 'nothing at all',
        
        # "Skip" variations
        'skip', 'skip it', 'skip this', 'skip that', 'skipping', 'skip instructions',
        'skip the instructions', 'skip this step', 'skip that step',
        
        # "Without" variations
        'without instructions', 'without any instructions', 'without special instructions',
        'without anything', 'without any',
        
        # "I don't know" variations
        "i don't know", "i dont know", "i do not know", "dunno", "idk", "not sure",
        "i'm not sure", "i am not sure", "i don't think so", "i dont think so",
        "i don't think there are", "i dont think there are", "not that i know",
        
        # Short/common responses
        'none thanks', 'no thanks', 'no thank you', 'no thx',
        'none for me', 'not for me', 'nothing for me',
        'just none', 'just no', 'just skip',
        'leave blank', 'leave empty', 'blank', 'empty',
        
        # Casual
        'nah', 'naw', 'naa', 'no way', 'not at all',
        'none whatsoever', 'absolutely none', 'absolutely not',
        'definitely not', 'certainly not', 'surely not',
        'i have none', "i don't have any", "i dont have any",
        'there are none', "there aren't any", 'there are not any',
        
        # Medication-specific
        'no special directions', 'no special direction', 'no directions',
        'no direction', 'no special notes', 'no notes', 'no note',
        'no special considerations', 'no considerations',
        'just take it', 'just take', 'just consume', 'just use',
        'take as directed', 'take normally', 'use normally',
        'standard instructions', 'regular instructions', 'usual instructions',
        'follow prescription', 'follow label', 'follow bottle',
        'as prescribed', 'as directed', 'as usual', 'as normal',
        'like usual', 'like normal', 'same as always',
        
        # With "any"
        'any instructions? no', 'any special? no', 'any? no',
        'not any instructions', 'not any special', 'not any specific',
    ]
        
        # Check for "none" patterns in either slot_value or raw text
        text_to_check = user_text
        if slot_value and isinstance(slot_value, str):
            text_to_check = slot_value.lower().strip()
        
        logger.debug(f"Text to check for none patterns: '{text_to_check}'")
        
        # Check for "none" patterns
        is_none_response = any(
            phrase in text_to_check or text_to_check == phrase 
            for phrase in none_phrases
        )
        
        logger.debug(f"is_none_response: {is_none_response}")
        
        if is_none_response:
            logger.debug(f"User indicated no instructions (matched: '{text_to_check}')")
            result = {
                "medication_instructions": "None",
                "requested_slot": None  # Form is complete!
            }
            logger.debug(f"Returning (none case): {result}")
            return result
        
        # If user provides instructions
        if slot_value and isinstance(slot_value, str) and slot_value.strip():
            # Clean up the instructions
            instructions = slot_value.strip()
            
            # Capitalize first letter of the sentence
            if instructions and len(instructions) > 0:
                instructions = instructions[0].upper() + instructions[1:]
            
            result = {
                "medication_instructions": instructions,
                "requested_slot": None  # Form is complete!
            }
            logger.debug(f"Returning (normal case): {result}")
            return result
        
        # If we get here, no valid input
        logger.debug("No valid instructions provided - asking again")
        return {"medication_instructions": None}

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
            
        elif active_loop == "refill_form":
            logger.debug('Cancelling refill form')
            response = "Okay. I've stopped adding the refill information. What would you like to do next?"
            attachment = {
                "query_response": response,
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            
        elif active_loop == "reminder_form":
            logger.debug('Cancelling reminder form')
            response = "Okay. I have I've stopped adding the reminder. What would you like to do next?"
            attachment = {
                "query_response": response,
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            
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
                SlotSet("requested_slot", None),
                SlotSet("medication_name", None),
                SlotSet("medication_type", None),
                SlotSet("medication_colour", None),
                SlotSet("medication_dose", None),
                SlotSet("medication_instructions", None),
                SlotSet("pending_medication_confirmation", None),
                SlotSet("fuzzy_result", None),
                SlotSet("original_medication_input", None),
                SlotSet('form_prompt', None),
                SlotSet("requested_slot", None),
                SlotSet("requested_slot", None),
                SlotSet("frequency", None),
                SlotSet("frequency", None),
                SlotSet("per_day_frequency", None),
                SlotSet("quantity", None),
                SlotSet("reminder_time", None),
                SlotSet("alert_type", None),
                SlotSet("reminder_day", None),
                SlotSet("stock_level", None),
                SlotSet("refill_day", None),
                SlotSet("current_step", None),
                SlotSet('form_interrupted', False),
                SlotSet('medication', None),
                SlotSet('pending_flow_type', None)
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
            SlotSet("medication_id", medication_id),
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
        
        # Get the active form
        active_loop = tracker.active_loop.get("name") if tracker.active_loop else None
        logger.debug(f"Active loop: {active_loop}")

        # Map form names to display text
        form_display = {
            "medication_form": "adding a medication",
            "refill_form": "setting up refill information",
            "reminder_form": "setting up a reminder"
        }

        # Get the appropriate display text for the current form
        current_action = form_display.get(active_loop, "completing a task")

         # Pass to ResponseBuilder
        builder = ResponseBuilder(tracker.sender_id, tracker)

        if intent == "greet":
            logger.debug('Form interrupted with Greet intent. Asking for cancel confirmation')
            response = builder.build_response(
                intent="greet-form", 
                current_action=current_action  # Pass the context
            )
            logger.debug(f'Response: {response}')
            dispatcher.utter_message(attachment=response)

            return [
                SlotSet("form_interrupted", True)
            ]
        
        else:
            response = builder.build_response(
                intent="form-interrupt",
                current_action=current_action  # Pass the context
            )

            logger.debug(f'Response: {response}')
            dispatcher.utter_message(attachment=response)

            return [
                SlotSet("form_interrupted", True)
            ]

class ActionGetMedicationId(Action):
    def name(self):
        return "action_get_medication_id"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.debug('Running Action_get_medication_id')
        
        # Check if we're returning with a medication name from a previous question
        pending_flow = tracker.get_slot("pending_flow_type")
        logger.debug(f'pending_flow: {pending_flow}')
        intent = tracker.latest_message.get('intent', {}).get('name')
        if pending_flow == None: 
            is_refill_flow = intent == "add_refill"
            is_reminder_flow = intent == "add_reminder"
        elif pending_flow == "refill":
            is_refill_flow = True
            is_reminder_flow = False
        elif pending_flow == "reminder":
            is_refill_flow = False
            is_reminder_flow = True
        else:
            is_refill_flow = False
            is_reminder_flow = False
        logger.debug(f'is_refill_flow: {is_refill_flow}, is_reminder_flow: {is_reminder_flow}')
        # Get medication name from different sources
        medication_name = None
        
        if pending_flow:
            # Get medication name from slot (set by _handle_medication_mention) or entities
            medication_name = tracker.get_slot("medication")
            if not medication_name:
                medication_name = next(tracker.get_latest_entity_values('medication'), None)
            if not medication_name:
                medication_name = tracker.latest_message.get('text', '').strip()
            logger.debug(f"Processing response for pending {pending_flow} flow: {medication_name}")
            
        # 1. Check if medication was provided in the current message
        medication_entity = next(tracker.get_latest_entity_values('medication'), None)
        if medication_entity:
            medication_name = medication_entity
            logger.debug(f"Found medication in entities: {medication_name}")
        
        # 2. If no medication found, ask for it
        if not medication_name:
            logger.debug('No medication name provided')
            if is_refill_flow:
                response = "Which medication would you like to set up the refill information for?"
            elif is_reminder_flow:
                response = "Which medication would you like to set up the reminder for?"
            else:
                response = "Which medication are you referring to?"
            
            attachment = {
                "query_response": response,
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            
            # Store the flow type in a slot so we know what to do when user responds
            return [
                SlotSet("pending_flow_type", "refill" if is_refill_flow else "reminder"),
                FollowupAction("action_listen")  # Wait for user response
            ]
        
        # We have a medication name, now find it in the user's medications
        try:           
            token = tracker.sender_id
            manager = MedicationManager(token)
            
            # Try to find the medication by name
            medication = manager.get_medication_by_name(medication_name)
            
            if medication:
                # Medication exists - get its ID
                medication_id = medication.get("id")
                medication_name = medication.get("name")  # Use the exact name from system
                
                logger.debug(f"Found medication: {medication_name} with ID: {medication_id}")
                
                # Check if there's existing refill info (for refill flow)
                if is_refill_flow and medication.get("refill_periods"):
                    logger.debug("Checking if there's existing refill information")
                    # Medication has refill periods - inform user
                    if len(medication["refill_periods"]) > 0:
                        logger.debug('Found refill information')
                        refill_date = medication["refill_periods"][0].get("refill_date", "Unknown")
                        response = f"You already have refill information for {medication_name}. The next refill is due on {refill_date}. Would you like to update it?"
                        
                        attachment = {
                            "query_response": response,
                            "type": "text",
                            "status": "success"
                        }
                        dispatcher.utter_message(attachment=attachment)
                        
                        # Still proceed to refill form to allow updates
                        return [
                            SlotSet("medication_id", medication_id),
                            SlotSet("pending_flow_type", 'refill'),
                            FollowupAction("action_listen")
                        ]
                logger.debug(medication.get('reminder'))
                # Check if there's existing reminder info (for reminder flow)
                if is_reminder_flow:
                    logger.debug('Inside reminder flow')
                    reminder_data = medication.get("reminder")
                    
                    id = reminder_data['id']
                    logger.debug(f'Reminder id: {id}')
                    # Check if reminder exists and has required fields
                    if reminder_data and isinstance(reminder_data, dict) and reminder_data.get("id"):
                        logger.debug('Found existing reminder information')
                        response = f"You already have reminders set up for {medication_name}. Would you like to update existing one?"
                        
                        attachment = {
                            "query_response": response,
                            "type": "text",
                            "status": "success"
                        }
                        dispatcher.utter_message(attachment=attachment)
                        
                        # Still proceed to reminder form to allow additions
                        return [
                            SlotSet("medication_id", medication_id),
                            SlotSet('reminder_id', id),
                            SlotSet("pending_flow_type", 'reminder'),
                            FollowupAction("action_listen")
                        ]
                    else:
                        logger.debug('No existing reminder found')
                
                # No existing info or proceeding with new entry
                if is_refill_flow:
                    logger.debug('No refill information found')
                    return [
                        SlotSet("medication_id", medication_id),
                        SlotSet('pending_flow_type', None),
                        SlotSet('medication', None),
                        FollowupAction("refill_form")
                    ]
                elif is_reminder_flow:
                    return [
                        SlotSet("medication_id", medication_id),
                        SlotSet("pending_flow_type", None),
                        SlotSet('medication', None),
                        FollowupAction("reminder_form")
                    ]
                else:
                    return [FollowupAction("action_listen")]
            
            else:
                # Medication not found in user's list
                response = f"I couldn't find {medication_name} in your medication list. Would you like to add it first?"
                
                attachment = {
                    "query_response": response,
                    "type": "text",
                    "status": "success"
                }
                dispatcher.utter_message(attachment=attachment)
                
                # Set the medication name slot and activate medication form
                return [
                    SlotSet("medication_name", medication_name),
                    SlotSet("pending_flow_type", "medication_form"),
                    FollowupAction("action_listen")
                ]
                
        except Exception as e:
            logger.error(f"Error in ActionGetMedicationId: {e}")
            response = "I'm having trouble finding that medication. Please try again."
            attachment = {
                "query_response": response,
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
            return [FollowupAction("action_listen")]
        
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
        
        logger.debug("ActionAskStockLevel - Basic ask")
        
        # Just the basic question - fallback handles all edge cases
        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_stock_level")
        dispatcher.utter_message(attachment=response)
        
        return []

class ActionAskRefillDay(BaseAction):
    def name(self) -> Text:
        return "action_ask_refill_day"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        "Asks refill days to the user"
        
        logger.debug("ActionAskRefillDay - Basic ask")
        
        # Just the basic question - fallback handles all edge cases
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
        logger.debug("="*80)
        logger.debug("REQUIRED_SLOTS DEBUG:")
        logger.debug(f"Active loop: {tracker.active_loop}")
        logger.debug(f"Requested slot: {tracker.get_slot('requested_slot')}")
        logger.debug("="*80)
        
        all_slots = ["stock_level", "refill_day"]
        
        required = []
        for slot in all_slots:
            if tracker.get_slot(slot) is None:
                required.append(slot)
        
        logger.debug(f"Required slots: {required}")
        return required

    async def validate_stock_level(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Minimal validation for stock level."""
        
        logger.debug('######### VALIDATING STOCK LEVEL #########')
        
        # Extract numbers from the text
        import re
        text = tracker.latest_message.get("text", "")
        numbers = re.findall(r'\d+', text)
        
        if not numbers:
            # No numbers found - validation fails, fallback will handle
            logger.debug("No numbers found for stock level")
            return {"stock_level": None}
        
        try:
            stock = int(numbers[0])
            
            # Basic validation: must be positive
            if stock < 0:
                logger.debug(f"Negative stock level: {stock}")
                return {"stock_level": None}
            
            # Valid stock level
            logger.debug(f"Valid stock level: {stock}")
            return {"stock_level": stock}
            
        except (ValueError, TypeError):
            logger.debug(f"Invalid stock level value")
            return {"stock_level": None}

    async def validate_refill_day(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Minimal validation for refill day."""
        
        logger.debug('######### VALIDATING REFILL DAY #########')
        
        # Extract numbers from the text
        import re
        text = tracker.latest_message.get("text", "")
        numbers = re.findall(r'\d+', text)
        
        if not numbers:
            # No numbers found - validation fails, fallback will handle
            logger.debug("No numbers found for refill day")
            return {"refill_day": None}
        
        try:
            days = int(numbers[0])
            
            # Basic validation: reasonable range (1-365 days)
            if days < 1 or days > 365:
                logger.debug(f"Refill day out of range: {days}")
                return {"refill_day": None}
            
            # Valid refill day
            logger.debug(f"Valid refill day: {days}")
            return {"refill_day": days}
            
        except (ValueError, TypeError):
            logger.debug(f"Invalid refill day value")
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
        logger.debug(f"Current step: {tracker.get_slot('current_step')}")
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
        medication_id = tracker.get_slot("medication_id")
        
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
            "user_medication_id": medication_id,
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
        
        # Success   
        builder = ResponseBuilder(token=tracker.sender_id) 
        current_step = tracker.get_slot('current_step')
        if current_step == None:
            current_step = None
            response = builder.build_response(intent='submit_refill_no_reminder')
        else:
            current_step = 'ask_reminder'
            response = builder.build_response(intent='submit_refill')
        dispatcher.utter_message(attachment=response)

        return [
            ActiveLoop(None),  # Deactivate refill form
            SlotSet("current_step", current_step),
            SlotSet('stock_level', None),
            SlotSet('refill_day', None),
            SlotSet('pending_flow_type', None)
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
            {"title": "Once", "payload": "once"},
            {"title": "Twice", "payload": "twice"},
            {"title": "Thrice", "payload": "thrice"},
        ]

        # attachment = send_response(response)
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

        # Buttons
        buttons = [
            {"title": "Voice", "payload": "Voice"},
            {"title": "Alarm", "payload": "Alarm"}
        ]

        # attachment = send_response(response)
        attachment = send_response_with_buttons(response, buttons)

        dispatcher.utter_message(attachment=attachment)
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
    
import re
from typing import Any, Dict, Text, Optional
from rasa_sdk import Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.forms import FormValidationAction
import logging

logger = logging.getLogger(__name__)

class ValidateReminderForm(FormValidationAction):
    """Validates slots for reminder form with smart dependency handling."""
    
    def name(self) -> Text:
        return "validate_reminder_form"

    @staticmethod
    def normalize_time_unit(number: int, unit: str) -> str:
        """Normalize time unit to proper singular/plural form."""
        unit = unit.lower().rstrip('s')  # Remove trailing 's' for base form
        
        # Map to proper plural
        unit_map = {
            "day": "days",
            "week": "weeks", 
            "month": "months",
            "year": "years"
        }
        
        if number == 1:
            return f"{number} {unit}"
        else:
            return f"{number} {unit_map.get(unit, unit + 's')}"
        
    async def extract_frequency(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict
    ) -> Dict[Text, Any]:
        """
        Minimal function to extract frequency from user message.
        Checks NLU entities first, then falls back to pattern matching.
        """
        logger.debug('EXTRACTING FREQUENCY')

        requested_slot = tracker.get_slot('requested_slot')
        if requested_slot != 'frequency':
            logger.debug(f'Skipping extract_frequency!! requested_slot: {requested_slot}')
            return {}
        
        # 1. Check for time_period entity from NLU
        for entity in tracker.latest_message.get("entities", []):
            if entity.get("entity") == "time_period":
                logger.debug('Extracting from entity')
                return {"frequency": entity.get("value")}  # Return as dict
        
        # 2. Fallback: extract from text
        text = tracker.latest_message.get("text", "").lower().strip()

        if not text:
            logger.debug('Not text')
            return {}  # Return empty dict, not None
        
        # Match patterns like "30 days", "2 weeks", "1 month", "a week"
        patterns = [
            r'(\d+)\s*(day|days|week|weeks|month|months|year|years)',
            r'(a|an)\s+(day|week|month|year)',
            r'in\s+(\d+)\s*(day|days|week|weeks|month|months|year|years)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                if groups[0] in ['a', 'an']:
                    return {"frequency": f"1 {groups[1]}"}  # Return as dict
                else:
                    return {"frequency": f"{groups[0]} {groups[1]}"}  # Return as dict
        
        # Check if just a number (assume days)
        if re.match(r'^\d+$', text):
            return {"frequency": f"{text} days"}  # Return as dict
        
        return {}  # Return empty dict if nothing found

    async def validate_frequency(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate and normalize frequency (e.g., '30 days', '2 weeks', 'a month')."""
        logger.debug('VALIDATING FREQUENCY')
        requested_slot = tracker.get_slot('requested_slot')
        if requested_slot != "frequency":
            return {"frequency": slot_value}  # Don't validate if not requested
        
        current_step = tracker.get_slot('current_step')
        intent = tracker.latest_message.get("intent", {}).get("name")
        
        # Handle confirmation flow
        if current_step == "pending_confirmation":
            if intent == "affirm":
                return {'requested_slot': 'frequency'}
            elif intent == "deny":
                return {"form_prompt": "deny_redo"}
        
        # If no value provided, try to extract from entities first
        if not slot_value:
            # Check if there's a time_period entity from NLU
            entities = tracker.latest_message.get("entities", [])
            for entity in entities:
                if entity.get("entity") == "time_period":
                    slot_value = entity.get("value")
                    logger.debug(f"Extracted frequency from entity: {slot_value}")
                    break
            
            if not slot_value:
                return {"frequency": None}

        value = str(slot_value).lower().strip()

        # Handle "a week", "a month", "an hour" (from your training data)
        if value.startswith("a ") or value.startswith("an "):
            value = value.replace("a ", "1 ").replace("an ", "1 ")

        # Pattern for time periods: number + time unit
        # Supports: days, weeks, months, years (singular/plural)
        time_unit_pattern = r"^(\d+)\s*(day|days|week|weeks|month|months|year|years)$"
        
        # Also handle "1week" without space
        time_unit_no_space = r"^(\d+)(day|days|week|weeks|month|months|year|years)$"
        
        match = re.match(time_unit_pattern, value)
        if not match:
            match = re.match(time_unit_no_space, value)
        
        if not match:
            # Check if it's just a number (assume days)
            number_only = re.match(r"^(\d+)$", value)
            if number_only:
                number = int(number_only.group(1))
                unit = "days" if number != 1 else "day"
                normalized = f"{number} {unit}"
                logger.debug(f"Assumed number {number} as {normalized}")
                return {"frequency": normalized}
            
            # Check for common phrases from your training data
            if "in " in value:
                # Extract number from phrases like "in 30 days"
                in_pattern = r"in\s+(\d+)\s*(day|days|week|weeks|month|months|year|years)"
                in_match = re.search(in_pattern, value)
                if in_match:
                    number = int(in_match.group(1))
                    unit = in_match.group(2)
                    normalized = self.normalize_time_unit(number, unit)
                    return {"frequency": normalized}
            
            # dispatcher.utter_message(
            #     text="Please tell me for how long. For example: '30 days', '2 weeks', or '1 month'."
            # )
            return {"frequency": None}

        number = int(match.group(1))
        unit = match.group(2)

        if number <= 0:
            dispatcher.utter_message(text="The duration must be greater than 0.")
            return {"frequency": None}

        # Normalize plural properly
        normalized = self.normalize_time_unit(number, unit)
        return {"frequency": normalized}
    
    async def validate_quantity(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate quantity of medication (supports units like mg, ml, IU, tablets)."""
        logger.debug('VALIDATING QUANTITY')
        requested_slot = tracker.get_slot('requested_slot')
        if requested_slot != "quantity":
            return {"quantity": slot_value}  # Don't validate if not requested
        
        # If no value provided, try to extract from entities
        if not slot_value:
            entities = tracker.latest_message.get("entities", [])
            for entity in entities:
                if entity.get("entity") == "medication_dosage":
                    slot_value = entity.get("value")
                    logger.debug(f"Extracted quantity from entity: {slot_value}")
                    break
            
            if not slot_value:
                return {"quantity": None}

        value = str(slot_value).lower().strip()
        
        # Extract quantity with unit (based on your training data)
        # Patterns: "10 mg", "5 ml", "100 IU", "1 tablet", etc.
        
        # Pattern for number + unit
        unit_pattern = r"^(\d+(?:\.\d+)?)\s*([a-z]+)$"
        match = re.match(unit_pattern, value)
        
        if match:
            quantity_num = float(match.group(1))
            unit = match.group(2).lower()
            
            # Validate that quantity is positive
            if quantity_num <= 0:
                # dispatcher.utter_message(text="The quantity must be greater than 0.")
                return {"quantity": None}
            
            # Store as float but preserve the unit information
            # You might want to store unit separately or combine
            formatted_quantity = f"{quantity_num} {unit}"
            logger.debug(f"Extracted quantity with unit: {formatted_quantity}")
            
            # Provide context with medication dose if available
            # medication_dose = tracker.get_slot("medication_dose")
            # if medication_dose:
            #     dispatcher.utter_message(
            #         text=f"Perfect! I'll remind you to take {formatted_quantity} ({medication_dose} strength) each time."
            #     )
            # else:
            #     dispatcher.utter_message(text=f"Got it! {formatted_quantity} each time.")
            
            # Store as float for calculations, but we have the full string if needed
            return {"quantity": quantity_num}
        
        # Try to extract just a number (assume pills/tablets)
        number_pattern = r"^(\d+(?:\.\d+)?)$"
        number_match = re.match(number_pattern, value)
        
        if number_match:
            quantity_num = float(number_match.group(1))
            
            if quantity_num <= 0:
                dispatcher.utter_message(text="The quantity must be greater than 0.")
                return {"quantity": None}
            
            # Determine if it's likely tablets/pills
            unit = "tablet" if quantity_num == 1 else "tablets"
            formatted = f"{quantity_num} {unit}"
            
            medication_dose = tracker.get_slot("medication_dose")
            
            return {"quantity": quantity_num}
        
        # Check for word numbers (one, two, etc.)
        word_to_number = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "a": 1, "an": 1, "single": 1, "double": 2, "triple": 3
        }
        
        if value in word_to_number:
            quantity_num = word_to_number[value]
            unit = "tablet" if quantity_num == 1 else "tablets"
            formatted = f"{quantity_num} {unit}"
            
            medication_dose = tracker.get_slot("medication_dose")
            
            return {"quantity": quantity_num}
        
        # If nothing matches
        # dispatcher.utter_message(
        #     text="Please enter a valid quantity with units. For example: '10 mg', '5 ml', or '1 tablet'."
        # )
        return {"quantity": None}

    async def validate_per_day_frequency(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate how many times per day (once, twice, thrice)."""
        logger.debug('VALIDATING PER_DAY_FREQUENCY')
        requested_slot = tracker.get_slot('requested_slot')
        if requested_slot != "per_day_frequency":
            return {"per_day_frequency": slot_value}
        
        if not slot_value:
            # Try to extract from medication_instructions if that was the intent
            intent = tracker.latest_message.get("intent", {}).get("name")
            if intent == "provide_medication_instructions":
                entities = tracker.latest_message.get("entities", [])
                for entity in entities:
                    if entity.get("entity") == "medication_instructions":
                        instructions = entity.get("value", "").lower()
                        # Map common instructions to frequency
                        if "once" in instructions or "daily" in instructions:
                            slot_value = "once"
                        elif "twice" in instructions:
                            slot_value = "twice"
                        elif "thrice" in instructions or "three times" in instructions:
                            slot_value = "thrice"
                        logger.debug(f"Mapped medication_instructions '{instructions}' to '{slot_value}'")
                        break
            
            if not slot_value:
                return {"per_day_frequency": None}
        
        value = str(slot_value).lower().strip()
        
        # Normalize common variations
        frequency_map = {
            "once": "once",
            "1": "once",
            "one": "once",
            "single": "once",
            "1 time": "once",
            "once daily": "once",
            "once a day": "once",
            "qd": "once",  # medical abbreviation
            
            "twice": "twice",
            "2": "twice",
            "two": "twice",
            "double": "twice",
            "2 times": "twice",
            "twice daily": "twice",
            "twice a day": "twice",
            "bid": "twice",  # medical abbreviation
            
            "thrice": "thrice",
            "3": "thrice",
            "three": "thrice",
            "triple": "thrice",
            "3 times": "thrice",
            "three times daily": "thrice",
            "three times a day": "thrice",
            "tid": "thrice",  # medical abbreviation
        }
        
        for key, normalized in frequency_map.items():
            if key in value or value == key:
                logger.debug(f"Mapped '{value}' to '{normalized}'")
                # dispatcher.utter_message(text=f"Got it! I'll remind you {normalized} daily.")
                return {"per_day_frequency": normalized}
        
        # If no match
        # dispatcher.utter_message(
        #     text="How many times a day should I remind you? Please say 'once', 'twice', or 'thrice'."
        # )
        return {"per_day_frequency": None}
    
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
        
        logger.debug('VALIDATING REMINDER TIME')
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
            # dispatcher.utter_message(
            #     text="Please enter a valid time like '8 am', '20:30', '6 in the morning', or 'eight thirty am'."
            # )
            return {"reminder_time": None}

        # Remove duplicates while preserving order
        seen = set()
        normalized_times = [t for t in normalized_times if not (t in seen or seen.add(t))]

        return {"reminder_time": normalized_times}

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
        logger.debug(f"current_step: {tracker.get_slot('current_step')}")
        medication_id = tracker.get_slot("medication_id")
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
            "user_medication_id": medication_id,
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

        current_step = tracker.get_slot('current_step')
        id = tracker.get_slot('reminder_id')
        if current_step == None or id != None:
            reminder_data['id'] = id
            success, message = medmanager.update_reminder(reminder_data)
        else:
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
                SlotSet("reminder_day", None),
                SlotSet('pending_flow_type', None)
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
                # Create structured data array with each medication as an item
                medications_data = [
                    {
                        "name": name,
                        "value": "",
                    }
                    for idx, name in enumerate(medication_names)
                ]
                
                builder = ResponseBuilder(tracker.sender_id, tracker)
                attachment = builder.build_response(
                    "list_medications",
                    data=medications_data,  # Pass as data array
                    count=len(medication_names)  # Still pass count for the text
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
        
        return [SlotSet('period', None)]
    
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
        
class ActionSymptoms(Action):
    """Action to fetch and show user's symptoms."""
    
    def name(self) -> Text:
        return "action_symptoms"
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.info("Starting action_symptoms")
        
        try:
            from .helpers.symptoms_manager import symptoms_manager
            from .helpers.response_builder import ResponseBuilder
            
            # Create ResponseBuilder
            builder = ResponseBuilder(tracker.sender_id, tracker)
            
            # Get period from slot
            period = tracker.get_slot('period')
            
            # Handle different period values
            days_map = {
                "day": 1,
                "week": 7,
                "month": 30,
                "3 months": 90,
                "year": 365
            }
            
            # Default to month if no period or invalid period
            if not period or period not in days_map:
                logger.debug(f"No valid period provided, defaulting to month")
                period = "month"
                days = 30
            else:
                days = days_map[period]
                logger.debug(f"Period: {period}, looking back {days} days")
            
            # Handle special case for "day" - show today's symptoms
            if period == "day":
                time_context = "today"
            else:
                time_context = f"last {period}"
            
            logger.debug(f"Fetching symptoms for period: {period} ({time_context})")
            
            # Use symptoms_manager to get symptoms
            symptoms_data = symptoms_manager.get_symptoms(tracker.sender_id)
            
            if not symptoms_data:
                logger.info("No symptoms data returned from API")
                attachment = {
                    "query_response": f"You have no recorded symptoms.",
                    "data": [],
                    "type": "string",
                    "status": "success"
                }
                dispatcher.utter_message(attachment=attachment)
                return []
            
            # Format symptoms for display, filtered by period
            # Pass the actual days value for more precise filtering
            formatted_symptoms = symptoms_manager.format_symptoms_list(
                symptoms_data, 
                period=period,
                days=days
            )
            
            if not formatted_symptoms:
                logger.info(f"No symptoms found for {time_context}")
                
                # Custom message based on period
                if period == "day":
                    message = "You have no recorded symptoms for today."
                elif period == "week":
                    message = "You have no recorded symptoms for the last 7 days."
                elif period == "month":
                    message = "You have no recorded symptoms for the last 30 days."
                elif period == "3 months":
                    message = "You have no recorded symptoms for the last 3 months."
                elif period == "year":
                    message = "You have no recorded symptoms for the last year."
                else:
                    message = f"You have no recorded symptoms for the last {period}."
                
                attachment = {
                    "query_response": message,
                    "data": [],
                    "type": "string",
                    "status": "success"
                }
                dispatcher.utter_message(attachment=attachment)
                return [SlotSet("symptoms_available", True)]
            
            # Build response with appropriate message based on period
            if period == "day":
                reply = f"Here are the symptoms you experienced today:"
            elif period == "week":
                reply = f"Here are the symptoms you experienced in the last 7 days:"
            elif period == "month":
                reply = f"Here are the symptoms you experienced in the last 30 days:"
            elif period == "3 months":
                reply = f"Here are the symptoms you experienced in the last 3 months:"
            elif period == "year":
                reply = f"Here are the symptoms you experienced in the last year:"
            else:
                reply = f"Here are your symptoms:"
            
            attachment = {
                "query_response": reply,
                "data": formatted_symptoms,
                "type": "array",
                "status": "success"
            }
            
            dispatcher.utter_message(attachment=attachment)
            logger.info(f"Successfully returned {len(formatted_symptoms)} symptoms for {time_context}")
            
            # Clear the period slot after use
            return [SlotSet("symptoms_available", True), 
                    SlotSet('period', None)]
            
        except Exception as e:
            logger.error(f"Error getting symptoms: {e}", exc_info=True)
            
            # Try to get period for error message, default to empty string
            try:
                period = tracker.get_slot('period') or "requested"
            except:
                period = "requested"
                
            reply = f"Failed to get your {period} symptoms. Please try again."
            attachment = {
                "query_response": reply,
                "data": [],
                "type": "string",
                "status": "failed"
            }
            dispatcher.utter_message(attachment=attachment)
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
            "Authorization": f"Bearer {tracker.sender_id}"
        }
        
        # Initialize date variable to None
        date = None
        
        try:
            response = requests.post(url, headers=header)
            response_data = response.json()["result"]["items"]
            
            for data in response_data:
                if data["name"].lower() == medication_name.lower() and len(data["refill_periods"]) > 0:
                    # Remove the trailing comma which was creating a tuple
                    date = data["refill_periods"][0]["refill_date"]
                    break  # Exit loop once found
            
            if date:
                messages = ["Refill date of your medication ", 
                           "Refill date for your prescription ",
                           "Refill date regarding your medication "]
                response = random.choice(messages)
                reply = f"{response} {medication_name} is {date}"
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
                
        except Exception as ex:
            reply = "Failed to get information about medication refill. Please try again!!"
            attachment = {
                "query_response": reply,
                "data": [],
                "type": "string",
                "status": "failed"
            }
        
        dispatcher.utter_message(attachment=attachment)
        
        return [SlotSet("medication", None)]
    
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
        return[SlotSet("period", None)]
    
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
        
        return [SlotSet("period", None)]
    
        
class ActionCustomFallback(Action):
    def __init__(self):
        # Load medications from CSV
        self.medications_df = pd.read_csv('data/medications.csv')
        self.KNOWN_MEDICATIONS = self.medications_df['medication_name'].tolist()

        # Pattern-based responses for non-intent matches
        self.PATTERN_RESPONSES = [
            {
                "patterns": [
                    r"what (can|ca)n? (you|u) do", 
                    r"help", 
                    r"features", 
                    r"capabilities",
                    r"what (?:do|does) (?:you|u) (?:do|have)"
                ],
                "response": "I can help you manage your medications! You can:\n• Add new medications\n• List your medications\n• Check today's medications\n• Request refills\n• Set reminders\n• Track symptoms\nWhat would you like to do?"
            },
            {
                "patterns": [
                    r"thank you|thanks|appreciate it|thankyou|thx"
                ],
                "response": "You're welcome! Let me know if you need anything else with your medications."
            },
            {
                "patterns": [
                    r"how (?:do|can|to) (?:set|create) reminder",
                    r"how (?:do|to) set up reminder"
                ],
                "response": "To set a reminder, just say 'set reminder' or 'remind me to take my medication' and I'll help you set it up!"
            },
            {
                "patterns": [
                    r"how (?:do|can|to) request refill",
                    r"how (?:do|to) (?:get|ask for) refill"
                ],
                "response": "To request a refill, simply say 'request refill' or 'I need a refill' and I'll assist you!"
            },
            {
                "patterns": [
                    r"what is this bot|who are you|what are you"
                ],
                "response": "I'm Angela, your medical assistant! I'm here to help you manage your medications, set reminders, and track your health."
            },
            {
                "patterns": [
                    r"(?:good|great|excellent|awesome|nice) (?:job|work|bot)"
                ],
                "response": "Thank you! I'm glad I could help. Let me know if you need anything else!"
            },
            {
                "patterns": [
                    r"i (?:want|need|would like) to talk to (?:a|the) (?:human|person|agent|doctor)"
                ],
                "response": "I understand you'd like to speak with a human. While I'm here to help with medication management, for urgent medical concerns, please consult your doctor or pharmacist directly."
            }
        ]

        # Medication name patterns for identifying potential medication mentions
        self.MEDICATION_PATTERNS = [
            r'\b[A-Z][a-z]+(?:[-\s][A-Z][a-z]+)*\b',  # Capitalized words
            r'\b(?:ibuprofen|paracetamol|aspirin|amoxicillin|lisinopril|metformin|atorvastatin|omeprazole|levothyroxine|simvastatin)\b',
            r'\b(?:lipitor|synthroid|norvasc|prinivil|glucophage|lasix|prednisone|zoloft|prozac|xanax)\b'  # Brand names
        ]

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
                return [SlotSet("medication_name", match.title()),
                        ActiveLoop(form_name)]
            
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
                    SlotSet('original_medication_input', user_text_lower),
                    FollowupAction("action_listen")
                ]
            
            # Low confidence 
            logger.debug("Low fuzzy confidence - storing raw input as medication_name")
            return [
                SlotSet("medication_name", user_text_lower),
                ActiveLoop(form_name)
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
        
        # Check if we're waiting for a medication name after asking for it
        pending_flow = tracker.get_slot("pending_flow_type")
        if pending_flow and not form_name:
            logger.debug(f"Have pending flow: {pending_flow} - processing medication name")
            
            # The user just provided a medication name - process it
            try:
                
                token = tracker.sender_id
                manager = MedicationManager(token)
                
                # Try to find the medication by name
                medication = manager.get_medication_by_name(user_text)
                
                if medication:
                    # Medication exists - get its ID
                    medication_id = medication.get("id")
                    medication_name = medication.get("name")
                    
                    logger.debug(f"Found medication: {medication_name} with ID: {medication_id}")
                    
                    # Check existing info and activate appropriate form
                    if pending_flow == "refill":
                        if medication.get("refill_periods") and len(medication["refill_periods"]) > 0:
                            refill_date = medication["refill_periods"][0].get("refill_date", "Unknown")
                            response = f"You already have refill information for {medication_name}. The next refill is due on {refill_date}. Would you like to update it?"
                            
                            attachment = {
                                "query_response": response,
                                "data": [],
                                "type": "text",
                                "status": "question"
                            }
                            dispatcher.utter_message(attachment=attachment)
                        
                        return [
                            SlotSet("medication_id", medication_id),
                            SlotSet("pending_flow_type", None),
                            FollowupAction("refill_form")
                        ]
                        
                    elif pending_flow == "reminder":
                        if medication.get("reminders") and len(medication["reminders"]) > 0:
                            response = f"You already have reminders set up for {medication_name}. Would you like to add another reminder?"
                            
                            attachment = {
                                "query_response": response,
                                "data": [],
                                "type": "text",
                                "status": "question"
                            }
                            dispatcher.utter_message(attachment=attachment)
                        
                        return [
                            SlotSet("medication_id", medication_id),
                            SlotSet("pending_flow_type", None),
                            FollowupAction("reminder_form")
                        ]
                else:
                    # Medication not found
                    response = f"I couldn't find {user_text} in your medication list. Would you like to add it first?"
                    attachment = {
                        "query_response": response,
                        "data": [],
                        "type": "text",
                        "status": "question"
                    }
                    dispatcher.utter_message(attachment=attachment)
                    
                    return [
                        SlotSet("medication_name", user_text),
                        SlotSet("pending_flow_type", "medication_form"), 
                        FollowupAction("action_listen")
                    ]
            except Exception as e:
                logger.error(f"Error processing pending flow: {e}")
                return [FollowupAction("action_listen")]
        
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
        """Handle only cases that don't match existing intents"""
        logger.debug("----------------------------------------")
        logger.debug("🔧 CUSTOM FALLBACK - No intent matched")
        
        user_query = tracker.latest_message.get('text', '').strip()
        user_query_lower = user_query.lower()
        
        # Get the intent that was matched (if any)
        intent = tracker.latest_message.get('intent', {}).get('name')
        intent_confidence = tracker.latest_message.get('intent', {}).get('confidence', 0)
        
        logger.debug(f"Original intent: {intent} (confidence: {intent_confidence})")
        logger.debug(f"User query: '{user_query}'")
        
        # ========== HANDLE AFFIRM/DENY INTENTS WITH PENDING FLOW ==========
        if intent in ["affirm", "deny"]:
            result = self._handle_affirm_deny(dispatcher, tracker, intent)
            if result:
                return result
            
        # CRITICAL FIX: Check if this is actually a refill query
        # Look for refill-related keywords in the query
        refill_keywords = ['refill', 'due']
        has_refill_keywords = any(keyword in user_query_lower for keyword in refill_keywords)
        
        # If it has refill keywords and contains a medication mention, it's likely a refill query
        if has_refill_keywords and self._is_likely_medication_mention(user_query):
            logger.debug("Detected refill query with medication - redirecting to action_refill_information")
            
            # Extract medication name if present in entities
            medication_slot = tracker.get_slot('medication')
            medication_entity = next(tracker.get_latest_entity_values('medication'), None)
            medication_name = medication_slot or medication_entity
            
            if medication_name:
                # Set the medication slot and trigger refill action
                return [
                    SlotSet("medication", medication_name),
                    FollowupAction("action_refill_information")
                ]
            else:
                # Try to extract medication from text
                # This is a simplified extraction - you might want to enhance this
                words = user_query.split()
                for word in words:
                    if word[0].isupper() and len(word) > 2:  # Likely a medication name
                        return [
                            SlotSet("medication", word),
                            FollowupAction("action_refill_information")
                        ]
                
                # If we can't extract medication, ask for it
                response = "Which medication would you like to check the refill date for?"
                attachment = {
                    "query_response": response,
                    "data": [],
                    "type": "text",
                    "status": "question"
                }
                dispatcher.utter_message(attachment=attachment)
                return [FollowupAction("action_listen")]
        
        # ========== HANDLE PENDING FLOW + MEDICATION ==========
        pending_flow = tracker.get_slot("pending_flow_type")

        if pending_flow in ["refill", "reminder"]:
            logger.debug(f"Pending flow detected: {pending_flow}")

            medication_name = None

            # 1. Try BOTH entity types (medication + medication_name)
            for entity_key in ["medication", "medication_name"]:
                medication_name = next(tracker.get_latest_entity_values(entity_key), None)
                if medication_name:
                    logger.debug(f"Medication found via entity: {entity_key} = {medication_name}")
                    break

            # 2. STRICT: fallback ONLY to current message text (no memory, no slot)
            if not medication_name:
                if self._is_likely_medication_mention(user_query):
                    medication_name = user_query.strip()
                    logger.debug(f"Medication inferred from text: {medication_name}")

            # 3. FINAL SAFETY CHECK: prevent stale slot reuse
            if medication_name:
                # ensure it actually appears in current message
                if medication_name.lower() not in user_query.lower():
                    logger.debug("Rejecting stale or mismatched medication value")
                    medication_name = None

            # 4. If valid medication found → continue flow
            if medication_name:
                return [
                    SlotSet("medication", medication_name),
                    FollowupAction("action_get_medication_id")
                ]

            # 5. If still not found → ask user clearly
            response = "Which medication are you referring to?"

            dispatcher.utter_message(
                attachment={
                    "query_response": response,
                    "data": [],
                    "type": "text",
                    "status": "question"
                }
            )

            return [FollowupAction("action_listen")]

        # STRATEGY 1: Pattern matching for common questions
        import re
        for pattern_config in self.PATTERN_RESPONSES:
            for pattern in pattern_config["patterns"]:
                if re.search(pattern, user_query_lower):
                    logger.debug(f"Pattern matched: '{pattern}'")
                    return self._send_response(dispatcher, pattern_config["response"])

        # If no patterns match, use OpenAI
        logger.debug("No patterns matched - using OpenAI fallback")
        return self._fallback_response(dispatcher, tracker)

    def _handle_affirm_deny(self, dispatcher, tracker, intent):
        """Handle affirm and deny intents when there's a pending flow"""
        
        pending_flow = tracker.get_slot("pending_flow_type")
        
        if not pending_flow:
            return None  # No pending flow to handle
        
        # Handle AFFIRM intent
        if intent == "affirm":
            logger.debug(f"User affirmed pending {pending_flow} flow")
            
            if pending_flow == "refill":
                return [FollowupAction("refill_form")]
            elif pending_flow == "reminder":
                return [FollowupAction("reminder_form")]
            elif pending_flow == "medication_form":
                return[FollowupAction("medication_form")]
            else:
                # Clear pending flow if unknown
                return [SlotSet("pending_flow_type", None), FollowupAction("action_listen")]
        
        # Handle DENY intent
        if intent == "deny":
            logger.debug(f"User denied pending {pending_flow} flow")
            
            if pending_flow == 'refill' or pending_flow == 'reminder' or pending_flow == 'medication_form':
                # Clear the pending flow and ask what they want to do next
                response = "Okay, what would you like me to help you with next?"
                attachment = {
                    "query_response": response,
                    "data": [],
                    "type": "text",
                    "status": "question"
                }
                dispatcher.utter_message(attachment=attachment)
                
                return [
                    SlotSet("pending_flow_type", None),
                    FollowupAction("action_listen")
                ]
        
        return None  # Not affirm or deny

    def _is_likely_medication_mention(self, text):
        """Check if text might be mentioning a medication"""
        text_lower = text.lower()
        
        # Check against known medications from CSV
        for med in self.KNOWN_MEDICATIONS[:50]:  # Check first 50
            if med.lower() in text_lower:
                return True
        
        # Check against medication patterns
        import re
        for pattern in self.MEDICATION_PATTERNS:
            if re.search(pattern, text):
                return True
        
        # Check for common medication suffixes
        med_suffixes = ['mycin', 'prazole', 'dipine', 'cillin', 'lol', 'sartan', 'vir', 'navir']
        if any(suffix in text_lower for suffix in med_suffixes):
            return True
        
        return False
    
    def _handle_medication_mention(self, dispatcher, tracker, text):
        """Generate response for medication mention, checking for pending flows first"""
        
        # Check if we have a pending flow (user was asked for medication name)
        pending_flow = tracker.get_slot("pending_flow_type")
        
        if pending_flow in ["refill", "reminder"]:
            logger.debug(f"Medication mention detected with pending {pending_flow} flow")
            
            # Extract medication name from the text
            # You might want to enhance this extraction logic
            medication_name = text.strip()
            logger.debug(f'medication_name = {medication_name}')
            # Check if there's a medication entity in the message
            medication_entity = next(tracker.get_latest_entity_values('medication'), None)
            if medication_entity:
                medication_name = medication_entity
            
            # The user is responding to our question about which medication
            # Set the medication slot and let action_get_medication_id handle it
            return [
                SlotSet("medication", medication_name),  # Set the medication slot
                FollowupAction("action_get_medication_id")
            ]
        
        # No pending flow - show the generic menu
        return f"I notice you mentioned '{text}'. If you'd like to manage this medication, you can say:\n• 'add medication' to add it to your list\n• 'check dosage' for dosage information\n• 'set reminder' to create a reminder\n• 'check refill' for refill status"

    def _send_response(self, dispatcher, text):
        """Send a text response"""
        attachment = {
            "query_response": text,
            "type": "text",
            "status": "success"
        }
        dispatcher.utter_message(attachment=attachment)
        return []
    
    def _fallback_response(self, dispatcher, tracker ):
        """Send a text response"""
        
        responses = [
            "I’m a medical assistant, and that’s currently outside my scope of support.",
            "As a medical assistant, I’m not able to help with that request right now.",
            "I’m here as a medical assistant, so I’m limited in what I can assist with, and this falls outside that.",
            "I’m a medical assistant, and I’m not equipped to handle that request at the moment.",
            "That seems to be beyond what I can support as a medical assistant right now.",
            "I’m currently limited in my role as a medical assistant, so I can’t assist with that.",
            "As a medical assistant, I can only help with certain types of queries, and this is outside my scope.",
            "I’m here to support as a medical assistant, but I’m unable to help with that request.",
            "That’s outside what I can currently assist with in my role as a medical assistant.",
            "I’m a medical assistant, so I have some limitations, and I can’t help with that right now."
        ]
        
        response = random.choice(responses)

        attachment = {
            "query_response": response,
            "type": "text",
            "status": "success"
        }
        dispatcher.utter_message(attachment=attachment)
        return []

    # def _openai_fallback(self, dispatcher, tracker):
    #     """Your existing OpenAI fallback logic"""
    #     logger.debug("Using OpenAI fallback")
        
    #     prompt = """You are 'Angela,' a helpful, trustworthy, and informative medical assistant. Follow these guidelines:
    #                 1.Respond to users’ health-related queries by providing clear, concise, and accurate information in a simple text to help them understand their concerns and direct them to appropriate resources.
    #                 2.Offer general health information and symptom assessments, but do not diagnose illnesses or prescribe medications.
    #                 3.If a user asks for medication recommendations, respond with: "I'm a simple medical assistant chatbot, and I'm not allowed to suggest any medication. Please consult a doctor or pharmacist for proper guidance."
    #                 4.Keep responses short, precise, and conversational, mimicking natural human interactions.
    #                 5.Emphasize the importance of consulting a doctor or pharmacist for medication advice.
    #                 6.Avoid giving specific dosages to prevent misuse.
    #                 7.Provide general information about side effects but direct users to reliable sources like medication leaflets or healthcare professionals for detailed guidance.
    #                 8.Do not assist with non-medical queries.
    #                 9.Offer only relevant information, ensuring it aligns with the user's needs.
    #                 10. If a user asks a non-medical question, respond with: "I'm a medical assistant, and I'm unable to help with your query."
    #             """  
        
    #     try:
    #         user_query = tracker.latest_message['text']
    #         import openai
    #         response = openai.chat.completions.create(
    #             model="gpt-4o",
    #             messages=[
    #                 {"role": "system", "content": prompt},
    #                 {"role": "user", "content": "What's the best medication for my cough?"},
    #                 {"role": "assistant", "content": "I understand you're looking for relief from your cough. While I can't recommend specific medications, I suggest consulting a doctor if your cough persists."},
    #                 {"role": "user", "content": user_query}
    #             ]
    #         )
    #         data = response.choices[0].message.content

    #         attachment = {
    #             "query_response": data,
    #             "data": [],
    #             "type": "text",
    #             "status": "success"
    #         }

    #     except Exception as e:
    #         logger.error(f"OpenAI error: {e}")
    #         attachment = {
    #             "query_response": "I'm having trouble processing your request right now. Please try again later.",
    #             "data": [],
    #             "type": "text",
    #             "status": "failed"
    #         }

    #     dispatcher.utter_message(attachment=attachment)
    #     return []