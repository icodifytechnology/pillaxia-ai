
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class UncertaintyClassifier:
    def __init__(self):
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(
                max_features=3000,
                ngram_range=(1, 3),
                stop_words='english',
                lowercase=True,
                strip_accents='unicode'
            )),
            ('classifier', RandomForestClassifier(
                n_estimators=150,
                max_depth=15,
                min_samples_split=5,
                min_samples_leaf=2,
                random_state=42,
                class_weight='balanced'
            ))
        ])
        
        self.categories = ['CERTAIN', 'UNCERTAIN']
        
    def train(self, texts, labels):
        """Train the classifier"""
        logger.info(f"Training on {len(texts)} examples")
        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )
        
        self.pipeline.fit(X_train, y_train)
        
        # Evaluate
        accuracy = self.pipeline.score(X_test, y_test)
        logger.info(f"Model accuracy: {accuracy:.3f}")
        
        return accuracy
    
    def predict(self, text):
        """Predict category and return structured result"""
        # Get probability
        probs = self.pipeline.predict_proba([text])[0]
        pred = self.pipeline.predict([text])[0]
        confidence = max(probs)
        
        # Get which class has highest probability
        class_index = 0 if pred == 'CERTAIN' else 1
        
        return {
            'is_uncertain': pred == 'UNCERTAIN',
            'category': pred,
            'confidence': float(confidence),
            'probabilities': {
                'CERTAIN': float(probs[0]),
                'UNCERTAIN': float(probs[1])
            }
        }
    
    def save(self, path):
        joblib.dump(self.pipeline, path)
        logger.info(f"Model saved to {path}")
    
    def load(self, path):
        self.pipeline = joblib.load(path)
        logger.info(f"Model loaded from {path}")

# Singleton instance
_classifier_instance = None

def get_classifier():
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = UncertaintyClassifier()
        
        model_path = Path(__file__).parent.parent / "models" / "uncertainty.pkl"
        if model_path.exists():
            try:
                _classifier_instance.load(model_path)
            except Exception as e:
                logger.warning(f"Could not load model: {e}")
    
    return _classifier_instance