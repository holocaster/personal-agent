from personal_agent.providers import anthropic, chatgpt, gemini, openai, openrouter

PROVIDERS = {"openrouter": openrouter, "anthropic": anthropic, "openai": openai, "gemini": gemini, "chatgpt": chatgpt}


def get_provider(name: str):
    return PROVIDERS[name]
