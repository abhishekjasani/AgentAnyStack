import pytest

from agent_anystack.adapters.bedrock import _parse_converse_output
from agent_anystack.adapters.llm import StackError, _parse_tool_calls


def test_openai_compatible_tool_call_preserves_provider_id():
    parsed = _parse_tool_calls(
        [
            {
                "id": "provider-call-1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": "{}"},
            }
        ]
    )

    assert parsed[0].provider_tool_call_id == "provider-call-1"
    assert parsed[0].name == "get_weather"


def test_openai_compatible_tool_call_without_provider_id_fails_closed():
    with pytest.raises(StackError, match="omitted its provider call ID"):
        _parse_tool_calls(
            [{"type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]
        )


def test_bedrock_tool_use_without_provider_id_fails_closed():
    response = {
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "name": "get_weather",
                            "input": {},
                        }
                    }
                ]
            }
        }
    }

    with pytest.raises(StackError, match="omitted toolUseId"):
        _parse_converse_output(response)