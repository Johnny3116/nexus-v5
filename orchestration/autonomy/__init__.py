"""autonomy — reflex engine, heartbeat, scheduler.

These modules run autonomously (no human in the loop) and are gated by
safety tiers (safety/output_filters/safety_tier_gate.py). Every autonomous
action writes to automation_history (Doctrine 7).
"""
