from schemas import Event
import typing
from typing import Any, List, Union
# local imports
from extractors.SessionFeature import SessionFeature
from schemas.Event import Event

class OverallPercentOffsetMoves(SessionFeature):
    def __init__(self, name:str, description:str):
        SessionFeature.__init__(self, name=name, description=description)
        self._offset_count = 0
        self._move_count = 0

    def GetEventTypes(self) -> List[str]:
        return ["CUSTOM.1", "CUSTOM.2"]
        # return ["SLIDER_MOVE_RELEASE", "ARROW_MOVE_RELEASE"]

    def CalculateFinalValues(self) -> Any:
        if self._move_count > 0:
            return self._offset_count / self._move_count * 100
        else:
            return None

    def _extractFromEvent(self, event:Event) -> None:
        self._move_count += 1
        if event.event_data["slider"] == "OFFSET":
            self._offset_count += 1

    def MinVersion(self) -> Union[str,None]:
        return None

    def MaxVersion(self) -> Union[str,None]:
        return None
