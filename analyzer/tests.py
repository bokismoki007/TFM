import numpy as np
import pandas as pd
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch

from .models import UploadedFile
from .imputation import recommend_strategies
from .forms import UploadFileForm

# Create your tests here.

class ArchitecturalUnitTests(TestCase):
    def test_recommendation_engine_threshold_boundaries(self):
        data = {"target_col": [1.0, 2.0, 3.0, np.nan, np.nan]}
        df = pd.DataFrame(data)
        missing_counts = {"target_col": 2}

        recs = recommend_strategies(df, missing_counts)
        self.assertIn("target_col", recs)
        self.assertTrue(isinstance(recs["target_col"]["strategy"], str))


class IntegrationAndSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="analyst", password="secure_pass_123")

    def test_malicious_or_invalid_extension_rejection(self):
        form_data = {
            'file': SimpleUploadedFile("malicious_script.sh", b"rm -rf /", content_type="text/x-shellscript")
        }
        form = UploadFileForm(files=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Only .csv and .xlsx files are supported.", form.errors['file'][0])

    @patch('analyzer.api_client.requests.get')
    def test_third_party_api_resilience_under_mock(self, mock_get):
        mock_get.return_value.status_code = 500

        self.client.login(username="analyst", password="secure_pass_123")

        file_record = UploadedFile.objects.create(
            user=self.user,
            analysis_result={"columns": ["Age", "Income"], "filename": "test.csv", "shape": [10, 2]}
        )

        response = self.client.get(reverse('results', kwargs={'pk': file_record.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "test.csv")