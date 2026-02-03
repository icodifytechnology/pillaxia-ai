from dotenv import load_dotenv
from typing import Any, Text, Dict, List
import logging
from abc import ABC, abstractmethod

from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta

import requests
from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet, SessionStarted
from rasa_sdk.executor import CollectingDispatcher
from rasa.shared.exceptions import RasaException
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
    
    # def run_with_slots(self, dispatcher: CollectingDispatcher,
    #                   tracker: Tracker,
    #                   domain: Dict[Text, Any]) -> List[SlotSet]:
    #     """
    #     Handle session start with slots already loaded
    #     """
    #     logger.info(debug_separator("ActionSessionStart"))
        
    #     # Send welcome message
    #     try:
    #         builder = ResponseBuilder(tracker.sender_id, tracker)
    #         welcome = builder.build_response("greet")
    #         dispatcher.utter_message(text=welcome)
    #         logger.info(f"Sent welcome message: '{welcome}'")
    #     except Exception as e:
    #         logger.error(f"Error sending welcome message: {e}", exc_info=True)
    #         dispatcher.utter_message(text="Hello! Welcome to Pillaxia.")
        
    #     return []
    
    def run(self, dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]) -> List[SlotSet]:
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
            reply = builder.build_response("greet")
            dispatcher.utter_message(text=reply)
            logger.info(f"Sent greeting: '{reply}'")
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
            reply = builder.build_response("goodbye")
            dispatcher.utter_message(text=reply)
            logger.info(f"Sent goodbye: '{reply}'")
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
            reply = random.choice(BOT_IDENTITY_RESPONSES)
            logger.debug(f"Selected bot identity response: '{reply[:50]}...'")
            
            # Only send text response since this is a simple identity message
            dispatcher.utter_message(text=reply)
            
        except Exception as e:
            logger.error(f"Error in action_iamabot: {e}", exc_info=True)
            error_message = "I'm having trouble responding right now. I'm a chatbot here to help you!"
            dispatcher.utter_message(text=error_message)
        
        logger.debug("Bot identity query handled successfully")
        return []

class ActionAddMedication(Action):
    def name(self):
        return "action_add_medication"
       
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        try:
            messages = ["Please fill the following form to add the medication in the list",
                       "To add this medication to your list, please complete the form below.",
                       "Please fill out the form to include this medication in your records.",
                       "Add this medication to your list by completing the following form."]
            reply = random.choice(messages)
            attachment = {
		    	"query_response": reply,
		    	"data":"/add-med-layout ",
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
        dispatcher.utter_message(text=reply)

        return []

class ActionListMedicationName(BaseAction):  
    def name(self):
        return "action_list_medication_name"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                      tracker: Tracker,
                      domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.info("Listing medication names")
        
        try:
            # Use the MedicationManager
            from .helpers.medication_manager import MedicationManager
            med_manager = MedicationManager(tracker.sender_id)
            
            medication_names = med_manager.get_medication_names()
            
            if not medication_names:
                logger.debug("No medications found for user")
                reply = "You don't have any medications in your list."
            else:
                # Use ResponseBuilder for personalization
                builder = ResponseBuilder(tracker.sender_id, tracker)
                reply = builder.build_response(
                    "list_medications",
                    medications=", ".join(medication_names)
                )
                logger.debug(f"Found {len(medication_names)} medications")
            
            dispatcher.utter_message(text=reply)
            
        except Exception as e:
            logger.error(f"Error listing medications: {e}", exc_info=True)
            dispatcher.utter_message(text="Sorry, I couldn't retrieve your medication list.")
        
        return []
    
class ActionMedicationReport(BaseAction):
    """Generate personalized medication tracking report"""
    
    def name(self) -> Text:
        return "action_medication_report"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                      tracker: Tracker,
                      domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.info("Generating medication tracking report")
        
        try:
            from .helpers.medication_manager import MedicationManager
            med_manager = MedicationManager(tracker.sender_id)
            
            # Get tracking data (default: last 30 days)
            tracking_data = med_manager.get_recent_tracking(days=30)
            
            if not tracking_data:
                logger.debug("No tracking data found")
                builder = ResponseBuilder(tracker.sender_id, tracker)
                reply = builder.build_response("no_tracking_data")
                dispatcher.utter_message(text=reply)
                return []
            
            # Analyze compliance for summary
            stats = med_manager.analyze_tracking_compliance(tracking_data)
            logger.debug(f"Report stats: {stats}")
            
            # Get medication names for context
            medication_names = med_manager.get_medication_names()
            logger.debug(f"User has {len(medication_names)} medications in list")
            
            # Build personalized response with summary AND list
            attachment = self._build_combined_report(tracker, stats, tracking_data, medication_names)
            
            dispatcher.utter_message(attachment=attachment)
            logger.info(f"✓ Report generated: {stats['taken']}/{stats['total']} taken")
            
        except Exception as e:
            logger.error(f"✗ Error generating report: {e}", exc_info=True)
            dispatcher.utter_message(text="Sorry, I couldn't generate your medication report.")
        
        return []
    
    def _build_combined_report(self, tracker: Tracker, stats: Dict, 
                              tracking_data: List[Dict], medication_names: List[str]) -> Dict:
        """Build combined report with summary and recent entries"""
        
        # 1. Build the summary text (with problematic note)
        builder = ResponseBuilder(tracker.sender_id, tracker)
        
        # Find most problematic medication for note
        problematic_note = ""
        if stats.get('medication_stats'):
            total_meds = len(stats['medication_stats'])
            problematic_meds = []

            # Identify meds with low compliance
            for med_name, med_stats in stats['medication_stats'].items():
                if med_stats.get('total', 0) > 0:
                    med_compliance = (med_stats['taken'] / med_stats['total'] * 100)
                    if med_compliance < 70:
                        problematic_meds.append((med_name, med_compliance))

            # Generate problematic note
            if problematic_meds:
                num_problematic = len(problematic_meds)
                percent_problematic = (num_problematic / total_meds) * 100
                problematic_meds.sort(key=lambda x: x[1])
                med_names = [m[0] for m in problematic_meds]

                if percent_problematic == 100:
                    problematic_note = "It seems you haven't been taking any of your medications on time. Let's try to improve that!"
                elif percent_problematic >= 70:
                    problematic_note = f"Almost all of your medications ({', '.join(med_names)}) need more attention."
                elif percent_problematic >= 40:
                    if num_problematic == 1:
                        problematic_note = f"Try to be more consistent with your {med_names[0]}."
                    elif num_problematic == 2:
                        problematic_note = f"Focus on taking {med_names[0]} and {med_names[1]} more regularly."
                    else:
                        problematic_note = f"Pay special attention to: {', '.join(med_names[:-1])} and {med_names[-1]}."
                else:
                    if num_problematic == 1:
                        problematic_note = f"You mostly did well, but keep an eye on your {med_names[0]}."
                    else:
                        problematic_note = f"You mostly took your medications on time. A few like {', '.join(med_names[:-1])} and {med_names[-1]} could use more consistency."
        
        # Build summary text
        summary_text = builder.build_response(
            "medication_report",
            total=stats['total'],
            taken=stats['taken'],
            missed=stats['missed'],
            compliance_rate=stats['compliance_rate'],
            day="month",
            medication_count=len(medication_names),
            problematic_meds="None",
            problematic_note=problematic_note
        )
        
        # 2. Build recent entries list (limit to last 10 for readability)
        recent_entries = tracking_data[:10]  # Show only last 10 entries
        
        report_data = []
        for item in recent_entries:
            reminder_at = item.get('reminder_at', 'Unknown time')
            tracked_at = item.get('tracked_at')
            
            # Format the time strings
            if reminder_at:
                try:
                    # Extract just date and time (without seconds if present)
                    reminder_time = reminder_at.split()[1][:5] if ' ' in reminder_at else reminder_at[:5]
                    reminder_date = reminder_at.split()[0] if ' ' in reminder_at else ""
                    reminder_str = f"{reminder_date} {reminder_time}" if reminder_date else reminder_time
                except:
                    reminder_str = reminder_at
            else:
                reminder_str = "Unknown time"
            
            # Determine status
            if tracked_at:
                try:
                    tracked_time = tracked_at.split()[1][:5] if ' ' in tracked_at else tracked_at[:5]
                    status = f"Taken at {tracked_time}"
                except:
                    status = "Taken"
            else:
                status = "Medication not taken"
            
            report_data.append({
                'name': item.get('reminder', 'Unknown medication'),
                'value': f"Reminded at {reminder_str}, {status}"
            })
        
        # Add note if there are more entries
        if len(tracking_data) > 10:
            report_data.append({
                'name': 'Note',
                'value': f"... and {len(tracking_data) - 10} more entries this month"
            })
        
        # 3. Return combined response in attachment format
        return {
            "query_response": summary_text,
            "data": report_data,
            "type": "array",
            "status": "success"
        }
    
    def _get_time_period_text(self, days: int) -> str:
        """Convert days to human-readable time period"""
        if days == 1:
            return "day"
        elif days == 7:
            return "week"
        elif days == 30:
            return "month"
        elif days == 90:
            return "3 months"
        else:
            return f"{days} days"
    
class ActionMedicationReportWithTimeframe(BaseAction):
    """Generate medication report for specific timeframe (week/month)"""
    
    def name(self) -> Text:
        return "action_medication_report_with_timeframe"
    
    def run_with_slots(self, dispatcher: CollectingDispatcher,
                      tracker: Tracker,
                      domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        logger.info("Generating medication report with timeframe")
        
        try:
            # Get period from slot
            period = tracker.get_slot("period")
            if not period:
                logger.warning("No period specified, defaulting to month")
                period = "month"
            
            logger.debug(f"Generating report for period: {period}")
            
            # Get medication manager
            from .helpers.medication_manager import MedicationManager
            med_manager = MedicationManager(tracker.sender_id)
            
            # Determine days based on period
            if period.lower() == "month":
                days = 30 
            elif period.lower() == "today":
                days = 1
            else:
                days = 7
        
            # Get tracking data for the specified period
            tracking_data = med_manager.get_recent_tracking(days=days)
            
            if not tracking_data:
                logger.debug(f"No tracking data found for last {period}")
                reply = f"I couldn't find any medication tracking data for the past {period}."
                dispatcher.utter_message(text=reply)
                return []
            
            # Analyze compliance
            stats = med_manager.analyze_tracking_compliance(tracking_data)
            logger.debug(f"Report stats for {period}: {stats}")
            
            # Get medication names for context
            medication_names = med_manager.get_medication_names()
            
            # Build combined report
            attachment = self._build_combined_report(tracker, stats, tracking_data, medication_names, period)
            
            dispatcher.utter_message(attachment=attachment)
            logger.info(f"✓ {period.capitalize()} report generated: {stats['taken']}/{stats['total']} taken")
            
        except Exception as e:
            logger.error(f"✗ Error generating {period} report: {e}", exc_info=True)
            dispatcher.utter_message(text=f"Sorry, I couldn't generate your {period} medication report.")
        
        return []
    
    def _build_combined_report(self, tracker: Tracker, stats: Dict, 
                              tracking_data: List[Dict], medication_names: List[str], period: str) -> Dict:
        """Build combined report with summary and recent entries for timeframe"""
        
        # 1. Build the summary text
        builder = ResponseBuilder(tracker.sender_id, tracker)
        
        # Generate problematic note
        problematic_note = ""
        if stats.get('medication_stats'):
            total_meds = len(stats['medication_stats'])
            problematic_meds = []

            for med_name, med_stats in stats['medication_stats'].items():
                if med_stats.get('total', 0) > 0:
                    compliance = (med_stats['taken'] / med_stats['total']) * 100
                    if compliance < 70:
                        problematic_meds.append((med_name, compliance))

            if problematic_meds:
                num_problematic = len(problematic_meds)
                percent_problematic = (num_problematic / total_meds) * 100
                problematic_meds.sort(key=lambda x: x[1])
                med_names = [m[0] for m in problematic_meds]

                if percent_problematic == 100:
                    problematic_note = f"It seems you haven't been taking any of your medications on time this {period}."
                elif percent_problematic >= 70:
                    problematic_note = f"Almost all of your medications ({', '.join(med_names)}) need more attention this {period}."
                elif percent_problematic >= 40:
                    if num_problematic == 1:
                        problematic_note = f"Try to be more consistent with your {med_names[0]} this {period}."
                    elif num_problematic == 2:
                        problematic_note = f"Focus on taking {med_names[0]} and {med_names[1]} more regularly this {period}."
                    else:
                        problematic_note = f"Pay special attention to: {', '.join(med_names[:-1])} and {med_names[-1]} this {period}."
                else:
                    if num_problematic == 1:
                        problematic_note = f"You mostly did well this {period}, but keep an eye on your {med_names[0]}."
                    else:
                        problematic_note = f"You mostly took your medications on time this {period}. A few like {', '.join(med_names[:-1])} and {med_names[-1]} could use more consistency."
        
        # Build summary text
        summary_text = builder.build_response(
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
        
        # 2. Build recent entries list
        # Show more entries for week, fewer for month
        max_entries = 15 if period.lower() == "week" else 10
        
        recent_entries = tracking_data[:max_entries]
        report_data = []
        
        for item in recent_entries:
            reminder_at = item.get('reminder_at', 'Unknown time')
            tracked_at = item.get('tracked_at')
            
            # Format time
            if reminder_at and ' ' in reminder_at:
                date_part, time_part = reminder_at.split(' ', 1)
                time_short = time_part[:5] if len(time_part) >= 5 else time_part
                reminder_str = f"{date_part} {time_short}"
            else:
                reminder_str = reminder_at or "Unknown time"
            
            # Status
            if tracked_at:
                if ' ' in tracked_at:
                    _, tracked_time = tracked_at.split(' ', 1)
                    time_short = tracked_time[:5] if len(tracked_time) >= 5 else tracked_time
                    status = f"Taken at {time_short}"
                else:
                    status = "Taken"
            else:
                status = "Medication not taken"
            
            report_data.append({
                'name': item.get('reminder', 'Unknown medication'),
                'value': f"Reminded at {reminder_str}, {status}"
            })
        
        # Add note if truncated
        if len(tracking_data) > max_entries:
            report_data.append({
                'name': 'Note',
                'value': f"... and {len(tracking_data) - max_entries} more entries this {period}"
            })
        
        # 3. Return combined response
        return {
            "query_response": summary_text,
            "data": report_data,
            "type": "array",
            "status": "success"
        }
    
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
        dispatcher.utter_message(text=reply)

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
        dispatcher.utter_message(text=reply)
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
        dispatcher.utter_message(text=reply)
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
        dispatcher.utter_message(text=reply)
        
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
#         dispatcher.utter_message(text=reply)
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
                    reply = f"You're scheduled to take your {next_med['name']} at {formatted_time_full}. I'll remind you when it's time!"
                else:
                    reply = "Looks like you don’t have any meds scheduled for the rest of today."
            else:
                reply = "Looks like you don’t have any meds scheduled!"
        
        except Exception as ex:
            # reply already has a default error message
            pass
        
        dispatcher.utter_message(text=reply)
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
            dispatcher.utter_message(text=reply)
        
            return [SlotSet("medication", None)]
    
# class actionSymtomsOccured(Action):
#     def name(self):
#         return "action_symtoms_occured"
    
#     def run(self, dispatcher: CollectingDispatcher, 
#             tracker: Tracker, 
#             domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
#         symptom = tracker.get_slot('symptom')
#         time_period = tracker.get_slot('time_period')
#         today = date.today()
#         if time_period.lower() == "week":
#                 date = today - timedelta(days = 7)
#         elif time_period.lower() == "month":
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
        dispatcher.utter_message(text=reply)
        return[]

class ActionSymptoms(Action):
    def name(self):
        return "action_symptoms"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any])  -> List[Dict[Text, Any]]: 
        time_period = tracker.get_slot('period')

        if time_period == None:
            time_periods = ("week", "month", "week", "month")
            time_period = random.choice(time_periods)
        today = date.today()
        Date = today
        if time_period.lower() == "week":
                Date = today - timedelta(days = 7)
        elif time_period.lower() == "month":
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

                reply = f"Here's your list of symptoms you experienced last {time_period}"
                attachment = {
                    "query_response": reply,
                    "data": symptoms,
                    "type":"array",
                    "status": "success"
                }
            else:
                reply = f"You have no recorded symptoms for last {time_period}"
                attachment = {
                    "query_response": reply,
                    "data": [],
                    "type":"string",
                    "status": "failed"
                }

        except Exception as ex:
            reply = f"Failed to get your last {time_period} symptoms"
            attachment = {
                    "query_response": reply,
                    "data": [],
                    "type":"string",
                    "status": "failed"
                }
        dispatcher.utter_message(text=reply)
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
        dispatcher.utter_message(text=reply)
        return[]
    
class ActionMedicationAdherence(Action):
    def name(self):
        return "action_medication_adherence"
    
    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
        try:
            end_date = start_date = date.today()  
            period = tracker.get_slot("period")   
            if period:    
                if period.lower() == "week":
                        start_date = start_date - relativedelta(weeks=1)
                elif period.lower() == "month":
                        start_date = start_date - relativedelta(months=1)
        
            url = f'https://api.pillaxia.com/api/v1/pxtracker?start_date={start_date}&end_date={end_date}'
            header = {
                "Authorization": f"Bearer {tracker.sender_id}"
            }
            response = requests.get(url, headers=header)
            response_data = response.json()["result"]["summary"]
            adherence_percentage = response_data.get("taken_medication_percent")
            reply = self.get_adherence_response(adherence_percentage)
            attachment = {
                "query_response": reply,
                "data": [],
                "type": "string",
                "status": "success"
            }
            
        except Exception as e:
            reply = "Sorry, we couldn't access your medication adherence. Please try again later !!!"
            attachment = {
                "query_response": reply,
                "data": str(e),
                "type": "string",
                "status": "failed"
            }
        dispatcher.utter_message(text=reply)
        return[]
    
    def get_adherence_response(self, percentage):
        ADHERENCE_RESPONSES = {
            (0, 9): [
                "Your adherence is {adherence_percentage}% - let's focus on getting you the support you need. I'm here to help you succeed.",
                "You're {adherence_percentage}% adherent. Taking medications consistently is crucial for your health. Let's work together to improve this.",
                "Your medication adherence is {adherence_percentage}%. Every small step counts - let's start building better habits today."
            ],
            (10, 19): [
                "Your adherence is {adherence_percentage}% - let's talk about what's making it difficult to take your medications consistently.",
                "You're {adherence_percentage}% adherent. I'm here to help you succeed with your medications and overcome any barriers.",
                "Your medication adherence is {adherence_percentage}%. Let's identify what's challenging and create solutions together."
            ],
            (20, 29): [
                "Your adherence is {adherence_percentage}% - let's prioritize getting back on track with your medication routine.",
                "You're {adherence_percentage}% adherent. Your medications are important for your health - let's work on consistency.",
                "Your medication adherence is {adherence_percentage}%. Small improvements can make a big difference in your health outcomes."
            ],
            (30, 39): [
                "Your adherence is {adherence_percentage}% - this needs attention. Let's figure out how to support you better.",
                "You're {adherence_percentage}% adherent. Your health is important - let's develop strategies to improve your routine.",
                "Your medication adherence is {adherence_percentage}%. Let's focus on small, achievable improvements that stick."
            ],
            (40, 49): [
                "Your adherence is {adherence_percentage}% - let's work together to improve this and get you on the right track.",
                "You're {adherence_percentage}% adherent. I know you can do better! Let's identify what's getting in the way.",
                "Your medication adherence is {adherence_percentage}%. Let's turn this around together - you've got this!"
            ],
            (50, 59): [
                "You're {adherence_percentage}% adherent - about halfway there. Let's work on building stronger medication habits.",
                "Your medication adherence is {adherence_percentage}%. There's definitely room to grow - every improvement matters!",
                "You're {adherence_percentage}% adherent. Let's focus on improving your routine and making it more consistent."
            ],
            (60, 69): [
                "You're {adherence_percentage}% adherent - not bad, but there's room for improvement. You're making progress!",
                "Your adherence is {adherence_percentage}% - you're on the right path! Let's see where we can help you improve further.",
                "You're {adherence_percentage}% adherent. You're getting there! Keep building on this positive momentum."
            ],
            (70, 79): [
                "You're {adherence_percentage}% adherent - that's pretty good! You're on the right track with your medications.",
                "Nice progress! {adherence_percentage}% adherence shows you're building good habits. Keep it up!",
                "You're {adherence_percentage}% adherent - solid work! With a little more consistency, you'll be doing even better."
            ],
            (80, 89): [
                "You're {adherence_percentage}% adherent, that's amazing! You're doing really well with your medication routine.",
                "Great job! {adherence_percentage}% adherence shows you're staying on track beautifully. Keep up the excellent work!",
                "You're {adherence_percentage}% adherent - that's really impressive! Your consistency is paying off."
            ],
            (90, 100): [
                "You're {adherence_percentage}% adherent - that's exceptional! You're doing an outstanding job with your medications.",
                "Wow! {adherence_percentage}% adherence is fantastic! You're really committed to your health. Keep it up!",
                "Amazing work! You're {adherence_percentage}% adherent - that's excellent medication management. You should be proud!"
            ]
        }
                
        for (min_val, max_val), responses in ADHERENCE_RESPONSES.items():
            if min_val <= percentage <= max_val:
                return random.choice(responses).format(adherence_percentage=percentage)
        return f"Your adherence is {percentage}%. Want to see your visual report?"
    
        
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

        dispatcher.utter_message(text=reply)
        return []
