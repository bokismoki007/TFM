from django.db import models
from django.contrib.auth.models import User


class UploadedFile(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='uploads')
    file = models.FileField(upload_to='uploads/', blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    analysis_result = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        name = (self.analysis_result or {}).get('filename', str(self.pk))
        owner = self.user.username if self.user else 'guest'
        return f"{name} - {owner} @ {self.uploaded_at:%Y-%m-%d %H:%M}"