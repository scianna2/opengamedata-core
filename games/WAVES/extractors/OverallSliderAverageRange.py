from schemas import Event
import typing
from typing import Any, List, Union
# local imports
from extractors.SessionFeature import SessionFeature
from schemas.Event import Event

class OverallSliderAverageRange(SessionFeature):
    def __init__(self, name:str, description:str):
        SessionFeature.__init__(self, name=name, description=description)
        self._ranges = []

    def GetEventTypes(self) -> List[str]:
        return ["CUSTOM.1"]
        # return ["SLIDER_MOVE_RELEASE"]

    def CalculateFinalValues(self) -> Any:
        if len(self._ranges) > 0:
            return sum(self._ranges) / len(self._ranges)
        else:
            return None

    def _extractFromEvent(self, event:Event) -> None:
        self._ranges.append(event.event_data["max_val"] - event.event_data["min_val"])

    def MinVersion(self) -> Union[str,None]:
        return None

    def MaxVersion(self) -> Union[str,None]:
        return None


