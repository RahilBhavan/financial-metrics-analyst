"""In-process access to the validated financial tools, without MCP or a model API."""
import copy

from .domain import AnalystService, DEFAULT_DATA
from .policy import Refusal
from .tools import TOOLS, call_tool


class DirectClient:
    def __init__(self, data_dir=DEFAULT_DATA):
        self.service = AnalystService(data_dir)

    def request(self, method, params=None):
        if method != 'tools/list':
            raise Refusal('unsupported_method', 'Direct access supports tools/list and tool calls only.')
        return {'result': {'tools': copy.deepcopy(TOOLS)}}

    def reviewed_profiles(self):
        return self.service.reviewed_profiles()

    def call_raw(self, name, arguments):
        return call_tool(self.service, name, arguments)

    def call(self, name, arguments):
        return self.call_raw(name, arguments)['structuredContent']

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
