import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseGone
from django.utils import timezone
from django.views.decorators.http import require_safe
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsActiveStudent

from . import razorpay
from .models import ZERO, FeeAccount, Installment, Payment, Refund
from .receipt import build_receipt_pdf, read_receipt_token
from .serializers import (
    FeeAccountCreateSerializer,
    FeeAccountUpdateSerializer,
    InstallmentSerializer,
    OfflinePaymentSerializer,
    RefundSerializer,
    account_data,
    amount,
    payment_data,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def student_accounts(profile):
    return FeeAccount.objects.filter(enrollment__student=profile).select_related("enrollment__course", "enrollment__student__user")


# ----- Student -------------------------------------------------------------------------------


class StudentFeesView(APIView):
    permission_classes = [IsActiveStudent]

    def get(self, request):
        accounts = student_accounts(request.user.student_profile)
        return Response(
            {
                "online_enabled": razorpay.enabled(),
                "accounts": [account_data(account, request.user) for account in accounts],
            }
        )


class PayInstallmentView(APIView):
    permission_classes = [IsActiveStudent]

    def post(self, request, pk):
        installment = (
            Installment.objects.filter(pk=pk, account__enrollment__student=request.user.student_profile)
            .select_related("account__enrollment__course", "account__enrollment__student__user")
            .first()
        )
        if installment is None:
            raise NotFound("Installment not found.")
        if not razorpay.enabled():
            return Response(
                {"detail": "Online payment is not available yet. Please contact the admissions team to pay."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        due = installment.remaining
        if due <= ZERO:
            return Response({"detail": "This installment is already paid."}, status=status.HTTP_400_BAD_REQUEST)

        account = installment.account
        student = account.enrollment.student
        payment = Payment.objects.create(account=account, installment=installment, amount=due, method=Payment.Method.RAZORPAY)
        try:
            order = razorpay.create_order(
                due,
                receipt=f"gbet-pay-{payment.pk}",
                notes={"payment": str(payment.pk), "student_id": student.student_id or "", "course": account.enrollment.course.slug},
            )
        except razorpay.GatewayError as error:
            logger.warning("Razorpay order failed for payment %s: %s", payment.pk, error)
            payment.status, payment.failure_reason = Payment.Status.FAILED, "Could not start the payment."
            payment.save(update_fields=["status", "failure_reason"])
            return Response({"detail": "The payment could not be started. Please try again in a few minutes."}, status=status.HTTP_502_BAD_GATEWAY)

        payment.gateway_order_id = order["id"]
        payment.save(update_fields=["gateway_order_id"])
        return Response(
            {
                "payment_id": payment.pk,
                "key_id": settings.RAZORPAY_KEY_ID,
                "order_id": order["id"],
                "amount": razorpay.to_paise(due),
                "currency": "INR",
                "name": settings.RECEIPT_ORG_NAME,
                "description": f"{account.enrollment.course.title} – {installment.title}",
                "prefill": {"name": student.full_name, "email": student.user.email, "contact": f"+91{student.mobile}"},
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyInput(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=64)
    razorpay_payment_id = serializers.CharField(max_length=64)
    razorpay_signature = serializers.CharField(max_length=128)


def own_payment(request, pk):
    payment = Payment.objects.filter(pk=pk, account__enrollment__student=request.user.student_profile).first()
    if payment is None:
        raise NotFound("Payment not found.")
    return payment


class VerifyPaymentView(APIView):
    permission_classes = [IsActiveStudent]

    def post(self, request, pk):
        payment = own_payment(request, pk)
        data = VerifyInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        if payment.status == Payment.Status.PAID:
            return Response(payment_data(payment, request.user))
        if values["razorpay_order_id"] != payment.gateway_order_id or not razorpay.valid_payment_signature(
            values["razorpay_order_id"], values["razorpay_payment_id"], values["razorpay_signature"]
        ):
            logger.warning("Rejected payment signature for payment %s", payment.pk)
            return Response({"detail": "The payment could not be verified. If money was deducted, contact the admissions team."}, status=400)
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if payment.status != Payment.Status.PAID:
                payment.gateway_payment_id = values["razorpay_payment_id"]
                payment.mark_paid()
                try:
                    payment.save()
                except IntegrityError:
                    return Response({"detail": "This payment was already recorded."}, status=409)
        return Response(payment_data(payment, request.user))


class FailedPaymentView(APIView):
    permission_classes = [IsActiveStudent]

    def post(self, request, pk):
        payment = own_payment(request, pk)
        if payment.status == Payment.Status.CREATED:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = str(request.data.get("reason", "Payment was not completed."))[:300]
            payment.save(update_fields=["status", "failure_reason"])
        return Response(payment_data(payment, request.user))


class RazorpayWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        body = request.body
        if not razorpay.valid_webhook_signature(body, request.headers.get("X-Razorpay-Signature", "")):
            return Response({"detail": "Invalid signature."}, status=400)
        event = json.loads(body or b"{}")
        if event.get("event") in {"payment.captured", "order.paid"}:
            entity = event.get("payload", {}).get("payment", {}).get("entity", {})
            order_id, payment_id = entity.get("order_id"), entity.get("id")
            with transaction.atomic():
                payment = Payment.objects.select_for_update().filter(gateway_order_id=order_id).first() if order_id else None
                if payment and payment.status != Payment.Status.PAID and payment_id:
                    payment.gateway_payment_id = payment_id
                    payment.mark_paid()
                    payment.save()
        return Response({"ok": True})


@require_safe
def receipt_view(request, token):
    try:
        claim = read_receipt_token(token)
    except signing.SignatureExpired:
        return HttpResponseGone("This receipt link has expired. Reload the page to get a new one.")
    except signing.BadSignature:
        return HttpResponseForbidden("Invalid link.")
    user = User.objects.filter(pk=claim.get("u"), is_active=True).first()
    payment = (
        Payment.objects.filter(pk=claim.get("p"), status=Payment.Status.PAID)
        .select_related("account__enrollment__course", "account__enrollment__student__user", "installment")
        .first()
    )
    if payment is None:
        raise Http404
    if not user or not (user.is_staff or payment.account.enrollment.student.user_id == user.id):
        return HttpResponseForbidden("You do not have access to this receipt.")
    response = HttpResponse(build_receipt_pdf(payment), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="receipt-{payment.receipt_number}.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response


# ----- Admin ---------------------------------------------------------------------------------


class AdminFinanceSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        paid = Payment.objects.filter(status=Payment.Status.PAID)
        today = timezone.localdate()
        month_start = today.replace(day=1)
        total_fees = FeeAccount.objects.aggregate(total=Sum("total_fee"))["total"] or ZERO
        collected = paid.aggregate(total=Sum("amount"))["total"] or ZERO
        refunded = Refund.objects.aggregate(total=Sum("amount"))["total"] or ZERO
        outstanding = sum((account.balance for account in FeeAccount.objects.all()), ZERO)
        overdue = [item for item in Installment.objects.filter(due_date__lt=today) if item.remaining > ZERO]
        months = []
        for offset in range(5, -1, -1):
            year, month = divmod(month_start.year * 12 + month_start.month - 1 - offset, 12)
            month += 1
            total = paid.filter(paid_at__year=year, paid_at__month=month).aggregate(total=Sum("amount"))["total"] or ZERO
            months.append({"month": f"{year}-{month:02d}", "collected": amount(total)})
        return Response(
            {
                "accounts": FeeAccount.objects.count(),
                "total_fees": amount(total_fees),
                "collected": amount(collected),
                "refunded": amount(refunded),
                "outstanding": amount(outstanding),
                "collected_this_month": amount(
                    paid.filter(paid_at__date__gte=month_start).aggregate(total=Sum("amount"))["total"] or ZERO
                ),
                "overdue_installments": len(overdue),
                "overdue_amount": amount(sum((item.remaining for item in overdue), ZERO)),
                "monthly": months,
                "online_enabled": razorpay.enabled(),
                "recent_payments": [
                    {**payment_data(payment, request.user), "student": payment.account.enrollment.student.full_name}
                    for payment in paid.select_related("account__enrollment__student", "installment").order_by("-paid_at")[:8]
                ],
            }
        )


class AdminFeeAccountViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = FeeAccount.objects.select_related("enrollment__course", "enrollment__student__user")
        query = self.request.query_params.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(enrollment__student__full_name__icontains=query)
                | Q(enrollment__student__user__email__icontains=query)
                | Q(enrollment__student__student_id__icontains=query)
                | Q(enrollment__course__title__icontains=query)
            )
        return queryset

    def list(self, request):
        state = request.query_params.get("state")
        rows = []
        for account in self.get_queryset():
            balance = account.balance
            if state == "due" and balance == ZERO or state == "paid" and balance > ZERO:
                continue
            next_due = next((item for item in account.installments.all() if item.remaining > ZERO), None)
            rows.append(
                {
                    "id": account.id,
                    "enrollment": account.enrollment_id,
                    "student": {"name": account.enrollment.student.full_name, "student_id": account.enrollment.student.student_id},
                    "course": account.enrollment.course.title,
                    "total_fee": amount(account.total_fee),
                    "net_paid": amount(account.net_paid),
                    "balance": amount(balance),
                    "next_due": {"title": next_due.title, "due_date": next_due.due_date.isoformat(), "status": next_due.status}
                    if next_due
                    else None,
                }
            )
        return Response(rows)

    def retrieve(self, request, pk=None):
        return Response(account_data(self.get_object(), request.user, admin=True))

    def create(self, request):
        serializer = FeeAccountCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            account = serializer.save()
        return Response(account_data(account, request.user, admin=True), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        account = self.get_object()
        serializer = FeeAccountUpdateSerializer(account, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(account_data(account, request.user, admin=True))


class AdminInstallmentViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    http_method_names = ["post", "patch", "delete", "options"]
    serializer_class = InstallmentSerializer
    queryset = Installment.objects.all()

    def destroy(self, request, *args, **kwargs):
        installment = self.get_object()
        if installment.payments.exists():
            return Response({"detail": "This installment has payments and cannot be deleted."}, status=status.HTTP_409_CONFLICT)
        installment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminPaymentCreateView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = OfflinePaymentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        return Response(payment_data(payment, request.user), status=status.HTTP_201_CREATED)


class AdminRefundCreateView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = RefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund = serializer.save(recorded_by=request.user)
        return Response({"id": refund.id, "amount": amount(refund.amount)}, status=status.HTTP_201_CREATED)
