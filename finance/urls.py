from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("admin/finance/accounts", views.AdminFeeAccountViewSet, basename="admin-fee-account")
router.register("admin/finance/installments", views.AdminInstallmentViewSet, basename="admin-installment")

urlpatterns = [
    path("finance/summary/", views.StudentFeesView.as_view()),
    path("finance/installments/<int:pk>/pay/", views.PayInstallmentView.as_view()),
    path("finance/payments/<int:pk>/verify/", views.VerifyPaymentView.as_view()),
    path("finance/payments/<int:pk>/failed/", views.FailedPaymentView.as_view()),
    path("finance/razorpay/webhook/", views.RazorpayWebhookView.as_view()),
    path("finance/receipt/<str:token>/", views.receipt_view),
    path("admin/finance/summary/", views.AdminFinanceSummaryView.as_view()),
    path("admin/finance/payments/", views.AdminPaymentCreateView.as_view()),
    path("admin/finance/refunds/", views.AdminRefundCreateView.as_view()),
    *router.urls,
]
