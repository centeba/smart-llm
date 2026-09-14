import asyncio
import os

from smart_llm import Agent, AgentManager, ContextPruningTool


async def main():
    """
    Demo script showcasing how to use the 'smart-llm' package standalone.
    """
    print("--- smart-llm Agent Demo ---")

    # 1. Define an Agent with specific tools
    # Note: Replace with your actual API key for a live test.
    api_key = os.getenv("GOOGLE_API_KEY", "your_api_key_here")

    agent = Agent(
        name="demo_agent",
        provider_type="gemini",
        system_prompt="You are a helpful and concise coding assistant.",
        api_key=api_key,
        tools=[ContextPruningTool(max_chars=500)],  # Limits context for efficiency
    )

    # 2. Use a Manager for failover (optional but recommended)
    manager = AgentManager()
    manager.register_agent(agent)

    # 3. Analyze content
    content = "Explain the benefit of an agentic AI architecture in 3 bullet points."
    print(f"\nPrompting: {content}")

    try:
        response = await manager.analyze(content)
        print(f"\nResponse (Metadata): {response.metadata}")
        print(f"Response (Content): {response.data}")
    except Exception as e:
        print(f"\nError: {e}")


if __name__ == "__main__":
    asyncio.run(main())
