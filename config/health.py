from django.db import connection
from django.http import JsonResponse


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception:
        database = "unavailable"
    return JsonResponse({"status": "ok" if database == "ok" else "degraded", "database": database}, status=200 if database == "ok" else 503)
