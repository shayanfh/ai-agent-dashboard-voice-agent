from app.agent.instructions import compose_instructions
from app.backend.schemas import ResolvedAgent


def test_default_instructions_require_clarification_instead_of_guessing() -> None:
    instructions = compose_instructions(
        ResolvedAgent(
            company_id="company",
            agent_id="agent",
            agent_name="Restaurant Agent",
            language="fa",
            system_prompt="Help callers reserve a table.",
        )
    )

    assert "do not guess or pretend to understand" in instructions
    assert "ask the caller" in instructions
    assert "repeat or clarify" in instructions
    assert "in the conversation's current" in instructions
    assert "language, to repeat" in instructions
    assert "Default language: fa" in instructions
    assert "clearly says goodbye" in instructions
    assert "use the end_call tool" in instructions
    assert "transfer_to_extension" in instructions
    assert "Do not use it for silence" in instructions
