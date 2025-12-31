#!/usr/bin/env python3
"""
Google Drive - Interactive Demo

Demonstrates key system design concepts:
- Block-level storage (chunking)
- Delta sync (only upload changed blocks)
- Conflict resolution (concurrent edits)
- Version history
- Real-time notifications (long polling simulation)
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.database import AsyncSessionLocal, init_db, drop_db
from src.services.file_service import file_service
from src.services.notification_service import notification_service
from src.services.block_processor import block_processor
from src.storage.s3_simulator import s3


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    """Print section header"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text:^60}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.END}\n")


def print_success(text: str):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_info(text: str):
    """Print info message"""
    print(f"{Colors.CYAN}ℹ {text}{Colors.END}")


def print_warning(text: str):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")


def print_step(step: int, text: str):
    """Print step number"""
    print(f"\n{Colors.BOLD}Step {step}:{Colors.END} {text}")


async def demo_1_block_storage():
    """Demonstrate block-level storage with chunking"""
    print_header("Demo 1: Block-Level Storage")

    print_step(1, "Create a sample file (1.5 MB)")
    # Create file larger than one block (4 MB block size)
    sample_data = b"This is sample data for Google Drive demo.\n" * 50000
    print_info(f"File size: {len(sample_data):,} bytes ({len(sample_data) / 1024 / 1024:.2f} MB)")

    print_step(2, "Chunk file into blocks")
    blocks = []
    async for block in block_processor.chunk_file(sample_data):
        blocks.append(block)
        print_info(
            f"  Block {block.block_index}: {block.size_bytes:,} bytes, "
            f"hash={block.hash[:16]}..."
        )

    print_success(f"File split into {len(blocks)} blocks")

    print_step(3, "Process blocks (compress + encrypt)")
    for i, block in enumerate(blocks[:2]):  # Show first 2 blocks
        processed = await block_processor.process_block(block)
        compression_ratio = (1 - len(processed) / block.size_bytes) * 100
        print_info(
            f"  Block {i}: {block.size_bytes:,} → {len(processed):,} bytes "
            f"({compression_ratio:.1f}% compression)"
        )

    return sample_data, blocks


async def demo_2_delta_sync():
    """Demonstrate delta sync - only upload changed blocks"""
    print_header("Demo 2: Delta Sync")

    print_step(1, "Create original file")
    original_data = b"Line 1: Original content\n" * 1000
    original_data += b"Line 2: Original content\n" * 1000
    original_data += b"Line 3: Original content\n" * 1000
    original_blocks = [b async for b in block_processor.chunk_file(original_data)]
    print_success(f"Original file: {len(original_data):,} bytes, {len(original_blocks)} blocks")

    print_step(2, "Edit file (change only middle section)")
    edited_data = b"Line 1: Original content\n" * 1000
    edited_data += b"Line 2: EDITED CONTENT!\n" * 1000  # Changed
    edited_data += b"Line 3: Original content\n" * 1000
    print_info(f"Edited file: {len(edited_data):,} bytes")

    print_step(3, "Calculate delta (which blocks changed?)")
    changed_blocks, reused_blocks = await block_processor.calculate_delta(
        original_blocks, edited_data
    )

    print_success(f"Changed blocks: {len(changed_blocks)}")
    print_success(f"Reused blocks: {len(reused_blocks)}")

    bandwidth_saved = sum(b.size_bytes for b in reused_blocks)
    total_size = len(edited_data)
    savings_pct = (bandwidth_saved / total_size) * 100

    print_warning(f"Bandwidth savings: {bandwidth_saved:,} bytes ({savings_pct:.1f}%)")
    print_info("Only changed blocks will be uploaded!")


async def demo_3_deduplication():
    """Demonstrate content-based deduplication"""
    print_header("Demo 3: Block Deduplication")

    print_step(1, "Create two files with identical content blocks")

    file1_data = b"Shared content block A\n" * 1000
    file1_data += b"Unique to file 1\n" * 1000

    file2_data = b"Shared content block A\n" * 1000  # Same as file1
    file2_data += b"Unique to file 2\n" * 1000

    print_step(2, "Chunk both files")
    file1_blocks = [b async for b in block_processor.chunk_file(file1_data)]
    file2_blocks = [b async for b in block_processor.chunk_file(file2_data)]

    print_step(3, "Find duplicate blocks by hash")
    file1_hashes = {b.hash for b in file1_blocks}
    file2_hashes = {b.hash for b in file2_blocks}
    duplicate_hashes = file1_hashes & file2_hashes

    print_success(f"File 1: {len(file1_blocks)} blocks")
    print_success(f"File 2: {len(file2_blocks)} blocks")
    print_warning(f"Duplicate blocks: {len(duplicate_hashes)}")
    print_info("Duplicate blocks will share the same storage!")


async def demo_4_full_upload_download():
    """Full upload and download workflow"""
    print_header("Demo 4: Upload & Download Workflow")

    async with AsyncSessionLocal() as db:
        print_step(1, "Upload file")
        user_id = uuid4()
        file_path = "/demo/test-document.txt"
        file_data = b"This is a test document.\nIt has multiple lines.\n" * 500

        print_info(f"User ID: {user_id}")
        print_info(f"File path: {file_path}")
        print_info(f"File size: {len(file_data):,} bytes")

        metadata = await file_service.create_file(
            db=db,
            user_id=user_id,
            file_path=file_path,
            file_data=file_data,
        )

        print_success(f"File uploaded: {metadata.id}")
        print_success(f"Status: {metadata.status}")
        print_success(f"Current version: {metadata.current_version_id}")

        print_step(2, "Download file")
        downloaded_data = await file_service.download_and_reconstruct_file(
            db=db,
            file_id=metadata.id,
        )

        print_success(f"Downloaded {len(downloaded_data):,} bytes")

        if downloaded_data == file_data:
            print_success("✓ File integrity verified! Download matches upload.")
        else:
            print_warning("✗ File mismatch!")

        print_step(3, "Update file (delta sync)")
        edited_data = b"UPDATED: This is a test document.\nIt has multiple lines.\n" * 500

        updated_metadata = await file_service.update_file(
            db=db,
            file_id=metadata.id,
            user_id=user_id,
            new_file_data=edited_data,
            enable_delta_sync=True,
        )

        print_success(f"File updated: version {updated_metadata.current_version_id}")

        print_step(4, "View version history")
        from src.storage.schema import FileVersionModel
        from sqlalchemy import select

        result = await db.execute(
            select(FileVersionModel)
            .where(FileVersionModel.file_id == metadata.id)
            .order_by(FileVersionModel.version_number)
        )
        versions = result.scalars().all()

        for v in versions:
            print_info(
                f"  Version {v.version_number}: {v.size_bytes:,} bytes, "
                f"{v.block_count} blocks, {v.created_at}"
            )


async def demo_5_storage_stats():
    """Show storage statistics"""
    print_header("Demo 5: Storage Statistics")

    stats = s3.get_storage_stats()

    print_info(f"Total blocks: {stats['total_blocks']}")
    print_info(f"Total size: {stats['total_size_bytes']:,} bytes ({stats['total_size_mb']:.2f} MB)")
    print_info(f"Average block size: {stats['total_size_bytes'] / max(stats['total_blocks'], 1):,.0f} bytes")

    notif_stats = notification_service.get_stats()
    print_info(f"\nNotification service:")
    print_info(f"  Active connections: {notif_stats['active_connections']}")
    print_info(f"  Subscribed users: {notif_stats['subscribed_users']}")


async def main():
    """Run all demos"""
    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║           GOOGLE DRIVE - SYSTEM DESIGN DEMO               ║
    ║                                                           ║
    ║  Demonstrates: Block storage, Delta sync, Deduplication   ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    print(Colors.END)

    print_info("Initializing database...")
    await drop_db()
    await init_db()
    print_success("Database ready!\n")

    try:
        # Run demos
        await demo_1_block_storage()
        await demo_2_delta_sync()
        await demo_3_deduplication()
        await demo_4_full_upload_download()
        await demo_5_storage_stats()

        print_header("Demo Complete!")
        print_success("All system design concepts demonstrated successfully!")

        print(f"\n{Colors.CYAN}Key Takeaways:{Colors.END}")
        print("  • Block-level storage enables efficient delta sync")
        print("  • Hash-based deduplication saves storage space")
        print("  • Compression reduces data size by 50-70% for text")
        print("  • Strong consistency via ACID database transactions")
        print("  • Real-time sync via long polling notifications")

        print(f"\n{Colors.YELLOW}Next Steps:{Colors.END}")
        print("  • Read docs/02-learnings.md for interview prep")
        print("  • Explore src/ code to understand implementation")
        print("  • Try 'make run' to start API server")
        print("  • Visit http://localhost:8000/docs for API docs")

    except Exception as e:
        print_warning(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
