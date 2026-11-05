from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

ZERO = Decimal("0.00")
MONEY = {"max_digits": 10, "decimal_places": 2}


class FeeAccount(models.Model):
    """The agreed fee for one enrolment. Fees are set by the admissions team, never shown publicly."""

    enrollment = models.OneToOneField("academics.Enrollment", on_delete=models.PROTECT, related_name="fee_account")
    total_fee = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("1.00"))])
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.enrollment} – ₹{self.total_fee}"

    @property
    def paid(self):
        return self.payments.filter(status=Payment.Status.PAID).aggregate(total=Sum("amount"))["total"] or ZERO

    @property
    def refunded(self):
        return Refund.objects.filter(payment__account=self).aggregate(total=Sum("amount"))["total"] or ZERO

    @property
    def net_paid(self):
        return self.paid - self.refunded

    @property
    def balance(self):
        return max(self.total_fee - self.net_paid, ZERO)


class Installment(models.Model):
    account = models.ForeignKey(FeeAccount, on_delete=models.CASCADE, related_name="installments")
    number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120)
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("1.00"))])
    due_date = models.DateField()

    class Meta:
        ordering = ["account", "number"]
        constraints = [models.UniqueConstraint(fields=["account", "number"], name="unique_installment_number")]

    def __str__(self):
        return f"{self.title} – ₹{self.amount}"

    @property
    def paid(self):
        return self.payments.filter(status=Payment.Status.PAID).aggregate(total=Sum("amount"))["total"] or ZERO

    @property
    def remaining(self):
        return max(self.amount - self.paid, ZERO)

    @property
    def status(self):
        if self.remaining == ZERO:
            return "paid"
        if self.paid > ZERO:
            return "partial"
        return "overdue" if self.due_date < timezone.localdate() else "due"


class Payment(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Awaiting payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    class Method(models.TextChoices):
        RAZORPAY = "razorpay", "Online (Razorpay)"
        UPI = "upi", "UPI (offline)"
        BANK = "bank_transfer", "Bank transfer"
        CASH = "cash", "Cash"
        CHEQUE = "cheque", "Cheque / DD"
        OTHER = "other", "Other"

    account = models.ForeignKey(FeeAccount, on_delete=models.PROTECT, related_name="payments")
    installment = models.ForeignKey(Installment, on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("1.00"))])
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    gateway_order_id = models.CharField(max_length=64, blank=True, db_index=True)
    gateway_payment_id = models.CharField(max_length=64, blank=True)
    reference = models.CharField(max_length=120, blank=True, help_text="UTR / cheque / transaction reference for offline payments.")
    failure_reason = models.CharField(max_length=300, blank=True)
    receipt_number = models.CharField(max_length=32, unique=True, null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["gateway_payment_id"], condition=~models.Q(gateway_payment_id=""), name="unique_gateway_payment"
            )
        ]

    def __str__(self):
        return f"{self.receipt_number or self.pk} – ₹{self.amount} ({self.status})"

    @property
    def refunded(self):
        return self.refunds.aggregate(total=Sum("amount"))["total"] or ZERO

    def mark_paid(self, when=None):
        self.status = self.Status.PAID
        self.paid_at = when or timezone.now()
        self.failure_reason = ""
        if not self.receipt_number:
            self.receipt_number = f"{settings.RECEIPT_PREFIX}{self.paid_at:%Y}-{self.pk:06d}"


class Refund(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("1.00"))])
    reason = models.CharField(max_length=300)
    reference = models.CharField(max_length=120, blank=True)
    refunded_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-refunded_at"]

    def __str__(self):
        return f"Refund ₹{self.amount} on {self.payment}"
