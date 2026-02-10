#!/bin/bash
# Script to retranslate GPT-4 Technical Report after API cooldown
# Usage: ./retranslate_gpt4.sh

echo "Waiting for API to become available..."

while true; do
    result=$(docker compose exec -T paperflow-converter python3 -c "
from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()
client = OpenAI(base_url=os.getenv('OPENAI_BASE_URL'), api_key=os.getenv('OPENAI_API_KEY'))
try:
    resp = client.chat.completions.create(
        model=os.getenv('TRANSLATION_MODEL', 'gemini-claude-sonnet-4-5'),
        messages=[{'role': 'user', 'content': 'Say hello in Korean'}],
        max_tokens=20
    )
    print('OK:' + resp.choices[0].message.content)
except Exception as e:
    print(f'WAIT:{e}')
" 2>/dev/null)

    if [[ "$result" == OK:* ]]; then
        echo "API is available! Starting retranslation..."
        break
    else
        echo "$(date '+%H:%M:%S') API still cooling down, retrying in 60s..."
        sleep 60
    fi
done

# Run retranslation
docker compose exec paperflow-converter python3 -c "
import sys
sys.path.insert(0, '/app')
from main_terminal import load_config, load_prompt, translate_md_to_korean_openai
import os

output_dir = '/app/outputs/GPT-4 Technical Report'
md_path = os.path.join(output_dir, 'GPT-4 Technical Report.md')
ko_path = os.path.join(output_dir, 'GPT-4 Technical Report_ko.md')

if os.path.exists(ko_path):
    os.remove(ko_path)
    print(f'Removed old: {ko_path}')

config = load_config()
prompt = load_prompt()
print(f'Starting translation...')

result = translate_md_to_korean_openai(md_path, output_dir, config, prompt)
if result:
    print(f'SUCCESS: {result}')
else:
    print('FAILED')
"

echo "Done!"
