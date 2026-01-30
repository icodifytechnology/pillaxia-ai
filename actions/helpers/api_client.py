import requests
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class PillaxiaAPIClient:
    def __init__(self):
        self.base_url = os.getenv("PILLAXIA_API_URL", "https://api.pillaxia.com/api/v1")
        self.timeout = int(os.getenv("API_TIMEOUT", 30))
    
    def get_user_profile(self, token: str) -> Optional[Dict[str, Any]]:
        """Get user profile"""
        url = f"{self.base_url}/profile"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                # Extract from "result" key in your API response
                return data.get("result")
            else:
                logger.error(f"API Error {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching profile: {str(e)}")
            return None

# Singleton instance
api_client = PillaxiaAPIClient()