import os
from django import forms
from django.core.exceptions import ValidationError
from .models import UploadedFile

class UploadFileForm(forms.ModelForm):
    class Meta:
        model = UploadedFile
        fields = ('file',)

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in ['.csv', '.xlsx']:
                raise forms.ValidationError('Only .csv and .xlsx files are supported.')

            if file.size > 50 * 1024 * 1024:
                raise forms.ValidationError('File size cannot exceed 50 MB.')
        return file