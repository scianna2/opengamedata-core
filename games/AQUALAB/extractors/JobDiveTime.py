from datetime import timedelta
from typing import Any, List

from extractors.Feature import Feature
from schemas.Event import Event

class JobDiveTime(Feature):

    def __init__(self, name:str, description:str, job_num:int, job_map:dict):
        self._job_map = job_map
        min_data_version = None
        max_data_version = None
        super().__init__(name=name, description=description, count_index=job_num, min_version=min_data_version, max_version=max_data_version)
        self._dive_start_time = None
        self._time = timedelta(0)

    def GetEventTypes(self) -> List[str]:
        return []

    def CalculateFinalValues(self) -> Any:
        return self._time

    def _extractFromEvent(self, event:Event) -> None:
        if self._job_map[event.event_params["job_id"]] == self._count_index:
            if event.event_name == "begin_dive":
                self._dive_start_time = event.timestamp
            elif event.event_name == "scene_changed":
                self._time += event.timestamp - self._dive_start_time
                self._dive_start_time = None
