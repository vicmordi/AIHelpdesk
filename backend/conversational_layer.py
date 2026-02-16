"""
Conversational Layer: OpenAI generates ONLY tone/framing.
All troubleshooting steps come strictly from the Knowledge Base.
OpenAI MUST NOT invent steps or use external knowledge.
"""

from typing import Optional

# System prompts: OpenAI may ONLY rephrase tone, never add instructions
SYSTEM_INTRO = """You are a professional IT helpdesk agent.
Generate a short, natural, friendly introduction to a troubleshooting process.
Do NOT generate instructions. Do NOT generate steps. Only introduce the troubleshooting process.
Reply with ONLY the intro sentence, no preamble. Keep it under 2 sentences."""

SYSTEM_PROGRESS = """You are a professional IT helpdesk agent.
Generate a short, natural progress response to encourage the user.
Do NOT repeat previous wording. Do NOT generate instructions. Do NOT add steps.
Reply with ONLY the encouragement sentence, no preamble. Keep it under 2 sentences."""

SYSTEM_COMPLETION = """You are a professional IT helpdesk agent.
Generate a short completion message. Ask if the issue is resolved.
Do NOT restart troubleshooting. Do NOT add new steps.
Reply with ONLY the completion sentence, no preamble. Keep it under 2 sentences."""

SYSTEM_ESCALATION = """You are a professional IT helpdesk agent.
Generate a short escalation message. Inform the user that a support specialist will take over.
Do NOT continue steps. Do NOT add technical advice.
Reply with ONLY the escalation sentence, no preamble. Keep it under 2 sentences."""


def generate_flow_intro(openai_client, topic: str = "this") -> str:
    """Generate intro framing only. No instructions."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": SYSTEM_INTRO},
                {"role": "user", "content": f"The user needs help with: {topic}. Write a friendly intro."},
            ],
            temperature=0.7,
            max_tokens=80,
        )
        return (response.choices[0].message.content or "").strip() or "I'll guide you through this."
    except Exception:
        return "I'll guide you through this."


def generate_flow_progress(openai_client, step_number: int, total_steps: int) -> str:
    """Generate progress encouragement only. No instructions."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": SYSTEM_PROGRESS},
                {"role": "user", "content": f"User completed step {step_number} of {total_steps}. Encourage them briefly."},
            ],
            temperature=0.7,
            max_tokens=60,
        )
        return (response.choices[0].message.content or "").strip() or "Got it."
    except Exception:
        return "Got it."


def generate_flow_completion(openai_client, topic: str = "this") -> str:
    """Generate completion message only. No new steps."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": SYSTEM_COMPLETION},
                {"role": "user", "content": f"Troubleshooting for '{topic}' is done. Ask if it's working."},
            ],
            temperature=0.7,
            max_tokens=80,
        )
        return (response.choices[0].message.content or "").strip() or "Is everything working correctly now?"
    except Exception:
        return "Is everything working correctly now?"


def generate_flow_escalation(openai_client) -> str:
    """Generate escalation message only."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": SYSTEM_ESCALATION},
                {"role": "user", "content": "Inform user a support specialist will take over."},
            ],
            temperature=0.5,
            max_tokens=80,
        )
        return (response.choices[0].message.content or "").strip() or "I'm escalating this to a support specialist."
    except Exception:
        return "I'm escalating this to a support specialist."
