from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload_file, name='upload'),
    path('results/<int:pk>/', views.results, name='results'),
    path('export/<int:pk>/', views.export_excel, name='export_excel'),
    path('impute/<int:pk>/', views.impute, name='impute'),
    path('history/', views.history, name='history'),
    path('history/<int:pk>/delete/', views.delete_analysis, name='delete_analysis'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]