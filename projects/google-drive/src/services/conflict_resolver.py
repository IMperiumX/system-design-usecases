"""
Conflict Resolver - Sync conflict detection and resolution

System Design Concept:
    Implements [[conflict-resolution]] with first-write-wins strategy

Key insight:
    When two users edit the same file simultaneously, one edit must win.
    We preserve both versions and let the user manually resolve.
"""

from datetime import datetime
from uuid import UUID
from typing import Optional

from src.models import SyncConflict, ConflictResolution, FileStatus
from src.storage.schema import FileModel, FileVersionModel


class ConflictResolver:
    """
    Detects and resolves sync conflicts

    Strategy: First-write-wins
    - User 1 and User 2 edit file.txt at 10:00:00
    - User 1's upload reaches server first (10:00:01)
    - User 2's upload reaches server second (10:00:02)
    - User 1 wins, User 2 gets conflict notification
    """

    async def detect_conflict(
        self,
        file: FileModel,
        incoming_version_timestamp: datetime,
        incoming_user_id: UUID,
    ) -> Optional[SyncConflict]:
        """
        Check if incoming upload conflicts with existing version

        Args:
            file: Current file in database
            incoming_version_timestamp: When new version was created
            incoming_user_id: Who is uploading

        Returns:
            SyncConflict if detected, None otherwise
        """
        if file.current_version_id is None:
            # First version, no conflict possible
            return None

        # Compare timestamps
        # If incoming version is older or same time as current, it lost the race
        if incoming_version_timestamp <= file.updated_at:
            return SyncConflict(
                file_id=file.id,
                local_version_id=UUID("00000000-0000-0000-0000-000000000000"),  # Placeholder
                server_version_id=file.current_version_id,
                resolution_options=[
                    ConflictResolution.MERGE,
                    ConflictResolution.KEEP_LOCAL,
                    ConflictResolution.KEEP_SERVER,
                ],
            )

        return None

    async def resolve_conflict(
        self, file_id: UUID, resolution: ConflictResolution, merged_data: Optional[bytes] = None
    ) -> UUID:
        """
        Apply user's conflict resolution

        Args:
            file_id: File in conflict
            resolution: How to resolve
            merged_data: If resolution=MERGE, the merged file content

        Returns:
            version_id of resolved version
        """
        if resolution == ConflictResolution.KEEP_SERVER:
            # User chose server version, nothing to do
            # Just discard local changes
            pass

        elif resolution == ConflictResolution.KEEP_LOCAL:
            # User chose local version, upload as new version
            # This will be handled by normal upload flow
            pass

        elif resolution == ConflictResolution.MERGE:
            # User manually merged both versions
            if not merged_data:
                raise ValueError("merged_data required for MERGE resolution")
            # Upload merged version as new version
            pass

        # Return the version ID that won
        # (Implementation would interact with file_service here)
        return UUID("00000000-0000-0000-0000-000000000000")  # Placeholder

    async def create_conflict_copy(
        self, file: FileModel, conflicting_version: FileVersionModel
    ) -> str:
        """
        Save conflicting version as separate file

        Example:
            Original: document.txt
            Conflict copy: document (User's conflicted copy 2025-12-31).txt

        Returns:
            Path to conflict copy
        """
        base_name = file.name.rsplit(".", 1)[0] if "." in file.name else file.name
        extension = file.name.rsplit(".", 1)[1] if "." in file.name else ""

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H-%M-%S")
        conflict_name = f"{base_name} (conflicted copy {timestamp})"

        if extension:
            conflict_name += f".{extension}"

        conflict_path = f"{file.path.rsplit('/', 1)[0]}/{conflict_name}"

        return conflict_path


# Global instance
conflict_resolver = ConflictResolver()
