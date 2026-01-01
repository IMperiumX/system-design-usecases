"""
Django Admin Configuration for Payment System

Provides admin interface for debugging and monitoring payments.
"""

from django.contrib import admin
from django.utils.html import format_html
from payments.models import PaymentEvent, PaymentOrder, WalletAccount, LedgerEntry


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    """Admin for PaymentEvent model."""

    list_display = [
        'checkout_id',
        'buyer_email',
        'order_count',
        'is_payment_done_badge',
        'created_at',
        'updated_at'
    ]
    list_filter = ['is_payment_done', 'created_at']
    search_fields = ['checkout_id', 'buyer_info__email']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'

    def buyer_email(self, obj):
        """Extract buyer email from JSON field."""
        return obj.buyer_info.get('email', 'N/A')
    buyer_email.short_description = 'Buyer Email'

    def order_count(self, obj):
        """Count of payment orders."""
        return obj.orders.count()
    order_count.short_description = '# Orders'

    def is_payment_done_badge(self, obj):
        """Display colored badge for payment status."""
        if obj.is_payment_done:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ COMPLETE</span>'
            )
        return format_html(
            '<span style="color: orange; font-weight: bold;">⏳ PROCESSING</span>'
        )
    is_payment_done_badge.short_description = 'Status'


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    """Admin for PaymentOrder model."""

    list_display = [
        'payment_order_id',
        'checkout_id',
        'status_badge',
        'amount',
        'currency',
        'buyer_account',
        'seller_account',
        'flags',
        'retry_count',
        'created_at'
    ]
    list_filter = ['status', 'currency', 'wallet_updated', 'ledger_updated', 'created_at']
    search_fields = ['payment_order_id', 'buyer_account', 'seller_account', 'psp_token']
    readonly_fields = ['created_at', 'updated_at', 'last_retry_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Identification', {
            'fields': ('payment_order_id', 'checkout')
        }),
        ('Parties', {
            'fields': ('buyer_account', 'seller_account')
        }),
        ('Financial Details', {
            'fields': ('amount', 'currency', 'status')
        }),
        ('PSP Integration', {
            'fields': ('psp_token', 'psp_nonce')
        }),
        ('Processing Status', {
            'fields': ('wallet_updated', 'ledger_updated')
        }),
        ('Retry Logic', {
            'fields': ('retry_count', 'last_retry_at', 'error_message')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def checkout_id(self, obj):
        """Get checkout ID from foreign key."""
        return obj.checkout.checkout_id
    checkout_id.short_description = 'Checkout ID'

    def status_badge(self, obj):
        """Display colored badge for status."""
        colors = {
            'NOT_STARTED': 'gray',
            'EXECUTING': 'blue',
            'SUCCESS': 'green',
            'FAILED': 'red'
        }
        color = colors.get(obj.status, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.status
        )
    status_badge.short_description = 'Status'

    def flags(self, obj):
        """Show wallet/ledger update flags."""
        wallet = '✓ W' if obj.wallet_updated else '✗ W'
        ledger = '✓ L' if obj.ledger_updated else '✗ L'
        return f"{wallet}  {ledger}"
    flags.short_description = 'W/L Updated'


@admin.register(WalletAccount)
class WalletAccountAdmin(admin.ModelAdmin):
    """Admin for WalletAccount model."""

    list_display = [
        'account_id',
        'balance_display',
        'currency',
        'created_at',
        'updated_at'
    ]
    list_filter = ['currency', 'created_at']
    search_fields = ['account_id']
    readonly_fields = ['balance_dollars', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'

    def balance_display(self, obj):
        """Format balance with currency symbol."""
        return f"${obj.balance_dollars:.2f}"
    balance_display.short_description = 'Balance'
    balance_display.admin_order_field = 'balance_cents'


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """Admin for LedgerEntry model."""

    list_display = [
        'entry_id_short',
        'transaction_id',
        'account_id',
        'entry_type_badge',
        'amount_display',
        'currency',
        'created_at'
    ]
    list_filter = ['currency', 'created_at']
    search_fields = ['entry_id', 'transaction_id', 'account_id', 'description']
    readonly_fields = ['entry_id', 'amount_dollars', 'created_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Identification', {
            'fields': ('entry_id', 'transaction_id', 'account_id')
        }),
        ('Amounts', {
            'fields': ('debit_cents', 'credit_cents', 'amount_dollars', 'currency')
        }),
        ('Reference', {
            'fields': ('payment_order', 'description')
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )

    def entry_id_short(self, obj):
        """Show first 8 chars of UUID."""
        return str(obj.entry_id)[:8]
    entry_id_short.short_description = 'Entry ID'

    def entry_type_badge(self, obj):
        """Display colored badge for debit/credit."""
        if obj.debit_cents > 0:
            return format_html(
                '<span style="color: red; font-weight: bold;">DR (Debit)</span>'
            )
        return format_html(
            '<span style="color: green; font-weight: bold;">CR (Credit)</span>'
        )
    entry_type_badge.short_description = 'Type'

    def amount_display(self, obj):
        """Format amount with currency symbol."""
        return f"${obj.amount_dollars:.2f}"
    amount_display.short_description = 'Amount'

    def has_add_permission(self, request):
        """Ledger is append-only, prevent manual additions via admin."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Ledger is immutable, prevent deletions."""
        return False
