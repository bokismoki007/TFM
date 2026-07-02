from django.contrib import admin
from .models import UploadedFile

# Register your models here.

@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ('get_filename', 'user', 'uploaded_at', 'get_rows', 'get_missing_pct')
    list_filter = ('uploaded_at', 'user')
    search_fields = ('analysis_result__filename', 'user__username')
    readonly_fields = ('uploaded_at', 'analysis_result')

    def get_filename(self, obj):
        return (obj.analysis_result or {}).get('filename', f'#{obj.pk}')
    get_filename.short_description = 'File'

    def get_rows(self, obj):
        shape = (obj.analysis_result or {}).get('shape', [])
        return f"{shape[0]} × {shape[1]}" if shape else '-'
    get_rows.short_description = 'Shape'

    def get_missing_pct(self, obj):
        ms = (obj.analysis_result or {}).get('missing_summary', {})
        return f"{ms.get('missing_percentage', 0)}%" if ms else '-'
    get_missing_pct.short_description = 'Missing %'