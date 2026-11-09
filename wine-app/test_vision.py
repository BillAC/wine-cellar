
import os
import base64
import sys
import requests

def test_vision_extraction(image_path):
    if not os.path.exists(image_path):
        print(f"Error: Image not found at {image_path}")
        return

    print(f"Running Vision Test on: {image_path}")
    print("Using model: moondream:latest")
    print("-" * 50)

    prompt = (
        "Identify this wine label. Please extract the following information in a structured format: "
        "1. Winery/Producer Name, 2. Wine Name/Type, 3. Vintage (Year), 4. Region, 5. Grape Variety. "
        "If any info is missing, say 'Unknown'."
    )

    try:
        with open(image_path, "rb") as img_file:
            img_base64 = base64.b64encode(img_file.read()).decode('utf-8')

        payload = {
            "model": "moondream:latest",
            "prompt": prompt,
            "stream": False,
            "images": [img_base64]
        }
        
        response = requests.post("http://localhost:11434/api/generate", json=payload)
        
        if response.status_code == 200:
            print("Extraction Result:")
            print(response.json().get("response", "No response received."))
        else:
            print(f"API Error: {response.status_code} - {response.text}")
        print("-" * 50)

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_vision_extraction(sys.argv[1])
    else:
        print("Usage: python test_vision.py <path_to_image>")
