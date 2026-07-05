import json
import os
import tempfile
import unittest
import numpy as np
import pandas as pd
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from .analysis import analyze_file
from .api_client import clean_query
from .imputation import apply_imputation, recommend_strategies, SKLEARN_AVAILABLE
from .models import UploadedFile

# Create your tests here.

# analysis.py
class AnalysisTests(TestCase):
    def _write_csv(self, content):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='')
        f.write(content)
        f.close()
        return f.name

    def test_shape_and_missing_values_detected(self):
        path = self._write_csv("name,age,city\nBoki,23,Madrid\nAlejandro,,Oslo\nLox,25,\n")
        try:
            result = analyze_file(path)
            self.assertNotIn('error', result)
            self.assertEqual(result['shape'], [3, 3])
            self.assertEqual(result['missing_values']['age'], 1)
            self.assertEqual(result['missing_values']['city'], 1)
            self.assertEqual(result['missing_values']['name'], 0)
        finally:
            os.remove(path)

    def test_missing_keyword_variants_are_detected(self):
        path = self._write_csv("a,b\n1,N/A\n2,unknown\n3,5\n")
        try:
            result = analyze_file(path)
            self.assertEqual(result['missing_values']['b'], 2)
        finally:
            os.remove(path)

    def test_invalid_file_path_returns_error_dict_not_exception(self):
        result = analyze_file('/nonexistent/path/does_not_exist.csv')
        self.assertIn('error', result)

    def test_data_preview_is_capped_at_ten_rows_by_design(self):
        rows = "\n".join(f"{i},{i*2}" for i in range(1, 21))
        path = self._write_csv(f"a,b\n{rows}\n")
        try:
            result = analyze_file(path)
            self.assertEqual(result['shape'][0], 20)
            self.assertEqual(len(result['data_preview']['rows']), 10)
        finally:
            os.remove(path)

# imputation.py
class ImputationTests(TestCase):
    def setUp(self):
        self.df = pd.DataFrame({
            'age': [25, np.nan, 35, 40, np.nan],
            'score': [1.0, 2.0, np.nan, 4.0, 5.0],
            'city': ['Madrid', None, 'Oslo', 'Oslo', None],
        })

    def test_mean_imputation(self):
        result = apply_imputation(self.df, {'age': 'mean'})
        self.assertEqual(result['age'].isna().sum(), 0)

    def test_median_imputation(self):
        result = apply_imputation(self.df, {'score': 'median'})
        self.assertEqual(result['score'].isna().sum(), 0)

    def test_mode_imputation_categorical(self):
        result = apply_imputation(self.df, {'city': 'mode'})
        self.assertEqual(result['city'].isna().sum(), 0)

    def test_constant_imputation_uses_provided_value(self):
        result = apply_imputation(self.df, {'city': 'constant'}, {'city': 'Unknown'})
        self.assertEqual(result['city'].isna().sum(), 0)
        self.assertIn('Unknown', result['city'].values)

    def test_drop_rows_removes_only_incomplete_rows(self):
        result = apply_imputation(self.df, {'age': 'drop_rows'})
        self.assertEqual(len(result), 3)

    @unittest.skipUnless(SKLEARN_AVAILABLE, "scikit-learn not installed in this environment")
    def test_knn_imputation_fills_numeric_columns(self):
        result = apply_imputation(self.df, {'age': 'knn', 'score': 'knn'})
        self.assertEqual(result['age'].isna().sum(), 0)
        self.assertEqual(result['score'].isna().sum(), 0)

    @unittest.skipUnless(SKLEARN_AVAILABLE, "scikit-learn not installed in this environment")
    def test_knn_imputation_fills_categorical_columns(self):
        df = pd.DataFrame({
            'city': [0.0, 1.0, 0.0, 1.0, np.nan, np.nan],
            'price': [100.0, 200.0, 110.0, 210.0, 150.0, 250.0]
        })
        strategies = {'city': 'knn', 'price': 'mean'}
        result = apply_imputation(df, strategies)
        self.assertEqual(result['city'].isna().sum(), 0)

    @unittest.skipUnless(SKLEARN_AVAILABLE, "scikit-learn not installed in this environment")
    def test_iterative_mice_imputation(self):
        result = apply_imputation(self.df, {'age': 'iterative', 'score': 'iterative'})
        self.assertEqual(result['age'].isna().sum(), 0)
        self.assertEqual(result['score'].isna().sum(), 0)

# api_client.py
class ApiClientTests(TestCase):
    def test_missing_like_values_return_none(self):
        self.assertIsNone(clean_query('n/a'))
        self.assertIsNone(clean_query(''))
        self.assertIsNone(clean_query(None))

    def test_underscores_and_hyphens_become_spaces(self):
        self.assertEqual(clean_query('my_data_file'), 'my data file')

    def test_punctuation_is_stripped(self):
        self.assertEqual(clean_query('sales-2024!!!'), 'sales 2024')

# auth (register/login views)
class AuthViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='StrongPass123!')

    def test_login_with_correct_credentials_redirects(self):
        response = self.client.post(reverse('login'), {'username': 'testuser', 'password': 'StrongPass123!'})
        self.assertEqual(response.status_code, 302)

    def test_login_with_wrong_password_shows_error(self):
        response = self.client.post(reverse('login'), {'username': 'testuser', 'password': 'WrongPassword'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'correct username and password')

    def test_login_with_nonexistent_user_shows_error(self):
        response = self.client.post(reverse('login'), {'username': 'ghost_user_1234', 'password': 'whatever'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'correct username and password')

    def test_register_creates_user_and_logs_them_in(self):
        response = self.client.post(reverse('register'), {
            'username': 'newperson',
            'password1': 'SuperSecret123!',
            'password2': 'SuperSecret123!',
        })
        self.assertTrue(User.objects.filter(username='newperson').exists())
        self.assertEqual(response.status_code, 302)

# full upload -> impute -> download flow
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ImputeDownloadFullRowsTests(TestCase):
    def setUp(self):
        rows = ["id,value\n"]
        for i in range(1, 26):
            val = '' if i % 5 == 0 else str(i * 2)
            rows.append(f"{i},{val}\n")
        self.csv_bytes = ''.join(rows).encode('utf-8')

    def test_imputed_download_contains_every_row_not_just_the_preview(self):
        upload = SimpleUploadedFile('bigdata.csv', self.csv_bytes, content_type='text/csv')
        response = self.client.post(reverse('upload'), {'file': upload})
        self.assertEqual(response.status_code, 302)
        pk = UploadedFile.objects.latest('uploaded_at').pk

        response = self.client.post(
            reverse('impute', args=[pk]),
            data=json.dumps({'strategies': {'value': 'mean'}}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        downloaded = response.content.decode('utf-8')
        data_lines = [l for l in downloaded.strip().split('\n') if l]
        self.assertEqual(len(data_lines), 26)

# server-side upload validation (.csv and .xlsx are both accepted)
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UploadValidationTests(TestCase):
    def test_invalid_extension_is_rejected_with_visible_error(self):
        bad_file = SimpleUploadedFile('notes.txt', b'just some text', content_type='text/plain')
        response = self.client.post(reverse('upload'), {'file': bad_file})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only CSV and Excel files are supported.')

    def test_valid_csv_file_is_accepted(self):
        good_file = SimpleUploadedFile('data.csv', b'a,b\n1,2\n3,4\n', content_type='text/csv')
        response = self.client.post(reverse('upload'), {'file': good_file})
        self.assertEqual(response.status_code, 302)

    def test_valid_xlsx_file_is_accepted(self):
        import openpyxl
        import io
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['a', 'b'])
        ws.append([1, 2])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        good_file = SimpleUploadedFile(
            'data.xlsx', buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response = self.client.post(reverse('upload'), {'file': good_file})
        self.assertEqual(response.status_code, 302)