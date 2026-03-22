"""Tests for ProtestEventPrompter."""


def test_zero_shot_prompt_contains_text(prompter):
    text = "Workers marched outside the factory."
    prompt = prompter.build_zero_shot_prompt(text)
    assert text in prompt
    assert "JSON" in prompt


def test_zero_shot_prompt_contains_codebook(prompter):
    prompt = prompter.build_zero_shot_prompt("some text")
    assert "EVENT TYPE DEFINITIONS" in prompt


def test_few_shot_prompt_contains_examples(prompter):
    examples = [
        {"text": "Crowd marched.", "classification": "demonstration_march", "reasoning": "March."}
    ]
    prompt = prompter.build_few_shot_prompt("New text.", examples)
    assert "Crowd marched" in prompt
    assert "New text." in prompt


def test_cot_prompt_contains_steps(prompter):
    prompt = prompter.build_chain_of_thought_prompt("Some protest text.")
    assert "step-by-step" in prompt.lower() or "IDENTIFY" in prompt
