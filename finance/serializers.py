from decimal import Decimal

from django.db.models import Max
from django.utils import timezone
from rest_framework import serializers

from academics.models import Enrollment

from .models import ZERO, FeeAccount, Installment, Payment, Refund
from .receipt import receipt_link


def amount(value):
    return f"{(value or ZERO):.2f}"


def installment_data(item):
    return {
        "id": item.id,
        "number": item.number,
        "title": item.title,
        "amount": amount(item.amount),
        "due_date": item.due_date.isoformat(),
        "paid": amount(item.paid),
        "remaining": amount(item.remaining),
        "status": item.status,
        "has_payments": item.payments.exists(),
    }


def payment_data(payment, user):
    return {
        "id": payment.id,
        "amount": amount(payment.amount),
        "method": payment.method,
        "method_label": payment.get_method_display(),
        "status": payment.status,
        "installment": payment.installment.title if payment.installment_id else None,
        "receipt_number": payment.receipt_number,
        "reference": payment.gateway_payment_id or payment.reference,
        "failure_reason": payment.failure_reason,
        "notes": payment.notes,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        "created_at": payment.created_at.isoformat(),
        "refunded": amount(payment.refunded),
        "receipt_url": receipt_link(payment.id, user.id) if payment.status == Payment.Status.PAID else None,
    }


def account_data(account, user, *, admin=False):
    enrollment = account.enrollment
    paid, refunded, net = account.paid, account.refunded, account.net_paid
    payments = account.payments.select_related("installment")
    if not admin:
        payments = payments.exclude(status=Payment.Status.CREATED)
    installments = list(account.installments.all())
    data = {
        "id": account.id,
        "enrollment": enrollment.id,
        "course": {"title": enrollment.course.title, "slug": enrollment.course.slug},
        "total_fee": amount(account.total_fee),
        "paid": amount(paid),
        "refunded": amount(refunded),
        "net_paid": amount(net),
        "balance": amount(account.balance),
        "percent": min(100, round(net * 100 / account.total_fee)) if account.total_fee else 0,
        "note": account.note,
        "installments_total": amount(sum((item.amount for item in installments), ZERO)),
        "installments": [installment_data(item) for item in installments],
        "payments": [payment_data(payment, user) for payment in payments],
        "refunds": [
            {
                "id": refund.id,
                "payment": refund.payment_id,
                "receipt_number": refund.payment.receipt_number,
                "amount": amount(refund.amount),
                "reason": refund.reason,
                "reference": refund.reference,
                "refunded_at": refund.refunded_at.isoformat(),
            }
            for refund in Refund.objects.filter(payment__account=account).select_related("payment")
        ],
    }
    if admin:
        student = enrollment.student
        data["student"] = {"id": student.id, "name": student.full_name, "email": student.user.email, "student_id": student.student_id}
        data["created_at"] = account.created_at.isoformat()
    return data


class InstallmentInput(serializers.Serializer):
    title = serializers.CharField(max_length=120)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1.00"))
    due_date = serializers.DateField()


class FeeAccountCreateSerializer(serializers.Serializer):
    enrollment = serializers.PrimaryKeyRelatedField(queryset=Enrollment.objects.select_related("course", "student"))
    total_fee = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1.00"))
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)
    installments = InstallmentInput(many=True, required=False)

    def validate_enrollment(self, enrollment):
        if FeeAccount.objects.filter(enrollment=enrollment).exists():
            raise serializers.ValidationError("A fee plan already exists for this enrolment.")
        return enrollment

    def validate(self, attrs):
        plan = attrs.get("installments") or []
        if plan and sum(item["amount"] for item in plan) != attrs["total_fee"]:
            raise serializers.ValidationError({"installments": ["The installments must add up to the total fee."]})
        return attrs

    def create(self, data):
        plan = data.pop("installments", None) or [
            {"title": "Full fee", "amount": data["total_fee"], "due_date": timezone.localdate()}
        ]
        account = FeeAccount.objects.create(created_by=self.context["request"].user, **data)
        for number, item in enumerate(plan, start=1):
            Installment.objects.create(account=account, number=number, **item)
        return account


class FeeAccountUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeAccount
        fields = ["total_fee", "note"]

    def validate_total_fee(self, value):
        if value < self.instance.net_paid:
            raise serializers.ValidationError("The total fee cannot be less than the amount already paid.")
        return value


class InstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Installment
        fields = ["id", "account", "number", "title", "amount", "due_date"]
        read_only_fields = ["number"]
        validators = []

    def validate(self, attrs):
        if self.instance:
            if "account" in attrs and attrs["account"] != self.instance.account:
                raise serializers.ValidationError({"account": "Installments cannot move between fee plans."})
            if "amount" in attrs and attrs["amount"] < self.instance.paid:
                raise serializers.ValidationError({"amount": "The amount cannot be less than what has already been paid."})
        return attrs

    def create(self, data):
        top = data["account"].installments.aggregate(top=Max("number"))["top"] or 0
        return Installment.objects.create(number=top + 1, **data)


class OfflinePaymentSerializer(serializers.ModelSerializer):
    paid_at = serializers.DateTimeField(required=False)

    class Meta:
        model = Payment
        fields = ["account", "installment", "amount", "method", "reference", "notes", "paid_at"]

    def validate_method(self, value):
        if value == Payment.Method.RAZORPAY:
            raise serializers.ValidationError("Online payments are recorded automatically by Razorpay.")
        return value

    def validate(self, attrs):
        account, installment = attrs["account"], attrs.get("installment")
        if installment and installment.account_id != account.id:
            raise serializers.ValidationError({"installment": "This installment belongs to a different fee plan."})
        limit = installment.remaining if installment else account.balance
        if attrs["amount"] > limit:
            raise serializers.ValidationError({"amount": f"The amount is more than the outstanding ₹{limit:.2f}."})
        if attrs["method"] != Payment.Method.CASH and not attrs.get("reference", "").strip():
            raise serializers.ValidationError({"reference": "Enter the UTR / transaction / cheque reference."})
        return attrs

    def create(self, data):
        paid_at = data.pop("paid_at", None)
        payment = Payment.objects.create(recorded_by=self.context["request"].user, **data)
        payment.mark_paid(paid_at)
        payment.save()
        return payment


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = ["payment", "amount", "reason", "reference"]

    def validate(self, attrs):
        payment = attrs["payment"]
        if payment.status != Payment.Status.PAID:
            raise serializers.ValidationError({"payment": "Only paid payments can be refunded."})
        available = payment.amount - payment.refunded
        if attrs["amount"] > available:
            raise serializers.ValidationError({"amount": f"Only ₹{available:.2f} of this payment can still be refunded."})
        return attrs
