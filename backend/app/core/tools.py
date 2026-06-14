import httpx
from datetime import datetime
from langchain_core.tools import tool


@tool
def web_search(query: str) -> str:
    """Search the web for information about a topic."""
    try:
        response = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=10,
        )
        data = response.json()
        if data.get("AbstractText"):
            return data["AbstractText"]
        topics = data.get("RelatedTopics", [])[:3]
        results = [t.get("Text", "") for t in topics if isinstance(t, dict) and t.get("Text")]
        return "\n".join(results) if results else f"No results found for: {query}"
    except Exception as e:
        return f"Search error: {str(e)}"


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression. Example: '2 + 2 * 3'"""
    try:
        allowed = set("0123456789+-*/()., ")
        if not all(c in allowed for c in expression):
            return "Error: Invalid characters in expression"
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307
        return str(result)
    except Exception as e:
        return f"Calculation error: {str(e)}"


@tool
def get_datetime() -> str:
    """Get the current date and time."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


@tool
def http_request(url: str, method: str = "GET", body: str = "") -> str:
    """Make an HTTP GET or POST request to a URL."""
    try:
        if method.upper() == "GET":
            r = httpx.get(url, timeout=10)
        elif method.upper() == "POST":
            r = httpx.post(url, content=body, timeout=10)
        else:
            return f"Unsupported method: {method}"
        return f"Status: {r.status_code}\n{r.text[:500]}"
    except Exception as e:
        return f"HTTP error: {str(e)}"


@tool
def summarize_text(text: str, max_words: int = 100) -> str:
    """Truncate text to a maximum number of words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


@tool
def weather_info(city: str) -> str:
    """Get simulated weather information for a city (demo)."""
    import random
    conditions = ["sunny", "cloudy", "rainy", "partly cloudy", "windy"]
    temp = random.randint(15, 35)
    humidity = random.randint(40, 90)
    return f"Weather in {city}: {random.choice(conditions)}, {temp}°C, {humidity}% humidity"


AVAILABLE_TOOLS = {
    "web_search": web_search,
    "calculator": calculator,
    "get_datetime": get_datetime,
    "http_request": http_request,
    "summarize_text": summarize_text,
    "weather_info": weather_info,
}

TOOL_DESCRIPTIONS = {
    "web_search": "Search the web for information",
    "calculator": "Evaluate mathematical expressions",
    "get_datetime": "Get current date and time",
    "http_request": "Make HTTP requests to URLs",
    "summarize_text": "Summarize or truncate long text",
    "weather_info": "Get weather information for a city",
}
