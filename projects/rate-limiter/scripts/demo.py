#!/usr/bin/env python3
"""
Interactive demo of rate limiting algorithms.

This script demonstrates all 5 rate limiting algorithms from the chapter
with side-by-side comparisons showing their different behaviors.

System Design Concepts Demonstrated:
    1. Burst handling (token bucket vs others)
    2. Edge case issue with fixed window
    3. Memory usage (sliding window log vs counter)
    4. Accuracy vs efficiency trade-offs
"""

import asyncio
import time
from typing import List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress
from rich import box

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage.redis_client import redis_client
from src.services.rate_limiter_service import RateLimiterService
from src.models import (
    ClientIdentifier,
    RateLimitRule,
    TimeUnit,
    RateLimitAlgorithm,
)

console = Console()


async def demo_introduction():
    """Display introduction to the demo."""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Rate Limiter Algorithm Comparison[/bold cyan]\n\n"
        "This demo implements all 5 algorithms from the System Design chapter:\n\n"
        "1. [yellow]Token Bucket[/yellow] - Allows bursts (Amazon, Stripe)\n"
        "2. [yellow]Leaky Bucket[/yellow] - Fixed processing rate (Shopify)\n"
        "3. [yellow]Fixed Window[/yellow] - Simple counter (edge case issues)\n"
        "4. [yellow]Sliding Window Log[/yellow] - Most accurate (memory intensive)\n"
        "5. [yellow]Sliding Window Counter[/yellow] - Hybrid approach (Cloudflare)\n\n"
        "[dim]Press Ctrl+C to exit at any time[/dim]",
        title="📊 System Design: Rate Limiter",
        border_style="cyan"
    ))
    await asyncio.sleep(2)


async def demo_burst_traffic():
    """
    Demonstrate how different algorithms handle burst traffic.

    This shows the key difference mentioned in the chapter:
    - Token bucket: ALLOWS bursts
    - Others: REJECT bursts
    """
    console.print("\n[bold]Demo 1: Burst Traffic Handling[/bold]")
    console.print("Sending 5 requests instantly (limit: 3 per 10 seconds)\n")

    algorithms = [
        RateLimitAlgorithm.TOKEN_BUCKET,
        RateLimitAlgorithm.LEAKY_BUCKET,
        RateLimitAlgorithm.FIXED_WINDOW,
        RateLimitAlgorithm.SLIDING_WINDOW_LOG,
        RateLimitAlgorithm.SLIDING_WINDOW_COUNTER,
    ]

    service = RateLimiterService(redis_client)

    results = {}

    for algo in algorithms:
        # Clear any previous state
        client = ClientIdentifier(user_id=f"burst_test_{algo.value}")

        rule = RateLimitRule(
            domain="burst_test",
            key="user_id",
            requests_per_unit=3,
            unit=TimeUnit.SECOND,
            algorithm=algo,
            bucket_size=5 if algo == RateLimitAlgorithm.TOKEN_BUCKET else 3,
        )

        service.add_rule(rule)

        # Send 5 rapid requests
        allowed_count = 0
        for i in range(5):
            result = await service.check_request(client, "burst_test", "user_id")
            if result.allowed:
                allowed_count += 1

        results[algo.value] = allowed_count

    # Display results
    table = Table(title="Burst Traffic Results", box=box.ROUNDED)
    table.add_column("Algorithm", style="cyan")
    table.add_column("Allowed (out of 5)", justify="center")
    table.add_column("Observation", style="dim")

    observations = {
        "token_bucket": "✓ Burst allowed (bucket size = 5)",
        "leaky_bucket": "✗ Queue filled quickly",
        "fixed_window": "✓ All fit in window",
        "sliding_window_log": "✓ Accurate count",
        "sliding_window_counter": "≈ Approximation based",
    }

    for algo, count in results.items():
        style = "green" if count >= 4 else "yellow" if count == 3 else "red"
        table.add_row(
            algo.replace("_", " ").title(),
            f"[{style}]{count}[/{style}]",
            observations.get(algo, "")
        )

    console.print(table)
    console.print("\n[dim]Key insight: Token bucket handles bursts best![/dim]\n")
    await asyncio.sleep(3)


async def demo_fixed_window_edge_case():
    """
    Demonstrate the edge case problem with fixed window counters.

    From chapter Figure 4-9: Requests at window boundaries can
    exceed the limit in a rolling window.
    """
    console.print("\n[bold]Demo 2: Fixed Window Edge Case (Chapter Figure 4-9)[/bold]")
    console.print("Limit: 5 per minute. Sending 5 at :50s, then 5 at :10s\n")

    service = RateLimiterService(redis_client)
    client = ClientIdentifier(user_id="edge_case_test")

    rule = RateLimitRule(
        domain="edge_test",
        key="user_id",
        requests_per_unit=5,
        unit=TimeUnit.MINUTE,
        algorithm=RateLimitAlgorithm.FIXED_WINDOW,
    )

    service.add_rule(rule)

    console.print("[yellow]Simulating requests near window boundary...[/yellow]")
    console.print("In a 60-second rolling window, only 5 should be allowed.")
    console.print("But fixed window has an edge case...\n")

    # This demonstrates the problem mentioned in the chapter
    total_allowed = 0
    for batch in range(2):
        console.print(f"[dim]Batch {batch + 1}: Sending 5 requests...[/dim]")
        batch_allowed = 0

        for i in range(5):
            result = await service.check_request(client, "edge_test", "user_id")
            if result.allowed:
                batch_allowed += 1
                total_allowed += 1

        console.print(f"  → Allowed: {batch_allowed}/5")

        if batch == 0:
            # Simulate waiting for next window
            console.print("[dim]  Waiting for window to reset (simulated)...[/dim]")
            await asyncio.sleep(1)
            # In real scenario, would wait 60 seconds

    console.print(f"\n[bold red]Total allowed: {total_allowed}/10[/bold red]")
    console.print("[dim]In production, requests at :59 and :01 could both succeed,[/dim]")
    console.print("[dim]allowing 10 requests in 62 seconds despite 5/minute limit![/dim]\n")
    await asyncio.sleep(3)


async def demo_algorithm_comparison():
    """
    Side-by-side comparison of all algorithms with same traffic pattern.
    """
    console.print("\n[bold]Demo 3: Algorithm Comparison Under Load[/bold]")
    console.print("Sending 10 requests over 5 seconds (limit: 5 per 5 seconds)\n")

    algorithms = list(RateLimitAlgorithm)
    service = RateLimiterService(redis_client)

    # Setup rules for each algorithm
    for algo in algorithms:
        rule = RateLimitRule(
            domain="comparison",
            key="user_id",
            requests_per_unit=5,
            unit=TimeUnit.SECOND,
            algorithm=algo,
        )
        service.add_rule(rule)

    # Send requests and track results
    results = {algo.value: [] for algo in algorithms}

    with Progress() as progress:
        task = progress.add_task("[cyan]Sending requests...", total=10)

        for i in range(10):
            for algo in algorithms:
                client = ClientIdentifier(user_id=f"compare_{algo.value}")
                result = await service.check_request(client, "comparison", "user_id")
                results[algo.value].append("✓" if result.allowed else "✗")

            progress.update(task, advance=1)
            await asyncio.sleep(0.5)  # 10 requests over 5 seconds

    # Display results
    table = Table(title="Request Results", box=box.ROUNDED)
    table.add_column("Algorithm", style="cyan")
    table.add_column("Results (10 requests)", justify="center")
    table.add_column("Allowed", justify="center")

    for algo_name, req_results in results.items():
        allowed = sum(1 for r in req_results if r == "✓")
        result_str = "".join(req_results)
        style = "green" if allowed >= 5 else "yellow"

        table.add_row(
            algo_name.replace("_", " ").title(),
            result_str,
            f"[{style}]{allowed}/10[/{style}]"
        )

    console.print(table)
    console.print()


async def demo_memory_comparison():
    """
    Show conceptual memory usage differences.

    From chapter:
    - Sliding window log: Stores all timestamps (high memory)
    - Others: Store counters only (low memory)
    """
    console.print("\n[bold]Demo 4: Memory Usage Comparison[/bold]")
    console.print("Conceptual memory usage for 1000 requests\n")

    table = Table(title="Estimated Memory Usage", box=box.ROUNDED)
    table.add_column("Algorithm", style="cyan")
    table.add_column("Data Stored", style="yellow")
    table.add_column("Memory", justify="right")

    memory_data = [
        ("Token Bucket", "2 values (tokens, timestamp)", "~100 bytes"),
        ("Leaky Bucket", "2 values (queue count, last leak)", "~100 bytes"),
        ("Fixed Window", "1 counter per window", "~50 bytes"),
        ("Sliding Window Log", "1000 timestamps", "~32 KB"),
        ("Sliding Window Counter", "2 counters", "~100 bytes"),
    ]

    for algo, data, memory in memory_data:
        style = "red" if "KB" in memory else "green"
        table.add_row(algo, data, f"[{style}]{memory}[/{style}]")

    console.print(table)
    console.print("\n[dim]Note: Sliding window log is accurate but memory-intensive![/dim]\n")
    await asyncio.sleep(3)


async def demo_summary():
    """Display summary of trade-offs from the chapter."""
    console.print("\n[bold]Algorithm Trade-off Summary (from Chapter)[/bold]\n")

    summaries = [
        {
            "name": "Token Bucket",
            "pros": "Allows bursts, memory efficient",
            "cons": "Parameters can be hard to tune",
            "use_case": "APIs needing burst tolerance (Amazon, Stripe)",
        },
        {
            "name": "Leaky Bucket",
            "pros": "Stable outflow rate, memory efficient",
            "cons": "Old requests block new ones",
            "use_case": "Scenarios needing constant rate (Shopify)",
        },
        {
            "name": "Fixed Window",
            "pros": "Very simple, memory efficient",
            "cons": "Edge case allows 2x limit",
            "use_case": "Non-critical rate limiting",
        },
        {
            "name": "Sliding Window Log",
            "pros": "Most accurate, no edge cases",
            "cons": "High memory usage",
            "use_case": "Strict rate limits needed",
        },
        {
            "name": "Sliding Window Counter",
            "pros": "Good accuracy, low memory",
            "cons": "Approximate (0.003% error)",
            "use_case": "Production systems (Cloudflare)",
        },
    ]

    for algo in summaries:
        console.print(f"[bold cyan]{algo['name']}[/bold cyan]")
        console.print(f"  [green]✓ Pros:[/green] {algo['pros']}")
        console.print(f"  [red]✗ Cons:[/red] {algo['cons']}")
        console.print(f"  [yellow]→ Use case:[/yellow] {algo['use_case']}\n")


async def main():
    """Run the interactive demo."""
    try:
        # Connect to Redis
        await redis_client.connect()

        # Run demos
        await demo_introduction()
        await demo_burst_traffic()
        await demo_fixed_window_edge_case()
        await demo_algorithm_comparison()
        await demo_memory_comparison()
        await demo_summary()

        console.print(Panel.fit(
            "[bold green]Demo Complete![/bold green]\n\n"
            "You've seen all 5 rate limiting algorithms in action.\n\n"
            "Next steps:\n"
            "• Run the API: [cyan]make run[/cyan]\n"
            "• Try the endpoints in your browser or with curl\n"
            "• Experiment with different algorithms via /simulate/{algorithm}\n\n"
            "[dim]See README.md for more details[/dim]",
            border_style="green"
        ))

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Demo interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n\n[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        await redis_client.disconnect()


if __name__ == "__main__":
    # Install rich if not available
    try:
        from rich.console import Console
    except ImportError:
        print("Installing required package 'rich'...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "rich"])
        from rich.console import Console

    asyncio.run(main())
