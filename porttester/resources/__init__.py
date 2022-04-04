from abc import ABC, abstractmethod
from pathlib import Path


class Resource(ABC):
    @abstractmethod
    async def destroy(self) -> None:
        pass

    @abstractmethod
    def get_path(self) -> Path:
        pass
