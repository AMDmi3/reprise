from pathlib import Path
from abc import ABC, abstractmethod


class Resource(ABC):
    @abstractmethod
    async def destroy(self) -> None:
        pass

    @abstractmethod
    def get_path(self) -> Path:
        pass
