from django.contrib import admin

from .models import FeeAccount, Installment, Payment, Refund


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0


@admin.register(FeeAccount)
class FeeAccountAdmin(admin.ModelAdmin):
    list_display = ["enrollment", "total_fee", "created_at"]
    search_fields = ["enrollment__student__full_name", "enrollment__course__title"]
    raw_id_fields = ["enrollment"]
    inlines = [InstallmentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["receipt_number", "account", "amount", "method", "status", "paid_at"]
    list_filter = ["status", "method"]
    search_fields = ["receipt_number", "gateway_order_id", "gateway_payment_id", "reference", "account__enrollment__student__full_name"]
    readonly_fields = ["gateway_order_id", "gateway_payment_id", "receipt_number", "paid_at", "created_at"]


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ["payment", "amount", "reason", "refunded_at"]
