"""One short call to the Claude API. Task 5.1.

The smallest possible proof that four things are true at once: the key in
`backend/.env` is valid, the SDK is installed, this machine can reach the API,
and the model id in configuration exists. When the explainer misbehaves later,
running this first separates "my code is wrong" from "my setup is wrong" --
which is most of debugging.

    cd backend
    .venv/Scripts/python.exe scripts/hello_claude.py

**The key is never typed here and never printed.** It comes from
`backend/.env` through `app.config`, which stores it as a `SecretStr`, so even
an accidental print shows `**********`. The whole point of task 5.1's second
"done when" -- `git grep` for your key finds nothing -- is that there is
nowhere in this repository for it to be.

Costs a fraction of a cent: about 20 tokens in, at most 100 out.
"""

import sys
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ConfigError, get_settings  # noqa: E402

QUESTION = "Reply with exactly: A11y-Lens is connected."


def main() -> int:
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    if settings.uses_placeholder_api_key:
        print(
            "ANTHROPIC_API_KEY in backend/.env is still the placeholder.\n"
            "\n"
            "Get a key from https://console.anthropic.com -> API keys, then\n"
            "put it in backend/.env as:\n"
            "\n"
            "    ANTHROPIC_API_KEY=sk-ant-...\n"
            "\n"
            "backend/.env is git-ignored, so it will not be committed.",
            file=sys.stderr,
        )
        return 1

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value()
    )

    print(f"Model:  {settings.anthropic_model}")
    print(f"Effort: {settings.anthropic_effort}")
    print(f"Asking: {QUESTION}\n")

    try:
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=100,
            output_config={"effort": settings.anthropic_effort},
            messages=[{"role": "user", "content": QUESTION}],
        )
    # Most specific first. AuthenticationError, NotFoundError and
    # RateLimitError are all subclasses of APIStatusError, so a broad except
    # placed above them would swallow every one of these messages.
    except anthropic.AuthenticationError:
        print(
            "The API key was rejected (401). Check for a copied space or a\n"
            "revoked key at https://console.anthropic.com -> API keys.",
            file=sys.stderr,
        )
        return 1
    except anthropic.NotFoundError:
        print(
            f"The model id {settings.anthropic_model!r} does not exist (404).\n"
            "Check ANTHROPIC_MODEL in backend/.env.",
            file=sys.stderr,
        )
        return 1
    except anthropic.RateLimitError:
        print("Rate limited (429). Wait a moment and run it again.", file=sys.stderr)
        return 1
    except anthropic.APIStatusError as exc:
        print(f"The API returned {exc.status_code}.", file=sys.stderr)
        return 1
    except anthropic.APIConnectionError:
        print(
            "Could not reach the API at all. Check this machine's internet\n"
            "connection, and any proxy or firewall in the way.",
            file=sys.stderr,
        )
        return 1

    # Always before reading content. `max_tokens` means the answer was cut off
    # mid-sentence, and `refusal` means there is no answer in there to read.
    if message.stop_reason not in ("end_turn", "stop_sequence"):
        print(f"Stopped early: stop_reason={message.stop_reason}", file=sys.stderr)
        return 1

    # content is a list of blocks, not a string: on this model it holds a
    # thinking block as well as the answer, so the type has to be checked
    # rather than assuming content[0] is the text.
    answer = "".join(block.text for block in message.content if block.type == "text")

    print(f"Claude: {answer.strip()}")
    print(
        f"\nTokens: {message.usage.input_tokens} in, "
        f"{message.usage.output_tokens} out  (request {message._request_id})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
