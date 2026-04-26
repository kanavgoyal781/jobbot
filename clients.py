import anthropic
from dotenv import load_dotenv
from langchain_nia import NiaAPIWrapper

load_dotenv(override=True)

nia = NiaAPIWrapper()
_claude = anthropic.Anthropic()
