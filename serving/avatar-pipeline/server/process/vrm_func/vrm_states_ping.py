# test_ping_states.py - Test VRM avatar state transitions and microexpressions
# Updated with tests for new realistic head movement features
import time
import sys
import requests

BASE_URL = "http://localhost:8001"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def set_vrm_state(state):
    """
    Set the VRM avatar's animation state.

    Valid states:
        - idle: Avatar looks around naturally, with chance to look at user
        - listening: Avatar focuses on user with occasional side glances
        - thinking: Avatar looks away with eyes leading head movement
        - talking: Avatar nods with variable intensity and head tilts
    """
    url = f"{BASE_URL}/set_state"
    payload = {"state": state}
    resp = requests.post(url, json=payload)
    print(f"[set_state] Status: {resp.status_code}, State: {state}")
    return resp


def set_movement_lock_duration(duration):
    """
    Set the movement lock duration after state transitions.
    During lock, head stays centered before new state animations begin.

    Args:
        duration: Lock duration in seconds (default 1.0)
    """
    url = f"{BASE_URL}/set_movement_lock_duration"
    payload = {"duration": duration}
    resp = requests.post(url, json=payload)
    print(f"[set_lock_duration] Status: {resp.status_code}, Duration: {duration}s")
    return resp


def vrm_animate(animation_type, animate_url, play_once=False, lock_position=False, track_position=True):
    """Play a VRMA or Mixamo animation."""
    url = f"{BASE_URL}/animate"
    payload = {
        "animate_type": animation_type,
        "animation_url": animate_url,
        "play_once": play_once,
        "crop_start": 0.0,
        "crop_end": 0.0,
        "lock_position": lock_position,
        "track_position": track_position,
    }
    resp = requests.post(url, json=payload)
    print(f"[animate] Status: {resp.status_code}")
    return resp


def vrm_walk_to(x, y, z, speed=1.5):
    """Walk the VRM character to a position."""
    url = f"{BASE_URL}/walk_to"
    payload = {"x": x, "y": y, "z": z, "speed": speed}
    resp = requests.post(url, json=payload)
    print(f"[walk_to] Status: {resp.status_code}, Target: ({x}, {y}, {z})")
    return resp


def vrm_stop_movement():
    """Stop VRM movement and return to idle."""
    url = f"{BASE_URL}/stop_movement"
    resp = requests.post(url)
    print(f"[stop_movement] Status: {resp.status_code}")
    return resp


def print_header(title, description=""):
    """Print a formatted test header."""
    print("\n" + "=" * 70)
    print(f"TEST: {title}")
    print("=" * 70)
    if description:
        print(description)
    print()


def print_step(step_num, total, description):
    """Print a formatted step indicator."""
    print(f"\n[{step_num}/{total}] {description}")
    print("-" * 50)


# =============================================================================
# INDIVIDUAL STATE TESTS
# =============================================================================

def test_idle_state():
    """Test: Idle state with look-at-user feature"""
    print_header(
        "IDLE STATE - Natural Looking Around with User Focus",
        "Features being tested:\n"
        "  - Natural head movements with smooth acceleration/deceleration\n"
        "  - Periodic chance (35%) to look back at user/camera\n"
        "  - Adjustable user-look duration (1.5-3.5 seconds)\n"
        "  - Eyes and head reset to center when looking at user"
    )

    set_vrm_state("idle")
    print("\nWatch for:")
    print("  - Head should look around smoothly")
    print("  - Periodically returns to center (looking at you)")
    print("  - Movement should have natural acceleration/deceleration")

    time.sleep(12)
    print("\n[OK] Idle state test complete")


def test_listening_state():
    """Test: Listening state with side glances"""
    print_header(
        "LISTENING STATE - Focused Attention with Side Glances",
        "Features being tested:\n"
        "  - Primary focus on user (eyes centered)\n"
        "  - Occasional side glances (1-3 seconds)\n"
        "  - Subtle nodding while listening\n"
        "  - Micro eye movements while focused"
    )

    set_vrm_state("listening")
    print("\nWatch for:")
    print("  - Avatar mainly focused on you (centered)")
    print("  - Occasional brief glances to left or right")
    print("  - Gentle nodding showing engagement")

    time.sleep(12)
    print("\n[OK] Listening state test complete")


def test_thinking_state():
    """Test: Thinking state with eye-leads-head behavior"""
    print_header(
        "THINKING STATE - Contemplative with Eyes Leading Head",
        "Features being tested:\n"
        "  - Eyes move BEFORE head (0.25s lead time)\n"
        "  - Eyes and head move in same direction (85% sync)\n"
        "  - Look-up bias for contemplative appearance\n"
        "  - Distant gaze while thinking"
    )

    set_vrm_state("thinking")
    print("\nWatch for:")
    print("  - Eyes move first, then head follows")
    print("  - Tendency to look upward (thinking gesture)")
    print("  - Smooth, contemplative movements")

    time.sleep(12)
    print("\n[OK] Thinking state test complete")


def test_talking_state():
    """Test: Talking state with variable nodding"""
    print_header(
        "TALKING STATE - Variable Nodding with Head Tilts",
        "Features being tested:\n"
        "  - Variable nod frequency (changes every 1.5s)\n"
        "  - Variable nod intensity (+/- 40%)\n"
        "  - Occasional head tilts for emphasis\n"
        "  - Brief micro-pauses in nodding"
    )

    set_vrm_state("talking")
    print("\nWatch for:")
    print("  - Nodding speed/intensity changes over time")
    print("  - Occasional head tilts (left/right)")
    print("  - Brief pauses between nod sequences")

    time.sleep(12)
    print("\n[OK] Talking state test complete")


# =============================================================================
# TRANSITION TESTS
# =============================================================================

def test_smooth_transitions():
    """Test: Smooth state transitions with movement lock"""
    print_header(
        "SMOOTH TRANSITIONS - Reset to Center with Lock",
        "Features being tested:\n"
        "  - Head smoothly resets to center on state change\n"
        "  - Natural acceleration/deceleration during reset\n"
        "  - 1 second movement lock after transition\n"
        "  - Clean start for new state animations"
    )

    print_step(1, 5, "Starting in IDLE state")
    set_vrm_state("idle")
    print("Avatar looking around...")
    time.sleep(15)

    print_step(2, 5, "Transition to LISTENING")
    set_vrm_state("listening")
    print("Watch: Head should smoothly return to center")
    print("Watch: 1 second pause before listening animations start")
    time.sleep(15)

    print_step(3, 5, "Transition to THINKING")
    set_vrm_state("thinking")
    print("Watch: Smooth reset, then thinking animations begin")
    time.sleep(15)

    print_step(4, 5, "Transition to TALKING")
    set_vrm_state("talking")
    print("Watch: Clean transition to talking animations")
    time.sleep(15)

    print_step(5, 5, "Return to IDLE")
    set_vrm_state("idle")
    print("Completing transition cycle")
    time.sleep(13)

    print("\n[OK] Smooth transitions test complete")


def test_rapid_transitions():
    """Test: Rapid state changes to verify smooth behavior"""
    print_header(
        "RAPID TRANSITIONS - Quick State Changes",
        "Testing smooth behavior under rapid state changes.\n"
        "Head should always reset smoothly, never snap."
    )

    states = ["idle", "listening", "thinking", "talking", "idle", "talking", "listening"]

    for i, state in enumerate(states, 1):
        print_step(i, len(states), f"Switching to {state.upper()}")
        set_vrm_state(state)
        print("Head should smoothly center before new animations")
        time.sleep(2.5)

    print("\n[OK] Rapid transitions test complete")


def test_variable_lock_duration():
    """Test: Different movement lock durations"""
    print_header(
        "VARIABLE LOCK DURATION - Testing Different Lock Times",
        "Testing how different lock durations affect transitions."
    )

    # Short lock (0.3 seconds)
    print_step(1, 3, "Testing SHORT lock duration (0.3s)")
    set_movement_lock_duration(0.3)
    set_vrm_state("thinking")
    print("Animations should start quickly after reset")
    time.sleep(4)

    # Medium lock (1.0 seconds - default)
    print_step(2, 3, "Testing DEFAULT lock duration (1.0s)")
    set_movement_lock_duration(1.0)
    set_vrm_state("talking")
    print("Standard 1 second pause after reset")
    time.sleep(4)

    # Long lock (2.0 seconds)
    print_step(3, 3, "Testing LONG lock duration (2.0s)")
    set_movement_lock_duration(2.0)
    set_vrm_state("idle")
    print("Longer pause before idle animations")
    time.sleep(5)

    # Reset to default
    set_movement_lock_duration(1.0)
    print("\n[OK] Variable lock duration test complete")


# =============================================================================
# CONVERSATION FLOW TESTS
# =============================================================================

def test_conversation_flow():
    """Test: Full conversation flow with realistic timings"""
    print_header(
        "FULL CONVERSATION FLOW",
        "Simulating a realistic conversation cycle:\n"
        "User speaks -> Avatar listens -> Avatar thinks -> Avatar responds"
    )

    # Start idle
    print_step(1, 6, "Avatar is IDLE, waiting")
    set_vrm_state("idle")
    print("Avatar naturally looking around, occasionally at user")
    time.sleep(6)

    # User starts speaking
    print_step(2, 6, "User starts speaking - LISTENING")
    set_vrm_state("listening")
    print("Avatar focuses on user, occasional side glances")
    print("Subtle nodding shows engagement")
    time.sleep(8)

    # User finishes, avatar processes
    print_step(3, 6, "User finishes - THINKING")
    set_vrm_state("thinking")
    print("Avatar looks away, eyes lead head")
    print("Contemplative upward gaze")
    time.sleep(6)

    # Avatar responds
    print_step(4, 6, "Avatar responds - TALKING")
    set_vrm_state("talking")
    print("Variable nodding with head tilts")
    print("Animated but natural speaking gestures")
    time.sleep(10)

    # Conversation pauses
    print_step(5, 6, "Brief pause - IDLE")
    set_vrm_state("idle")
    print("Waiting for user response")
    time.sleep(4)

    # Quick follow-up
    print_step(6, 6, "Quick follow-up - TALKING")
    set_vrm_state("talking")
    print("Quick response, different nod pattern")
    time.sleep(5)

    set_vrm_state("idle")
    print("\n[OK] Conversation flow test complete")


def test_extended_states():
    """Test: Extended time in each state to observe variations"""
    print_header(
        "EXTENDED STATE DURATION",
        "Spending longer in each state to observe animation variations.\n"
        "Each state runs for 15 seconds."
    )

    test_states = [
        ("idle", "Multiple look cycles, several returns to user"),
        ("listening", "Several side glances, multiple nod sequences"),
        ("thinking", "Multiple eye-lead-head movements, varied directions"),
        ("talking", "Nod pattern changes, multiple tilts"),
    ]

    for i, (state, expected) in enumerate(test_states, 1):
        print_step(i, len(test_states), f"Extended {state.upper()} state (15 seconds)")
        print(f"Expected: {expected}")
        set_vrm_state(state)
        time.sleep(15)
        print(f"[OK] {state} observations complete")

    print("\n[OK] Extended state duration tests complete")


# =============================================================================
# COMBINED TESTS
# =============================================================================

def test_state_with_movement():
    """Test: States combined with walking movement"""
    print_header(
        "STATES WITH MOVEMENT",
        "Testing state animations while character is walking."
    )

    print_step(1, 4, "Start walking while IDLE")
    set_vrm_state("idle")
    vrm_walk_to(2, 0, 2, speed=1.0)
    print("Head should look around while walking")
    time.sleep(4)

    print_step(2, 4, "Switch to LISTENING while moving")
    set_vrm_state("listening")
    print("Should focus forward more while walking")
    time.sleep(4)

    print_step(3, 4, "Stop movement, enter THINKING")
    vrm_stop_movement()
    set_vrm_state("thinking")
    print("Contemplative state after stopping")
    time.sleep(4)

    print_step(4, 4, "Walk back while TALKING")
    set_vrm_state("talking")
    vrm_walk_to(0, 0, 0, speed=1.0)
    print("Nodding while returning to center")
    time.sleep(4)

    vrm_stop_movement()
    set_vrm_state("idle")
    print("\n[OK] State with movement test complete")


def test_all():
    """Run all tests in sequence"""
    print("\n" + "=" * 70)
    print("RUNNING ALL STATE ANIMATION TESTS")
    print("=" * 70)

    tests = [
        ("Individual States", [
            test_idle_state,
            test_listening_state,
            test_thinking_state,
            test_talking_state,
        ]),
        ("Transitions", [
            test_smooth_transitions,
            test_rapid_transitions,
            test_variable_lock_duration,
        ]),
        ("Conversation Flows", [
            test_conversation_flow,
            test_extended_states,
        ]),
        ("Combined Tests", [
            test_state_with_movement,
        ]),
    ]

    for category, test_funcs in tests:
        print(f"\n{'='*70}")
        print(f"CATEGORY: {category}")
        print(f"{'='*70}")
        for test_func in test_funcs:
            test_func()
            time.sleep(1)

    print("\n" + "=" * 70)
    print("ALL TESTS COMPLETE")
    print("=" * 70)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    # Dictionary of available tests
    tests = {
        # Individual states
        "idle": test_idle_state,
        "listening": test_listening_state,
        "thinking": test_thinking_state,
        "talking": test_talking_state,
        # Transitions
        "transitions": test_smooth_transitions,
        "rapid": test_rapid_transitions,
        "lock": test_variable_lock_duration,
        # Flows
        "conversation": test_conversation_flow,
        "extended": test_extended_states,
        # Combined
        "movement": test_state_with_movement,
        # All
        "all": test_all,
    }

    print("\n" + "=" * 70)
    print("VRM AVATAR STATE SYSTEM TEST SUITE")
    print("=" * 70)
    print("\nNew Features:")
    print("  - Idle: Look-at-user reset chance with adjustable duration")
    print("  - Listening: Side glances while focused on user")
    print("  - Thinking: Eyes lead head movement")
    print("  - Talking: Variable nodding with head tilts")
    print("  - Transitions: Smooth reset with movement lock")

    if len(sys.argv) > 1:
        for test_name in sys.argv[1:]:
            if test_name in tests:
                tests[test_name]()
            else:
                print(f"\nUnknown test: {test_name}")
                print(f"Available tests: {', '.join(tests.keys())}")
                sys.exit(1)
    else:
        print("\nUsage: python test_ping_states.py <test_name>")
        print("\nAvailable tests:")
        print("  Individual states: idle, listening, thinking, talking")
        print("  Transitions: transitions, rapid, lock")
        print("  Conversation: conversation, extended")
        print("  Combined: movement")
        print("  Run all: all")
        print("\nRunning default test (smooth transitions)...\n")
        test_smooth_transitions()
