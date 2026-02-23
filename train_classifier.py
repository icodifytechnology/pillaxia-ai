
import pandas as pd
from pathlib import Path
import logging
from actions.uncertainty_classifier import UncertaintyClassifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # Load training data
    data_path = Path(__file__).parent / "data" / "uncertainty_training_data.csv"
    df = pd.read_csv(data_path)
    
    logger.info(f"Loaded {len(df)} training examples")
    logger.info(f"CERTAIN: {len(df[df['category']=='CERTAIN'])}")
    logger.info(f"UNCERTAIN: {len(df[df['category']=='UNCERTAIN'])}")
    
    # Create and train classifier
    classifier = UncertaintyClassifier()
    accuracy = classifier.train(df['text'].tolist(), df['category'].tolist())
    
    # Save model
    model_path = Path(__file__).parent / "models" / "uncertainty.pkl"
    model_path.parent.mkdir(exist_ok=True)
    classifier.save(model_path)
    
    # Test examples
    test_phrases = [
        "Lisinopril",
        "dont know",
        "not sure",
        "Metformin 500mg",
        "skip",
        "what should I do",
        "blue pill",
        "I think it's Amlodipine"
    ]
    
    logger.info("\n🔍 Testing model predictions:")
    for phrase in test_phrases:
        result = classifier.predict(phrase)
        logger.info(f"'{phrase}' -> {result['category']} (conf: {result['confidence']:.3f})")

if __name__ == "__main__":
    main()