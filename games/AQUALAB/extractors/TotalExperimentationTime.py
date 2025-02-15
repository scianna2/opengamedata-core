from datetime import timedelta
from typing import Any, List

from extractors.Feature import Feature
from schemas.Event import Event

class TotalExperimentationTime(Feature):

    def __init__(self, name:str, description:str):
        super().__init__(name=name, description=description, count_index=0)
        self._experiment_start_time = None
        self._time = timedelta(0)

    def GetEventTypes(self) -> List[str]:
        return ["begin_experiment", "room_changed"]

    def CalculateFinalValues(self) -> Any:
        return self._time

    def _extractFromEvent(self, event:Event) -> None:
        if event.event_name == "begin_experiment":
            self._experiment_start_time = event.timestamp
        elif event.event_name == "room_changed":
            self._time += event.timestamp - self._experiment_start_time
            self._experiment_start_time = None
