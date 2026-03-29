"""
Multi-provider orchestration layer for OllaBridge Cloud.

Provides a unified interface to route requests across:
- Local OllamaBridge nodes (private, no external spend)
- Free LLM APIs (Gemini, Groq, OpenRouter, HuggingFace)
- Cheap LLM APIs (DeepSeek, Mistral, Together)
- Paid LLM APIs (OpenAI-compatible endpoints)

Architecture:
    adapters/   - how to talk to each provider
    catalog/    - which providers exist and how they are grouped
    services/   - load, seed, validate, and expose providers
"""
