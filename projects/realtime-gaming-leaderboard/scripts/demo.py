#!/usr/bin/env python
"""
Interactive demo for Real-time Gaming Leaderboard system.

This script demonstrates the core functionality:
1. Creating test users
2. Simulating game wins
3. Querying leaderboard (top 10)
4. Getting user rankings
5. Viewing surrounding players

Run with: python scripts/demo.py
"""

import os
import sys
import django
from datetime import datetime
import uuid
import random
from time import sleep

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "leaderboard_project.settings")
django.setup()

from core.models import User, Game
from core.services.leaderboard_service import LeaderboardService
from colorama import init, Fore, Style

# Initialize colorama for colored terminal output
try:
    init(autoreset=True)
except:
    # Fallback if colorama not installed
    class DummyFore:
        GREEN = YELLOW = BLUE = CYAN = RED = MAGENTA = ""
    class DummyStyle:
        BRIGHT = RESET_ALL = ""
    Fore = DummyFore()
    Style = DummyStyle()


def print_header(text):
    """Print section header."""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{'=' * 70}")
    print(f"{text}")
    print(f"{'=' * 70}{Style.RESET_ALL}\n")


def print_success(text):
    """Print success message."""
    print(f"{Fore.GREEN}✓ {text}{Style.RESET_ALL}")


def print_info(text):
    """Print info message."""
    print(f"{Fore.BLUE}→ {text}{Style.RESET_ALL}")


def print_error(text):
    """Print error message."""
    print(f"{Fore.RED}✗ {text}{Style.RESET_ALL}")


def create_test_users(num_users=50):
    """Create test users for demo."""
    print_header("Step 1: Creating Test Users")

    # Famous mobile game player names for realism
    first_names = ["Shadow", "Dragon", "Phoenix", "Storm", "Ninja", "Warrior",
                   "Mystic", "Cyber", "Thunder", "Blaze", "Frost", "Viper"]
    last_names = ["Slayer", "Master", "Hunter", "Killer", "Ranger", "Knight",
                  "Wizard", "Samurai", "Legend", "Champion", "Hero", "Pro"]

    users = []
    for i in range(num_users):
        username = f"{random.choice(first_names)}{random.choice(last_names)}{random.randint(100, 999)}"
        display_name = f"{random.choice(first_names)} {random.choice(last_names)}"

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "display_name": display_name,
                "avatar_url": f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}",
            }
        )
        users.append(user)
        if created:
            print_success(f"Created user: {user.display_name} (@{user.username})")

    print_info(f"\nTotal users in database: {User.objects.count()}")
    return users


def simulate_game_wins(users, service, games_per_user_range=(5, 50)):
    """Simulate random game wins for users."""
    print_header("Step 2: Simulating Game Wins")

    month = datetime.now().strftime("%Y-%m")
    total_games = 0

    print_info(f"Simulating matches for {len(users)} players...")
    print_info(f"Each player wins between {games_per_user_range[0]}-{games_per_user_range[1]} matches\n")

    for user in users:
        num_wins = random.randint(*games_per_user_range)

        for _ in range(num_wins):
            try:
                service.update_score(
                    user_id=str(user.id),
                    points=1,
                    match_id=str(uuid.uuid4()),
                    month=month,
                )
                total_games += 1
            except Exception as e:
                print_error(f"Failed to update score for {user.username}: {e}")

    print_success(f"\nSimulated {total_games} game wins!")
    print_info(f"Games recorded in database: {Game.objects.count()}")


def display_top_10(service):
    """Display top 10 leaderboard."""
    print_header("Step 3: Top 10 Leaderboard")

    try:
        top_10 = service.get_top_n(n=10)

        if not top_10:
            print_error("No players in leaderboard yet!")
            return None

        print(f"{Fore.YELLOW}{'Rank':<6} {'Player':<25} {'Score':>8}{Style.RESET_ALL}")
        print(f"{'-' * 45}")

        for player in top_10:
            rank_color = Fore.GREEN if player['rank'] <= 3 else Fore.WHITE
            print(f"{rank_color}#{player['rank']:<5} {player['display_name']:<25} {player['score']:>8}{Style.RESET_ALL}")

        return top_10[0] if top_10 else None

    except Exception as e:
        print_error(f"Failed to fetch top 10: {e}")
        return None


def display_user_rank(service, user_id, username):
    """Display specific user's rank."""
    print_header(f"Step 4: User Rank - {username}")

    try:
        result = service.get_user_rank(str(user_id))

        if not result:
            print_error(f"User {username} not found in leaderboard")
            return

        print(f"{Fore.CYAN}Player:{Style.RESET_ALL}  {result['display_name']} (@{result['username']})")
        print(f"{Fore.CYAN}Rank:{Style.RESET_ALL}    #{result['rank']:,}")
        print(f"{Fore.CYAN}Score:{Style.RESET_ALL}   {result['score']} wins")
        print(f"{Fore.CYAN}Month:{Style.RESET_ALL}   {result['month']}")

    except Exception as e:
        print_error(f"Failed to get user rank: {e}")


def display_surrounding_players(service, user_id, username):
    """Display players around a specific user."""
    print_header(f"Step 5: Players Surrounding {username} (±4 positions)")

    try:
        result = service.get_surrounding_players(str(user_id), offset=4)

        if not result['data']:
            print_error(f"User {username} not found in leaderboard")
            return

        print(f"{Fore.YELLOW}{'Rank':<6} {'Player':<25} {'Score':>8}  {'':>6}{Style.RESET_ALL}")
        print(f"{'-' * 50}")

        for player in result['data']:
            is_current = player.get('is_current_user', False)
            color = Fore.GREEN if is_current else Fore.WHITE
            marker = "⭐ YOU" if is_current else ""

            print(f"{color}#{player['rank']:<5} {player['display_name']:<25} {player['score']:>8}  {marker}{Style.RESET_ALL}")

        print(f"\n{Fore.CYAN}Your Rank:{Style.RESET_ALL} #{result['user_rank']:,}")

    except Exception as e:
        print_error(f"Failed to get surrounding players: {e}")


def display_stats(service):
    """Display leaderboard statistics."""
    print_header("Step 6: Leaderboard Statistics")

    try:
        stats = service.get_leaderboard_stats()

        print(f"{Fore.CYAN}Total Players:{Style.RESET_ALL}    {stats['total_users']:,}")
        print(f"{Fore.CYAN}Highest Score:{Style.RESET_ALL}    {stats['top_score']}")
        print(f"{Fore.CYAN}Month:{Style.RESET_ALL}            {stats['month']}")

        # Calculate average score
        total_games = Game.objects.filter(leaderboard_month=stats['month'].replace('-', '-')).count()
        avg_score = total_games / stats['total_users'] if stats['total_users'] > 0 else 0

        print(f"{Fore.CYAN}Total Matches:{Style.RESET_ALL}    {total_games:,}")
        print(f"{Fore.CYAN}Avg Score:{Style.RESET_ALL}        {avg_score:.1f}")

    except Exception as e:
        print_error(f"Failed to get stats: {e}")


def demonstrate_redis_operations(service):
    """Demonstrate Redis sorted set operations."""
    print_header("Bonus: Redis Sorted Set Operations")

    print_info("Demonstrating O(log n) operations...\n")

    # Show Redis key
    month = datetime.now().strftime("%Y-%m")
    redis_key = service.redis_store._get_leaderboard_key(month)
    print(f"{Fore.CYAN}Redis Key:{Style.RESET_ALL}  {redis_key}")

    # Show leaderboard size
    size = service.redis_store.get_leaderboard_size(month)
    print(f"{Fore.CYAN}Entries:{Style.RESET_ALL}    {size:,}")

    # Health check
    health = service.redis_store.health_check()
    status_text = f"{Fore.GREEN}Healthy" if health else f"{Fore.RED}Unhealthy"
    print(f"{Fore.CYAN}Redis:{Style.RESET_ALL}      {status_text}{Style.RESET_ALL}")

    # Time complexity info
    print(f"\n{Fore.YELLOW}Time Complexities:{Style.RESET_ALL}")
    print(f"  • ZINCRBY (increment score):  O(log n)")
    print(f"  • ZREVRANGE (top 10):         O(log n + 10)")
    print(f"  • ZREVRANK (get rank):        O(log n)")
    print(f"  • ZSCORE (get score):         O(1)")


def handle_edge_cases():
    """Demonstrate edge case handling."""
    print_header("Step 7: Edge Case Handling")

    service = LeaderboardService()

    # Case 1: User not in leaderboard
    print_info("Case 1: Querying non-existent user")
    fake_uuid = str(uuid.uuid4())
    result = service.get_user_rank(fake_uuid)
    if result is None:
        print_success("Correctly returns None for non-existent user")
    else:
        print_error("Should return None!")

    # Case 2: Empty leaderboard (different month)
    print_info("\nCase 2: Querying empty leaderboard (future month)")
    future_month = "2099-12"
    top_10 = service.get_top_n(n=10, month=future_month)
    if len(top_10) == 0:
        print_success("Correctly returns empty list for future month")
    else:
        print_error(f"Should return empty list, got {len(top_10)} entries")

    # Case 3: Large limit (capped at 100)
    print_info("\nCase 3: Requesting more than max limit")
    print_info("Note: In production, API would reject requests > 100")


def main():
    """Run the demo."""
    print(f"\n{Fore.MAGENTA}{Style.BRIGHT}")
    print("╔═══════════════════════════════════════════════════════════════════╗")
    print("║                                                                   ║")
    print("║        Real-time Gaming Leaderboard System Demo                  ║")
    print("║        Based on System Design Interview Vol 2 - Chapter 10       ║")
    print("║                                                                   ║")
    print("╚═══════════════════════════════════════════════════════════════════╝")
    print(f"{Style.RESET_ALL}\n")

    service = LeaderboardService()

    # Check if Redis is available
    if not service.redis_store.health_check():
        print_error("Redis is not available! Please start Redis:")
        print_error("  docker-compose up -d redis")
        return

    # Step 1: Create users
    users = create_test_users(num_users=50)

    # Step 2: Simulate games
    simulate_game_wins(users, service, games_per_user_range=(10, 100))

    # Step 3: Show top 10
    top_player = display_top_10(service)

    # Step 4: Show a specific user's rank (pick a middle-ranked user)
    middle_user = random.choice(users[10:30])
    display_user_rank(service, middle_user.id, middle_user.username)

    # Step 5: Show surrounding players
    display_surrounding_players(service, middle_user.id, middle_user.username)

    # Step 6: Show stats
    display_stats(service)

    # Bonus: Redis operations
    demonstrate_redis_operations(service)

    # Step 7: Edge cases
    handle_edge_cases()

    # Final summary
    print_header("Demo Complete!")
    print_success("All leaderboard operations demonstrated successfully!")
    print_info("\nNext steps:")
    print(f"  1. Check Django admin: http://localhost:8000/admin")
    print(f"  2. Try API endpoints: http://localhost:8000/api/v1/scores")
    print(f"  3. Explore Redis data: redis-cli ZREVRANGE leaderboard_2025_01 0 9 WITHSCORES")
    print(f"\n{Fore.YELLOW}Press Ctrl+C to exit...{Style.RESET_ALL}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}Demo interrupted. Goodbye!{Style.RESET_ALL}\n")
        sys.exit(0)
    except Exception as e:
        print_error(f"\nDemo failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
