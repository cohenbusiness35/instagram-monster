#!/bin/bash
cd /home/cohen/instagram-monster
source venv/bin/activate
python3 scraper.py 2>&1 | tee -a run.log
