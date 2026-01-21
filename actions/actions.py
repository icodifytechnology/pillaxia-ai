# This files contains your custom actions which can be used to run
# custom Python code.
#
# See this guide on how to implement these action:
# https://rasa.com/docs/rasa/custom-actions


from dotenv import load_dotenv

from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta

import random
import requests
from typing import Any, Text, Dict, List

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher
from rasa.shared.exceptions import RasaException
import openai
from openai import OpenAI
import os
load_dotenv()

openai_api_key = os.getenv("openai_api_key")

client = OpenAI(api_key=openai_api_key)

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

class Greet(Action):
    def name(self):
        return "action_greet"
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        try:
            messages = ["Hi there. It's such a pleasure to have you here. How can we help you?",
                        "Hello, how can we assist you?",
                        "Nice to meet you! How can I assist?",
                        "Greetings! How may I be of service?",
                        "Hi! How can I make your day better?",
                        "Welcome! How can I help you today?",
                        "Hi there! Need a hand?",
                        "Hello! What can I do for you?"]
            reply = random.choice(messages)
            attachment={
                "query_response": reply,
			    "data":[],
			    "type":"string",
			    "status": "success"
            }
        except Exception as e:
            reply = "Error!"
            attachment={
                "query_response": reply,
			    "data":[],
			    "type":"string",
			    "status": "failed"
            }
        dispatcher.utter_message(attachment=attachment)
        return

class GoodBye(Action):
    def name(self):
        return "action_goodbye"
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        try:
            messages = ["Thank you😁, I am happy to help you👋.",
                        "I hope I was helpful for you👋😁.",
                        "You're welcome! 😊 Have a great day!",
                        "Happy to help. Best wishes! 👋",
                        "No problem! 😊 Feel free to reach out again.",
                        "It was my pleasure assisting you. Don't hesitate to ask if you need anything else. 😊"]
            reply = random.choice(messages)
            attachment = {
		    	"query_response": reply,
		    	"data":[],
		    	"type":"string",
		    	"status": "success"
		    }
        except Exception as e:
            reply = "Error!"
            attachment = {
		    	"query_response": reply,
		    	"data":[],
		    	"type":"string",
		    	"status": "failed"
		    }
        dispatcher.utter_message(attachment=attachment)
        return[]

class IAmABot(Action):
    def name(self):
        return "action_iamabot"
    
    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        try:
            messages = ["You got me! I am a large language model powered by Rasa, but I try my best to be helpful. What can I assist you with today?",
                        "I plead the fifth! But seriously, I'm here to answer your questions and complete tasks as instructed.",
                        "I am a chatbot powered by Rasa, designed to simulate conversation and provide information.",
                        "Top secret! Okay, fine. I'm a language model here to help you with your requests. How can I assist you today?",
                        "Hello there! I'm a chatbot designed to provide information and complete tasks. What can I do for you?"]
            reply = random.choice(messages)
            attachment = {
                "query_response": reply,
                "data":[],
                "type":"string",
                "status": "success"
            }
        except Exception as e:
            reply = "Error!"
            attachment = {
                "query_response": reply,
                "data":[],
                "type":"string",
                "status": "failed"
            }
        dispatcher.utter_message(attachment=attachment)
        return[]



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
        dispatcher.utter_message(attachment=attachment)
        return []

class actionmedicationname(Action):
    def name(self):
        return "action_list_medication_name"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
        
        url = "https://api.pillaxia.com/api/v1/user-medications/list"
        header = {
                "Authorization" : f"Bearer {tracker.sender_id}"    
            }
        
        try: 
            response = requests.post(url, headers=header)
            response_data = response.json()
            if response_data["message"] and "result" in response_data:
                responses = response_data["result"]["items"]    
            medicationNames = [response["name"] for response in responses]
            
            messages = [
                "Your Medication Names are",
                "Here are your Medication Names:",
                "Your Medications include:",
                "The Medications you're taking are:",
                "Your prescribed Medications are:"
            ]

            reply = random.choice(messages) + ", ".join([str(med) for med in medicationNames])
            
            attachment = {
                "query_response": reply,
                "data":[],
                "type":"string",
                "status": "success"
		    }                      
        except requests.exceptions.RequestException as e:
            reply = "Failed to Get Medication Names"
            attachment = {
		    	"query_response": reply,
		    	"data":[],
		    	"type":"string",
		    	"status": "Failed"
		    }
            raise RasaException("Error fetching medication data")
        
        dispatcher.utter_message(attachment=attachment)
        return []
    
class ActionMedicationReport(Action):
    def name(self):
        return "action_medication_report"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        try:
                url = 'https://api.pillaxia.com/api/v1/medication-tracker/list'
                header = {
                    "Authorization" : f"Bearer {tracker.sender_id}"
                }
                response = requests.post(url,headers=header)
                response_data = response.json()
                data = response_data['result']['items']
                report= [
                            {
                                'name': item['reminder'],
                                # 'reminder_id': item['reminder_id'],
                                'value':  f"Reminded at {item['reminder_at']}, {str('Taken at: ' + item['tracked_at'] if item['tracked_at'] is not None else 'Medication not taken')}"
                                # 'tracked_at': item['tracked_at'
                            } for item in data
                        ]
                reply = "Your Medication Report"
                attachment = {
                                "query_response": reply,
                                "data":report,
                                "type":"array",
                                "status": "success"
                }
        except requests.exceptions.RequestException as e:
                reply = "Failed to get your medication report!"
                attachment = {
                                "query_response": str(e),
                                "data":[],
                                "type":"string",
                                "status": "failed"
                } 
        dispatcher.utter_message(attachment=attachment)
        return []
    
class ActionMedicationReportWithTimeframe(Action):
    def name(self):
        return "action_medication_report_with_timeframe"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        today = date.today()
        period = tracker.get_slot("period")       
        if period.lower() == "week":
                start_date = today - timedelta(days = 7)
        elif period.lower() == "month":
                start_date = today - timedelta(days = 30)

        url = 'https://api.pillaxia.com/api/v1/medication-tracker/list'
        header = {
            "Authorization" : f"Bearer {tracker.sender_id}"
        }
        try:
            response = requests.post(url,headers=header)
            data = response.json()["result"]["items"]
            filtered_items = []

            for item in data:
                if item["tracked_at"] != None:
                    Date = datetime.strptime(item["tracked_at"], '%Y-%m-%d %H:%M:%S').date()
                    if Date <= today and Date >= start_date:
                        filtered_items.append(item)
            
            if len(filtered_items) == 0:
                reply = f"There is no records for last {period}"
                attachment = {
                    "query_response": reply,
                    "data":[],
                    "type":"string",
                    "status": "failed"
                }
            else:
                for item in filtered_items:
                    report= [{
                                'name': item['reminder'],
                                # 'reminder_id': item['reminder_id'],
                                'value':  f"Reminded at {item['reminder_at']}, {str('Taken at: ' + item['tracked_at'] if item['tracked_at'] is not None else 'Medication not taken')}"
                                # 'tracked_at': item['tracked_at'
                            } for item in filtered_items ]
                    
                        
                reply = "Here's your medication report:"
                attachment = {
                            "query_response": reply,
                            "data":report,
                            "type":"array",
                            "status": "success"
                            }
        except Exception as e:
            reply = "Failed!"
            attachment = {
                        "query_response": reply,
                        "data":[],
                        "type":"string",
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

class actionMedicationDosage(Action):
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
            reply = "Failed to get your medication dosage"
            attachment = {
		    	    "query_response": reply,
		    	    "data": [],
		    	    "type":"string",
		    	    "status": "failed"
		        }
        dispatcher.utter_message(attachment=attachment)
        return []

class MedicationTaken(Action):
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

class actionNextDose(Action):
   def name(self):
       return "action_next_dose"
  
   def run(self, dispatcher: CollectingDispatcher,
           tracker: Tracker,
           domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
        todays_time = str(datetime.today().strftime("%H:%M:%S"))
        current_time = datetime.now().strftime("%H:%M:%S")
        url = "https://api.pillaxia.com/api/v1/medication-reminders/list"
        header = {
                    "Authorization" : f"Bearer {tracker.sender_id}"
                }
        try:
            response = requests.post(url,headers=header)
            response_data = response.json()["result"]
            if response_data.get("count") != 0:
                medication_detail = []
                next_med = None
                now = datetime.strptime(current_time, "%H:%M:%S")

                for data in response_data.get("items"):
                    # Geting all future times
                    future_times = [
                        t for t in data["reminder_time"]
                        if t >= todays_time and datetime.strptime(t, "%H:%M:%S") > now
                    ]
                    if future_times:
                        earliest_time = min(future_times, key=lambda t: datetime.strptime(t, "%H:%M:%S"))
                        med_time = datetime.strptime(earliest_time, "%H:%M:%S")

                        # Update next_med if it's the soonest upcoming one
                        if not next_med or med_time < datetime.strptime(next_med["time"], "%H:%M:%S"):
                            next_med = {"name": data["medication"], "time": earliest_time}

                if next_med:
                    time_obj = datetime.strptime(next_med['time'], "%H:%M:%S")

                    # Formating time as 'HH:MM PM'
                    formatted_time_full = time_obj.strftime("%-I:%M %p")  # Use %-I for removing leading zero (Linux/macOS)

                    message = f"You're scheduled to take your {next_med['name']} at {formatted_time_full}. I'll remind you when it's time!"
                    attachment = {
                                    "query_response": message,
                                    "data": [],
                                    "type": "string",
                                    "status": "success"
                                }
            else:
                message = "Looks like you don’t have any meds scheduled!"
                attachment = {
                                    "query_response": message,
                                    "data": [],
                                    "type": "string",
                                    "status": "failed"
                                }
        except Exception as ex:
            reply = "Sorry, we couldn't access your medication information."
            attachment = {
                "query_response": reply,
                "data":[],
                "type":"string",
                "status": "failed"
            }
        dispatcher.utter_message(attachment=attachment)
        return[]

    
class actionStockLevel(Action):
   def name(self):
       return "action_stock_level"
  
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
               if data["code"].lower() == medication_name.lower():
                   stock_level = data["stock_level"]

           if stock_level >= 0:
               messages = [ f"Your current supply of {medication_name} is",
                            f"The quantity of {medication_name} you have left is",
                            f"Your available doses of {medication_name} are",
                            f"The remaining stock of {medication_name} in your possession is",
                            f"Your {medication_name} count stands at",
                            f"The number of {medication_name} doses you still have is",
                            f"Your inventory of {medication_name} shows"]
               reply = random.choice(messages)
               attachment = {
                   "query_response": f"{reply} {stock_level}",
                   "data": [],
                   "type": "string",
                   "status": "success"
               }
           else:
               reply = f"You do not have recorded medication with the name {medication_name}"
               attachment = {
                   "query_response": reply,
                   "data": [],
                   "type": "string",
                   "status": "failed"
               }
          
       except Exception as ex:
            reply = "Failed to get information about left dosage. Please try again!!"
            attachment = {
               "query_response": reply,
               "data":[],
               "type":"string",
               "status": "failed"
           }
       dispatcher.utter_message(attachment=attachment)
       return [SlotSet("medication", None)]

class actionRefilInformation(Action):
    def name(self):
        return "action_refil_information"
    
    def run(self, dispatcher: CollectingDispatcher, 
            tracker: Tracker, 
            domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
            medication_name = tracker.get_slot('medication')
            url = 'https://api.pillaxia.com/api/v1/user-medications/list'
            header = {
                        "Authorization" : f"Bearer {tracker.sender_id}"
                    }
            refil_info = {}
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
        
        
class actionNewSymptom(Action):
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


class actionSymptions(Action):
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
        dispatcher.utter_message(attachment=attachment)
        return[]
    
class checkMedication(Action):
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
    
class actionactionMedicationAdherence(Action):
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
        dispatcher.utter_message(attachment=attachment)
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
    
class actionCustomFallback(Action):
    def name(self):
        return "action_custom_fallback"       
        
    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any])  -> List[Dict[Text, Any]]:
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
                model = "gpt-4o",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "What's the best medication for my cough?"},
                    {"role": "assistant", "content": "I understand you're looking for relief from your cough. While I can't recommend specific medications, I suggest consulting a doctor if your cough persists."},
                    {"role": "user","content": user_query}
                ]
            )
            data = response.choices[0].message.content
            attachment = {
		    	"query_response": data,
		    	"data":[],
		    	"type":"string",
		    	"status": "success"
		    }
        except openai.OpenAIError as e:
            error_message = e.args[0].split("message': '")[1].split("',")[0] if "message" in str(e) else "Unknown error occurred."
            messages = ["Sorry, I can't process your request right now due to high demand. Please try again later.",
                    "Apologies, but it seems we're experiencing a temporary issue and cannot process your request at the moment. Please try again shortly."
                    ]
            attachment = {
                "query_response": random.choice(messages),
                "error": error_message,
                "data": [],
                "type": "string",
                "status": "failed"
            }
        except Exception as e:
            data = "Can you rephrase it."
            attachment = {
		    	"query_response": data,
                "error": str(e),
		    	"data":[],
		    	"type":"string",
		    	"status": "failed"
		    }
        dispatcher.utter_message(attachment=attachment)
        return []
        
