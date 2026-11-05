"""Plain PDF fee receipt (no third-party PDF library)."""

from django.conf import settings
from django.core import signing
from django.utils import timezone

SALT = "gbet-fee-receipt"


def receipt_link(payment_id, user_id):
    token = signing.dumps({"p": payment_id, "u": user_id}, salt=SALT, compress=True)
    return f"{settings.PUBLIC_API_URL}/api/portal/finance/receipt/{token}/"


def read_receipt_token(token):
    return signing.loads(token, salt=SALT, max_age=settings.LMS_MEDIA_LINK_TTL_SECONDS)


def _text(value):
    cleaned = str(value).replace("₹", "Rs. ").replace("–", "-").replace("—", "-").replace("’", "'")
    cleaned = cleaned.encode("latin-1", "replace").decode("latin-1")
    return cleaned.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def money(amount):
    return f"Rs. {amount:,.2f}"


def build_receipt_pdf(payment):
    account = payment.account
    enrollment = account.enrollment
    student = enrollment.student
    paid_at = timezone.localtime(payment.paid_at) if payment.paid_at else None
    rows = [
        ("Receipt number", payment.receipt_number or "-"),
        ("Date", f"{paid_at:%d %b %Y, %I:%M %p}" if paid_at else "-"),
        ("Student", student.full_name),
        ("Student ID", student.student_id or "-"),
        ("Course", enrollment.course.title),
        ("Towards", payment.installment.title if payment.installment_id else "Course fee"),
        ("Payment method", payment.get_method_display()),
        ("Transaction reference", payment.gateway_payment_id or payment.reference or "-"),
        ("Amount received", money(payment.amount)),
    ]
    if payment.refunded:
        rows.append(("Refunded", money(payment.refunded)))

    ops = [
        "0.04 0.12 0.23 rg 0 772 595 70 re f",
        f"BT /F2 18 Tf 1 1 1 rg 50 808 Td ({_text(settings.RECEIPT_ORG_NAME)}) Tj ET",
        f"BT /F1 10 Tf 1 1 1 rg 50 790 Td ({_text(settings.RECEIPT_ORG_ADDRESS)}) Tj ET",
        "BT /F2 16 Tf 0.04 0.12 0.23 rg 50 730 Td (Fee Receipt) Tj ET",
    ]
    y = 690
    for label, value in rows:
        ops.append(f"BT /F1 11 Tf 0.28 0.33 0.41 rg 50 {y} Td ({_text(label)}) Tj ET")
        font = "/F2 12" if label == "Amount received" else "/F1 11"
        ops.append(f"BT {font} Tf 0.04 0.12 0.23 rg 220 {y} Td ({_text(value)}) Tj ET")
        ops.append(f"0.89 0.91 0.94 RG 0.5 w 50 {y - 9} m 545 {y - 9} l S")
        y -= 30
    ops.append(
        f"BT /F1 9 Tf 0.28 0.33 0.41 rg 50 {y - 20} Td (This is a computer-generated receipt and does not need a signature.) Tj ET"
    )
    ops.append(f"BT /F1 9 Tf 0.28 0.33 0.41 rg 50 {y - 34} Td ({_text(settings.RECEIPT_CONTACT)}) Tj ET")
    stream = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
