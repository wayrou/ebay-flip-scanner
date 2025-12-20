#!/bin/bash
cd /Users/alexhungate/Desktop/ebay-flip-scanner
source .venv/bin/activate
python src/main.py >> scanner.log 2>&1
