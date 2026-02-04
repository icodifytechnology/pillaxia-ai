"""
API CLIENT
==========
Central API client for Pillaxia backend services with retry logic and error handling.

Key:
- Singleton pattern (api_client instance)
- Retry logic with exponential backoff
- Authentication via Bearer tokens
- Comprehensive error handling

Env vars: PILLAXIA_API_URL, API_TIMEOUT, API_RETRY_ATTEMPTS, API_RETRY_DELAY
Endpoints: /profile, /user-medications/list, /medication-tracker/list, /user-medications/save, /health
"""

import requests
import os
import logging
from typing import Dict, Any, Optional, Tuple
import time

logger = logging.getLogger(__name__)


class PillaxiaAPIClient:
    """API client for Pillaxia backend services."""
    
    def __init__(self):
        """Initialize with environment variables or defaults."""
        self.base_url = os.getenv("PILLAXIA_API_URL", "https://api.pillaxia.com/api/v1")
        self.timeout = int(os.getenv("API_TIMEOUT", 30))
        self.retry_attempts = int(os.getenv("API_RETRY_ATTEMPTS", 2))
        self.retry_delay = int(os.getenv("API_RETRY_DELAY", 1))
        logger.debug(f"API Client base_url: {self.base_url}")
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Tuple[Optional[Dict], int, Optional[str]]:
        """
        Make HTTP request with retry logic.
        Returns: (data, status_code, error_message)
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        request_id = f"req_{int(time.time())}_{hash(url) % 1000:03d}"
        
        for attempt in range(self.retry_attempts + 1):
            try:
                response = requests.request(method=method, url=url, timeout=self.timeout, **kwargs)
                
                if response.status_code == 200:
                    return response.json(), response.status_code, None
                else:
                    # Don't retry on client errors (except 429 rate limit)
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        return None, response.status_code, f"Client error: {response.text[:100]}"
                    
                    # Retry on server errors and rate limits
                    if attempt < self.retry_attempts:
                        delay = self.retry_delay * (2 ** attempt)
                        time.sleep(delay)
                        continue
                    
                    return None, response.status_code, f"Server error: {response.status_code}"
                    
            except requests.exceptions.Timeout:
                if attempt < self.retry_attempts:
                    continue
                return None, 408, f"Request timeout"
            except requests.exceptions.ConnectionError:
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_delay)
                    continue
                return None, 503, "Connection failed"
            except Exception as e:
                return None, 500, f"Unexpected error: {str(e)}"
        
        return None, 500, "Max retries exceeded"
    
    def _get_auth_headers(self, token: str) -> Dict[str, str]:
        """Get authentication headers for API requests."""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Pillaxia-Rasa-Bot/1.0"
        }
    
    def get_user_profile(self, token: str) -> Optional[Dict[str, Any]]:
        """Get user profile information."""
        data, status_code, error = self._make_request(
            "GET", "/profile", headers=self._get_auth_headers(token)
        )
        
        if status_code == 200 and data:
            return data.get("result")
        return None
    
    def get_user_medications(self, token: str) -> Optional[Dict[str, Any]]:
        """Get user's medication list."""
        data, status_code, error = self._make_request(
            "POST", "/user-medications/list", headers=self._get_auth_headers(token)
        )
        
        if status_code == 200 and data:
            return data.get("result")
        return None
    
    def get_medication_tracking(self, token: str, start_date: str = None, end_date: str = None) -> Optional[Dict[str, Any]]:
        """Get medication tracking data with optional date filtering."""
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        
        data, status_code, error = self._make_request(
            "POST", "/medication-tracker/list", 
            headers=self._get_auth_headers(token),
            params=params
        )
        
        if status_code == 200 and data:
            return data.get("result", {})
        return None
    
    def save_user_medication(self, token: str, medication_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Save or update a user medication."""
        data, status_code, error = self._make_request(
            "POST", "/user-medications/save",
            headers=self._get_auth_headers(token),
            json=medication_data
        )
        
        if status_code == 200:
            message = data.get("message") if data else "Medication saved successfully"
            return True, message
        return False, error
        
    def health_check(self) -> bool:
        """Check if API is reachable (public endpoint)."""
        try:
            url = f"{self.base_url}/health"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False


# Singleton instance - import this in other files
api_client = PillaxiaAPIClient()