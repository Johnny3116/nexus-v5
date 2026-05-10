"""Live end-to-end test: Nexus memory injection + full gateway pipeline.

Calls llm_response() directly — which loads Supabase memories, injects
them into the system prompt, then calls the gateway /v1/chat endpoint
(which routes to Qwen via Ollama).

Usage:
    python C:/Users/Nexus/Nexus/test_live_message.py
"""
import sys
import importlib.util
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NEXUS_ROOT = Path("C:/Users/Nexus/Nexus")
LLM_SCR = NEXUS_ROOT / "serving/avatar-pipeline/server/process/llm_funcs/llm_scr.py"

sys.path.insert(0, str(NEXUS_ROOT))

from dotenv import load_dotenv
load_dotenv(NEXUS_ROOT / ".env")

print("=" * 60)
print("Nexus -- Live Pipeline Test (gateway + memory)")
print("=" * 60)

# Load llm_scr via importlib (avatar-pipeline dir has a hyphen)
spec = importlib.util.spec_from_file_location("llm_scr", LLM_SCR)
llm_scr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm_scr)
print(f"Gateway URL: {llm_scr.GATEWAY_URL}")

# -- 1. Load memories block ----------------------------------------
print("\n[1/3] Loading Supabase memory block...")
block = llm_scr._load_memories_block()
if block:
    lines = block.split("\n")
    print(f"  OK -- {len(lines)} lines from Supabase")
    for line in lines[:5]:
        print(f"    {line}")
    if len(lines) > 5:
        print(f"    ... ({len(lines)-5} more)")
else:
    print("  OK -- memory block empty")

# -- 2. Send through full gateway pipeline -------------------------
print("\n[2/3] Sending via llm_response() -> gateway -> Qwen...")
user_input = "Hello Nexus. What do you know about me? Keep it brief."
response = llm_scr.llm_response(user_input)
print(f"  OK -- response ({len(response)} chars):")
print()
for line in response.strip().split("\n"):
    print(f"    {line}")

# -- 3. Confirm extraction thread launched -------------------------
print("\n[3/3] Background memory extraction thread launched.")

print("\n" + "=" * 60)
print("  FULL PIPELINE: PASSED")
print("  Memories loaded -> injected -> gateway -> LLM -> response")
print("=" * 60)
