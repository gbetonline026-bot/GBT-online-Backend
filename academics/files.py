import logging
import mimetypes
import re

from django.conf import settings
from django.core import signing
from django.http import FileResponse, HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from django.utils.http import content_disposition_header

logger = logging.getLogger(__name__)
SALT = "gbet-lms-media"
RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 64 * 1024


def delete_stored_file(storage, name):
    """Remove a stored file; a file locked by an open download is logged and left for later cleanup."""
    if not name:
        return
    try:
        storage.delete(name)
    except OSError:
        logger.warning("Could not delete stored file %s; remove it manually.", name)


def media_link(kind, object_id, user_id):
    token = signing.dumps({"k": kind, "i": object_id, "u": user_id}, salt=SALT, compress=True)
    return f"{settings.PUBLIC_API_URL}/api/portal/learning/media/{token}/"


def read_media_token(token):
    return signing.loads(token, salt=SALT, max_age=settings.LMS_MEDIA_LINK_TTL_SECONDS)


def _chunks(handle, length):
    try:
        remaining = length
        while remaining > 0:
            data = handle.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
    finally:
        handle.close()


def serve_private(request, field, filename, attachment):
    """Send a private file the caller is allowed to see: redirect to cloud storage, or stream from disk."""
    if hasattr(field.storage, "delivery_url"):
        response = HttpResponseRedirect(field.storage.delivery_url(field.name, attachment=attachment, filename=filename))
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response
    return serve_file(request, field, filename, attachment)


def serve_file(request, field, filename, attachment):
    """Serve a private file, honouring single byte-range requests so videos can seek."""
    content_type = mimetypes.guess_type(field.name)[0] or "application/octet-stream"
    size = field.size
    handle = field.open("rb")
    match = RANGE.match(request.headers.get("Range", ""))
    if match and any(match.groups()):
        first, last = match.groups()
        if first == "":
            start, end = max(size - int(last), 0), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        if start >= size or start > end:
            handle.close()
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        handle.seek(start)
        response = StreamingHttpResponse(_chunks(handle, end - start + 1), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(end - start + 1)
        response["Content-Disposition"] = content_disposition_header(attachment, filename)
    else:
        response = FileResponse(handle, content_type=content_type, as_attachment=attachment, filename=filename)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response
