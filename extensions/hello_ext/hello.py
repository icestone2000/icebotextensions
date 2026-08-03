from datetime import datetime


def greet(name: str = "world") -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"hello, {name}! time={now}"

