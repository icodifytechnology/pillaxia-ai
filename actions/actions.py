import re
from dotenv import load_dotenv
from typing import Any, Text, Dict, List, Optional, Tuple
import logging
from abc import ABC, abstractmethod

from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta

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
            dispatcher.utter_message(text="Hello! Nice to see you.")
        
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
            dispatcher.utter_message(text="Goodbye! Take care.")
        
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
            dispatcher.utter_message(text=error_message)
        
        logger.debug("Bot identity query handled successfully")
        return []

class ActionAskMedicationName(BaseAction):
    def name(self) -> Text:
        return "action_ask_medication_name"
    
    def run_with_slots(self, dispatcher, tracker, domain):
        "Asks medication name to the user"

        builder = ResponseBuilder(tracker.sender_id, tracker)
        response = builder.build_response(intent="ask_medication_name")
        dispatcher.utter_message(attachment=response)
        return []

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
    def name(self) -> Text:
        return "validate_medication_form"

    async def _ask_for_next_slot(
        self,
        slot_to_fill: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict]:
        """Override the default slot asking behavior to use custom attachment format."""
        
        # Define your slot questions
        slot_questions = {
            "medication_name": "What is the name of the medication you would like to add?",
            "medication_type": "What type of medication is this? (e.g., Antidepressant, Painkiller, Antibiotic, etc.)",
            "medication_colour": "What color would you like to associate with the medication? (Choose from: red, blue, white, yellow, green, orange, purple, pink, black, grey, brown)",
            "medication_dose": "What is the dosage? (e.g., 500mg, 10ml, 1 tablet)",
            "medication_instructions": "Any special instructions for taking this medication? (e.g., take with food, take before bed, etc.)"
        }
        
        # Get the question text
        question = slot_questions.get(
            slot_to_fill, 
            f"Please provide {slot_to_fill.replace('_', ' ')}"
        )
        
        # Send in the custom attachment format
        dispatcher.utter_message(
            attachment={
                "query_response": question,
                "type": "text",
                "status": "success"
            }
        )
        return []
    
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
            "medication_name", 
            "medication_type", 
            "medication_colour",
            "medication_dose", 
            "medication_instructions"
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
    
    # async def extract_medication_name(
    #     self,
    #     dispatcher: CollectingDispatcher,
    #     tracker: Tracker,
    #     domain: Dict[Text, Any],
    # ) -> Dict[Text, Any]:
    #     """Extract medication name - only when form is asking for it."""
        
    #     requested_slot = tracker.get_slot("requested_slot")
    #     text = tracker.latest_message.get("text", "").strip()
    #     intent = tracker.latest_message.get("intent", {}).get("name", "")
        
    #     logger.debug(f"Extracting medication name. Requested slot: {requested_slot}, Intent: {intent}, Text: '{text}'")
        
    #     # # Only proceed if we're asking for medication_name AND user said something
    #     # if requested_slot != "medication_name" or not text:
    #     #     return {}

    #     # # ============ INTENT VALIDATION ============
    #     # # If the intent is wrong, reject without message - form will re-ask
    #     # if intent != "provide_medication_name" and intent != "add_medication":
    #     #     logger.debug(f"Rejecting - intent '{intent}' is not 'provide_medication_name'")
    #     #     dispatcher.utter_message("Please provide the name of the medication.")
    #     #     return {}  # Just return empty - form's utter_ask will handle the re-prompt
    #     # # ===========================================
        
    #     # if intent == "cancel_medication_form":
    #     #     dispatcher.utter_message(response="utter_ask_continue", medication_name=text)

    #     # if intent == "add_medication":
    #     #     dispatcher.utter_message("Great! Let's add a new medication. What is the name of the medication?")
    #     # logger.debug(f"✓ Accepting '{text}' as medication_name")
        
    #     # Validate and return
    #     validation_result = await self.validate_medication_name(text, dispatcher, tracker, domain)
    #     return validation_result
    
    # async def extract_medication_type(
    #     self,
    #     dispatcher: CollectingDispatcher,
    #     tracker: Tracker,
    #     domain: Dict[Text, Any],
    # ) -> Dict[Text, Any]:
    #     """Extract medication type."""
        
    #     requested_slot = tracker.get_slot("requested_slot")
    #     text = tracker.latest_message.get("text", "").strip()
        
    #     if requested_slot == "medication_type" and text:
    #         logger.debug(f"✓ Accepting '{text}' as medication_type")
    #         return {"medication_type": text}
        
    #     return {}
    
    # async def extract_medication_colour(
    #     self,
    #     dispatcher: CollectingDispatcher,
    #     tracker: Tracker,
    #     domain: Dict[Text, Any],
    # ) -> Dict[Text, Any]:
    #     """Extract medication colour."""
        
    #     requested_slot = tracker.get_slot("requested_slot")
    #     text = tracker.latest_message.get("text", "").strip()
        
    #     if requested_slot == "medication_colour" and text:
    #         logger.debug(f"✓ Accepting '{text}' as medication_colour")
    #         return {"medication_colour": text}
        
    #     return {}
    
    # async def extract_medication_dose(
    #     self,
    #     dispatcher: CollectingDispatcher,
    #     tracker: Tracker,
    #     domain: Dict[Text, Any],
    # ) -> Dict[Text, Any]:
    #     """Extract medication dose."""
        
    #     requested_slot = tracker.get_slot("requested_slot")
    #     text = tracker.latest_message.get("text", "").strip()
        
    #     if requested_slot == "medication_dose" and text:
    #         logger.debug(f"✓ Accepting '{text}' as medication_dose")
    #         return {"medication_dose": text}
        
    #     return {}
    
    # async def extract_medication_instructions(
    #     self,
    #     dispatcher: CollectingDispatcher,
    #     tracker: Tracker,
    #     domain: Dict[Text, Any],
    # ) -> Dict[Text, Any]:
    #     """Extract medication instructions."""
        
    #     requested_slot = tracker.get_slot("requested_slot")
    #     text = tracker.latest_message.get("text", "").strip()
        
    #     if requested_slot == "medication_instructions" and text:
    #         logger.debug(f"✓ Accepting '{text}' as medication_instructions")
    #         return {"medication_instructions": text}
        
    #     return {}
        
    async def validate_medication_name(
    self,
    slot_value: Any,
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
    domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate medication name."""
        logger.debug('######### Validating medication name #########')
        
        if not slot_value:
            return {"medication_name": None}
        
        if len(slot_value.strip()) < 2:
            return {"medication_name": None}
        
        # Check if it's a common type/colour that shouldn't be a name
        common_types = ["pill", "tablet", "capsule", "liquid", "injection", "cream", "ointment"]
        if slot_value.lower() in common_types:
            dispatcher.utter_message(f"'{slot_value}' sounds like a medication type. Please provide the specific medication name.")
            return {"medication_name": None}
        
        common_colours = ["red", "blue", "white", "yellow", "green", "orange", "purple", "pink", "black", "grey", "brown"]
        if slot_value.lower() in common_colours:
            dispatcher.utter_message(f"'{slot_value}' is a colour. I need the medication name first.")
            return {"medication_name": None}
        
        logger.debug(f"Valid medication name: {slot_value.strip()}")
        
        return {
            "medication_name": slot_value.strip()
        }

    async def validate_medication_type(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        logger.debug('Validating medication type')
        if not slot_value or len(slot_value.strip()) < 2:
            dispatcher.utter_message("Please specify the medication type.")
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
            dispatcher.utter_message(
                f"Please choose from these colours: {', '.join(valid_colours)}. "
                f"Which colour would you like?"
            )
            return {"medication_colour": None}

    async def validate_medication_dose(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        if not slot_value:
            dispatcher.utter_message("Please provide the dosage.")
            return {"medication_dose": None}
        
        if not re.search(r'\d+', slot_value):
            dispatcher.utter_message("Please include the dosage amount (e.g., 500 mg).")
            return {"medication_dose": None}
        
        return {"medication_dose": slot_value.strip()}

    async def validate_medication_instructions(
    self,
    slot_value: Any,
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
    domain: Dict[Text, Any],
) -> Dict[Text, Any]:
        """Handle medication instructions."""
        
        logger.debug("="*80)
        logger.debug(f"VALIDATE_MEDICATION_INSTRUCTIONS called with: '{slot_value}'")
        logger.debug("="*80)
        
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
        dispatcher.utter_message(
            "You haven't provided any instructions. Is that correct? "
            "(say 'yes' to continue, or provide instructions)"
        )
        result = {"medication_instructions": None}
        logger.debug(f"Returning (empty case): {result}")
        return result

class ActionCancelForm(BaseAction):
    """Cancells the active form."""

    def name(self) -> Text:
        return "action_cancel_form"
    
    def run_with_slots(self, dispatcher, tracker, domain):

        if ActiveLoop == "medication_form":
            response = "Okay. I have cancelled the medication adding process. What would you like to do next?"
            attachment = {
                "query_response": response,
                "data": [],
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
        
            # THIS is where deactivation happens
            return [
                ActiveLoop(None),  # Deactivate the form
                SlotSet("requested_slot", None),  # Clear requested slot
                SlotSet("medication_name", None),  # Clear form data
                SlotSet("medication_type", None),
                SlotSet("medication_colour", None),
                SlotSet("medication_dose", None),
                SlotSet("medication_instructions", None)
            ]
        elif ActiveLoop == "refill_form":
            response = "Okay. I have cancelled the refill information adding process. What would you like to do next?"
            attachment = {
                "query_response": response,
                "data": [],
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
        
            # THIS is where deactivation happens
            return [
                ActiveLoop(None),  # Deactivate the form
                SlotSet("requested_slot", None),  # Clear requested slot
                SlotSet("stock_level", None),  # Clear form data
                SlotSet("refill_day", None)
            ]
        elif ActiveLoop == "reminder_form":
            response = "Okay. I have cancelled the reminder adding process. What would you like to do next?"
            attachment = {
                "query_response": response,
                "data": [],
                "type": "text",
                "status": "success"
            }
            dispatcher.utter_message(attachment=attachment)
        
            # THIS is where deactivation happens
            return [
                ActiveLoop(None),  # Deactivate the form
                SlotSet("requested_slot", None),  # Clear requested slot
                SlotSet("frequency_type", None),  # Clear form data
                SlotSet("frequency_period", None),
                SlotSet('time_period', None),
                SlotSet("quantity", None),
                SlotSet('reminder_time', None),
                SlotSet("alert_type", None),
                SlotSet('reminder_day', None),
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

        # Collect medication data
        medmanager = MedicationManager(token=tracker.sender_id)
        colour = medmanager.color_to_hex(tracker.get_slot("medication_colour"))
        logger.debug(f"Converted colour '{tracker.get_slot('medication_colour')}' to hex: {colour}")

        medication_data = {
            "name": tracker.get_slot("medication_name"),
            "medication_type": tracker.get_slot("medication_type"),
            "colour": colour,
            "dose": tracker.get_slot("medication_dose"),
            "instructions": tracker.get_slot("medication_instructions") or "",
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
            return [
                ActiveLoop(None),
                SlotSet("current_step", None)
            ]
        
        # Use ResponseBuilder for success + refill prompt
        response = builder.build_response(intent='submit_medication')
        dispatcher.utter_message(attachment=response)

        return [
            ActiveLoop(None),  # Deactivate medication form
            SlotSet("current_step", "ask_refill"),
            SlotSet("user_medication_id", medication_id)
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

        if intent == "deny" or intent == "skip":
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

    async def _ask_for_next_slot(
        self,
        slot_to_fill: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict]:
        """Override the default slot asking behavior to use custom attachment format."""
        
        # Define your slot questions
        slot_questions = {
            "stock_level": "How many pills/units do you currently have in stock?",
            "refill_day": "In how many days would you need to refill the medication?"
        }
        
        # Get the question text
        question = slot_questions.get(
            slot_to_fill, 
            f"Please provide {slot_to_fill.replace('_', ' ')}"
        )
        
        # Send in the custom attachment format
        dispatcher.utter_message(
            attachment={
                "query_response": question,
                "type": "text",
                "status": "success"
            }
        )
        return []
    
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
        
        # If intent is wrong but value is numeric, try to extract anyway
        if intent != "provide_stock_level" and intent != "provide_medication_dose":
            return {"stock_level": None}
        
        # Try to extract number from text
        try:
            # If slot_value is already a number
            if slot_value is not None:
                stock = int(slot_value)
            else:
                # Try to extract number from text
                import re
                numbers = re.findall(r'\d+', text)
                if numbers:
                    stock = int(numbers[0])
                else:
                    dispatcher.utter_message("Please enter a valid number for stock level.")
                    return {"stock_level": None}
            
            if stock < 0:
                dispatcher.utter_message("Please enter a positive number for stock level.")
                return {"stock_level": None}
            
            if stock < 7:
                dispatcher.utter_message(f"Only {stock} left? You might need a refill soon!")
            
            return {"stock_level": stock}
        except (ValueError, TypeError):
            dispatcher.utter_message("Please enter a valid number for stock level.")
            return {"stock_level": None}

    async def validate_refill_day(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate refill period in days and calculate actual date."""
        
        logger.debug("="*80)
        logger.debug(f"VALIDATE_refill_day called with: '{slot_value}'")
        logger.debug("="*80)
        
        if slot_value is None:
            return {"refill_day": None}
        
        try:
            days = int(slot_value)
            
            if days <= 0:
                response = {
                     "query_response": "Please enter a positive number of days (e.g., 30 for one month).",
                     "type": "text",
                     "status": "success"
                    }
                dispatcher.utter_message(attachment=response)
                return {"refill_day": None}
            
            if days > 365:
                dispatcher.utter_message("That's more than a year! Please enter a number of days (1-365).")
                return {"refill_day": None}
            
            return {
                "refill_day": days,
            }
            
        except (ValueError, TypeError):
            dispatcher.utter_message("Please enter a valid number of days (e.g., 7, 30, 90).")
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

        # Collect refill data
        refill_data = {
            "user_medication_id": tracker.get_slot("user_medication_id"),
            "stock_level": int(tracker.get_slot("stock_level")),
            "refill_day": int(tracker.get_slot("refill_day"))}

        if refill_data:
            logger.debug(f"refill_data:{refill_data}")

            # Save refill data
            medmanager = MedicationManager(token=tracker.sender_id)
            success, message = medmanager.save_refill(refill_data)

            if not success: 
                response = "Sorry, I couldn't save your refill information. Would you like to try again?"
                attachment = {
                "query_response": response,
                "type": "text",
                "status": "success"
                }
                return [
                    ActiveLoop(None),
                    SlotSet("current_step", None)
                ]
            
            # Initialize ResponseBuilder with sender token
            builder = ResponseBuilder(token=tracker.sender_id)
            
            response = builder.build_response(intent='submit_refill')
            dispatcher.utter_message(attachment=response)
            return [
                ActiveLoop(None),  # Deactivate refill form
                SlotSet("current_step", "ask_reminder")
            ]
        
        else:
            logger.debug(f"No refill data")
            return []

class ValidateReminderForm(FormValidationAction):
    """Validates slots for reminder form with smart dependency handling."""
    
    def name(self) -> Text:
        return "validate_reminder_form"
    
    async def required_slots(
        self,
        domain_slots: List[Text],
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Text]:
        """Dynamically determine required slots based on user choices."""
        required_slots = []
        
        # If wants_reminders is not set, ask it first
        if tracker.get_slot("wants_reminders") is None:
            return ["wants_reminders"]
        
        # If user doesn't want reminders, we're done
        if tracker.get_slot("wants_reminders") is False:
            return []
        
        # User wants reminders, check what's already filled
        slots_needed = []
        
        # Check frequency slots
        if tracker.get_slot("frequency_type") is None:
            slots_needed.append("frequency_type")
        elif tracker.get_slot("frequency_period") is None:
            slots_needed.append("frequency_period")
        
        # Check time period
        elif tracker.get_slot("time_period") is None:
            slots_needed.append("time_period")
        
        # Check quantity
        elif tracker.get_slot("quantity") is None:
            slots_needed.append("quantity")
        
        # Check reminder times
        elif tracker.get_slot("reminder_time") is None:
            slots_needed.append("reminder_time")
        
        # Check days if weekly
        elif (tracker.get_slot("frequency_type") == "week" and 
            tracker.get_slot("reminder_day") is None):
            slots_needed.append("reminder_day")
        
        # Check alert type
        elif tracker.get_slot("alert_type") is None:
            slots_needed.append("alert_type")
        
        return slots_needed
    
    async def validate_wants_reminders(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate if user wants reminders."""
        return {"wants_reminders": slot_value}
    
    async def validate_frequency_type(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate frequency type (day/week/month/year)."""
        if not slot_value:
            return {"frequency_type": None}
        
        valid_types = ["day", "week", "month", "year"]
        slot_value_lower = str(slot_value).lower().strip()
        
        # Map common variations
        type_mapping = {
            "days": "day",
            "daily": "day",
            "everyday": "day",
            "weeks": "week",
            "weekly": "week",
            "months": "month",
            "monthly": "month",
            "years": "year",
            "yearly": "year",
            "annually": "year"
        }
        
        # Check mapped values
        if slot_value_lower in type_mapping:
            slot_value_lower = type_mapping[slot_value_lower]
        
        # Validate
        if slot_value_lower in valid_types:
            # Provide context for next question
            context_messages = {
                "day": "Great! Now, for how many days would you like to be reminded?",
                "week": "Got it! For how many weeks would you like reminders?",
                "month": "Perfect! How many months of reminders do you need?",
                "year": "Alright! For how many years should I remind you?"
            }
            
            dispatcher.utter_message(context_messages[slot_value_lower])
            return {"frequency_type": slot_value_lower}
        else:
            dispatcher.utter_message(
                "Please specify: day, week, month, or year. "
                "For example: 'weekly reminders' or 'for a month'."
            )
            return {"frequency_type": None}
    
    async def validate_frequency_period(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate frequency period number with context from frequency_type."""
        if slot_value is None:
            return {"frequency_period": None}
        
        try:
            # Extract number from text if needed
            import re
            if isinstance(slot_value, str):
                match = re.search(r'(\d+)', slot_value)
                if match:
                    number = int(match.group(1))
                else:
                    # Try word to number conversion
                    word_to_number = {
                        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                        "once": 1, "twice": 2
                    }
                    number = word_to_number.get(slot_value.lower(), None)
                    if number is None:
                        raise ValueError
            else:
                number = int(slot_value)
            
            # Get frequency type for context
            freq_type = tracker.get_slot("frequency_type")
            
            # Validate based on frequency type
            max_limits = {
                "day": 365,    # Max 1 year in days
                "week": 52,    # Max 1 year in weeks
                "month": 12,   # Max 1 year in months
                "year": 5      # Max 5 years
            }
            
            if freq_type and freq_type in max_limits:
                if number <= 0:
                    dispatcher.utter_message(f"Please enter a positive number of {freq_type}s.")
                    return {"frequency_period": None}
                
                if number > max_limits[freq_type]:
                    suggestion = max_limits[freq_type]
                    dispatcher.utter_message(
                        f"That's quite a long time! For {freq_type}s, "
                        f"I'd suggest up to {suggestion}. How many {freq_type}s would you like?"
                    )
                    return {"frequency_period": None}
            
            # Provide confirmation with context
            freq_type = tracker.get_slot("frequency_type") or "period"
            time_phrases = {
                1: "one",
                2: "two",
                3: "three",
                4: "four",
                5: "five",
                6: "six",
                7: "seven",
                30: "thirty"
            }
            
            number_word = time_phrases.get(number, str(number))
            dispatcher.utter_message(f"Alright, reminders for {number_word} {freq_type}(s)!")
            
            # Calculate end date for user info
            if freq_type in ["day", "week", "month", "year"]:
                from datetime import datetime, timedelta
                from dateutil.relativedelta import relativedelta
                
                today = datetime.now()
                if freq_type == "day":
                    end_date = today + timedelta(days=number)
                elif freq_type == "week":
                    end_date = today + timedelta(weeks=number)
                elif freq_type == "month":
                    end_date = today + relativedelta(months=+number)
                elif freq_type == "year":
                    end_date = today + relativedelta(years=+number)
                
                date_str = end_date.strftime("%B %d, %Y")
                dispatcher.utter_message(f"That means reminders until approximately {date_str}.")
            
            return {"frequency_period": number}
            
        except (ValueError, TypeError):
            dispatcher.utter_message(f"Please enter a valid number. How many {tracker.get_slot('frequency_type') or 'periods'}?")
            return {"frequency_period": None}
    
    async def validate_time_period(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate times per period (once/twice/thrice)."""
        if not slot_value:
            return {"time_period": None}
        
        valid_periods = ["once", "twice", "thrice"]
        slot_value_lower = str(slot_value).lower().strip()
        
        # Map variations
        period_mapping = {
            "1": "once",
            "one": "once",
            "1x": "once",
            "one time": "once",
            "single": "once",
            "2": "twice",
            "two": "twice",
            "2x": "twice",
            "two times": "twice",
            "double": "twice",
            "3": "thrice",
            "three": "thrice",
            "3x": "thrice",
            "three times": "thrice",
            "triple": "thrice"
        }
        
        # Check mapped values
        if slot_value_lower in period_mapping:
            slot_value_lower = period_mapping[slot_value_lower]
        
        # Validate
        if slot_value_lower in valid_periods:
            # Get frequency context
            freq_type = tracker.get_slot("frequency_type")
            freq_period = tracker.get_slot("frequency_period")
            
            if freq_type:
                message = f"Got it! {slot_value_lower.title()} per {freq_type}."
                if freq_period:
                    message += f" That's {slot_value_lower} for {freq_period} {freq_type}(s)."
                dispatcher.utter_message(message)
            
            return {"time_period": slot_value_lower}
        else:
            dispatcher.utter_message(
                "Please specify: once, twice, or thrice. "
                "For example: 'twice daily' or 'once a week'."
            )
            return {"time_period": None}
    
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
            
            # Validate
            if quantity <= 0:
                dispatcher.utter_message("Please enter a positive number of pills/units.")
                return {"quantity": None}
            
            if quantity > 10:  # Reasonable upper limit
                dispatcher.utter_message(f"{quantity} pills per dose seems high. Is that correct?")
                # Could add confirmation here
            
            # Get medication dose for context
            medication_dose = tracker.get_slot("medication_dose")
            if medication_dose:
                dispatcher.utter_message(f"Perfect! {quantity} pill(s) of {medication_dose} each time.")
            else:
                dispatcher.utter_message(f"Got it! {quantity} pill(s) each time.")
            
            return {"quantity": quantity}
            
        except (ValueError, TypeError):
            dispatcher.utter_message(
                "Please enter a valid number of pills/units. "
                "For example: '1 pill', '2 tablets', or just '1'."
            )
            return {"quantity": None}
    
    async def validate_reminder_time(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate reminder times based on time_period."""
        if not slot_value:
            return {"reminder_time": None}
        
        time_period = tracker.get_slot("time_period")
        times_needed = {
            "once": 1,
            "twice": 2,
            "thrice": 3
        }.get(time_period, 1)
        
        # If slot_value is already a list (from previous validation)
        if isinstance(slot_value, list):
            if len(slot_value) >= times_needed:
                return {"reminder_time": slot_value}
            else:
                # Need more times
                remaining = times_needed - len(slot_value)
                dispatcher.utter_message(
                    f"I have {len(slot_value)} time(s). Need {remaining} more. "
                    f"What time? (e.g., 8:00 AM)"
                )
                return {"reminder_time": slot_value}
        
        # Convert string input to list if needed
        current_times = tracker.get_slot("reminder_time") or []
        if not isinstance(current_times, list):
            current_times = []
        
        # Parse time input
        time_input = str(slot_value)
        parsed_time = self._parse_time_input(time_input)
        
        if parsed_time:
            # Add to list
            current_times.append(parsed_time)
            
            # Check if we have enough times
            if len(current_times) >= times_needed:
                # Sort times chronologically
                current_times.sort()
                time_list_str = ", ".join(current_times)
                dispatcher.utter_message(f"Perfect! Reminders set for: {time_list_str}")
                return {"reminder_time": current_times}
            else:
                remaining = times_needed - len(current_times)
                if remaining == 1:
                    dispatcher.utter_message(f"Great! Need 1 more time. What time?")
                else:
                    dispatcher.utter_message(f"Got it! Need {remaining} more times. What's the next time?")
                return {"reminder_time": current_times}
        else:
            dispatcher.utter_message(
                "Please enter a valid time in 12-hour or 24-hour format. "
                "Examples: '8:00 AM', '14:30', '9 PM'."
            )
            return {"reminder_time": current_times}
    
    async def validate_reminder_day(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate reminder days (only for weekly frequency)."""
        freq_type = tracker.get_slot("frequency_type")
        
        # Only validate if frequency_type is "week"
        if freq_type != "week":
            return {"reminder_day": None}
        
        if not slot_value:
            return {"reminder_day": None}
        
        # If already a list
        if isinstance(slot_value, list):
            # Validate each day
            valid_days = self._validate_day_list(slot_value)
            if valid_days:
                days_str = ", ".join(valid_days)
                dispatcher.utter_message(f"Perfect! Weekly reminders on: {days_str}")
                return {"reminder_day": valid_days}
        
        # Parse day input
        days_input = str(slot_value)
        parsed_days = self._parse_days_input(days_input)
        
        if parsed_days:
            days_str = ", ".join(parsed_days)
            dispatcher.utter_message(f"Great! Reminders on: {days_str}")
            return {"reminder_day": parsed_days}
        else:
            dispatcher.utter_message(
                "Please specify days of the week. "
                "Examples: 'Monday, Wednesday, Friday' or 'everyday' or 'weekdays'."
            )
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
            message = f"Perfect! I'll use {slot_value_lower} alerts for your reminders."
            dispatcher.utter_message(message)
            return {"alert_type": slot_value_lower}
        else:
            dispatcher.utter_message(
                "Please choose: alarm (sound notification) or voice (spoken reminder)."
            )
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
        import re
        
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


    
class ActionSubmitReminderForm(BaseAction):
    """Submits reminder form and saves to API."""
    
    def name(self) -> Text:
        return "action_submit_reminder_form"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                       tracker: Tracker,
                       domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Check if user wants reminders
        wants_reminders = tracker.get_slot("wants_reminders")
        
        if not wants_reminders:
            dispatcher.utter_message("No reminders set up. Your medication has been added successfully!")
            return self._complete_flow()
        
        # Collect reminder data
        reminder_data = {
            "user_medication_id": tracker.get_slot("user_medication_id"),
            "frequency_type": tracker.get_slot("frequency_type"),
            "frequency_period": tracker.get_slot("frequency_period"),
            "reminder_day": tracker.get_slot("reminder_day"),
            "time_period": tracker.get_slot("time_period"),
            "quantity": tracker.get_slot("quantity"),
            "snooze": 15,  # Default
            "alert_type": tracker.get_slot("alert_type"),
            "reminder_time": tracker.get_slot("reminder_time")
        }
        
        # Validate required fields
        required_fields = ["frequency_type", "frequency_period", "time_period", "reminder_time"]
        missing_fields = [field for field in required_fields if not reminder_data[field]]
        
        if missing_fields:
            dispatcher.utter_message(f"Missing information: {', '.join(missing_fields)}. Let's complete that.")
            # Reactivate form for missing info
            return [
                ActiveLoop("reminder_form"),
            ]
        
        # Format the data for user confirmation
        confirmation = self._format_reminder_confirmation(reminder_data)
        dispatcher.utter_message(confirmation)
        
        # Ask for confirmation
        dispatcher.utter_message("Does this look correct? (yes/no)")
        return [SlotSet("awaiting_reminder_confirmation", True)]
    
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
    
from rasa_sdk import Tracker, Action
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActiveLoop

class ActionHandleRefillDecision(Action):
    def name(self):
        return "action_handle_refill_decision"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict):
        latest_intent = tracker.latest_message.get("intent", {}).get("name")
        builder = ResponseBuilder(token=tracker.sender_id)

        if tracker.get_slot("current_step") == "ask_refill":
            if latest_intent == "affirm":
                # Open refill form
                dispatcher.utter_message(text="Great! Let's set up refill info.")
                return [SlotSet("current_step", None), ActiveLoop("refill_form")]
            elif latest_intent == "deny":
                # Ask about reminder
                dispatcher.utter_message(text="No problem! Would you like to add reminder information?")
                return [SlotSet("current_step", "ask_reminder")]
            else:
                dispatcher.utter_message(text="Please answer yes or no.")
                return []

class ActionHandleReminderDecision(BaseAction):
    """Handles yes/no decision about reminders."""
    
    def name(self) -> Text:
        return "action_handle_reminder_decision"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                       tracker: Tracker,
                       domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        latest_intent = tracker.latest_message.get("intent", {}).get("name")
        builder = ResponseBuilder(token=tracker.sender_id)
        
        if tracker.get_slot("current_step") == "ask_reminder":
            if latest_intent == "affirm":
                # Open reminder form
                dispatcher.utter_message(text="Perfect! Let's set up your reminders.")
                return [SlotSet("current_step", None), ActiveLoop("reminder_form")]
            elif latest_intent == "deny":
                dispatcher.utter_message(text="That's fine. What else can I help you with?")
                return [SlotSet("current_step", None)]
            else:
                dispatcher.utter_message(text="Please answer yes or no.")
                return []

class ActionHandleReminderConfirmation(BaseAction):
    """Handles confirmation for reminder setup."""
    
    def name(self) -> Text:
        return "action_handle_reminder_confirmation"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                       tracker: Tracker,
                       domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        intent = tracker.get_intent_of_latest_message()
        
        if intent == "affirm":
            # Save reminder to API
            reminder_data = {
                "user_medication_id": tracker.get_slot("user_medication_id"),
                "frequency_type": tracker.get_slot("frequency_type"),
                "frequency_period": tracker.get_slot("frequency_period"),
                "reminder_day": tracker.get_slot("reminder_day"),
                "time_period": tracker.get_slot("time_period"),
                "quantity": tracker.get_slot("quantity"),
                "snooze": 15,
                "alert_type": tracker.get_slot("alert_type"),
                "reminder_time": tracker.get_slot("reminder_time")
            }
            
            # Save reminder
            success, message = self._save_reminder_to_api(tracker, reminder_data)
            
            if success:
                dispatcher.utter_message("Reminder setup complete!")
            else:
                dispatcher.utter_message(f"Error saving reminder: {message}")
            
            return ActionSubmitReminderForm()._complete_flow(success, message)
        
        elif intent == "deny":
            # User wants to change something - reactivate form
            dispatcher.utter_message("Let's adjust the reminder settings.")
            return [
                ActiveLoop("reminder_form"),
                SlotSet("awaiting_reminder_confirmation", None)
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
                            "type": "String",
                            "status": "success"
                }
            else:
                reply = "Your medications for today: " + ", ".join([str(med) for med in medication_names])
                attachment = {
                                "query_response": reply,
                                "data": [],
                                "type": "string",
                                "status": "success"
                }
        except Exception as e:
            reply = e
            attachment = {
                    "query_response": reply,
                    "data": [],
                    "type": "string",
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
                        "type": "string",
                        "status": "success"
                    }
        except Exception as ex:
            reply = "Sorry, we couldn't access your medication information."
            attachment = {
                "query_response": reply,
                "data": str(ex),
                "type": "string",
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
#                     "type": "string",
#                     "status": "success"
#                 }
#             else:
#                 reply = "You do not have any medications for today"
#                 attachment = {
#                     "query_response": reply,
#                     "data": [],
#                     "type": "string",
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
                    "type": "string",
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
                    "type": "string",
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
    def name(self):
        return "action_custom_fallback"       
        
    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
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
        logger.debug("="*80)
        logger.debug("🔧 ACTION_CUSTOM_FALLBACK STARTING")
        logger.debug(f"Active loop: {tracker.active_loop}")
        logger.debug(f"Requested slot: {tracker.get_slot('requested_slot')}")
        logger.debug("="*80)
        
        # CRITICAL: SKIP OpenAI fallback if ANY form is active
        if tracker.active_loop:
            form_name = tracker.active_loop.get("name")
            logger.debug(f"Form '{form_name}' ACTIVE - SKIPPING OPENAI")
            logger.debug("Returning empty list to let form handle it")
            return []  # ← This should stop the OpenAI call!
        
        prompt = """You are 'Angela,' a helpful, trustworthy, and informative medical assistant..."""
        
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
                "type": "string",
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
                "type": "string",
                "status": "failed"
            }

        except Exception as e:
            reply = "Can you rephrase it."  

            attachment = {
                "query_response": reply,
                "error": str(e),
                "data": [],
                "type": "string",
                "status": "failed"
            }

        dispatcher.utter_message(attachment=attachment)
        return []
