from typing import List, Literal, TypedDict

Role = Literal["system", "user", "assistant"]

class Message(TypedDict):
    role: Role
    content: str

Dialog = List[Message]
HistoryPairs = List[tuple[str, str]]
