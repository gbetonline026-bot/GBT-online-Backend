"""Private file storage on Cloudinary for lesson videos, study material and other uploads.

Files are uploaded with delivery type ``authenticated`` so they cannot be opened by guessing a URL.
The API checks the student's access first and then redirects to a signed Cloudinary URL
(see ``academics.files.serve_private``). Configure with the ``CLOUDINARY_URL`` environment variable.
"""

import os
import time
import urllib.request

import cloudinary
import cloudinary.api
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
DELIVERY_TYPE = "authenticated"
LARGE_UPLOAD_BYTES = 90 * 1024 * 1024


def resource_type(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "raw"


@deconstructible
class CloudinaryPrivateStorage(Storage):
    def __init__(self, folder=None):
        self.folder = (folder or settings.CLOUDINARY_FOLDER).strip("/")
        cloudinary.config(secure=True)

    def _public_id(self, name):
        path = f"{self.folder}/{name}" if self.folder else name
        # Cloudinary keeps the extension in the public id for raw files only.
        return path if resource_type(name) == "raw" else os.path.splitext(path)[0]

    def _options(self, name):
        return {"resource_type": resource_type(name), "type": DELIVERY_TYPE}

    def _save(self, name, content):
        options = {**self._options(name), "public_id": self._public_id(name), "overwrite": False, "unique_filename": False}
        content.seek(0)
        size = getattr(content, "size", 0) or 0
        if options["resource_type"] == "video" or size > LARGE_UPLOAD_BYTES:
            cloudinary.uploader.upload_large(content, chunk_size=20 * 1024 * 1024, **options)
        else:
            cloudinary.uploader.upload(content, **options)
        return name

    def exists(self, name):
        # Upload names contain a random UUID, so a clash is not possible; avoid an API call per upload.
        return False

    def delete(self, name):
        if name:
            cloudinary.uploader.destroy(self._public_id(name), invalidate=True, **self._options(name))

    def size(self, name):
        return cloudinary.api.resource(self._public_id(name), **self._options(name))["bytes"]

    def url(self, name):
        return self.delivery_url(name)

    def delivery_url(self, name, *, attachment=False, filename=None, ttl=None):
        kind = resource_type(name)
        public_id = self._public_id(name)
        extension = os.path.splitext(name)[1].lstrip(".").lower()
        if attachment or kind == "raw":
            expires_at = int(time.time()) + int(ttl or settings.LMS_MEDIA_LINK_TTL_SECONDS)
            return cloudinary.utils.private_download_url(
                public_id,
                "" if kind == "raw" else extension,
                resource_type=kind,
                type=DELIVERY_TYPE,
                attachment=attachment,
                expires_at=expires_at,
            )
        url, _ = cloudinary.utils.cloudinary_url(
            public_id, resource_type=kind, type=DELIVERY_TYPE, sign_url=True, secure=True, format=extension
        )
        return url

    def _open(self, name, mode="rb"):
        with urllib.request.urlopen(self.delivery_url(name), timeout=60) as response:
            return ContentFile(response.read(), name=name)
