"""Base importer interface."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field

from ..exercises import Exercise


@dataclass
class ImportResult:
    """Summary of an import operation."""

    source: str
    total_fetched: int = 0
    total_added: int = 0
    total_skipped: int = 0  # Duplicates or filtered
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return True if no errors occurred during import."""
        return len(self.errors) == 0

    def __str__(self) -> str:
        return (
            f"Import from {self.source}: "
            f"{self.total_added} added, {self.total_skipped} skipped, "
            f"{len(self.errors)} errors"
        )


class Importer(ABC):
    """Base class for content importers.

    Importers fetch exercises from external sources (Lichess, Chessable,
    PGN files, etc.) and convert them to the internal Exercise format.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable name of this import source."""
        ...

    @abstractmethod
    def fetch(self, **kwargs) -> Iterator[Exercise]:
        """Fetch exercises from the source.

        Yields Exercise objects as they are fetched. Implementations
        should handle pagination, rate limiting, etc.

        Args:
            **kwargs: Source-specific parameters (count, filters, etc.)

        Yields:
            Exercise objects ready for storage
        """
        ...

    def import_to(self, store, **kwargs) -> ImportResult:
        """Import exercises directly to a store.

        Convenience method that handles iteration and error tracking.

        Args:
            store: ExerciseStore to add exercises to
            **kwargs: Passed to fetch()

        Returns:
            ImportResult with summary statistics
        """
        result = ImportResult(source=self.source_name)

        for exercise in self.fetch(**kwargs):
            result.total_fetched += 1
            try:
                store.add(exercise)
                result.total_added += 1
            except Exception as e:
                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                    result.total_skipped += 1
                else:
                    result.errors.append(f"{exercise.id}: {e}")

        return result
