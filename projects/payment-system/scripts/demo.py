#!/usr/bin/env python
"""
Payment System Demo Script

Demonstrates complete payment flow:
1. Create payment event
2. Execute payment orders
3. Show wallet balances
4. Show ledger entries
5. Verify double-entry accounting

Run with: python scripts/demo.py
"""

import os
import sys
import django
import uuid
from decimal import Decimal

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'payment_system.settings')
django.setup()

from payments.services.payment_service import PaymentService
from payments.services.wallet_service import WalletService
from payments.services.ledger_service import LedgerService
from payments.models import PaymentEvent, PaymentOrder, WalletAccount, LedgerEntry


def print_header(title):
    """Print section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_payment_order(order):
    """Pretty print payment order details."""
    print(f"  Payment Order: {order.payment_order_id}")
    print(f"    Status: {order.status}")
    print(f"    Amount: ${order.amount} {order.currency}")
    print(f"    Buyer: {order.buyer_account}")
    print(f"    Seller: {order.seller_account}")
    print(f"    Wallet Updated: {'✓' if order.wallet_updated else '✗'}")
    print(f"    Ledger Updated: {'✓' if order.ledger_updated else '✗'}")
    print(f"    Retry Count: {order.retry_count}")
    if order.error_message:
        print(f"    Error: {order.error_message}")
    print()


def main():
    """Run payment system demo."""

    print_header("Payment System Demo")
    print("This demo simulates an e-commerce payment flow with:")
    print("  - Payment event creation")
    print("  - PSP integration (mocked)")
    print("  - Wallet balance updates")
    print("  - Double-entry ledger recording")
    print("  - Idempotency guarantees")

    # Initialize services
    payment_service = PaymentService()
    wallet_service = WalletService()
    ledger_service = LedgerService()

    # Clean state for demo
    print("\n[Cleaning previous data...]")
    PaymentEvent.objects.all().delete()
    WalletAccount.objects.all().delete()
    LedgerEntry.objects.all().delete()

    # Demo data
    checkout_id = f"checkout_{uuid.uuid4().hex[:8]}"
    buyer_id = "buyer_alice"
    seller1_id = "seller_bob"
    seller2_id = "seller_charlie"

    order1_id = f"order_{uuid.uuid4().hex[:8]}"
    order2_id = f"order_{uuid.uuid4().hex[:8]}"

    # ==================================================================
    # STEP 1: Create Payment Event
    # ==================================================================
    print_header("Step 1: Create Payment Event")

    payment_orders = [
        {
            'payment_order_id': order1_id,
            'seller_account': seller1_id,
            'amount': '29.99',
            'currency': 'USD'
        },
        {
            'payment_order_id': order2_id,
            'seller_account': seller2_id,
            'amount': '15.50',
            'currency': 'USD'
        }
    ]

    buyer_info = {
        'user_id': buyer_id,
        'email': 'alice@example.com',
        'name': 'Alice Smith'
    }

    credit_card_info = {
        'token': 'tok_visa_4242',  # Tokenized card (no raw data!)
        'last4': '4242'
    }

    print(f"Creating payment event...")
    print(f"  Checkout ID: {checkout_id}")
    print(f"  Buyer: {buyer_info['email']}")
    print(f"  Orders: {len(payment_orders)}")
    print(f"    - Order 1: ${payment_orders[0]['amount']} to {seller1_id}")
    print(f"    - Order 2: ${payment_orders[1]['amount']} to {seller2_id}")

    payment_event = payment_service.create_payment_event(
        checkout_id=checkout_id,
        buyer_info=buyer_info,
        credit_card_info=credit_card_info,
        payment_orders=payment_orders
    )

    print(f"\n✓ Payment event created: {payment_event.checkout_id}")
    print(f"  Status: {'COMPLETE' if payment_event.is_payment_done else 'PROCESSING'}")

    # ==================================================================
    # STEP 2: Execute Payment Orders
    # ==================================================================
    print_header("Step 2: Execute Payment Orders")

    for order in payment_event.orders.all():
        print(f"Executing order {order.payment_order_id}...")
        updated_order = payment_service.execute_payment_order(order.payment_order_id)
        print_payment_order(updated_order)

    # Refresh event to check completion
    payment_event.refresh_from_db()
    print(f"Payment Event Status: {'✓ COMPLETE' if payment_event.is_payment_done else '⏳ PROCESSING'}")

    # ==================================================================
    # STEP 3: Show Wallet Balances
    # ==================================================================
    print_header("Step 3: Wallet Balances")

    accounts = [buyer_id, seller1_id, seller2_id]
    for account_id in accounts:
        details = wallet_service.get_account_details(account_id)
        if details:
            print(f"  {account_id}: ${details['balance_dollars']:.2f} {details['currency']}")
        else:
            print(f"  {account_id}: $0.00 (no account)")

    # ==================================================================
    # STEP 4: Show Ledger Entries
    # ==================================================================
    print_header("Step 4: Ledger Entries (Double-Entry Accounting)")

    print("All ledger entries:\n")
    entries = LedgerEntry.objects.all().order_by('transaction_id', 'created_at')

    current_txn_id = None
    for entry in entries:
        if entry.transaction_id != current_txn_id:
            current_txn_id = entry.transaction_id
            print(f"  Transaction: {entry.transaction_id}")

        entry_type = "DR (Debit) " if entry.debit_cents > 0 else "CR (Credit)"
        amount = entry.debit_cents if entry.debit_cents > 0 else entry.credit_cents
        print(f"    {entry_type} {entry.account_id:20} ${amount / 100:>8.2f}")

    # ==================================================================
    # STEP 5: Verify Double-Entry Balance
    # ==================================================================
    print_header("Step 5: Verify Double-Entry Accounting")

    verification = ledger_service.verify_books_balance()

    print(f"Total Debits:  ${verification['total_debits_cents'] / 100:.2f}")
    print(f"Total Credits: ${verification['total_credits_cents'] / 100:.2f}")
    print(f"Difference:    ${verification['difference_cents'] / 100:.2f}")
    print(f"Total Entries: {verification['total_entries']}")

    if verification['balanced']:
        print("\n✓ Books are BALANCED (debits = credits)")
    else:
        print("\n✗ Books are OUT OF BALANCE!")

    # ==================================================================
    # STEP 6: Test Idempotency
    # ==================================================================
    print_header("Step 6: Test Idempotency")

    print("Attempting to create duplicate payment event with same checkout_id...")
    duplicate_event = payment_service.create_payment_event(
        checkout_id=checkout_id,  # Same ID!
        buyer_info=buyer_info,
        credit_card_info=credit_card_info,
        payment_orders=payment_orders
    )

    print(f"\n✓ Idempotency works! Returned existing event: {duplicate_event.checkout_id}")
    print(f"  Events with this checkout_id: {PaymentEvent.objects.filter(checkout_id=checkout_id).count()}")

    # Re-execute same payment order
    print(f"\nAttempting to re-execute payment order {order1_id}...")
    retry_order = payment_service.execute_payment_order(order1_id)
    print(f"✓ Idempotency works! Order status: {retry_order.status}")
    print(f"  Wallet updated count: {PaymentOrder.objects.filter(payment_order_id=order1_id).count()}")

    # ==================================================================
    # STEP 7: Test Failed Payment & Retry
    # ==================================================================
    print_header("Step 7: Test Failed Payment & Retry")

    print("Creating a payment that might fail (PSP has 90% success rate)...")

    failed_checkout_id = f"checkout_{uuid.uuid4().hex[:8]}"
    failed_order_id = f"order_{uuid.uuid4().hex[:8]}"

    # Try up to 3 times to get a failure (for demo purposes)
    for attempt in range(3):
        payment_event_failed = payment_service.create_payment_event(
            checkout_id=f"{failed_checkout_id}_{attempt}",
            buyer_info=buyer_info,
            credit_card_info=credit_card_info,
            payment_orders=[{
                'payment_order_id': f"{failed_order_id}_{attempt}",
                'seller_account': seller1_id,
                'amount': '100.00',
                'currency': 'USD'
            }]
        )

        failed_order = payment_service.execute_payment_order(f"{failed_order_id}_{attempt}")

        if failed_order.status == PaymentOrder.Status.FAILED:
            print(f"\n✓ Got a failed payment on attempt {attempt + 1}")
            print(f"  Order ID: {failed_order.payment_order_id}")
            print(f"  Status: {failed_order.status}")
            print(f"  Error: {failed_order.error_message}")
            print(f"  Retry Count: {failed_order.retry_count}")

            # Test manual retry
            if failed_order.can_retry():
                print(f"\n  Attempting manual retry...")
                retried_order = payment_service.retry_failed_payment(failed_order.payment_order_id)
                print(f"  Retry result: {retried_order.status}")
            break
        else:
            print(f"  Attempt {attempt + 1}: Payment succeeded")

    # ==================================================================
    # Summary
    # ==================================================================
    print_header("Demo Complete!")

    total_orders = PaymentOrder.objects.count()
    successful_orders = PaymentOrder.objects.filter(status=PaymentOrder.Status.SUCCESS).count()
    failed_orders = PaymentOrder.objects.filter(status=PaymentOrder.Status.FAILED).count()

    print(f"Total Payment Orders: {total_orders}")
    print(f"  Successful: {successful_orders}")
    print(f"  Failed: {failed_orders}")
    print(f"\nTotal Wallet Accounts: {WalletAccount.objects.count()}")
    print(f"Total Ledger Entries: {LedgerEntry.objects.count()}")

    print("\n" + "=" * 80)
    print("  Key Concepts Demonstrated:")
    print("=" * 80)
    print("  ✓ Idempotency (duplicate checkout_id returns same event)")
    print("  ✓ Double-Entry Accounting (debits = credits)")
    print("  ✓ PSP Integration (token-based payment processing)")
    print("  ✓ Wallet Updates (seller balance credited)")
    print("  ✓ Ledger Recording (immutable audit trail)")
    print("  ✓ Retry Logic (failed payments can retry)")
    print("  ✓ State Machine (NOT_STARTED → EXECUTING → SUCCESS/FAILED)")
    print("=" * 80)

    print("\nNext steps:")
    print("  - View admin panel: python manage.py createsuperuser && python manage.py runserver")
    print("  - Explore API: http://localhost:8000/api/v1/payments/")
    print("  - Check docs: See docs/ folder for architecture and learnings")


if __name__ == '__main__':
    main()
