"""
API Client for Pillaxia with enhanced debugging and error handling
"""

import requests
import os
import logging
from typing import Dict, Any, Optional, Tuple
import time

logger = logging.getLogger(__name__)


class PillaxiaAPIClient:
    """API client for Pillaxia backend services"""
    
    def __init__(self):
        self.base_url = os.getenv("PILLAXIA_API_URL", "https://api.pillaxia.com/api/v1")
        self.timeout = int(os.getenv("API_TIMEOUT", 30))
        self.retry_attempts = int(os.getenv("API_RETRY_ATTEMPTS", 2))
        self.retry_delay = int(os.getenv("API_RETRY_DELAY", 1))
        
        logger.debug(f"API Client initialized with base_url: {self.base_url}")
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Tuple[Optional[Dict], int, Optional[str]]:
        """
        Make HTTP request with retry logic and comprehensive debugging
        
        Returns: (data, status_code, error_message)
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        request_id = f"req_{int(time.time())}_{hash(url) % 1000:03d}"
        
        logger.debug(f"[{request_id}] {method} {url}")
        
        for attempt in range(self.retry_attempts + 1):
            try:
                start_time = time.time()
                response = requests.request(
                    method=method,
                    url=url,
                    timeout=self.timeout,
                    **kwargs
                )
                elapsed = time.time() - start_time
                
                logger.debug(f"[{request_id}] Attempt {attempt + 1}/{self.retry_attempts + 1}")
                logger.debug(f"[{request_id}] Status: {response.status_code}, Time: {elapsed:.2f}s")
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        logger.debug(f"[{request_id}] Success - Response keys: {list(data.keys())}")
                        return data, response.status_code, None
                    except ValueError as e:
                        logger.error(f"[{request_id}] JSON decode error: {e}")
                        return None, response.status_code, f"Invalid JSON response: {e}"
                else:
                    logger.warning(f"[{request_id}] HTTP {response.status_code}: {response.text[:200]}")
                    
                    # Don't retry on client errors (4xx) except 429 (rate limit)
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        return None, response.status_code, f"Client error: {response.text[:100]}"
                    
                    # Retry on server errors (5xx) and rate limits
                    if attempt < self.retry_attempts:
                        delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.debug(f"[{request_id}] Retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    
                    return None, response.status_code, f"Server error: {response.status_code}"
                    
            except requests.exceptions.Timeout:
                logger.error(f"[{request_id}] Timeout after {self.timeout}s")
                if attempt < self.retry_attempts:
                    logger.debug(f"[{request_id}] Retrying timeout...")
                    continue
                return None, 408, f"Request timeout after {self.timeout}s"
                
            except requests.exceptions.ConnectionError:
                logger.error(f"[{request_id}] Connection error")
                if attempt < self.retry_attempts:
                    logger.debug(f"[{request_id}] Retrying connection...")
                    time.sleep(self.retry_delay)
                    continue
                return None, 503, "Connection failed"
                
            except Exception as e:
                logger.error(f"[{request_id}] Unexpected error: {str(e)}", exc_info=True)
                return None, 500, f"Unexpected error: {str(e)}"
        
        return None, 500, "Max retries exceeded"
    
    def get_user_profile(self, token: str) -> Optional[Dict[str, Any]]:
        """Get user profile with authentication"""
        logger.info(f"Fetching user profile for token: {token[:20]}...")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Pillaxia-Rasa-Bot/1.0"
        }
        
        data, status_code, error = self._make_request(
            "GET",
            "/profile",
            headers=headers
        )
        
        if status_code == 200 and data:
            # Extract from "result" key in API response
            result = data.get("result")
            if result:
                logger.info(f"Profile fetched successfully")
                logger.debug(f"Profile fields: {list(result.keys())}")
                
                # Log specific fields (mask sensitive data)
                safe_profile = result.copy()
                for key in ["email", "phone", "password"]:
                    if key in safe_profile and safe_profile[key]:
                        safe_profile[key] = f"{safe_profile[key][:3]}...{safe_profile[key][-2:]}"
                
                logger.debug(f"Profile data (sanitized): {safe_profile}")
                return result
            else:
                logger.warning("API response missing 'result' key")
                logger.debug(f"Full response: {data}")
                return None
        else:
            logger.error(f"Failed to fetch profile: {error}")
            return None
    
    def get_user_medications(self, token: str) -> Optional[Dict[str, Any]]:
        """Get user's medication list"""
        logger.info(f"Fetching medications for token: {token[:20]}...")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Pillaxia-Rasa-Bot/1.0"
        }

        data, status_code, error = self._make_request(
            "POST",  
            "/user-medications/list",  
            headers=headers
        )

        if status_code == 200 and data:
            result = data.get("result")
            if result:
                logger.info(f"Medications fetched successfully - {result.get('count', 0)} items")
                logger.debug(f"Medication data structure: {list(result.keys())}")
                return result
            else:
                logger.warning("API response missing 'result' key for medications")
                return None
        else:
            logger.error(f"Failed to fetch medications: {error}")
            return None
     
    def save_user_medication(self, token: str, medication_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Save/update a user medication"""
        logger.info(f"Saving medication for token: {token[:20]}...")
        logger.debug(f"Medication data: {medication_data}")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Pillaxia-Rasa-Bot/1.0"
        }

        data, status_code, error = self._make_request(
            "POST",
            "/user-medications/save",  
            headers=headers,
            json=medication_data
        )

        if status_code == 200:
            logger.info("Medication saved successfully")
            if data and "message" in data:
                return True, data.get("message")
            return True, "Medication saved successfully"
        else:
            logger.error(f"Failed to save medication: {error}")
            return False, error
        
    def health_check(self) -> bool:
        """Check if API is reachable"""
        try:
            url = f"{self.base_url}/health"
            logger.debug(f"Health check: {url}")
            response = requests.get(url, timeout=5)
            logger.debug(f"Health check status: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False


# Singleton instance
api_client = PillaxiaAPIClient()